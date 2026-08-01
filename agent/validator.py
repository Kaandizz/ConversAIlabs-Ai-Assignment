import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils.filesystem import is_text_file, list_files
from utils.logger import logger


_SUSPICIOUS_PATH_TOKENS = (
    "ACTION:",
    "CONTENT:",
    "```",
    "FILE: ",
    "---",
    "\n",
    "\r",
    "javascript",
    "python",
)


class Validator:
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.logger = logger

    def _check_path_safety(self, relative_path: str) -> bool:
        try:
            resolved = (self.repo_path / relative_path).resolve()
        except (OSError, ValueError):
            return False
        try:
            resolved.relative_to(self.repo_path.resolve())
            return True
        except ValueError:
            return False

    def _check_path_not_mangled(self, file_path: str) -> Tuple[bool, List[str]]:
        issues: List[str] = []
        upper = file_path.upper()
        for tok in _SUSPICIOUS_PATH_TOKENS:
            if tok.upper() in upper:
                issues.append(
                    f"Path contains suspicious token {tok!r} — likely label leak from LLM response"
                )
        if len(file_path) > 300:
            issues.append(f"Path is too long ({len(file_path)} chars — looks like content leakage)")
        return (len(issues) == 0), issues

    def _check_basic_syntax(self, content: str, extension: str) -> Tuple[bool, List[str]]:
        issues: List[str] = []

        if not content.strip():
            issues.append("File content is empty")
            return False, issues

        brace_open = content.count("{")
        brace_close = content.count("}")
        paren_open = content.count("(")
        paren_close = content.count(")")
        bracket_open = content.count("[")
        bracket_close = content.count("]")

        if brace_open != brace_close:
            issues.append(f"Unbalanced braces: {{ {brace_open} }} vs {{ {brace_close} }}")
        if paren_open != paren_close:
            issues.append(f"Unbalanced parens: ( {paren_open} ) vs ( {paren_close} )")
        if bracket_open != bracket_close:
            issues.append(f"Unbalanced brackets: [ {bracket_open} ] vs [ {bracket_close} ]")

        if len(issues) > 2:
            return False, issues
        return True, issues

    def validate_updates(self, updates: List[Dict[str, str]]) -> Tuple[bool, List[Dict[str, Any]]]:
        self.logger.info(f"Validating {len(updates)} file updates...")

        validated: List[Dict[str, Any]] = []
        has_errors = False

        for update in updates:
            file_path = update.get("file_path", "").strip()
            action = update.get("action", "Replace Entire File")
            content = update.get("content", "")

            issues: List[str] = []
            ok = True

            if not file_path:
                issues.append("Missing file_path")
                ok = False

            if not content:
                issues.append("Missing/empty content")
                ok = False

            if file_path:
                path_ok, path_issues = self._check_path_not_mangled(file_path)
                if not path_ok:
                    issues.extend(path_issues)
                    ok = False

            if not self._check_path_safety(file_path):
                issues.append(f"Unsafe path escapes repo: {file_path}")
                ok = False

            ext = Path(file_path).suffix.lower().lstrip(".")
            syntax_ok, syntax_issues = self._check_basic_syntax(content, ext)
            if not syntax_ok:
                issues.extend(syntax_issues)
                ok = False

            target_abs = self.repo_path / file_path
            file_exists = target_abs.exists()
            if not file_exists and ok:
                self.logger.info(f"  Note: {file_path} will be created (new file)")

            result = {
                **update,
                "valid": ok,
                "issues": issues,
                "target_exists": file_exists,
                "extension": ext,
            }
            validated.append(result)

            if not ok:
                has_errors = True
                self.logger.warning(f"  Validation issues for {file_path!r}: {issues}")
            else:
                self.logger.debug(f"  Validated OK: {file_path}")

        if has_errors:
            self.logger.warning("Validation found issues in some updates")
        else:
            self.logger.info("All updates passed basic validation")

        return not has_errors, validated

    def validate_repo_state(self) -> bool:
        self.logger.info("Validating repository state...")
        files = list_files(self.repo_path)
        non_text = [f for f in files if not is_text_file(f)]
        self.logger.info(f"Repository has {len(files)} files ({len(non_text)} binary)")
        return True
