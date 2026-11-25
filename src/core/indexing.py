"""Index completion contracts; no UI, SDK initialization or provider calls."""

import hashlib
import json
import math
from numbers import Real

from ..utils.extraction_validation import validate_extracted_text


class IndexingError(ValueError):
    """Safe display message; underlying service diagnostics remain private."""


def content_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def chunks_hash(chunks):
    return content_hash(json.dumps(chunks, ensure_ascii=False, separators=(",", ":")))


def required_chunks(text, splitter):
    validate_extracted_text(text)
    chunks = splitter(text)
    if not isinstance(chunks, (list, tuple)) or any(
        not isinstance(chunk, str) or "\x00" in chunk for chunk in chunks
    ):
        raise IndexingError("Document chunking returned invalid content.")
    chunks = [chunk for chunk in chunks if chunk.strip()]
    if not chunks:
        raise IndexingError("No usable document chunks were available to index.")
    return chunks


def validated_vector(vector, dimension=None):
    if isinstance(vector, (str, bytes, dict)):
        raise IndexingError("The embedding provider returned an invalid vector.")
    try:
        values = list(vector)
    except TypeError as error:
        raise IndexingError("The embedding provider returned an invalid vector.") from error
    if not values or any(isinstance(value, bool) or not isinstance(value, Real)
                         or not math.isfinite(value) for value in values):
        raise IndexingError("The embedding provider returned an invalid vector.")
    if dimension is not None and len(values) != dimension:
        raise IndexingError("Embedding dimensions were inconsistent.")
    return values


def embed_chunks(chunks, embed):
    vectors = []
    for chunk in chunks:
        try:
            vectors.append(validated_vector(embed(chunk), len(vectors[0]) if vectors else None))
        except IndexingError:
            raise
        except Exception as error:
            raise IndexingError("A required document chunk could not be embedded.") from error
    return vectors


def verify_rows(rows, ids, documents, embeddings, metadatas=None):
    """Require exact readback, tolerating Chroma's float32 vector storage."""
    actual_ids = rows.get("ids")
    if not isinstance(actual_ids, list) or len(actual_ids) != len(ids) or set(actual_ids) != set(ids):
        raise IndexingError("Not all document chunks were persisted.")
    stored_docs, stored_vectors = rows.get("documents"), rows.get("embeddings")
    if stored_docs is None or stored_vectors is None or len(stored_docs) != len(ids) or len(stored_vectors) != len(ids):
        raise IndexingError("The stored document index could not be verified.")
    stored_meta = rows.get("metadatas")
    if metadatas is not None and (stored_meta is None or len(stored_meta) != len(ids)):
        raise IndexingError("The stored document metadata could not be verified.")
    positions = {identifier: i for i, identifier in enumerate(actual_ids)}
    for i, identifier in enumerate(ids):
        position = positions[identifier]
        vector = validated_vector(stored_vectors[position], len(embeddings[i]))
        if stored_docs[position] != documents[i] or any(
            not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-7)
            for a, b in zip(vector, embeddings[i])
        ) or (metadatas is not None and stored_meta[position] != metadatas[i]):
            raise IndexingError("The stored document index did not match its required chunks.")


def write_verified(collection, ids, documents, embeddings, metadatas=None):
    """Only use fresh IDs: cleanup cannot touch a previous valid index."""
    try:
        arguments = dict(ids=ids, documents=documents, embeddings=embeddings)
        include = ["documents", "embeddings"]
        if metadatas is not None:
            arguments["metadatas"] = metadatas
            include.append("metadatas")
        collection.add(**arguments)
        verify_rows(collection.get(ids=ids, include=include), ids, documents, embeddings, metadatas)
    except Exception as error:
        try:
            collection.delete(ids=ids)
        except Exception:
            raise IndexingError("Indexing failed and cleanup could not be confirmed. Retry before generating.") from error
        raise IndexingError("The document was not completely indexed. Please retry.") from error
