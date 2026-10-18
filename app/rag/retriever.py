from pathlib import Path

from app.core.exceptions import RetrievalError
from app.llm.ollama_client import embed as ollama_embed
from app.rag import chunker, vector_store

RAW_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"


def build_index(embed_fn=ollama_embed, force: bool = False) -> int:
    """Chunks every .md file in data/raw/ and embeds+stores each chunk.
    Idempotent by default: if the collection already has content, this is a
    no-op unless force=True. Returns the resulting chunk count.
    """
    collection = vector_store.reset_collection() if force else vector_store.get_collection()
    if not force and collection.count() > 0:
        return collection.count()

    all_chunks: list[dict] = []
    for md_file in sorted(RAW_DATA_DIR.glob("*.md")):
        all_chunks.extend(chunker.chunk_document(md_file))

    if not all_chunks:
        return 0

    return vector_store.add_chunks(all_chunks, embed_fn=embed_fn, collection=collection)


def retrieve(query: str, embed_fn=ollama_embed, k: int = 3) -> list[dict]:
    """Returns up to k chunks with source metadata, or an empty list if the
    index has nothing indexed yet. Raises RetrievalError on an actual
    failure (e.g. embedding call failed) - callers must not treat that the
    same as "no results found"; per Q6, the system must say it couldn't
    retrieve, not silently proceed as if there was nothing to find.
    """
    try:
        return vector_store.query(query, embed_fn=embed_fn, k=k)
    except Exception as exc:
        raise RetrievalError(f"Retrieval failed for query '{query}': {exc}") from exc
