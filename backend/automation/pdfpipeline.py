from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable

try:
    from .pdfreader import (
        PDFReadError,
        PageText,
        combine_page_text,
        read_pdf_byte_pages,
        read_pdf_pages,
    )
except ImportError:  
    from pdfreader import (
        PDFReadError,
        PageText,
        combine_page_text,
        read_pdf_byte_pages,
        read_pdf_pages,
    )


Summarizer = Callable[[str], str]


@dataclass
class PipelineResult:
    filename: str
    path: str | None
    page_count: int
    character_count: int
    word_count: int
    text: str
    keywords: list[str] = field(default_factory=list)
    summary: str | None = None

    def to_dict(self, include_text: bool = True) -> dict:
        data = asdict(self)
        if not include_text:
            data.pop("text", None)
        return data


class PDFPipeline:
    """Small PDF pipeline for extraction, basic metadata, keywords, and summaries."""

    def __init__(self, summarizer: Summarizer | None = None, summary_limit: int = 6000):
        self.summarizer = summarizer
        self.summary_limit = summary_limit

    def process_file(self, path: str | Path, summarize: bool = False) -> PipelineResult:
        pdf_path = Path(path).expanduser()
        pages = read_pdf_pages(pdf_path)
        text = combine_page_text(pages)
        return self._build_result(
            filename=pdf_path.name,
            path=str(pdf_path),
            pages=pages,
            text=text,
            summarize=summarize,
        )

    def process_bytes(
        self,
        file_bytes: bytes,
        filename: str = "uploaded.pdf",
        summarize: bool = False,
    ) -> PipelineResult:
        pages = read_pdf_byte_pages(file_bytes)
        text = combine_page_text(pages)
        return self._build_result(
            filename=filename,
            path=None,
            pages=pages,
            text=text,
            summarize=summarize,
        )

    def _build_result(
        self,
        filename: str,
        path: str | None,
        pages: Iterable[PageText],
        text: str,
        summarize: bool,
    ) -> PipelineResult:
        page_list = list(pages)
        words = _words(text)
        summary = None

        if summarize:
            summary = self._summarize(text)

        return PipelineResult(
            filename=filename,
            path=path,
            page_count=len(page_list),
            character_count=len(text),
            word_count=len(words),
            text=text,
            keywords=extract_keywords(text),
            summary=summary,
        )

    def _summarize(self, text: str) -> str:
        if not text.strip():
            return ""
        if self.summarizer is None:
            return simple_summary(text)
        return self.summarizer(text[: self.summary_limit])


def run_pipeline(
    path: str | Path,
    output: str | Path | None = None,
    summarize: bool = False,
    summarizer: Summarizer | None = None,
) -> PipelineResult:
    """Process one PDF and optionally write the extracted text to disk."""
    result = PDFPipeline(summarizer=summarizer).process_file(path, summarize=summarize)

    if output:
        output_path = Path(output)
        output_path.write_text(result.text, encoding="utf-8")

    return result


def extract_keywords(text: str, limit: int = 10) -> list[str]:
    stop_words = {
        "about",
        "after",
        "also",
        "and",
        "are",
        "because",
        "been",
        "but",
        "can",
        "for",
        "from",
        "has",
        "have",
        "into",
        "not",
        "that",
        "the",
        "their",
        "this",
        "with",
        "you",
        "your",
    }
    candidates = [
        word
        for word in _words(text)
        if len(word) > 3 and word.lower() not in stop_words
    ]
    return [word for word, _ in Counter(candidates).most_common(limit)]


def simple_summary(text: str, max_sentences: int = 4) -> str:
    """Fallback summary when no LLM summarizer is supplied."""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip())
        if sentence.strip()
    ]
    return " ".join(sentences[:max_sentences])


def chunk_text(text: str, max_chars: int = 4000, overlap: int = 200) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be greater than zero.")
    if overlap < 0:
        raise ValueError("overlap cannot be negative.")
    if overlap >= max_chars:
        raise ValueError("overlap must be smaller than max_chars.")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _words(text: str) -> list[str]:
    return [word.lower() for word in re.findall(r"[A-Za-z][A-Za-z'-]*", text)]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract text and metadata from a PDF.")
    parser.add_argument("pdf", help="Path to the PDF file.")
    parser.add_argument("-o", "--output", help="Optional .txt file for extracted text.")
    parser.add_argument("--summary", action="store_true", help="Include a simple summary.")
    parser.add_argument("--json", action="store_true", help="Print metadata as JSON.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    try:
        result = run_pipeline(args.pdf, output=args.output, summarize=args.summary)
    except (FileNotFoundError, PDFReadError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    if args.json:
        print(json.dumps(result.to_dict(include_text=False), indent=2))
    else:
        print(f"Processed: {result.filename}")
        print(f"Pages: {result.page_count}")
        print(f"Characters: {result.character_count}")
        print(f"Words: {result.word_count}")
        if result.keywords:
            print(f"Keywords: {', '.join(result.keywords)}")
        if result.summary:
            print(f"Summary: {result.summary}")
        if args.output:
            print(f"Text written to: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
