import shutil
from pathlib import Path, PureWindowsPath, PurePosixPath
from typing import Any, Dict, List

from utils.filesystem import read_file_safe, write_file_safe
from utils.logger import logger


_PATCHER_PATH_FORBIDDEN = ("ACTION:", "CONTENT:", "```", "FILE: ")


class Patcher:
    def __init__(self, repo_path: str | Path, backup: bool = True):
        self.repo_path = Path(repo_path).resolve()
        self.backup = backup
        self.backup_dir = self.repo_path / ".agent_backup"
        self.logger = logger

    @staticmethod
    def _normalize_path(relative: str) -> str:
        cleaned = relative.strip().strip('"').strip("'")
        cleaned = cleaned.replace("\\", "/")
        parts = [p for p in cleaned.split("/") if p not in ("", ".")]
        return "/".join(parts)

    @classmethod
    def _safe_target_path(cls, relative: str) -> str:
        norm = cls._normalize_path(relative)
        upper = norm.upper()
        for tok in _PATCHER_PATH_FORBIDDEN:
            if tok.upper() in upper or "\n" in norm or "\r" in norm:
                raise ValueError(
                    f"Refusing to patch suspicious path ({len(norm)} chars): "
                    f"contains forbidden token {tok!r}. This indicates parser failure."
                )
        return norm

    def _make_backup(self, relative_path: str) -> bool:
        if not self.backup:
            return False

        src = self.repo_path / relative_path
        if not src.exists():
            return False

        backup_path = self.backup_dir / relative_path
        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, backup_path)
            return True
        except (OSError, IOError) as e:
            self.logger.warning(f"Failed to backup {relative_path}: {e}")
            return False

    def _replace_file(self, relative_path: str, content: str) -> bool:
        target = self.repo_path / Path(relative_path)
        if target.exists():
            self._make_backup(relative_path)

        return write_file_safe(target, content)

    def apply(self, validated_updates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        self.logger.info(f"Applying {len(validated_updates)} patches...")

        applied: List[Dict[str, Any]] = []
        failures: List[str] = []

        for update in validated_updates:
            if not update.get("valid"):
                bad_path = str(update.get("file_path", "unknown"))
                self.logger.warning(f"Skipping invalid update: {bad_path}")
                failures.append(bad_path)
                continue

            raw_path = update["file_path"]
            try:
                file_path = self._safe_target_path(raw_path)
            except ValueError as verr:
                self.logger.error(f"  Skipping: {verr}")
                failures.append(raw_path)
                continue

            action = update.get("action", "Replace Entire File")
            content = update["content"]

            target_abs = self.repo_path / Path(file_path)
            exists_str = "exists" if target_abs.exists() else "new"
            self.logger.info(
                f"  Applying: {file_path} [{exists_str}] ({len(content)} chars)"
            )

            success = False
            try:
                if "Replace Entire File" in action or "replace" in action.lower():
                    success = self._replace_file(file_path, content)
                else:
                    self.logger.info(
                        f"  Action '{action}' not supported, falling back to full replace"
                    )
                    success = self._replace_file(file_path, content)
            except Exception as e:
                self.logger.error(f"  Exception applying {file_path}: {e}")
                success = False

            if success:
                applied.append(
                    {
                        "file_path": file_path,
                        "action": action,
                        "content": content,
                        "bytes_written": len(content.encode("utf-8")),
                    }
                )
                self.logger.debug(f"  Wrote {len(content)} chars to {file_path}")
            else:
                failures.append(file_path)
                self.logger.error(
                    f"  FAILED to write {file_path} (see preceding write_file_safe "
                    f"log for filesystem error, e.g. invalid chars in path or permissions)"
                )

        self.logger.info(
            f"Patch complete: {len(applied)} applied, {len(failures)} failed"
        )

        if failures:
            # Join with semicolons — commas inside file names would mislead
            self.logger.warning(
                "Failed files: " + " ; ".join(str(f) for f in failures)
            )

        return applied
