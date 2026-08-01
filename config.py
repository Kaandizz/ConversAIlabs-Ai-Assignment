import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PROMPTS_DIR = BASE_DIR / "prompts"
AGENT_DIR = BASE_DIR / "agent"
UTILS_DIR = BASE_DIR / "utils"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

IGNORED_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".env",
    ".idea",
    ".vscode",
}

IGNORED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "*.log",
    "package-lock.json",
    "yarn.lock",
}

METADATA_FILES = [
    "package.json",
    "README.md",
    "requirements.txt",
    "setup.py",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
    "tsconfig.json",
    "babel.config.js",
    "webpack.config.js",
    ".eslintrc",
    ".prettierrc",
    "jest.config.js",
    "vite.config.js",
    "Dockerfile",
    "Makefile",
    ".env.example",
]

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "120000"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

# Output size caps per LLM call (keeps calls fast):
# - Planner: short plan, ~1000 words is plenty for this assignment
# - Coder: ~6 files × ~400 tokens/file ≈ 2400 tokens; 4096 leaves headroom
MAX_PLAN_TOKENS = int(os.getenv("MAX_PLAN_TOKENS", "1500"))
MAX_CODE_TOKENS = int(os.getenv("MAX_CODE_TOKENS", "4096"))
MAX_SUMMARY_TOKENS = int(os.getenv("MAX_SUMMARY_TOKENS", "600"))

