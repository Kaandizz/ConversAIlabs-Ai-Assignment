import json
from pathlib import Path
from typing import Any, Dict, List

from config import MAX_CONTEXT_TOKENS
from utils.filesystem import read_file_safe
from utils.helpers import count_tokens_approx, truncate_text
from utils.logger import logger


class ContextBuilder:
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.logger = logger

    def _read_file(self, rel_path: str) -> Dict[str, Any]:
        abs_path = self.repo_path / rel_path
        content = read_file_safe(abs_path)
        if content is None:
            return {"path": rel_path, "content": None, "error": "Could not read file"}
        return {"path": rel_path, "content": content, "lines": content.count("\n") + 1}

    def _format_metadata(
        self,
        project_metadata: Dict[str, Any],
        include_file_snippets: bool = True,
    ) -> str:
        lines: List[str] = []
        lines.append("## Project Information")
        lines.append(f"- **Language:** {project_metadata.get('language', 'Unknown')}")
        lines.append(f"- **Framework:** {project_metadata.get('framework', 'N/A')}")
        lines.append(f"- **Database:** {project_metadata.get('database', 'N/A')}")
        lines.append(f"- **Entry Point:** {project_metadata.get('entry_point', 'N/A')}")

        structure = project_metadata.get("structure", {})
        if structure:
            lines.append("- **Detected Folders:**")
            for folder, files in structure.items():
                lines.append(f"  - `{folder}/` ({len(files)} files): {', '.join(Path(f).name for f in files[:5])}{'...' if len(files) > 5 else ''}")

        dependencies = project_metadata.get("dependencies", [])
        if dependencies:
            lines.append(f"- **Key Dependencies:** {', '.join(dependencies[:10])}{'...' if len(dependencies) > 10 else ''}")

        if include_file_snippets:
            metadata_contents = project_metadata.get("metadata_contents", {})
            for name, content in metadata_contents.items():
                name_lower = name.lower()
                if name_lower.endswith("package.json") or name_lower.endswith("readme.md"):
                    snippet = content[:500]
                    lines.append(f"\n### `{name}` (snippet)")
                    lines.append("```")
                    lines.append(snippet)
                    if len(content) > 500:
                        lines.append("\n... (truncated)")
                    lines.append("```")

        return "\n".join(lines)

    def _format_file_content(self, file_info: Dict[str, Any]) -> str:
        path = file_info["path"]
        content = file_info["content"] or "[COULD NOT READ]"
        return f"\n### FILE: `{path}`\n```\n{content}\n```"

    def _format_structure_tree(self, tree_string: str) -> str:
        return f"\n## Repository Structure\n```\n{tree_string}\n```"

    def build_planner_context(
        self,
        product_request: str,
        repo_exploration: Dict[str, Any],
        project_metadata: Dict[str, Any],
        selected_files: List[str],
    ) -> Dict[str, str]:
        self.logger.info("Building planner context...")

        metadata_section = self._format_metadata(project_metadata, include_file_snippets=True)
        tree_section = self._format_structure_tree(repo_exploration["tree_string"])

        file_sections: List[str] = []
        for rel_path in selected_files:
            info = self._read_file(rel_path)
            file_sections.append(self._format_file_content(info))

        relevant_files_section = "\n".join(file_sections)

        context = {
            "PRODUCT_REQUEST": product_request,
            "PROJECT_METADATA": metadata_section,
            "REPOSITORY_STRUCTURE": tree_section,
            "RELEVANT_FILES": relevant_files_section,
        }

        total_tokens = count_tokens_approx("\n".join(context.values()))
        self.logger.info(f"Planner context: ~{total_tokens} tokens")

        if total_tokens > MAX_CONTEXT_TOKENS:
            self.logger.warning(
                f"Planner context too large ({total_tokens} > {MAX_CONTEXT_TOKENS}). "
                "Truncating file contents..."
            )
            budget = MAX_CONTEXT_TOKENS - count_tokens_approx(
                metadata_section + tree_section + product_request
            ) - 1000
            budget_per_file = budget // max(1, len(file_sections))
            truncated: List[str] = []
            for rel_path in selected_files:
                info = self._read_file(rel_path)
                content = info.get("content", "") or ""
                content = truncate_text(content, budget_per_file)
                entry = f"\n### FILE: `{rel_path}`\n```\n{content}\n```"
                truncated.append(entry)
            context["RELEVANT_FILES"] = "\n".join(truncated)

        return context

    def build_coder_context(
        self,
        product_request: str,
        implementation_plan: str,
        project_metadata: Dict[str, Any],
        selected_files: List[str],
    ) -> Dict[str, str]:
        self.logger.info("Building coder context...")

        metadata_section = self._format_metadata(project_metadata, include_file_snippets=False)

        file_contents: List[str] = []
        per_file_tokens: List[str] = []
        for rel_path in selected_files:
            info = self._read_file(rel_path)
            raw_content = info.get("content", "") or ""
            ftok = count_tokens_approx(raw_content)
            per_file_tokens.append(f"    {rel_path}: ~{ftok} tokens, {info.get('lines', 0)} lines")
            file_contents.append(self._format_file_content(info))

        self.logger.info("Selected files (for coder context):\n" + "\n".join(per_file_tokens))

        context = {
            "PRODUCT_REQUEST": product_request,
            "IMPLEMENTATION_PLAN": implementation_plan,
            "PROJECT_METADATA": metadata_section,
            "RELEVANT_FILES_CONTENT": "\n".join(file_contents),
        }

        total_tokens = count_tokens_approx("\n".join(context.values()))
        self.logger.info(
            f"Coder context: ~{total_tokens} tokens total "
            f"({len(file_contents)} files, output cap set separately via MAX_CODE_TOKENS)"
        )

        if total_tokens > MAX_CONTEXT_TOKENS:
            self.logger.warning(
                f"Coder context too large ({total_tokens} > {MAX_CONTEXT_TOKENS}). "
                "Truncating..."
            )
            budget = MAX_CONTEXT_TOKENS - count_tokens_approx(
                metadata_section + implementation_plan + product_request
            ) - 2000
            budget_per_file = budget // max(1, len(file_contents))
            truncated: List[str] = []
            for rel_path in selected_files:
                info = self._read_file(rel_path)
                content = info.get("content", "") or ""
                content = truncate_text(content, budget_per_file)
                entry = f"\n### FILE: `{rel_path}`\n```\n{content}\n```"
                truncated.append(entry)
            context["RELEVANT_FILES_CONTENT"] = "\n".join(truncated)

        return context

    def build_summary_context(
        self,
        product_request: str,
        implementation_plan: str,
        applied_patches: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        self.logger.info("Building summary context...")

        modified_summary_lines: List[str] = []
        for patch in applied_patches:
            path = patch["file_path"]
            action = patch.get("action", "Modified")
            size = len(patch.get("content", ""))
            modified_summary_lines.append(
                f"- `{path}` ({action}, {size} chars)"
            )

        context = {
            "PRODUCT_REQUEST": product_request,
            "IMPLEMENTATION_PLAN": implementation_plan,
            "MODIFIED_FILES_SUMMARY": "\n".join(modified_summary_lines) or "None",
        }
        return context
