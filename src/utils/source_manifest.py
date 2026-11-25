"""Source offsets, structural coverage and backward-compatible notes records.

No UI, provider or database initialization. Coverage proves source delivery and
host-side ancestry, not model attention, factual accuracy or semantic completeness.
"""
from dataclasses import asdict, dataclass
import hashlib
import json

from .extraction_validation import validate_extracted_text
from .generation_validation import (GenerationError, GenerationText, UNKNOWN,
                                    REPORTED_FINISHED, validate_generation_text)

from .source_references import validate_references

RECORD_PREFIX_V1 = "AI_STUDY_NOTES_GENERATION_V1\n"
RECORD_PREFIX = "AI_STUDY_NOTES_GENERATION_V2\n"
RECORD_FAMILY = "AI_STUDY_NOTES_GENERATION_"
SOURCE_UNIT_BYTES = 512
MAX_SOURCE_SPANS = 4096


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def meaningful(text):
    return bool(text.replace("\ufeff", "").strip())


@dataclass(frozen=True)
class SourceSpan:
    source_id: str
    start: int
    end: int
    text_hash: str
    required: bool


@dataclass(frozen=True)
class SourceManifest:
    source_hash: str
    char_length: int
    byte_length: int
    spans: tuple

    @property
    def required_ids(self):
        return tuple(span.source_id for span in self.spans if span.required)

    def validate(self, source):
        validate_extracted_text(source)
        if (type(self.char_length) is not int or type(self.byte_length) is not int
                or self.source_hash != digest(source) or self.char_length != len(source)
                or self.byte_length != len(source.encode("utf-8")) or not self.spans
                or len(self.spans) > MAX_SOURCE_SPANS):
            raise GenerationError("Source coverage does not match the selected document.")
        offset = 0
        for i, span in enumerate(self.spans):
            if (span.source_id != f"S{i:06d}" or type(span.start) is not int
                    or type(span.end) is not int or span.start != offset
                    or not span.start < span.end <= len(source)
                    or type(span.required) is not bool):
                raise GenerationError("Source coverage has missing or invalid boundaries.")
            text = source[span.start:span.end]
            if span.text_hash != digest(text) or span.required != meaningful(text):
                raise GenerationError("Source coverage contains inconsistent text records.")
            offset = span.end
        if offset != len(source) or not self.required_ids:
            raise GenerationError("Source coverage is incomplete.")


def build_manifest(source):
    validate_extracted_text(source)
    try:
        source.encode("utf-8")
    except UnicodeError as error:
        raise GenerationError("The source has invalid text encoding.") from error
    spans = []
    start = 0
    while start < len(source):
        if len(spans) >= MAX_SOURCE_SPANS:
            raise GenerationError("The document exceeds the source-manifest limit. Select a smaller source.")
        end, size = start, 0
        while end < len(source):
            length = len(source[end].encode("utf-8"))
            if size + length > SOURCE_UNIT_BYTES:
                break
            size += length
            end += 1
        if end == start:
            raise GenerationError("A source character cannot fit the configured source unit.")
        # Prefer a stable line boundary without dropping its newline. Long lines
        # still split on Unicode code-point boundaries, with contiguous offsets.
        newline = source.rfind("\n", start, end)
        if newline >= start and newline + 1 > start:
            end = newline + 1
        text = source[start:end]
        spans.append(SourceSpan(f"S{len(spans):06d}", start, end, digest(text), meaningful(text)))
        start = end
    manifest = SourceManifest(digest(source), len(source), len(source.encode("utf-8")), tuple(spans))
    manifest.validate(source)
    return manifest


@dataclass(frozen=True)
class CoverageRequest:
    node_id: str
    stage: str
    source_ids: tuple
    input_nodes: tuple
    prompt_bytes: int
    completion_status: str
    output_hash: str
    output_bytes: int
    reference_ids: tuple = ()


