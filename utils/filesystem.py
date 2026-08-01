import fnmatch
from pathlib import Path
from typing import List, Optional, Set, Tuple

from config import IGNORED_DIRS, IGNORED_FILES
from utils.logger import logger


def is_ignored_dir(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    for part in relative_parts:
        if part in IGNORED_DIRS:
            return True
    return False


def is_ignored_file(filename: str) -> bool:
    for pattern in IGNORED_FILES:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def is_text_file(path: Path, sample_size: int = 8192) -> bool:
    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
        if b"\x00" in chunk:
            return False
        try:
            chunk.decode("utf-8")
            return True
        except UnicodeDecodeError:
            try:
                chunk.decode("latin-1")
                return True
            except UnicodeDecodeError:
                return False
    except (OSError, IOError):
        return False


def read_file_safe(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, IOError) as e:
        return None


def write_file_safe(path: Path, content: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except (OSError, IOError) as e:
        logger.error(f"Failed to write {path}: {e}")
        return False


def list_files(root: Path) -> List[Path]:
    root = root.resolve()
    if not root.is_dir():
        return []

    result: List[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            if is_ignored_dir(path, root):
                continue
        elif path.is_file():
            if is_ignored_dir(path.parent, root):
                continue
            if is_ignored_file(path.name):
                continue
            result.append(path)
    return sorted(result)


def list_directories(root: Path) -> List[Path]:
    root = root.resolve()
    if not root.is_dir():
        return []

    result: List[Path] = []
    for path in root.rglob("*"):
        if path.is_dir():
            if is_ignored_dir(path, root):
                continue
            result.append(path)
    return sorted(result)


def get_file_extension(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def get_relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)
