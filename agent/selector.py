import json
from pathlib import Path
from typing import Any, Dict, List

from utils.logger import logger


class FileSelector:
    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.logger = logger

    def _heuristic_select(
        self,
        product_request: str,
        project_metadata: Dict[str, Any],
        all_files: List[Dict[str, Any]],
    ) -> List[str]:
        selected: List[str] = []
        request_lower = product_request.lower()

        keywords: List[str] = []
        for word in [
            "note",
            "archive",
            "tag",
            "category",
            "categor",
            "favorite",
            "favourite",
            "search",
            "sort",
            "filter",
            "markdown",
            "organize",
            "organise",
            "user",
            "auth",
            "comment",
            "label",
            "folder",
        ]:
            if word in request_lower:
                keywords.append(word)

        for f in all_files:
            path_lower = f["path"].lower()
            name_lower = Path(f["path"]).name.lower()

            score = 0

            structure = project_metadata.get("structure", {})
            for folder, paths in structure.items():
                if f["path"] in paths:
                    if folder in ("models", "controllers", "routes", "services"):
                        score += 5
                    elif folder == "middleware":
                        score += 2

            for kw in keywords:
                if kw in path_lower:
                    score += 10
                if kw in name_lower:
                    score += 15

            if f["extension"] in ("js", "jsx", "ts", "tsx", "py", "go", "rs", "java"):
                score += 1

            if f.get("is_metadata"):
                score += 3

            if score > 0:
                selected.append(f["path"])

        if not selected:
            structure = project_metadata.get("structure", {})
            for key in ("models", "controllers", "routes"):
                if key in structure:
                    selected.extend(structure[key])

        result = []
        for s in selected:
            if s not in result:
                result.append(s)
        return result

    def _llm_rank(
        self,
        product_request: str,
        project_metadata: Dict[str, Any],
        candidates: List[str],
        top_k: int = 15,
    ) -> List[str]:
        if len(candidates) <= top_k:
            return candidates

        language = project_metadata.get("language", "Unknown")
        framework = project_metadata.get("framework", "N/A")
        structure = project_metadata.get("structure", {})

        system_prompt = (
            "You are a Senior Software Engineer. Rank files by relevance to the feature request. "
            "Return ONLY valid JSON: {\"ranked_files\": [\"file1.js\", \"file2.js\", ...]} "
            "with the most relevant files first. Rank files that match project structure "
            "(models, controllers, routes) higher if their names relate to the request."
        )

        structure_desc = json.dumps(
            {k: v for k, v in structure.items() if v}, indent=2
        )
        user_prompt = f"""
## Feature Request
{product_request}

## Project
Language: {language}
Framework: {framework}

## Project Structure Folders
{structure_desc}

## Candidate Files (rank these)
{json.dumps(candidates, indent=2)}

Return ONLY a JSON object with a "ranked_files" array.
""".strip()

        try:
            response = self.llm_client.chat(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(response)
                ranked = data.get("ranked_files", [])
                if isinstance(ranked, list) and ranked:
                    result = []
                    for f in ranked:
                        if f in candidates and f not in result:
                            result.append(f)
                    for f in candidates:
                        if f not in result:
                            result.append(f)
                    return result[:top_k]
            except json.JSONDecodeError:
                pass
        except Exception as e:
            self.logger.warning(f"LLM file ranking failed, falling back to heuristic: {e}")

        return candidates[:top_k]

    def select(
        self,
        product_request: str,
        project_metadata: Dict[str, Any],
        repo_exploration: Dict[str, Any],
        max_files: int = 20,
    ) -> List[str]:
        self.logger.info("Selecting relevant files...")

        all_files = repo_exploration["files"]

        heuristic = self._heuristic_select(product_request, project_metadata, all_files)

        if not heuristic:
            heuristic = [
                f["path"]
                for f in all_files
                if f["extension"] in ("js", "jsx", "ts", "tsx", "py")
            ][:50]

        ranked = self._llm_rank(
            product_request, project_metadata, heuristic, top_k=max_files
        )

        selected = ranked[:max_files]

        self.logger.info(
            f"Selected {len(selected)} files (from {len(heuristic)} heuristic candidates)"
        )
        for i, f in enumerate(selected, 1):
            self.logger.debug(f"  {i:2d}. {f}")

        return selected