@dataclass(frozen=True)
class CoverageReport:
    manifest: SourceManifest
    requests: tuple
    prompt_limit: int
    output_reserve_bytes: int
    model_call_limit: int
    provider_call_limit: int
    source_batch_limit: int
    synthesis_round_limit: int
    synthesis_rounds: int
    reference_contract: int = 0

    @property
    def status(self):
        return "complete"

    @property
    def provider_call_upper_bound(self):
        # Current generate_content makes at most three explicit SDK invocations.
        # Hidden SDK transport retries are not represented by this number.
        return len(self.requests) * 3

    def validate(self, source):
        self.manifest.validate(source)
        for value in (self.prompt_limit, self.output_reserve_bytes, self.model_call_limit,
                      self.provider_call_limit, self.source_batch_limit, self.synthesis_round_limit):
            if type(value) is not int or value < 1:
                raise GenerationError("Generation coverage budgets are invalid.")
        if self.prompt_limit > 8192 or self.output_reserve_bytes > 8192:
            raise GenerationError("Generation coverage exceeds the hard byte limits.")
        if (self.model_call_limit > 128 or self.provider_call_limit > 384
                or self.source_batch_limit > 64 or self.synthesis_round_limit > 6):
            raise GenerationError("Generation coverage exceeds the hard processing limits.")
        if (not self.requests or len(self.requests) > self.model_call_limit
                or self.provider_call_upper_bound > self.provider_call_limit
                or type(self.synthesis_rounds) is not int
                or not 0 <= self.synthesis_rounds <= self.synthesis_round_limit):
            raise GenerationError("Generation coverage exceeded its processing limits.")
        if type(self.reference_contract) is not int or self.reference_contract not in (0, 1):
            raise GenerationError("The source-reference contract is unsupported.")
        required = self.manifest.required_ids
        nodes, leaves, depths = {}, [], {}
        for record in self.requests:
            if (not isinstance(record.node_id, str) or not record.node_id or record.node_id in nodes
                    or record.stage not in ("direct", "source", "synthesis")
                    or type(record.prompt_bytes) is not int or not 0 < record.prompt_bytes <= self.prompt_limit
                    or record.completion_status not in (UNKNOWN, REPORTED_FINISHED)
                    or not isinstance(record.output_hash, str) or len(record.output_hash) != 64
                    or any(char not in "0123456789abcdef" for char in record.output_hash)
                    or type(record.output_bytes) is not int or not 0 < record.output_bytes <= self.output_reserve_bytes
                    or not record.source_ids or len(set(record.source_ids)) != len(record.source_ids)):
                raise GenerationError("Generation coverage contains invalid or duplicate results.")
            if record.stage == "synthesis":
                if not record.input_nodes or len(set(record.input_nodes)) != len(record.input_nodes):
                    raise GenerationError("Synthesis coverage is incomplete.")
                if any(key not in nodes for key in record.input_nodes):
                    raise GenerationError("Synthesis results are missing or out of order.")
                expected = tuple(item for key in record.input_nodes for item in nodes[key].source_ids)
                if record.source_ids != expected:
                    raise GenerationError("Synthesis coverage dropped or reordered source sections.")
            else:
                if record.input_nodes:
                    raise GenerationError("Source results have invalid ancestry.")
                leaves.extend(record.source_ids)
            if self.reference_contract:
                if (len(set(record.reference_ids)) != len(record.reference_ids)
                        or any(item not in record.source_ids for item in record.reference_ids)):
                    raise GenerationError("A result claims an invalid source reference.")
                if record.stage == "synthesis":
                    inherited = {item for key in record.input_nodes for item in nodes[key].reference_ids}
                    if any(item not in inherited for item in record.reference_ids):
                        raise GenerationError("Synthesis introduced a reference absent from its input notes.")
            depths[record.node_id] = (1 + max(depths[key] for key in record.input_nodes)
                                      if record.stage == "synthesis" else 0)
            nodes[record.node_id] = record
        if tuple(leaves) != required or self.requests[-1].source_ids != required:
            raise GenerationError("Not every required source section was processed in order.")
        source_count = sum(record.stage == "source" for record in self.requests)
        direct_count = sum(record.stage == "direct" for record in self.requests)
        if direct_count:
            if len(self.requests) != 1 or direct_count != 1 or self.synthesis_rounds != 0:
                raise GenerationError("A direct generation record has invalid synthesis ancestry.")
        elif (not source_count or self.requests[-1].stage != "synthesis"
              or not 1 <= depths[self.requests[-1].node_id] <= self.synthesis_rounds):
            raise GenerationError("The final synthesis is missing or exceeds its recorded rounds.")
        if source_count > self.source_batch_limit:
            raise GenerationError("Source batch limit was exceeded.")
        seen = set()
        def visit(key):
            if key in seen:
                return
            seen.add(key)
            for parent in nodes[key].input_nodes:
                visit(parent)
        visit(self.requests[-1].node_id)
        if seen != set(nodes):
            raise GenerationError("Some intermediate results did not reach the final guide.")


