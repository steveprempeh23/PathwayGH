from pathlib import Path

import pytest

from app.core.exceptions import RetrievalError
from app.rag import chunker, retriever, vector_store

REAL_DOC = Path(__file__).resolve().parents[1] / "data" / "raw" / "wassce_grading_and_admission_guide.md"


def test_chunking_real_document_carries_provenance():
    chunks = chunker.chunk_document(REAL_DOC)
    assert len(chunks) > 1
    for c in chunks:
        assert c["source_urls"], "every chunk must carry source URLs from frontmatter"
        assert c["document_title"]
        assert c["text"].strip()


def test_second_source_document_has_its_own_distinct_source_urls():
    """Two markdown source files now exist, each with genuinely different
    citations (see docs/extending-data.md's guidance on this). Confirms
    the second file's chunks don't accidentally inherit the first file's
    URLs, or vice versa - each file's provenance must stay its own."""
    recent_doc = Path(__file__).resolve().parents[1] / "data" / "raw" / "recent_cutoff_examples_2026_2027.md"
    original_chunks = chunker.chunk_document(REAL_DOC)
    recent_chunks = chunker.chunk_document(recent_doc)

    original_urls = {u for c in original_chunks for u in c["source_urls"]}
    recent_urls = {u for c in recent_chunks for u in c["source_urls"]}

    assert original_urls.isdisjoint(recent_urls), (
        "the two source documents' URLs must not bleed into each other"
    )
    assert "yen.com.gh" in "".join(recent_urls)
    assert "yen.com.gh" not in "".join(original_urls)


# --- Controlled fixture for precise retrieval assertions ---
# Small deterministic vocabulary; fake embeddings are just keyword counts.
# This isolates "does ranking/filtering logic work" from "is the real
# embedding model good", which can't be tested without live Ollama anyway.
_VOCAB = ["creditgate", "medicine", "hnd", "irrelevant"]


def _fake_embed(text: str) -> list[float]:
    text_lower = text.lower()
    return [float(text_lower.count(word)) for word in _VOCAB]


_FIXTURE_CHUNKS = [
    {
        "chunk_id": "c0",
        "text": "This section is entirely about the mandatory creditgate creditgate rule.",
        "section_title": "Credit Gate",
        "source_urls": ["https://example.com/gate"],
        "document_title": "Fixture Doc",
    },
    {
        "chunk_id": "c1",
        "text": "Medicine medicine medicine requires a very low aggregate.",
        "section_title": "Medicine Bands",
        "source_urls": ["https://example.com/medicine"],
        "document_title": "Fixture Doc",
    },
    {
        "chunk_id": "c2",
        "text": "HND hnd hnd tracks allow a higher aggregate ceiling.",
        "section_title": "HND Bands",
        "source_urls": ["https://example.com/hnd"],
        "document_title": "Fixture Doc",
    },
    {
        "chunk_id": "c3",
        "text": "irrelevant irrelevant filler text about nothing in particular.",
        "section_title": "Filler",
        "source_urls": ["https://example.com/filler"],
        "document_title": "Fixture Doc",
    },
]


@pytest.fixture
def fresh_collection(tmp_path):
    client = vector_store.get_client(persist_dir=str(tmp_path))
    collection = vector_store.get_collection(client=client)
    vector_store.add_chunks(_FIXTURE_CHUNKS, embed_fn=_fake_embed, collection=collection)
    return collection


def test_retrieval_ranks_most_relevant_chunk_first(fresh_collection):
    results = vector_store.query("creditgate", embed_fn=_fake_embed, k=1, collection=fresh_collection)
    assert results[0]["section_title"] == "Credit Gate"
    assert results[0]["source_urls"] == ["https://example.com/gate"]


def test_retrieval_respects_k(fresh_collection):
    results = vector_store.query("medicine hnd", embed_fn=_fake_embed, k=2, collection=fresh_collection)
    assert len(results) == 2


def test_empty_collection_returns_empty_list_not_error(tmp_path):
    client = vector_store.get_client(persist_dir=str(tmp_path))
    empty_collection = vector_store.get_collection(client=client)
    results = vector_store.query("anything", embed_fn=_fake_embed, k=3, collection=empty_collection)
    assert results == []


def test_retriever_wraps_embedding_failures_as_retrieval_error(monkeypatch):
    def broken_embed(text):
        raise RuntimeError("embedding model unreachable")

    def fake_query(query_text, embed_fn, k=3, collection=None):
        return embed_fn(query_text)  # forces the broken_embed to raise here

    monkeypatch.setattr(vector_store, "query", fake_query)

    with pytest.raises(RetrievalError):
        retriever.retrieve("anything", embed_fn=broken_embed)
