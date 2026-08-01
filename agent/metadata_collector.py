import json
from pathlib import Path
from typing import Any, Dict, List

from config import METADATA_FILES
from utils.filesystem import get_relative_path, read_file_safe
from utils.logger import logger


class MetadataCollector:
    def __init__(self, repo_path: str | Path, repo_files: List[Dict[str, Any]]):
        self.repo_path = Path(repo_path).resolve()
        self.repo_files = repo_files
        self.logger = logger

    def _find_metadata_files(self) -> List[str]:
        found: List[str] = []
        for f in self.repo_files:
            if Path(f["path"]).name in METADATA_FILES:
                found.append(f["path"])
        return found

    def _parse_package_json(self, content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            data = json.loads(content)
            result["project_name"] = data.get("name", "unknown")
            result["project_version"] = data.get("version", "unknown")
            result["description"] = data.get("description", "")
            result["main_entry"] = data.get("main", "index.js")

            scripts = data.get("scripts", {})
            if scripts:
                result["scripts"] = list(scripts.keys())
                result["start_script"] = scripts.get("start", scripts.get("dev", ""))
                result["test_script"] = scripts.get("test", "")

            deps = list(data.get("dependencies", {}).keys())
            dev_deps = list(data.get("devDependencies", {}).keys())
            if deps:
                result["dependencies"] = deps
            if dev_deps:
                result["dev_dependencies"] = dev_deps

            if "express" in deps:
                result["framework"] = "Express.js"
            elif "fastify" in deps:
                result["framework"] = "Fastify"
            elif "koa" in deps:
                result["framework"] = "Koa"
            elif "nest" in deps or "@nestjs" in " ".join(deps):
                result["framework"] = "NestJS"
            elif "react" in deps:
                result["framework"] = "React"
            elif "vue" in deps:
                result["framework"] = "Vue"
            elif "next" in deps:
                result["framework"] = "Next.js"

            if "mongoose" in deps:
                result["database"] = "MongoDB (Mongoose)"
            elif "mongodb" in deps:
                result["database"] = "MongoDB"
            elif "sequelize" in deps:
                result["database"] = "SQL (Sequelize)"
            elif "typeorm" in deps:
                result["database"] = "SQL (TypeORM)"
            elif "prisma" in deps:
                result["database"] = "SQL (Prisma)"

        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse package.json: {e}")
        return result

    def _parse_requirements_txt(self, content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        deps: List[str] = []
        for line in content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                dep = line.split("=")[0].split("<")[0].split(">")[0].strip()
                if dep:
                    deps.append(dep)
        if deps:
            result["dependencies"] = deps
        result["language"] = "Python"

        if "flask" in " ".join(deps).lower():
            result["framework"] = "Flask"
        elif "django" in " ".join(deps).lower():
            result["framework"] = "Django"
        elif "fastapi" in " ".join(deps).lower():
            result["framework"] = "FastAPI"

        return result

    def _parse_readme(self, content: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        lines = content.strip().splitlines()
        if lines:
            result["readme_summary"] = " ".join(
                line.strip() for line in lines[:20] if line.strip()
            )[:500]
        return result

    def _detect_language(self, files: List[Dict[str, Any]]) -> str:
        ext_counts: Dict[str, int] = {}
        for f in files:
            ext = f["extension"]
            if ext:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

        js_count = ext_counts.get("js", 0) + ext_counts.get("jsx", 0)
        ts_count = ext_counts.get("ts", 0) + ext_counts.get("tsx", 0)
        py_count = ext_counts.get("py", 0)

        if py_count > js_count + ts_count:
            return "Python"
        if ts_count > js_count:
            return "TypeScript"
        if js_count > 0:
            return "JavaScript"
        return "Unknown"

    def _detect_structure(self, files: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        folders: Dict[str, List[str]] = {
            "models": [],
            "controllers": [],
            "routes": [],
            "services": [],
            "views": [],
            "middleware": [],
            "config": [],
            "utils": [],
            "tests": [],
        }

        for f in files:
            parts = Path(f["path"]).parts
            for folder in folders:
                if folder in parts:
                    folders[folder].append(f["path"])
                    break

        return {k: v for k, v in folders.items() if v}

    def collect(self) -> Dict[str, Any]:
        self.logger.info("Collecting project metadata...")

        metadata_files = self._find_metadata_files()
        metadata_contents: Dict[str, str] = {}
        parsed_metadata: Dict[str, Any] = {}

        for rel_path in metadata_files:
            abs_path = self.repo_path / rel_path
            content = read_file_safe(abs_path)
            if content is not None:
                metadata_contents[rel_path] = content
                name = Path(rel_path).name

                if name == "package.json":
                    parsed_metadata[name] = self._parse_package_json(content)
                elif name == "requirements.txt":
                    parsed_metadata[name] = self._parse_requirements_txt(content)
                elif name.lower() == "readme.md":
                    parsed_metadata[name] = self._parse_readme(content)

        language = self._detect_language(self.repo_files)
        structure = self._detect_structure(self.repo_files)

        entry_point = "index.js"
        for data in parsed_metadata.values():
            if "main_entry" in data:
                entry_point = data["main_entry"]
                break

        framework = None
        database = None
        dependencies: List[str] = []
        for data in parsed_metadata.values():
            if "framework" in data and not framework:
                framework = data["framework"]
            if "database" in data and not database:
                database = data["database"]
            if "dependencies" in data:
                dependencies.extend(data["dependencies"])

        project_info = {
            "language": language,
            "framework": framework,
            "database": database,
            "entry_point": entry_point,
            "structure": structure,
            "dependencies": sorted(set(dependencies)),
            "metadata_files_found": metadata_files,
            "metadata_contents": metadata_contents,
            "parsed_metadata": parsed_metadata,
        }

        self.logger.info(
            f"Project detected: {project_info['language']} | "
            f"Framework: {project_info['framework'] or 'N/A'} | "
            f"DB: {project_info['database'] or 'N/A'}"
        )
        if structure:
            self.logger.info(
                f"Structure detected: {', '.join(f'{k} ({len(v)})' for k, v in structure.items())}"
            )

        return project_info
