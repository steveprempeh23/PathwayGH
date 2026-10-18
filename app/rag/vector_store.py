"""Thin ChromaDB wrapper. Embedding is always passed in via `embed_fn`
rather than using Chroma's built-in embedding functions, for two reasons:
(1) it must use the same nomic-embed-text model as the rest of the app, not
whatever Chroma defaults to, and (2) it makes this module testable with a
fake embedding function, without a live Ollama server.
"""

import os
from pathlib import Path
from typing import Callable

import chromadb

_DEFAULT_PERSIST_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", str(_DEFAULT_PERSIST_DIR))
COLLECTION_NAME = "admission_guide"

EmbedFn = Callable[[str], list[float]]


def get_client(persist_dir: str | None = None) -> chromadb.ClientAPI:
    return chromadb.PersistentClient(path=persist_dir or PERSIST_DIR)


def get_collection(client: chromadb.ClientAPI | None = None):
    client = client or get_client()
    return client.get_or_create_collection(COLLECTION_NAME)


def reset_collection(client: chromadb.ClientAPI | None = None):
    client = client or get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # didn't exist yet - fine
    return client.get_or_create_collection(COLLECTION_NAME)


def add_chunks(chunks: list[dict], embed_fn: EmbedFn, collection=None) -> int:
    collection = collection or get_collection()
    embeddings = [embed_fn(c["text"]) for c in chunks]
    collection.add(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings,
        documents=[c["text"] for c in chunks],
        metadatas=[
            {
                "section_title": c["section_title"] or "",
                # Chroma metadata values must be scalar - URLs joined, split on read.
                "source_urls": ",".join(c["source_urls"]),
                "document_title": c["document_title"],
            }
            for c in chunks
        ],
    )
    return len(chunks)


def query(query_text: str, embed_fn: EmbedFn, k: int = 3, collection=None) -> list[dict]:
    collection = collection or get_collection()
    if collection.count() == 0:
        return []

    query_embedding = embed_fn(query_text)
    results = collection.query(
        query_embeddings=[query_embedding], n_results=min(k, collection.count())
    )

    out = []
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        out.append(
            {
                "text": results["documents"][0][i],
                "section_title": meta["section_title"],
                "source_urls": [u for u in meta["source_urls"].split(",") if u],
                "document_title": meta["document_title"],
                "distance": results["distances"][0][i],
            }
        )
    return out
