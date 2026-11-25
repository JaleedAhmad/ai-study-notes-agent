import os
import uuid
from dataclasses import dataclass
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter
from google import genai

import streamlit as st
from ..auth.identity import require_authenticated_user
from .indexing import (IndexingError, chunks_hash, content_hash, required_chunks,
                       validated_vector, embed_chunks, verify_rows, write_verified)

# Initialize ChromaDB persistent client locally
CHROMA_DB_DIR = "./chroma_db"
os.makedirs(CHROMA_DB_DIR, exist_ok=True)

@st.cache_resource
def get_chroma_client():
    return chromadb.PersistentClient(path=CHROMA_DB_DIR)

def get_gemini_embedding(text):
    """Hits the Gemini API to mathematically embed a text chunk into vectors."""
    client = genai.Client()
    response = client.models.embed_content(
        model='gemini-embedding-001',
        contents=text,
    )
    try:
        if len(response.embeddings) != 1:
            raise IndexingError("The embedding provider returned an invalid response.")
        return validated_vector(response.embeddings[0].values)
    except (AttributeError, TypeError, IndexError) as error:
        raise IndexingError("The embedding provider returned an invalid response.") from error

def chunk_text(text):
    """Splits massive PDFs into smaller, 1000-character overlapping chunks for precision RAG."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )
    return text_splitter.split_text(text)

@dataclass(frozen=True)
class IndexReceipt:
    user_id: str
    document_id: str
    index_id: str
    chunk_count: int


def _document_filter(user_id, document_id, index_id=None):
    terms = [{"user_id": user_id}, {"document_id": document_id}]
    if index_id is not None:
        terms.append({"index_id": index_id})
    return {"$and": terms}


def _complete_revision(rows, user_id, document_id, index_id):
    """Verify the full revision, not merely one matching chunk or a status flag."""
    metadata = rows.get("metadatas")
    if not metadata:
        raise IndexingError("The document index has no completion metadata.")
    first = metadata[0]
    if not all(isinstance(item, dict) for item in metadata):
        raise IndexingError("The document index has invalid metadata.")
    if not isinstance(first.get("filename"), str) or any(
        not isinstance(first.get(key), str) or len(first[key]) != 64
        or any(char not in "0123456789abcdef" for char in first[key])
        for key in ("source_hash", "chunks_hash")
    ) or any(type(item.get("chunk_number")) is not int for item in metadata):
        raise IndexingError("The document index has invalid completion metadata.")
    count, dimension = first.get("chunk_count"), first.get("vector_dimension")
    if type(count) is not int or count < 1 or type(dimension) is not int or dimension < 1:
        raise IndexingError("The document index has invalid completion metadata.")
    if len(metadata) != count or len(rows.get("ids", [])) != count:
        raise IndexingError("The document index is incomplete.")
    ordered = sorted(zip(rows["ids"], rows["documents"], rows["embeddings"], metadata),
                     key=lambda row: row[3]["chunk_number"])
    documents = [row[1] for row in ordered]
    if chunks_hash(documents) != first.get("chunks_hash"):
        raise IndexingError("The document index content is incomplete.")
    expected_meta = []
    vectors = []
    for i, (_, document, vector, _) in enumerate(ordered):
        if not isinstance(document, str) or not document.strip():
            raise IndexingError("The document index contains invalid chunks.")
        expected_meta.append(dict(first, user_id=user_id, document_id=document_id,
                                  index_id=index_id, chunk_number=i))
        vectors.append(validated_vector(vector, dimension))
    ids = [f"{index_id}_chunk_{i}" for i in range(count)]
    verify_rows(rows, ids, documents, vectors, expected_meta)
    return IndexReceipt(user_id, document_id, index_id, count)


def _revision_rows(collection, user_id, document_id, index_id):
    return collection.get(where=_document_filter(user_id, document_id, index_id),
                          include=["documents", "embeddings", "metadatas"])


def embed_and_store_document(user_id, document_id, pdf_text, filename):
    """Return a verified receipt or raise; never skip required embedding failures.

    A valid existing revision with different source is preserved and replacement
    is refused. Callers must use a new document ID for intentional replacements.
    Legacy rows without completion metadata are not evidence of completeness.
    """
    user_id = require_authenticated_user(user_id)
    try:
        if not isinstance(document_id, str) or not document_id or not isinstance(filename, str):
            raise IndexingError("Document identification is invalid.")
        chunks = required_chunks(pdf_text, chunk_text)
        source_hash, digest = content_hash(pdf_text), chunks_hash(chunks)
        collection = get_chroma_client().get_or_create_collection(name="user_libraries")
        existing = collection.get(where=_document_filter(user_id, document_id),
                                  include=["metadatas"])
        revisions = {item.get("index_id") for item in existing.get("metadatas", [])
                     if isinstance(item, dict) and item.get("index_id")}
        duplicate = None
        for revision in revisions:
            rows = _revision_rows(collection, user_id, document_id, revision)
            try:
                receipt = _complete_revision(rows, user_id, document_id, revision)
            except (IndexingError, KeyError, TypeError, ValueError):
                continue
            first = rows["metadatas"][0]
            # Filename is a display label, not content identity. Preserve the
            # original stored label when reusing the same verified source.
            if first["source_hash"] != source_hash or first["chunks_hash"] != digest:
                raise IndexingError("This document ID already has a valid index for different content. Use a new document ID.")
            duplicate = receipt
        if duplicate is not None:
            return duplicate
        vectors = embed_chunks(chunks, get_gemini_embedding)
        revision = uuid.uuid4().hex
        ids = [f"{revision}_chunk_{i}" for i in range(len(chunks))]
        metadata = [dict(user_id=user_id, document_id=document_id, filename=filename,
                         index_id=revision, chunk_number=i, chunk_count=len(chunks),
                         source_hash=source_hash, chunks_hash=digest,
                         vector_dimension=len(vectors[0])) for i in range(len(chunks))]
        write_verified(collection, ids, chunks, vectors, metadata)
        return IndexReceipt(user_id, document_id, revision, len(chunks))
    except IndexingError:
        raise
    except Exception as error:
        raise IndexingError("The document could not be completely indexed. Please retry.") from error

def query_relevant_chunks(user_id, query, n_results=5, *, document_ids=None):
    """Retrieve verified owner-scoped excerpts, optionally limited to selected documents.

    An empty explicit selection has no vector context; None retains the library
    search interface for existing non-UI callers.
    """
    user_id = require_authenticated_user(user_id)
    if document_ids is not None:
        if not isinstance(document_ids, (list, tuple)) or any(
            not isinstance(value, str) or not value for value in document_ids
        ):
            raise IndexingError("The selected document index is unavailable.")
        if not document_ids:
            return ""
    client = get_chroma_client()
    collection = client.get_or_create_collection(name="user_libraries")
    
    if collection.count() == 0:
        return ""
        
    try:
        query_embedding = get_gemini_embedding(query)
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=({"user_id": user_id} if document_ids is None else {
                "$and": [{"user_id": user_id}, {"document_id": {"$in": list(document_ids)}}]
            })
        )
        
        if not results['documents'] or not results['documents'][0]:
            return ""
            
        # Compile all matching text chunks into a unified context string, tagging the source book
        context_pieces = []
        verified = {}
        for i, text in enumerate(results['documents'][0]):
            metadata = results['metadatas'][0][i]
            document_id, revision = metadata.get("document_id"), metadata.get("index_id")
            if (metadata.get("user_id") != user_id or not document_id or not revision
                    or (document_ids is not None and document_id not in document_ids)):
                continue
            key = (document_id, revision)
            if key not in verified:
                rows = _revision_rows(collection, user_id, document_id, revision)
                try:
                    _complete_revision(rows, user_id, document_id, revision)
                    verified[key] = rows["documents"]
                except (IndexingError, KeyError, TypeError, ValueError):
                    verified[key] = []
            if text not in verified[key]:
                continue
            source_file = metadata.get("filename", "Unknown Document")
            context_pieces.append(f"[Excerpt from {source_file}]:\n{text}")
            
        return "\n\n---\n\n".join(context_pieces)
    except Exception:
        print("Semantic search failed or the index was incomplete.")
        return ""
