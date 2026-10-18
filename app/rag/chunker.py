"""Chunks the markdown source documents in data/raw/ by heading, carrying
each document's frontmatter (source_urls, title) onto every chunk it
produces. This is the "separation between source information and generated
information" requirement (Q6): every chunk can be traced back to exactly
the document and URLs it came from.
"""

from pathlib import Path

import yaml


def parse_document(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, frontmatter_raw, body = text.split("---", 2)
        frontmatter = yaml.safe_load(frontmatter_raw) or {}
    else:
        frontmatter, body = {}, text
    return frontmatter, body


def chunk_by_heading(body: str, max_chars: int = 800, overlap_chars: int = 150) -> list[dict]:
    """Splits on markdown headings first (so a chunk never straddles two
    unrelated sections), then sub-splits any section longer than max_chars
    with a small overlap so a fact near a chunk boundary isn't lost.
    """
    sections: list[tuple[str | None, str]] = []
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in body.splitlines():
        if line.startswith("#"):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line.lstrip("#").strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    chunks = []
    for heading, content in sections:
        if not content:
            continue
        if len(content) <= max_chars:
            chunks.append({"section_title": heading, "text": content})
            continue
        start = 0
        while start < len(content):
            end = min(start + max_chars, len(content))
            chunks.append({"section_title": heading, "text": content[start:end].strip()})
            if end >= len(content):
                break
            start = end - overlap_chars
    return chunks


def chunk_document(path: Path) -> list[dict]:
    """Returns a list of {chunk_id, text, section_title, source_urls,
    document_title} - everything the vector store and retriever need,
    with no further lookup required at query time.
    """
    frontmatter, body = parse_document(path)
    raw_chunks = chunk_by_heading(body)
    source_urls = frontmatter.get("source_urls", [])
    document_title = frontmatter.get("title", path.stem)

    chunks = []
    for i, c in enumerate(raw_chunks):
        chunks.append(
            {
                "chunk_id": f"{path.stem}_{i}",
                "text": c["text"],
                "section_title": c["section_title"] or document_title,
                "source_urls": source_urls,
                "document_title": document_title,
            }
        )
    return chunks
