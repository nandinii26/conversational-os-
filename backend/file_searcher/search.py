import os
import stat
import subprocess
import threading
import time
from queue import Queue

# Keep this a tuple: str.endswith(tuple) is implemented in C.
DOC_EXTENSION_TUPLE = (
    ".pdf", ".txt", ".csv", ".doc", ".docx", ".xlsx", ".xls",
    ".ppt", ".pptx", ".md", ".json",".mp3",".mp4",".mov","avi","wmv",".wav","jpeg","jpg",".png"
)

# Kept as an alias for callers that imported the old public constant.
DOC_EXTENSIONS = frozenset(DOC_EXTENSION_TUPLE)

SKIP_DIRS = frozenset([
    "windows", "program files", "program files (x86)",
    "system volume information", "$recycle.bin", "appdata",
    "programdata", "boot", "recovery", "perflogs", "node_modules",
    ".git", "__pycache__", "venv", ".venv", "env",
])

_DEFAULT_MAX_RESULTS = 20
_WORKER_COUNT = min(8, os.cpu_count() or 4)
CACHE_TTL = 300

_cache: dict[tuple[str, int], tuple[list[str], float]] = {}
_cache_lock = threading.Lock()
_windows_index_available: bool | None = None
_windows_index_lock = threading.Lock()


def _cache_get(key: tuple[str, int]) -> list[str] | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[1] < CACHE_TTL:
            return entry[0]
    return None


def _cache_set(key: tuple[str, int], value: list[str]) -> None:
    with _cache_lock:
        _cache[key] = (value, time.time())


def _unique_roots(roots: list[str]) -> list[str]:
    """Remove duplicate roots and roots already contained by another root."""
    unique: list[str] = []
    for root in roots:
        absolute = os.path.abspath(root)
        if not os.path.isdir(absolute):
            continue
        if any(os.path.normcase(absolute) == os.path.normcase(item) for item in unique):
            continue
        unique.append(absolute)

    selected: list[str] = []
    for root in sorted(unique, key=len):
        try:
            if any(os.path.commonpath([root, parent]) == parent for parent in selected):
                continue
        except ValueError:  # Different Windows drives.
            pass
        selected.append(root)
    return selected


def _is_reparse_point(entry: os.DirEntry[str]) -> bool:
    """Do not follow Windows junctions/reparse points into duplicate trees."""
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (AttributeError, OSError):
        return False


def _scan_roots(roots: list[str], needle: str, max_results: int,
                stop_event: threading.Event | None = None) -> list[str]:
    """Search roots with a fixed number of workers and one shared path queue."""
    stop_event = stop_event or threading.Event()
    paths: Queue[str | None] = Queue()
    for root in _unique_roots(roots):
        paths.put(root)

    matches: list[str] = []
    seen: set[str] = set()
    matches_lock = threading.Lock()

    def add_match(path: str) -> None:
        with matches_lock:
            key = os.path.normcase(path)
            if key in seen or len(matches) >= max_results:
                return
            seen.add(key)
            matches.append(path)
            if len(matches) >= max_results:
                stop_event.set()

    def worker() -> None:
        while True:
            current = paths.get()
            try:
                if current is None:
                    return
                if stop_event.is_set():
                    continue
                try:
                    with os.scandir(current) as entries:
                        for entry in entries:
                            if stop_event.is_set():
                                break
                            try:
                                if entry.is_dir(follow_symlinks=False):
                                    name = entry.name.casefold()
                                    if name not in SKIP_DIRS and not _is_reparse_point(entry):
                                        paths.put(entry.path)
                                elif entry.is_file(follow_symlinks=False):
                                    filename = entry.name.casefold()
                                    if filename.endswith(DOC_EXTENSION_TUPLE) and needle in filename:
                                        add_match(entry.path)
                            except (OSError, PermissionError):
                                continue
                except (OSError, PermissionError):
                    continue
            finally:
                paths.task_done()

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(_WORKER_COUNT)]
    for thread in workers:
        thread.start()
    paths.join()
    for _ in workers:
        paths.put(None)
    for thread in workers:
        thread.join()
    return matches


def _search_windows_index(name: str, max_results: int = _DEFAULT_MAX_RESULTS) -> list[str]:
    """Query Windows Search once it has proved available for this process."""
    global _windows_index_available
    with _windows_index_lock:
        if _windows_index_available is False:
            return []

    safe_name = name.replace("'", "''")
    extensions = ", ".join(f"'{extension}'" for extension in DOC_EXTENSION_TUPLE)
    sql = (
        "SELECT TOP {count} System.ItemPathDisplay FROM SystemIndex "
        "WHERE System.FileName LIKE '%{name}%' "
        "AND System.FileExtension IN ({extensions}) "
        "AND NOT System.ItemPathDisplay LIKE '%\\AppData\\%' "
        "ORDER BY System.DateModified DESC"
    ).format(count=max_results, name=safe_name, extensions=extensions)
    ps_script = f'''$conn = New-Object -ComObject ADODB.Connection
$conn.Open('Provider=Search.CollatorDSO;Extended Properties="Application=Windows"')
$rs = New-Object -ComObject ADODB.Recordset
$rs.Open(@"
{sql}
"@, $conn)
while (-not $rs.EOF) {{ $rs.Fields['System.ItemPathDisplay'].Value; $rs.MoveNext() }}
$rs.Close(); $conn.Close()'''
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=4,
        )
        if result.returncode != 0:
            raise RuntimeError("Windows Search query failed")
        with _windows_index_lock:
            _windows_index_available = True
        return [line.strip() for line in result.stdout.splitlines() if line.strip() and os.path.isfile(line.strip())]
    except Exception:
        with _windows_index_lock:
            _windows_index_available = False
        return []


def find_files(name: str, max_results: int = 0) -> list[str]:
    """Find matching documents, returning promptly once the requested cap is reached."""
    max_results = max_results or _DEFAULT_MAX_RESULTS
    needle = name.casefold()
    cache_key = (needle, max_results)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Scan the user profile only once; Desktop/Documents/Downloads are descendants.
    home = os.path.expanduser("~")
    quick_roots = [os.getcwd(), home]
    index_results: list[str] = []
    index_finished = threading.Event()
    scan_stop = threading.Event()

    def run_index() -> None:
        index_results.extend(_search_windows_index(needle, max_results))
        if len(index_results) >= max_results:
            scan_stop.set()
        index_finished.set()

    index_thread = threading.Thread(target=run_index, daemon=True)
    index_thread.start()
    phase_one = _scan_roots(quick_roots, needle, max_results, scan_stop)
    index_finished.wait(timeout=4)

    # A complete indexed result set is already ordered by DateModified and needs no disk scan.
    if len(index_results) >= max_results:
        result = index_results[:max_results]
        _cache_set(cache_key, result)
        return result

    merged: list[str] = []
    seen: set[str] = set()
    for path in index_results + phase_one:
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            merged.append(path)
        if len(merged) >= max_results:
            break
    if merged:
        _cache_set(cache_key, merged)
        return merged

    drives = [drive + "\\" for drive in "CDEF" if os.path.exists(drive + "\\")]
    result = _scan_roots(drives, needle, max_results)
    _cache_set(cache_key, result)
    return result


def search_pdf() -> None:
    name = input("Enter the name of the file to search for: ")
    start = time.time()
    files = find_files(name)
    for path in files:
        print(path)
    print(f"\nFound {len(files)} file(s) in {time.time() - start:.2f}s")


if __name__ == "__main__":
    search_pdf()
