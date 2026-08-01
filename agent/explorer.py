from pathlib import Path
from typing import Any, Dict, List

from config import METADATA_FILES
from utils.filesystem import (
    get_file_extension,
    get_relative_path,
    is_text_file,
    list_files,
)
from utils.logger import logger


class RepositoryExplorer:
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.logger = logger

    def validate(self) -> bool:
        if not self.repo_path.exists():
            self.logger.error(f"Repository does not exist: {self.repo_path}")
            return False
        if not self.repo_path.is_dir():
            self.logger.error(f"Path is not a directory: {self.repo_path}")
            return False
        return True

    def build_tree(self) -> Dict[str, Any]:
        all_files = list_files(self.repo_path)
        tree: Dict[str, Any] = {}

        for file_path in all_files:
            rel_path = get_relative_path(file_path, self.repo_path)
            parts = rel_path.split("/")

            current = tree
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            current[parts[-1]] = "FILE"

        return tree

    def format_tree(self, tree: Dict[str, Any], prefix: str = "") -> str:
        lines: List[str] = []
        items = sorted(tree.items())

        for i, (name, value) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "

            if isinstance(value, dict):
                lines.append(f"{prefix}{connector}{name}/")
                extension = "    " if is_last else "│   "
                lines.append(self.format_tree(value, prefix + extension))
            else:
                lines.append(f"{prefix}{connector}{name}")

        return "\n".join(line for line in lines if line)

    def get_file_list(self) -> List[Dict[str, Any]]:
        all_files = list_files(self.repo_path)
        result: List[Dict[str, Any]] = []

        for fp in all_files:
            try:
                stat = fp.stat()
                result.append(
                    {
                        "path": get_relative_path(fp, self.repo_path),
                        "absolute_path": str(fp),
                        "extension": get_file_extension(fp),
                        "size_bytes": stat.st_size,
                        "is_text": is_text_file(fp),
                        "is_metadata": fp.name in METADATA_FILES,
                    }
                )
            except (OSError, IOError):
                continue

        return result

    def explore(self) -> Dict[str, Any]:
        self.logger.info(f"Exploring repository: {self.repo_path}")

        if not self.validate():
            raise RuntimeError(f"Invalid repository path: {self.repo_path}")

        files = self.get_file_list()
        tree = self.build_tree()
        tree_str = self.format_tree(tree)

        extensions: Dict[str, int] = {}
        for f in files:
            ext = f["extension"] or "no_ext"
            extensions[ext] = extensions.get(ext, 0) + 1

        result = {
            "repo_path": str(self.repo_path),
            "file_count": len(files),
            "files": files,
            "tree_dict": tree,
            "tree_string": tree_str,
            "extensions": extensions,
            "text_file_count": sum(1 for f in files if f["is_text"]),
            "metadata_files": [f for f in files if f["is_metadata"]],
        }

        self.logger.info(
            f"Repository explored: {result['file_count']} files found "
            f"({result['text_file_count']} text, extensions: {sorted(extensions.items())})"
        )

        return result
