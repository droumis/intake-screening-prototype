"""Context document loader — reads a dataset's context/ folder."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ContextDocument:
    path: Path
    doc_type: str
    content: str


VALID_DOC_TYPES = {"program_description", "screening_criteria", "reference_material"}


def detect_doc_type(content: str, filename: str) -> str:
    """Detect the document type from the content's metadata line or filename."""
    for line in content.split("\n")[:10]:
        if "document type:" in line.lower():
            for dt in VALID_DOC_TYPES:
                if dt.replace("_", " ") in line.lower() or dt in line.lower():
                    return dt
    # Fallback to filename
    stem = filename.lower().replace("-", "_").replace(" ", "_")
    for dt in VALID_DOC_TYPES:
        if dt in stem:
            return dt
    return "unknown"


def load_context_documents(context_dir: Path, include_conflicting: bool = False) -> list[ContextDocument]:
    """Load all context documents from a directory.

    By default, skips files with 'CONFLICTING' in the name (test-only).
    Set include_conflicting=True for the conflict-detection test.
    """
    docs = []
    if not context_dir.exists():
        return docs

    for path in sorted(context_dir.iterdir()):
        if path.suffix not in (".md", ".txt", ".docx"):
            continue
        if "CONFLICTING" in path.name and not include_conflicting:
            continue

        content = path.read_text(encoding="utf-8")
        doc_type = detect_doc_type(content, path.name)
        docs.append(ContextDocument(path=path, doc_type=doc_type, content=content))

    return docs


def compute_context_hash(docs: list[ContextDocument]) -> str:
    """Compute a stable hash of all context documents for staleness detection."""
    hasher = hashlib.sha256()
    for doc in sorted(docs, key=lambda d: str(d.path)):
        hasher.update(str(doc.path).encode())
        hasher.update(doc.content.encode())
    return hasher.hexdigest()