def attach_coverage(text, report, source):
    text = validate_generation_text(text)
    report.validate(source)
    status = (REPORTED_FINISHED if all(item.completion_status == REPORTED_FINISHED
              for item in report.requests) else UNKNOWN)
    result = GenerationText(text, status)
    result.coverage = report
    if report.reference_contract:
        refs = validate_references(text, report.manifest.source_hash, report.requests[-1].reference_ids)
        if refs != report.requests[-1].reference_ids:
            raise GenerationError("Final source references do not match the validated generation record.")
        result.reference_ids = refs
        result.reference_status = "identifiers_valid" if refs else "not_provided"
    else:
        result.reference_ids = ()
        result.reference_status = "historical_unverified"
    return result


def validate_coverage(text, source, *, require_references=False):
    text = validate_generation_text(text)
    report = getattr(text, "coverage", None)
    if not isinstance(report, CoverageReport):
        raise GenerationError("Complete source coverage could not be verified. No guide was saved.")
    report.validate(source)
    if require_references and report.reference_contract != 1:
        raise GenerationError("New guides require source-reference validation before saving.")
    if (digest(text) != report.requests[-1].output_hash
            or len(text.encode("utf-8")) != report.requests[-1].output_bytes
            or len(text.encode("utf-8")) > report.output_reserve_bytes):
        raise GenerationError("The final notes do not match their validated generation record.")
    return attach_coverage(text, report, source)


def dump_notes(text, source):
    text = plain_notes(validate_coverage(text, source, require_references=True))
    record = RECORD_PREFIX + json.dumps({"version": 2, "text": str(text),
        "completion_status": text.completion_status, "coverage": asdict(text.coverage)},
        ensure_ascii=True, separators=(",", ":"))
    if len(record.encode("utf-8")) > 2 * 1024 * 1024:
        raise GenerationError("The generation record exceeds the saved-record budget.")
    return record


def load_notes(value, source):
    # Plain historical notes are not assigned fabricated coverage/references.
    if not isinstance(value, str):
        return value
    if value.startswith(RECORD_PREFIX):
        prefix, version = RECORD_PREFIX, 2
    elif value.startswith(RECORD_PREFIX_V1):
        prefix, version = RECORD_PREFIX_V1, 1
    elif value.lstrip().startswith(RECORD_FAMILY):
        raise GenerationError("The saved notes format is unsupported or malformed.")
    else:
        return value
    try:
        if len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("record limit")
        data = json.loads(value[len(prefix):])
        if type(data["version"]) is not int or data["version"] != version:
            raise ValueError("version")
        raw = data["coverage"]
        manifest = SourceManifest(**dict(raw["manifest"], spans=tuple(
            SourceSpan(**item) for item in raw["manifest"]["spans"])))
        requests = tuple(CoverageRequest(**dict(item, source_ids=tuple(item["source_ids"]),
            input_nodes=tuple(item["input_nodes"]), reference_ids=tuple(item.get("reference_ids", ())))) for item in raw["requests"])
        report = CoverageReport(**dict(raw, manifest=manifest, requests=requests))
        if report.reference_contract != (1 if version == 2 else 0):
            raise ValueError("reference contract/version")
        text = GenerationText(data["text"], data["completion_status"])
        text.coverage = report
        return validate_coverage(text, source)
    except Exception as error:
        raise GenerationError("The saved generation record could not be verified.") from error


def plain_notes(value):
    """Guard plain-text consumers; decode records with their source first."""
    if not isinstance(value, str) or value.lstrip().startswith(RECORD_FAMILY):
        raise GenerationError("Decode the selected saved-note record before using its study text.")
    return value
