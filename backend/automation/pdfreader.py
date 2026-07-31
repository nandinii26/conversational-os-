from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover - depends on local environment
    raise ImportError(
        "PyMuPDF is required for PDF reading. Install it with: pip install pymupdf"
    ) from exc


class PDFReadError(RuntimeError):
    """Raised when a PDF cannot be opened or text cannot be extracted."""


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str

    @property
    def character_count(self) -> int:
        return len(self.text)


def read_pdf(path: str | Path) -> str:
    """Return all extractable text from a PDF file."""
    pages = read_pdf_pages(path)
    return "\n\n".join(page.text for page in pages if page.text.strip()).strip()


def read_pdf_pages(path: str | Path) -> list[PageText]:
    """Return text per page from a PDF file."""
    pdf_path = _validate_pdf_path(path)

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:  # PyMuPDF raises several exception types
        raise PDFReadError(f"Could not open PDF: {pdf_path}") from exc

    try:
        return _extract_pages(doc)
    finally:
        doc.close()


def read_pdf_bytes(file_bytes: bytes) -> str:
    """Return all extractable text from in-memory PDF bytes."""
    pages = read_pdf_byte_pages(file_bytes)
    return combine_page_text(pages)


def read_pdf_byte_pages(file_bytes: bytes) -> list[PageText]:
    """Return text per page from in-memory PDF bytes."""
    if not file_bytes:
        raise PDFReadError("PDF bytes are empty.")

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise PDFReadError("Could not open PDF bytes.") from exc

    try:
        return _extract_pages(doc)
    finally:
        doc.close()


def _extract_pages(doc: fitz.Document) -> list[PageText]:
    pages: list[PageText] = []
    for index, page in enumerate(doc, start=1):
        pages.append(PageText(page_number=index, text=page.get_text("text") or ""))
    return pages


def _validate_pdf_path(path: str | Path) -> Path:
    pdf_path = Path(path).expanduser()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if not pdf_path.is_file():
        raise PDFReadError(f"Path is not a file: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise PDFReadError(f"Expected a .pdf file, got: {pdf_path.name}")
    return pdf_path


def combine_page_text(pages: Iterable[PageText]) -> str:
    """Combine page-level text into one readable document string."""
    return "\n\n".join(page.text for page in pages if page.text.strip()).strip()
