import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from file_searcher import search


def test_shared_queue_scanner_stops_at_result_cap(tmp_path):
    for index in range(5):
        (tmp_path / f"report-{index}.pdf").write_text("test")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "report-extra.docx").write_text("test")

    matches = search._scan_roots([str(tmp_path)], "report", max_results=2)

    assert len(matches) == 2
    assert all(Path(path).suffix in {".pdf", ".docx"} for path in matches)


def test_find_files_handles_empty_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(search, "_search_windows_index", lambda *_args: [])
    monkeypatch.setattr(search.os, "getcwd", lambda: str(tmp_path))
    monkeypatch.setattr(search.os.path, "expanduser", lambda *_args: str(tmp_path))
    monkeypatch.setattr(search, "_scan_roots", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(search.os.path, "exists", lambda *_args: False)
    search._cache.clear()

    assert search.find_files("missingfile123") == []


def test_unique_roots_avoids_scanning_nested_directories_twice(tmp_path):
    child = tmp_path / "child"
    child.mkdir()

    roots = search._unique_roots([str(child), str(tmp_path), str(tmp_path)])

    assert roots == [str(tmp_path)]
