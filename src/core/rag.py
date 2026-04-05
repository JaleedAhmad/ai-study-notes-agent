import os
import uuid
import chromadb
from chromadb.config import Settings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from google import genai
from google.genai import types

# Initialize ChromaDB persistent client locally
CHROMA_DB_DIR = "./chroma_db"
os.makedirs(CHROMA_DB_DIR, exist_ok=True)
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)

def get_gemini_embedding(text):
    """Hits the Gemini API to mathematically embed a text chunk into vectors."""
    client = genai.Client()
    response = client.models.embed_content(
        model='gemini-embedding-001',
        contents=text,
    )
    return response.embeddings[0].values

def chunk_text(text):
    """Splits massive PDFs into smaller, 1000-character overlapping chunks for precision RAG."""
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )
    return text_splitter.split_text(text)

def embed_and_store_document(user_id, document_id, pdf_text, filename):
    """Chunks a raw PDF, calculates vectors for each chunk, and saves to the user's Chroma collection."""
    collection = chroma_client.get_or_create_collection(name="user_libraries")
    
    # Check if this document was already embedded to skip duplicate processing
    existing = collection.get(where={"document_id": document_id})
    if existing and existing['ids']:
        return # Already indexed
        
    chunks = chunk_text(pdf_text)
    
    ids = []
    embeddings = []
    documents = []
    metadatas = []
    
    for i, chunk in enumerate(chunks):
        if not chunk.strip():
            continue
        try:
            emb = get_gemini_embedding(chunk)
            ids.append(f"{document_id}_chunk_{i}")
            embeddings.append(emb)
            documents.append(chunk)
            metadatas.append({"user_id": user_id, "document_id": document_id, "filename": filename})
        except Exception as e:
            print(f"Failed to embed chunk {i}: {e}")
            
    if ids:
        collection.add(
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
            ids=ids
        )
        
def query_relevant_chunks(user_id, query, n_results=5):
    """Full Library Search: Searches ALL textbooks uploaded by the user to find the best 5 paragraphs."""
    collection = chroma_client.get_or_create_collection(name="user_libraries")
    
    if collection.count() == 0:
        return ""
        
    try:
        query_embedding = get_gemini_embedding(query)
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"user_id": user_id} # Filter exclusively to this user's entire library!
        )
        
        if not results['documents'] or not results['documents'][0]:
            return ""
            
        # Compile all matching text chunks into a unified context string, tagging the source book
        context_pieces = []
        for i, text in enumerate(results['documents'][0]):
            source_file = results['metadatas'][0][i].get("filename", "Unknown Document")
            context_pieces.append(f"[Excerpt from {source_file}]:\n{text}")
            
        return "\n\n---\n\n".join(context_pieces)
    except Exception as e:
        print(f"Semantic search failed: {e}")
        return ""
