"""UI-independent content identity and selected-source state contracts."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import PurePath

from .extraction_validation import ExtractionError, validate_extracted_text
from .source_manifest import load_notes

PROCESSING_VERSION = "extraction-index-v1"


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def text_fingerprint(text):
    return fingerprint(text.encode("utf-8"))


def identity(*values):
    return text_fingerprint(json.dumps(values, separators=(",", ":"), ensure_ascii=False))


@dataclass(frozen=True)
class UploadSnapshot:
    name: str
    data: bytes
    digest: str
    format: str

    def stream(self):
        stream = io.BytesIO(self.data)
        stream.name = self.name
        return stream

    def document_id(self, owner):
        return identity(PROCESSING_VERSION, owner, self.digest, self.format)

    def index_document_id(self, owner, text):
        # OCR may differ on re-extraction: never overwrite a valid earlier index.
        return identity(self.document_id(owner), text_fingerprint(text))


def snapshot(upload):
    """Read complete bytes without retaining or consuming the upload's cursor."""
    if not isinstance(upload.name, str):
        raise ExtractionError("The uploaded file has an invalid name.")
    if hasattr(upload, "getvalue"):
        data = upload.getvalue()
    else:
        position = upload.tell()
        try:
            upload.seek(0)
            data = upload.read()
        finally:
            upload.seek(position)
    if not isinstance(data, bytes):
        raise ExtractionError("The uploaded file could not be read as bytes.")
    return UploadSnapshot(upload.name, data, fingerprint(data), PurePath(upload.name).suffix.lower())


def upload_selection(owner, uploads):
    return {"kind": "upload", "owner": owner,
            "key": identity(PROCESSING_VERSION, owner,
                            [(item.digest, item.format) for item in uploads])}


def clear_source(state, *, reset_uploader=False):
    for key in ("pdf_text", "notes", "chat_session", "current_file", "current_session_id",
                "podcast_bytes", "anki_bytes", "library_id", "source_selection",
                "ready_source", "notes_source", "chat_source", "history_source", "session_source",
                "generation_strategy", "generation_provider"):
        state[key] = None
    state["chat_history"] = []
    state["upload_cache"] = {}
    state["index_receipts"] = {}
    if reset_uploader:
        state["upload_epoch"] = state.get("upload_epoch", 0) + 1


def ensure_owner(state, owner):
    previous = state.get("source_owner")
    if previous is not None and previous != owner:
        clear_source(state, reset_uploader=True)
        state["source_owner"] = owner
        return False
    state["source_owner"] = owner
    return True


def mark_ready(state, owner):
    selection = state.get("source_selection")
    if not isinstance(selection, dict) or selection.get("owner") != owner or state.get("source_owner") != owner:
        raise ExtractionError("Select your study material again before continuing.")
    text = validate_extracted_text(state.get("pdf_text"))
    token = identity(selection, text_fingerprint(text))
    state["ready_source"] = token
    return token


def selected_source(state, owner):
    selection = state.get("source_selection")
    text = validate_extracted_text(state.get("pdf_text"))
    if (state.get("source_owner") != owner or not isinstance(selection, dict) or selection.get("owner") != owner
            or selection.get("kind") not in ("saved", "upload")
            or state.get("ready_source") != identity(selection, text_fingerprint(text))):
        raise ExtractionError("The selected study material is not ready. Please select it again.")
    if selection["kind"] == "saved" and selection.get("session_id") != state.get("current_session_id"):
        raise ExtractionError("The selected saved session has changed. Please reopen it.")
    session_id = state.get("current_session_id")
    if session_id is not None and state.get("session_source") != (session_id, state["ready_source"]):
        raise ExtractionError("The saved session does not match this source. Please reopen it.")
    return text, state["ready_source"]


def restore_saved_session(state, row, owner):
    """Accept only an owned server-fetched record; never infer original upload bytes."""
    if row.get("user_id") != owner or not isinstance(row.get("id"), str):
        raise PermissionError("Session unavailable.")
    text = validate_extracted_text(row.get("pdf_text"))
    history = row.get("chat_history") or []
    if not isinstance(history, list) or any(not isinstance(item, dict)
            or item.get("role") not in ("user", "assistant", "model")
            or not isinstance(item.get("content"), str) for item in history):
        raise ExtractionError("The saved session history is unavailable.")
    clear_source(state)
    state["source_owner"] = owner
    state["source_selection"] = {"kind": "saved", "owner": owner, "session_id": row["id"],
                                 "key": identity(owner, row["id"], text_fingerprint(text))}
    state["current_session_id"] = row["id"]
    state["current_file"] = row.get("filename")
    state["pdf_text"] = text
    state["notes"] = load_notes(row.get("notes"), text)
    state["chat_history"] = deepcopy(history)
    token = mark_ready(state, owner)
    state["notes_source"] = token
    state["history_source"] = token
    state["session_source"] = (row["id"], token)
