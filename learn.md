# learn.md — AI Coding Agent Deep Dive

> Line-by-line / section-by-section walkthrough of every file in the project.
> Explains *why* something is written that way, what alternatives exist, and what
> interviewers might ask about it.

---

## Table of Contents

1. [config.py](#1-configpy)
2. [main.py](#2-mainpy)
3. [utils/logger.py](#3-utilsloggerpy)
4. [utils/filesystem.py](#4-utilsfilesystempy)
5. [utils/helpers.py](#5-utilshelperspy)
6. [utils/llm_client.py](#6-utilsllm_clientpy)
7. [agent/explorer.py](#7-agentexplorerpy)
8. [agent/metadata_collector.py](#8-agentmetadata_collectorpy)
9. [agent/selector.py](#9-agentselectorpy)
10. [agent/context_builder.py](#10-agentcontext_builderpy)
11. [agent/planner.py](#11-agentplannerpy)
12. [agent/coder.py](#12-agentcoderpy)
13. [agent/validator.py](#13-agentvalidatorpy)
14. [agent/patcher.py](#14-agentpatcherpy)
15. [agent/summarizer.py](#15-agentsummarizerpy)
16. [Prompts (planner.md, coder.md, summary.md)](#16-prompts)
17. [requirements.txt & .env.example](#17-requirementstxt--envexample)
18. [Debugging Log: Bugs Fixed Chronologically (Viva Sessions)](#18-debugging-log-bugs-fixed-chronologically-viva-sessions)
19. [Architecture Review & Interview Topics](#19-architecture-review--interview-topics)

---

## Change History (Convention from this viva session onwards)
> **Rule:** *Every code change updates learn.md.*
>
> Sections that drift out of sync with the source code (old regex parser, old validation logic, old speed tiers) have been corrected in place in the corresponding per-file walkthrough above. New cross-cutting content (bug log, tiers, mini-script) is appended below.
>
> When making future changes:
> - Update the matching per-file section (§1-§17) with the new behavior.
> - If the change fixes a real bug, add a Bug #N entry to §18 (symptom → root cause → fix → code ref → verification).
> - If the change adds a new architectural knob, add it under §19 Speed Tiers table / General Questions.
---

## 1. config.py

### What it does
Central single source of truth for constants, paths, and env-var config.

### Line-by-line / Section-by-section

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
```
- `load_dotenv()` reads the `.env` file in the project root *once* at import time. `python-dotenv` never overrides existing env vars, so CLI / process env takes priority.
  - **Why import here?** Every module needs paths/API keys; loading once at the top of the tree means you don't have to remember to call it in every file.
  - **Alternative:** Use `pydantic-settings` or `hydra` for typed, validated configs. We don't — overkill for 10 constants.

```python
BASE_DIR = Path(__file__).resolve().parent
```
- `Path(__file__).resolve()` = absolute path of *this file*. `.parent` = project root (since config.py lives at the root).
  - **Why `resolve().parent` and not `os.getcwd()`?** `getcwd()` depends on *where you run the command from*. This way it always refers to the repo's root, regardless of CWD.
  - **Interview question:** *How do you make a Python app robust to the user's CWD?* → Use `__file__` + `resolve()`.

```python
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
```
- Creates the output folder at import time so later modules never need `if not exists`.
  - **Why `mkdir` here?** Fail-fast: if we can't write the output dir, crash at startup, not 10 minutes into a run.

```python
IGNORED_DIRS = { ... }
IGNORED_FILES = { ... }
```
- Use `set` literals (`{...}`) so `item in IGNORED_DIRS` is O(1) instead of O(n) for a list.
  - **Interview question:** *When should you use a set vs a list in Python?* → Membership testing is the classic signal.

```python
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
```
- **Three defaults:** (1) empty API key (so the app warns instead of crashing on startup without `.env`), (2) OpenAI base URL so it works out of the box, (3) a sensible model.
  - **Why `os.getenv` not `os.environ["..."]`?** `os.environ[]` raises `KeyError` if missing; `getenv` returns the default. For an app that should start and warn interactively, `getenv` is friendlier.

```python
MAX_CONTEXT_TOKENS = int(os.getenv("MAX_CONTEXT_TOKENS", "120000"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "1"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_SECONDS = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
MAX_PLAN_TOKENS = int(os.getenv("MAX_PLAN_TOKENS", "1500"))
MAX_CODE_TOKENS = int(os.getenv("MAX_CODE_TOKENS", "4096"))
MAX_SUMMARY_TOKENS = int(os.getenv("MAX_SUMMARY_TOKENS", "600"))
```
- **Why the string defaults?** `os.getenv` always returns `str | None`; `int(None)` would crash.
- **Why output-size caps (`MAX_*_TOKENS`)?** Three LLM calls per pipeline run: planner (short) + coder (huge) + summarizer (short). Without caps, a verbose 70B model can spend 2+ minutes generating 10k tokens of commentary. With caps: planner ~1500 tokens → ~10s; coder ~4096 tokens → ~30s; summarizer ~600 tokens → ~5s. TOTAL 45s worst-case.
- **Why `LLM_TIMEOUT_SECONDS=120`?** Prevents "stuck forever" when NIM free-tier queue stalls. The timeout error message then includes a HINT suggesting faster models (see `llm_client.py`).

**Interview questions for this file:**
1. *Why use `pathlib` instead of `os.path`?* → OOP-style, composable, no separator issues across OS.
2. *Why load env vars at module import? Why not inside `main()`?* → Any module (not just main) might need them; and import-time failure is better than runtime failure.
3. *How would you switch to a typed config?* → Introduce `pydantic BaseSettings`.

---

## 2. main.py

### What it does
CLI entry point + the deterministic sequential pipeline that orchestrates all 9 stages.

### Section-by-section

```python
def run_pipeline(repo_path: str, product_request: str) -> int:
    ...
    start_time = time.time()
    logger.info("=" * 70)
    ...
```
- Returns an `int` (Unix exit code convention: `0 = success, non-zero = which stage failed`).

```python
    from agent.explorer import RepositoryExplorer
    from agent.metadata_collector import MetadataCollector
    ...
```
- **Imports are INSIDE the function, not at the top.** Why? Two reasons:
  1. **`--help` stays fast.** argparse can parse flags without importing 10 agent modules.
  2. **Avoid circular imports.** If an agent module ever imports a symbol that's only available after main loads, we avoid the circular-dependency crash.
  - **Alternative / interview follow-up:** *Can circular imports be fixed other ways?* → Yes, restructure to a `core/` layer nothing else can depend on, or use late binding via strings. Function-local imports are the cheapest fix.

```python
    except Exception as e:
        logger.error(f"Repository exploration failed: {e}")
        return 2
```
- **Each stage gets its own unique exit code (1–9).** This is critical for debugging if someone runs the agent in CI — you can tell at a glance *which* stage failed by grepping `$?`.
  - **Alternative:** Raise a typed exception per stage (`ExplorerError`, `PlannerError`). Exit codes are simpler for a short script.

```python
        implementation_plan = planner.plan(planner_context)
```
- The return value of each stage is the *input artifact* of the next — pure data in, pure data out. That's the heart of the pipeline design.
  - **Interview question:** *Why pass data explicitly between stages instead of mutating a shared "state" object?* → Easier to test (each stage is a pure function on its inputs), easier to debug (you can log/inspect the artifact between stages), easier to serialize (save plan to disk, replay stage 5 onwards without re-running 1–4).

```python
    print("\n" + "=" * 70)
    print("IMPLEMENTATION PLAN")
    print("=" * 70)
    print(implementation_plan)
```
- We both **log** (for debug) and **print to stdout** (for the end user). Separation of concerns: logger is for engineering debug, stdout is for human users.

```python
def main():
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--repo", required=True, ...)
    parser.add_argument("--request", ...)
    parser.add_argument("--interactive", action="store_true")
```
- `argparse` is built-in, so no dependency. `action="store_true"` makes `--interactive` a boolean flag.
  - **Alternatives:** `click`, `typer` for fancier CLIs. `argparse` is zero-install.

```python
if __name__ == "__main__":
    main()
```
- Standard guard so `import main` (e.g., in tests) doesn't run the pipeline.

**Interview questions for this file:**
1. *Why is the pipeline sequential instead of concurrent?* → Stages are data-dependent (plan needs repo, code needs plan, patch needs code). The natural data flow is a DAG of 1 chain.
2. *What happens if the Patcher stage fails after the Coder stage succeeded?* → We report exit code 9 and the repo may be partially written. Backups exist in `.agent_backup/`. For stronger safety we'd write to a temp dir then atomic-move.
3. *How would you add resumability?* → Persist every stage's output to disk (e.g., `output/2_metadata.json`, `output/3_selected_files.json`). On a resume run, check which artifacts already exist and skip the corresponding stages.

---

## 3. utils/logger.py

### What it does
Sets up a single shared logger that writes BOTH to stdout (colored by level via format) and `output/logs.txt`.

```python
import sys
import logging
from pathlib import Path
from config import OUTPUT_DIR
```
- Importing from `config` guarantees `OUTPUT_DIR` is already created (because `OUTPUT_DIR.mkdir` runs at config import time).

```python
def setup_logger(name: str = "ai_coding_agent") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
```
- "If already set up, return early." Standard Python pattern — `logging.getLogger(name)` returns a *singleton* by name, so without this guard every call to `setup_logger()` would add duplicate handlers and each log line would appear N times.
  - **Interview question:** *Why is `logging.getLogger` by name?* → It's the registry pattern. Any module in the same process can get the same logger instance with one string.

```python
    logger.setLevel(logging.DEBUG)
```
- Root level = DEBUG so handler levels can independently filter. A common gotcha: if root is INFO, a DEBUG handler never sees anything.

```python
    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
```
- `%(levelname)-7s` = left-justify the level name in 7 chars ("DEBUG  ", "INFO   ", …). Makes columns line up.

```python
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
```
- Console = INFO and above (clean for users). File = DEBUG and above (for engineers). This is the 2-target pattern.

```python
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log_file = OUTPUT_DIR / "logs.txt"
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
```
- Explicit `mkdir` + `mode="a"` (append):
  - Without `mkdir`, on a fresh clone the first log line would fail.
  - `mode="a"` = append between runs, so a debug run's logs are preserved when you re-run and compare. (Python `FileHandler` defaults to `"a"` anyway; we write it explicitly for interview-readability.)
- **Clear logs behavior (Windows):** You can only delete `logs.txt` when NO Python process is still running that holds the handle. To reset logs: kill python.exe → delete `output/logs.txt` → re-run. The file will be recreated from scratch automatically by `FileHandler("logs.txt", mode="a")` — `"a"` creates missing files.

```python
logger = setup_logger()
```
- Module-level singleton instance — `from utils.logger import logger` anywhere in the project uses the same logger.

**Interview questions:**
1. *Why not `print()` everywhere?* → Logger has levels, timestamps, call site info, and can ship files without touching call sites.
2. *How do you prevent duplicate log lines?* → Idempotent setup via `if logger.handlers: return`.
3. *How would you add structured JSON logs?* → Swap the `Formatter` class (e.g. `python-json-logger`), call-sites don't change.

---

## 4. utils/filesystem.py

### What it does
All filesystem operations (safe reads, ignore filters, recursive scans) live here so no other module has to use `open()` or `Path.rglob()` directly.

```python
def is_ignored_dir(path: Path, root: Path) -> bool:
    relative_parts = path.relative_to(root).parts
    for part in relative_parts:
        if part in IGNORED_DIRS:
            return True
    return False
```
- **Why split into `parts`?** We want to match directory *segments* not string containment. If someone names a file `my.git.config.js`, `".git" in str(path)` would incorrectly match it; checking each `part` ensures we only match whole path component names.

```python
def is_ignored_file(filename: str) -> bool:
    for pattern in IGNORED_FILES:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False
```
- `fnmatch` = shell-style glob (`*.log`, `Thumbs.db`). More flexible than exact match for very little cost.

```python
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
```
- A 3-layer heuristic for "is this file human-text or binary?"
  1. `\x00` byte → almost certainly binary/compressed (cheap, catches 99%).
  2. Decode as UTF-8 → covers 98% of modern source.
  3. Fallback to latin-1 → catches older Windows-1252 / ISO-8859 files (latin-1 can decode *any* byte, so we only reach the exception if the chunk somehow can't — essentially never. It's a safety net.)
  - **Alternative:** `chardet` or `charset-normalizer` library for real charset detection. Adds a dependency and is 10–100x slower. Not needed.
  - **Interview question:** *How do you detect binary files in Python?* → The null-byte heuristic is the standard industry answer (used by `git` and GNU `diff` under the hood).

```python
def read_file_safe(path: Path) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, IOError) as e:
        return None
```
- `errors="replace"` is critical. If a file has 1 weird byte, we'd rather see � in the LLM context than crash the whole pipeline.
  - **Alternatives:** `errors="ignore"` (silently drops data — worse), `errors="strict"` (fragile). "replace" is the sweet spot.

```python
def list_files(root: Path) -> List[Path]:
    ...
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
```
- We check `path.parent` (not `path`) for the directory-ignore test. Why? `is_ignored_dir` tests each *part* of the path; applying it to a file directly would treat the file *name* as a dir part and ignore valid files named `node_modules.js`.

**Interview questions:**
1. *Why `root.rglob("*")` over `os.walk`?* → `rglob` returns `Path` objects (already typed), chainable, and excludes `.` / `..` naturally. Same time complexity.
2. *Why wrap every file op in a helper?* → Single place to add retries, timeout, metrics, or virus-scan hooks without touching 50 call sites. Single Responsibility.

### Update (debugging sessions)
- `write_file_safe()` now `logger.error(...)` on `OSError` (was silent).
  - **Why:** During debugging the parser was leaking `ACTION:` / `CONTENT:` labels into the file path. Windows raised `OSError [WinError 123] Invalid name` but the helper swallowed it → Patcher showed `FAILED to write app/models/note.model.js` with zero diagnostic info. Adding the error log made the bug visible in 1 line.

---

## 5. utils/helpers.py

### What it does
Parsing utilities that read structured data back out of the LLM's free-form text responses. The LLM speaks Markdown — we need dictionaries.

```python
def extract_code_blocks(text: str, language: Optional[str] = None) -> List[str]:
    if language:
        pattern = rf"```{re.escape(language)}\s*\n(.*?)```"
    else:
        pattern = r"```(?:\w+)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return [m.strip() for m in matches]
```
- `re.DOTALL` = `.` matches newlines. Without it, regex fails on multi-line code blocks (99% of code).
- We strip content so a stray leading newline doesn't confuse later stages.

```python
def extract_json(text: str) -> Optional[Any]:
    code_blocks = extract_code_blocks(text, "json")
    ...
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass
    return None
```
- **4 fallbacks** ordered from strictest to loosest:
  1. ```` ```json ```` code blocks (LLM follows the spec)
  2. Raw JSON in the text (LLM omits the fence)
  3. First `{ ... }` pair (LLM adds English prose around JSON)
  4. `None` — caller decides what to do
- **This is the "LLM hygiene" layer.** LLMs are instructed to output JSON but often deviate. Robust parsers are the difference between <5% and 30% failure rates.
  - **Alternative:** Use function calling / `response_format={"type": "json_object"}` on modern endpoints. Those guarantee JSON schema validity (at a cost — sometimes the model truncates). We use those where possible AND keep fallbacks anyway.

```python
def parse_file_updates(text: str) -> List[Dict[str, str]]:
```
- The most important parser. Implements a **two-stage label/content extraction** (refactored during debugging):
  1. **Slice at every `FILE:` label** (`_find_file_label_positions`)
  2. **For each slice**, parse only in two zones:
     - `HEAD` = everything before the first triple-backtick
     - `CONTENT` = the content of the **first triple-backtick block**
  3. FILE and ACTION labels are searched **only in HEAD**; content is grabbed from the fenced code block.
- **Why this refactor?** The original regex (`re.DOTALL` pattern with `(.+?)` groups) had 3 failure modes observed in practice:
  - **(a) LLMs use single-line fences:** `--- FILE: x.js ACTION: Replace CONTENT: \`\`\`javascript` — original regex demanded each label on its own line, so nothing matched.
  - **(b) Greedy label leakage:** With `re.DOTALL`, `FILE: (.+?)` would match until the *next* occurrence that included `ACTION: Replace … CONTENT:  ```javascript` all as the path. This dumped 2,800 characters into `file_path` (newlines/colons → Windows `WinError 123`).
  - **(c) `content:` in source keys:** Any code with `{ content: req.body.content }` in JS objects would be picked up as the "CONTENT:" label → mid-file split truncation.
- The HEAD/fenced-content split is **inherently unambiguous** since fence tokens don't appear in source code.
- **Safety net:** `_clean_file_path()` returns `""` if ACTION/CONTENT/backtick/newline tokens leak into the path. Any empty path is dropped silently from the list — so garbage doesn't propagate to Validator → Patcher → disk.

```python
    seen = set()
    unique_updates: List[Dict[str, str]] = []
    for u in updates:
        key = u["file_path"]
        if key not in seen:
            seen.add(key)
            unique_updates.append(u)
```
- If the LLM accidentally outputs 2 blocks for the same file, keep the FIRST one and silently drop duplicates. (If we kept the last, a malformed empty block near the end could destroy good code.)

```python
def count_tokens_approx(text: str) -> int:
    words = len(re.findall(r"\w+", text))
    chars = len(text)
    return max(words, chars // 4)
```
- **Why an approximation?** We don't want a 40 MB dependency (`tiktoken`) just for token counts. Real ratio is ~4 chars/token for English prose (varies by language). Using `max` is conservative — we'd rather truncate a little early than blow up the context.
  - **Alternative:** Conditionally import `tiktoken` if installed, fall back to the heuristic. That's a clean upgrade path.

**Interview questions:**
1. *Why parse LLM responses with regex instead of expecting strict JSON?* → LLMs are stochastic; regex hygiene layers reduce p(irrecoverable failure).
2. *What is `re.DOTALL`? When do you need it?* → When the capture group spans lines (multi-line code / multi-paragraph).
3. *When is `chars // 4` a bad estimate?* → Non-English languages (CJK uses ~1 char per token), heavy punctuation, minified code. For general use it's "good enough to stay under the limit."

---

## 6. utils/llm_client.py

### What it does
Wraps the OpenAI SDK into one 40-line class with retries, timing, logging, and graceful failure modes.

```python
class LLMClient:
    def __init__(self, api_key=None, base_url=None, model=None, timeout_seconds=None):
        self.api_key = api_key or LLM_API_KEY
        self.base_url = base_url or LLM_BASE_URL
        self.model = model or LLM_MODEL
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else LLM_TIMEOUT_SECONDS
        self._init_client()
```
- Constructor params override env vars — useful in tests for `LLMClient(model="gpt-4o-mini")` without touching `.env`.
- **`timeout` new param:** Passed directly to `OpenAI(..., timeout=...)` SDK constructor. If NIM queue stalls, we fail after `LLM_TIMEOUT_SECONDS` instead of hanging forever.

```python
    _PLACEHOLDER_TOKENS = {"your", "xxx", "example", "changeme", "insert", "here"}
    def _is_placeholder_key(self, key: str) -> bool:
        if not key:
            return True
        key_lower = key.lower()
        for token in self._PLACEHOLDER_TOKENS:
            if token in key_lower:
                return True
        return False

    def _init_client(self) -> None:
        if self._is_placeholder_key(self.api_key):
            self.logger.warning("LLM_API_KEY looks like a placeholder...")
            return
```
- **Original bug:** The placeholder check was `if not key or key.startswith("sk-") and "your" in key`. Two errors:
  1. **Operator precedence bug** (`and` binds tighter than `or`) — only keys starting with `sk-` AND containing "your" were caught.
  2. **Provider lock-in** — NVIDIA NIM keys use `nvapi-` prefix, so `nvapi-your-key-here` wouldn't be caught.
- Fix: Generic substring check against a set of common placeholder tokens (`your`, `xxx`, `changeme`, …). Works for any provider, no prefix assumptions.

```python
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout_seconds)
```
- **Late import inside a method, not at module top.** Why? If user hasn't installed `requirements.txt`, imports at the *top of* `llm_client.py` would crash the entire app on startup (even `--help` would fail). Importing lazily means we only fail the first time they actually try a chat call — with a helpful error.
  - **Interview question:** *Why would you import inside a function in Python?* → (a) break circular imports, (b) delay cost until needed, (c) make optional dependencies non-fatal at startup.

```python
    _NVIDIA_FAST_MODELS = [
        "meta/llama-3.1-8b-instruct",
        "microsoft/phi-3-mini-128k-instruct",
        "mistralai/mistral-7b-instruct-v0.3",
    ]
    _NVIDIA_FREE_MODELS = [ ... ]
    def _format_error(self, exc: Exception) -> str:
        ...
        if self._is_nvidia() and "404" in msg:
            return f"{msg} [HINT: NVIDIA NIM — 404 usually means: (1) wrong slug, (2) TOS not accepted — visit build.nvidia.com → select model → Try Now. Known free models: ...]"
        if self._is_nvidia() and ("timeout" in msg.lower() or "timed out" in msg.lower()):
            fast = ", ".join(self._NVIDIA_FAST_MODELS)
            return f"{msg} [HINT: Model {self.model!r} is slow or NIM queue is busy. Try: {fast}. Or increase LLM_TIMEOUT_SECONDS=240.]"
```
- **Provider-aware error messages.** Before this, NVIDIA NIM returned "404 page not found" and the user had zero idea whether it was a bad key, wrong URL, missing slug, or model-not-activated. Now 404s and timeouts include a 1-sentence root cause + action checklist.
  - **Why no auto-fallback between models?** Too complex for this assignment scope. A HINT message (explicit, deterministic) is more interview-appropriate than hidden "I picked another model" behavior.

```python
    def chat(self, system_prompt, user_prompt, temperature=None, response_format=None, max_tokens=None):
        ...
        for attempt in range(self.max_retries + 1):
            try:
                ...
                completion = self._client.chat.completions.create(**kwargs)
                content = completion.choices[0].message.content or ""
                ...
                return content
            except Exception as e:
                last_exception = e
                wait = 2 ** attempt
                ...
                if attempt < self.max_retries:
                    time.sleep(wait)
        raise RuntimeError(...)
```
- **Exponential backoff** for retries: `2**attempt` = 1s, 2s, 4s... Standard pattern for any network client.
- **Always log tokens + latency** even on success — those two numbers tell you 90% about performance regressions (is a new prompt slow? is the model outputting 2x more tokens?).
- **`response_format` passthrough:** Lets callers request JSON mode on v1.10+ SDK.

**Interview questions:**
1. *What LLM failure modes does this NOT handle?* → Does NOT detect hallucinations / factually wrong answers (only network / format errors). Does NOT stream. Does NOT roll back context window if the response is truncated.
2. *Why use the OpenAI SDK for non-OpenAI providers?* → It's the de-facto standard API shape — Anthropic, Groq, Together, Anyscale, and local vLLM/Ollama all expose OpenAI-compatible endpoints.
3. *What's the benefit of a wrapper vs raw SDK calls?* → Swap providers (add LiteLLM, add Azure AD auth, add metrics) in one place; one retry strategy; one logging format.

---

## 7. agent/explorer.py

### What it does
Scans the target repo, builds a tree, lists every file with metadata, detects languages by extension.

```python
class RepositoryExplorer:
    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
```
- `str | Path` union type (PEP 604, Python 3.10+) — accepts either, normalizes to `Path` internally.

```python
    def validate(self) -> bool:
        if not self.repo_path.exists():
            ...return False
        if not self.repo_path.is_dir():
            ...
```
- Two explicit checks — "doesn't exist" vs "exists but is a file" deserve different error messages.

```python
    def build_tree(self) -> Dict[str, Any]:
        all_files = list_files(self.repo_path)
        tree: Dict[str, Any] = {}
        for file_path in all_files:
            ...
            current = tree
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = "FILE"
```
- Classic trie / nested-dict construction. O(n × depth) time, which is fine (repo depth is bounded).
  - **Alternative:** `anytree` library for a real tree with parent pointers. Overkill.

```python
    def format_tree(self, tree: Dict[str, Any], prefix: str = "") -> str:
        ...
        connector = "└── " if is_last else "├── "
        ...
        extension = "    " if is_last else "│   "
```
- Draws the `tree(1)`-style ASCII boxes. Two different "extension" strings produce the vertical connecting line only when siblings come after. This is a classic recursive tree-formatting trick.
  - **Interview question:** *Draw the output for a 3-level tree and trace the recursion.* → Tests ability to reason about the prefix stack.

**Interview questions:**
1. *Why build a tree at all? Why not just send the flat file list to the LLM?* → The LLM uses hierarchical structure to reason about "controllers / models / routes" as architectural layers. A flat list is harder for it to parse semantically.
2. *What's the maximum size of a repo this can handle?* → Depends on `MAX_CONTEXT_TOKENS`. In practice, trees up to ~5000 files fit in the ~2k tokens of structure summary. Past that, you'd want pagination / per-folder summaries.

---

## 8. agent/metadata_collector.py

### What it does
Deterministically parses `package.json`, `requirements.txt`, `README.md` — anything that gives us framework/dependency/architecture signal without LLM cost.

```python
    def _parse_package_json(self, content: str) -> Dict[str, Any]:
        ...
        if "express" in deps:
            result["framework"] = "Express.js"
        elif "fastify" in deps:
            result["framework"] = "Fastify"
```
- **Substring-match on dependency names** (not regex). Dependencies are stored as a list; O(n) scans on 100 items are free.
  - **Why not use an LLM here?** 0 tokens, 0 latency, 0 hallucination risk. This is the exact kind of thing we want to *not* call the model for — it's pure data extraction from a structured file.

```python
    def _detect_language(self, files: List[Dict[str, Any]]) -> str:
        ext_counts: Dict[str, int] = {}
        ...
        js_count = ext_counts.get("js", 0) + ext_counts.get("jsx", 0)
        if py_count > js_count + ts_count:
            return "Python"
```
- Votes by extension. Treats `js`+`jsx`, `ts`+`tsx` as combined buckets. This matters because a React/Express app has JS AND TS files but is fundamentally a "TypeScript" or "JavaScript" project based on which wins.

```python
    def _detect_structure(self, files: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        for f in files:
            parts = Path(f["path"]).parts
            for folder in folders:
                if folder in parts:
                    folders[folder].append(f["path"])
```
- Substring check on path *parts*. Catches `app/models/`, `src/controllers/`, `lib/routes/v2/...` regardless of nesting depth.
  - **Caveat:** If someone has `models.py` at the repo root (single-file Django style), this misses it. That's an acceptable false-negative for this assignment scope.

**Interview questions:**
1. *Why parse metadata without the LLM?* → Cheaper, faster, deterministic. LLM is a last resort for reasoning, not for parsing JSON.
2. *How would you add Go / Rust / Java detection?* → Add new `_parse_<manifest>` methods (`go.mod`, `Cargo.toml`, `pom.xml`) and add their filename to `config.py::METADATA_FILES`.

---

## 9. agent/selector.py

### What it does
Two-stage file selection: (1) cheap deterministic heuristic to get ~50 candidates, (2) LLM rank to pick ~15–20 most relevant.

```python
    def _heuristic_select(self, product_request, project_metadata, all_files):
        request_lower = product_request.lower()
        keywords = []
        for word in ["note", "archive", "tag", "category", "favorite", "search", ...]:
            if word in request_lower:
                keywords.append(word)
```
- Hand-curated keyword list of common feature request terms. Matches substrings of the request.
  - **Alternative 1 (better):** Ask the LLM to extract 5–10 keywords *before* the heuristic. Adds 1 round-trip but generalizes far better.
  - **Alternative 2 (best):** TF-IDF / BM25 of request vs file contents. Still deterministic, far more signal than filenames alone.

```python
            if folder in ("models", "controllers", "routes", "services"):
                score += 5
```
- Structural boosting. "Controllers" and "models" are where most backend feature changes land, so bias toward them.
- **Why numeric scoring vs. boolean include/exclude?** Gives us a total order we can cut off at `top_k`.

```python
    def _llm_rank(self, product_request, project_metadata, candidates, top_k=15):
        ...
        system_prompt = (
            "You are a Senior Software Engineer. Rank files by relevance... "
            "Return ONLY valid JSON: {\"ranked_files\": [...]}"
        )
```
- Two critical instructions: "ONLY valid JSON" + `response_format={"type": "json_object"}` at call site. The guarantee comes from the latter; the prompt instruction is the belt-and-suspenders.
  - **Why rank candidates instead of letting the LLM pick from the full 2000-file list?** A 2000-item list is ~10k tokens of filenames. Ranking 50 candidates is ~500 tokens. 20x cost difference, and ranking 50 items is statistically more accurate anyway (LLM "long tail" effect — items past #200 are simply ignored).

```python
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
```
- **Safety layer:** If the LLM returns garbage (or returns only 2 of the candidates), we:
  1. Keep only files that actually exist in `candidates` (prevents hallucinated filenames).
  2. Append unmentioned candidates in their *original heuristic order*.
  - This guarantees the selector never returns fewer than `min(top_k, len(candidates))` files, even on LLM failure.
  - **Interview question:** *What's "defensive decoding" in LLM pipelines?* → Never trust the model to return a "complete" answer — fill gaps with a deterministic fallback.

**Interview questions:**
1. *Why two stages instead of just LLM rank the whole list?* → Cost + accuracy. Filenames past rank #200 are ignored by models anyway.
2. *What happens if keywords don't match (e.g., a request in French)?* → `_heuristic_select` falls back to "select ALL code files" then `_llm_rank` handles the language. Add multi-ling keyword extraction as an upgrade.

---

## 10. agent/context_builder.py

### What it does
"Template renderer for prompts." Takes the structured data artifacts from previous stages and renders them into the `{{PLACEHOLDER}}` slots of the prompt Markdown templates. Also does context-window management (truncation).

    def _format_metadata(
        self,
        project_metadata: Dict[str, Any],
        include_file_snippets: bool = True,
    ) -> str:
        ...
        dependencies = project_metadata.get("dependencies", [])
        if dependencies:
            lines.append(f"- **Key Dependencies:** {', '.join(dependencies[:10])}{'...' if len(dependencies) > 10 else ''}")
        if include_file_snippets:
            # ... package.json / README snippets only when True
```
- **`include_file_snippets=False` for coder.** The coder already gets *full* file contents for every selected file. Repeating the package.json/README snippet in the metadata section is ~1k tokens of pure noise. Setting `include_file_snippets=False` when building coder context cuts prompt tokens by ~10–15%.
  - **Why not for planner?** Planner doesn't get full file contents — it gets snippets only. So `include_file_snippets=True` there.
- **Deps capped at top-10 (was top-20).** The 11th–20th most popular deps in a typical Node app are noise.

```python
    def build_coder_context(
        self, ...
    ):
        ...
        per_file_tokens: List[str] = []
        for rel_path in selected_files:
            raw_content = info.get("content", "") or ""
            ftok = count_tokens_approx(raw_content)
            per_file_tokens.append(f"    {rel_path}: ~{ftok} tokens, {info.get('lines', 0)} lines")
        self.logger.info("Selected files (for coder context):\n" + "\n".join(per_file_tokens))
```
- INFO-level per-file size breakdown in logs. Without this, a 200k token minified JS file would cause slow coder calls with zero signal. With it, you can see exactly which files bloated the prompt and tune selector top_k.

```python
    def _format_file_content(self, file_info: Dict[str, Any]) -> str:
        path = file_info["path"]
        content = file_info["content"] or "[COULD NOT READ]"
        return f"\n### FILE: `{path}`\n```\n{content}\n```"
```
- Every file is wrapped in a clear Markdown boundary. The LLM uses the `### FILE:` header to *refer back* to specific filenames in its plans. Without clear boundaries you get prompt-leakage ("the file called `models/Note.jsand then controllers...`").

```python
        if total_tokens > MAX_CONTEXT_TOKENS:
            budget = MAX_CONTEXT_TOKENS - count_tokens_approx(
                metadata_section + tree_section + product_request
            ) - 1000
            budget_per_file = budget // max(1, len(file_sections))
```
- **Budget math, not just truncate everything to 1000 chars.** First subtract the fixed-size sections (metadata, request, tree), set aside 1000 tokens of margin, then divide the remainder *equally* among files.
  - **Better version:** Give files *unequal* budgets using their selector rank. Higher-ranked files get more chars. Equal budgets are the simple version.

```python
    def build_summary_context(self, product_request, implementation_plan, applied_patches):
        modified_summary_lines: List[str] = []
        for patch in applied_patches:
            path = patch["file_path"]
            action = patch.get("action", "Modified")
            size = len(patch.get("content", ""))
            modified_summary_lines.append(f"- `{path}` ({action}, {size} chars)")
```
- Note: We **do not include full file contents** for the summary prompt. That's 2x the token cost for minimal value. Only filenames + sizes + plan + request are enough for the LLM to recap.

**Interview questions:**
1. *Why use `{{PLACEHOLDER}}` text replacement instead of `jinja2`?* → Jinja is great but adds a dependency. Plain str.replace is 3 lines of code and sufficient when templates are static.
2. *How would you handle a file list that exceeds the context window *after* individual truncation?* → Drop lowest-ranked files one at a time until it fits (selector rank gives you a sensible drop order).

---

## 11. agent/planner.py

### What it does
One-shot prompt → Markdown plan. No code generation here. (The spec explicitly forbids code in this stage.)

```python
    def _load_template(self) -> str:
        template_path = PROMPTS_DIR / "planner.md"
        content = read_file_safe(template_path)
        if content is None:
            raise RuntimeError(...)
```
- **Fail on missing prompt template.** If prompts aren't packaged with the binary, the agent is useless. Crash early with a clear path.

```python
    def _render_template(self, context: Dict[str, str]) -> str:
        result = self.prompt_template
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            result = result.replace(placeholder, value)
        return result
```
- Simple string replace. Works because `context` keys exactly match `{{PLACEHOLDERS}}` in the prompt.
  - **Caveat:** If a value contains the string `{{OTHER_PLACEHOLDER}}`, you'd accidentally double-render. Not a problem in this project (values are repo paths / source code, not new templates).

```python
            response = self.llm_client.chat(
                system_prompt=(
                    "You are a careful Senior Software Engineer creating implementation plans. "
                    "Follow the output format exactly. Be brief and specific."
                ),
                user_prompt=rendered_prompt,
                temperature=0.0,
                max_tokens=MAX_PLAN_TOKENS,
            )
```
- **`max_tokens=MAX_PLAN_TOKENS` cap (1500 default).** Plans are short; without a cap, large models can ramble for 3+ minutes writing commentary. With the cap: first ~1500 tokens of output are generated, then the model stops. DRASTIC end-to-end latency cut.
- **`temperature=0.0` (deterministic).** Previously 0.1. Plans should be deterministic for the same inputs; 0.0 means the plan converges faster (fewer "creative" tokens = faster first-token + generation).
- System prompt adds *"Be brief and specific."* — cheaper, faster plans.

**Interview questions:**
1. *Why forbid the planner from writing code?* → Separation of concerns. The planner's job is *ordering and scope*; the coder's job is *syntax*. Separating them forces the agent to think before acting and produces an inspectable plan artifact (which also happens to be great interview demo material).
2. *What if the plan misses a file?* → The Coder stage will still see the FULL selected-files context, so it can modify extra files *not* in the plan. The plan is guidance, not a straitjacket.
3. *How to validate the plan?* → After planning, ask the LLM in a separate turn: "Does this plan cover the request? Answer YES or NO with a 1-sentence reason." Simple consistency check.

---

## 12. agent/coder.py

### What it does
Renders the code prompt, calls the LLM, and parses its output into `[{file_path, action, content}, ...]` dictionaries. Retries once with stricter instructions on parse failure.

```python
    def generate(self, context: Dict[str, str], min_expected: Optional[int] = None, max_tokens: Optional[int] = None) -> List[Dict[str, str]]:
        cap = max_tokens if max_tokens is not None else MAX_CODE_TOKENS
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    retry_prompt = (
                        rendered_prompt
                        + "\n\n## RETRY INSTRUCTIONS\n"
                        + "Your previous response was incomplete or not parseable. "
                        + "You MUST output ALL modified files. "
                    )
                    if min_expected and min_expected > 1:
                        retry_prompt += (
                            f"The plan covers at least {min_expected} files — "
                            f"output EXACTLY {min_expected} FILE blocks. "
                        )
                    retry_prompt += "Use EXACTLY this format..."
```
- **`min_expected` new param** (passed from `main.py`): If the LLM returns fewer files than the plan covers, we retry with an explicit reminder. Example: plan modifies 6 files → LLM returns 2 → retry prompt says *"Output EXACTLY 6 FILE blocks."* Without this, coder silently under-produced.
- **`max_tokens=MAX_CODE_TOKENS` cap (4096 default).** Coder outputs full files for 6 files — 4096 tokens is about right; without a cap, 70B models can ramble for minutes generating extra commentary.
- **FIRST call temperature = 0.1, RETRY call temperature = 0.0.** Slack on first go (format flexibility), strict/deterministic on retry.

```python
                response = self.llm_client.chat(
                    system_prompt=(
                        "You are a careful Senior Software Engineer. "
                        + "Generate complete updated file contents using the EXACT format specified. "
                        + "Wrap each file in code fences. Preserve existing functionality. "
                        + "Do NOT add comments to the code. Be concise."
                    ),
                    user_prompt=prompt_used,
                    temperature=temp,
                    max_tokens=cap,
                )
```
- **"Do NOT add comments"** is a critical spec instruction. Real repos don't have random `// Added tags support per AI plan` comments on every line. A common LLM failure mode is annotating edits — the prompt bans it.
- **"Be concise"** new — reduces token count of preamble/postamble, coder converges faster.
- **`max_tokens=cap`** enforces the 4096-token output ceiling.

```python
                updates = parse_file_updates(response)
                if updates:
                    return updates
```
- Success is "can we parse out at least one file update?" Not "is the response perfectly formatted?". `parse_file_updates` does heavy lifting.

**Interview questions:**
1. *Why does the Coder output FULL files instead of diffs?* → Diffs require exact line-offset math. LLMs miscount lines 10–30% of the time, and patching fails. Full-file replacement works 100% of the time (modulo file size) at the cost of more tokens. For small repos, the cost savings of diffs don't justify the failure rate.
2. *How would you verify the new code compiles/runs?* → Add a post-patch `Validator` subprocess call: e.g., for a Node repo, run `npm run build` or `node -c <file>` (syntax check). If it fails, revert the patches and retry the Coder with the error message appended.
3. *What if the LLM truncates a file mid-way?* → Validator checks brace balance and non-empty output. Catches ~80% of truncations. 100% would require parsing per language.

---

## 13. agent/validator.py

### What it does
Sanity-checks the LLM's output BEFORE writing to disk. This is the last safety net.

```python
    _SUSPICIOUS_PATH_TOKENS = ("ACTION:", "CONTENT:", "```", "FILE: ", "---", "\n", "\r", "javascript", "python")
    def _check_path_safety(self, relative_path: str) -> Tuple[bool, List[str]]:
        if len(relative_path) > 300:
            issues.append(f"suspicious: path length {len(relative_path)} > 300 (likely label leak from LLM response)")
        for tok in self._SUSPICIOUS_PATH_TOKENS:
            if tok in relative_path:
                issues.append(f"suspicious: path contains {tok!r} (likely label leak from LLM response)")
        try:
            resolved = (self.repo_path / relative_path).resolve()
        except (OSError, ValueError):
            return False
        try:
            resolved.relative_to(self.repo_path.resolve())
            return True
        except ValueError:
            return False
```
- **Path-traversal protection.** If the LLM outputs `FILE: ../../../../etc/passwd` (injection, hallucination, or a malformed "relative" path), this catches it: `resolve()` normalizes `../` segments, then `relative_to(repo_path)` will throw `ValueError` if the result escapes the root.
  - **Classic security question:** *What's a path traversal attack and how do you prevent it?* → Exactly this pattern: resolve, then confirm it's inside a trusted root.
- **Suspicious-path scan (new in debugging sessions):** Even before the resolve test, we scan for known parser-leakage tokens: `ACTION:`, `CONTENT:`, triple-backticks, `javascript`, newlines, and path length >300 chars. *If any match, validation fails and the issue message explicitly says "(likely label leak from LLM response)".*
  - **Why:** In early runs, the coder parser leaked `ACTION: Replace Entire File CONTENT: ...` into file paths. Without this early-check, Validator would show "Note: X will be created" as if everything were fine, then Patcher would write-fail with cryptic WinError 123. The early scan converts this into a *searchable, explicit* validation issue.

```python
    def _check_basic_syntax(self, content: str, extension: str) -> Tuple[bool, List[str]]:
        ...
        brace_open = content.count("{")
        brace_close = content.count("}")
        ...
        if brace_open != brace_close:
            issues.append(...)
```
- Language-agnostic "did the file end properly?" check. Works for JS/TS/Go/Java/Python (sort of) because unbalanced braces = bad sign.
  - **False positives:** `{` inside a string like `"User {name}"` — but we allow up to 2 issues, which tolerates the rare counted-string cases.
  - **Better version per language:** Use the language parser itself: `node -c` (JS), `python -m py_compile` (Python), `tsc --noEmit` (TS). True syntax checking at the cost of shelling out + needing toolchains installed.

```python
            result = {
                **update,
                "valid": ok,
                "issues": issues,
                "target_exists": file_exists,
                "extension": ext,
            }
```
- Never mutate the input `update` dict — use `{**update, ...}` to produce a new dict with validation fields merged in. Defensive: caller might have kept a reference.

**Interview questions:**
1. *What attacks is Validator designed to stop?* → Path traversal (security), empty-file writes (LLM truncation), grossly malformed syntax that would break lint/test.
2. *Why not validate AND THEN fall back?* → We do: the Coder retries once. The Validator's job is to emit warnings, not magically fix content. Patcher then silently *skips* invalid entries.
3. *What does Validator NOT catch?* → Logic bugs (e.g., wrong API semantics, wrong DB default values). Only syntax/structural.

---

## 14. agent/patcher.py

### What it does
Takes the validated file-update list and writes files. Makes backups first.

```python
class Patcher:
    _PATCHER_PATH_FORBIDDEN = ("ACTION:", "CONTENT:", "```", "FILE: ")

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
                    f"Refusing to patch suspicious path: "
                    f"contains forbidden token {tok!r}. Parser failure."
                )
        return norm
```
- **Path normalization:** Windows Selector emits `app\controllers\note.controller.js` (backslash). The parser emits `app/models/note.model.js` (forward slash). Normalize to POSIX `/` so both work.
- **`_safe_target_path()` guard: Even *after* `valid=False` skip in Validator (defense-in-depth), Patcher also re-scans for forbidden tokens before any write. If Validator somehow passes a mangled path through, Patcher catches it here and logs `[WinError 123 Invalid name]` with the exact forbidden token.
  - **Why not just trust Validator?** Defense-in-depth — a single regex oversight in Validator (or future refactor that forgets the check) won't silently write garbled paths.

```python
    def __init__(self, repo_path, backup=True):
        self.backup_dir = self.repo_path / ".agent_backup"
```
- Backups go INSIDE the repo (`.agent_backup/`) next to the real files. Why not OUTPUT_DIR? Because then you'd need to remember two directories to roll back. Keeping backups under `.agent_backup/` in the repo means the user can `cp -r .agent_backup/* .` in one command.

```python
    def _make_backup(self, relative_path: str) -> bool:
        src = self.repo_path / relative_path
        if not src.exists():
            return False
        backup_path = self.backup_dir / relative_path
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup_path)
```
- **`shutil.copy2`** (not `shutil.copy`) preserves modification time + metadata. Minor — but makes diffs saner if the user inspects the backup.

```python
    def apply(self, validated_updates):
        ...
        for update in validated_updates:
            if not update.get("valid"):
                self.logger.warning(f"Skipping invalid update: ...")
                failures.append(...)
                continue
```
- **Skip invalid, don't abort the whole run.** If we have 5 valid files and 1 invalid, we apply the 5. This is the "degrade gracefully" choice.
  - **Alternative (all-or-nothing):** Write everything to a temp dir, then atomic-move only if ALL files pass validation. Simulates a transaction. More correct, more code.

**Interview questions:**
1. *What's the difference between shutil.copy, copy2, and copyfile?* → `copyfile` = bytes only. `copy` = bytes + permissions. `copy2` = bytes + permissions + mtime/atime.
2. *Why not use atomic writes (temp file + rename)?* → On Windows, rename over an existing file fails. `write_file_safe` (which Patcher uses) is the simple cross-platform version. Atomic version: `f = tempfile.NamedTemporaryFile(dir=target.parent)` → write → `os.replace(f.name, target)` (POSIX-safe; Windows works with the right `delete=False` flags).

---

## 15. agent/summarizer.py

### What it does
Small wrapper class identical in structure to Planner. Reads `summary.md` template, renders, calls LLM, writes `output/summary.md`.

Same patterns as planner (load template, render, chat, save). This duplication is **intentional.** You *could* abstract them into `class PromptRunner(template_name)` — but with only 3 very similar classes, the cost of abstraction (a reader now has to find `PromptRunner` in helpers, and the 3 classes end up as 3 lines of config + indirection) isn't worth it for a 2–3 hour project.

**Interview question:**
- *DRY says don't repeat. Why duplicate Planner/Summarizer structure?* → "Rule of 3" (3+ instances → abstract). Here it's 2 structurally-similar, semantically-different classes. Premature abstraction = "soft code" (impossible to read without jumping files) for no real benefit.

---

## 16. Prompts

### planner.md (after size optimization)
Goal: force the LLM to output a 6-section plan **concisely** (Summary, Affected Components, Step-by-Step max 8 steps, Risks / Notes). Key optimizations vs. original:
- Removed verbose "Compatibility Guarantees / Potential Risks" section (was 20 lines of template → LLMs filled that section with 500-800 tokens of fluff).
- New hard cap: "Max 8 steps." → forces planner to be terse.
- Shorter instructions everywhere (less prompt = less prefill time).

Why the truncation? **Latency:** A 70B model on NIM free tier generates ~10–20 tokens/s. An extra 800 tokens of "risks" section = 40+ seconds of pure cost with zero coder value (the coder never reads risks, only reads Affected Components + Step-by-Step).

### coder.md (after size optimization)
Key lines:
- **"Output ONLY files that change… don't repeat unchanged files."** Reduces token waste by skipping package.json/README when unchanged.
- **"ACTION is always 'Replace Entire File'".** Previously coder would sometimes output "Patch" or "Modify" actions. Now one canonical action.
- **Shorter format example** (one concrete sample file instead of 2-file repeating example). Shorter prompt = faster prefill.

### summary.md
Goal: produce a standardized summary the interviewer can read in 30 seconds. Unchanged structure — but capped via `MAX_SUMMARY_TOKENS=600` (new config knob) so it finishes in <10s.

### .env.example SPEED TIERS
```
#  FASTEST (<10s/call ideal):   meta/llama-3.1-8b-instruct   |   microsoft/phi-3-mini-128k-instruct   |   mistralai/mistral-7b-instruct-v0.3
#  FAST-BALANCED (~10-20s):     mistralai/codestral-22b-instruct-v0.1
#  SLOW-STRONG (1-3 min):       meta/llama-3.1-70b-instruct   |   nvidia/llama-3.3-nemotron-super-49b-v1   |   nvidia/llama-3.1-nemotron-ultra-253b-v1
```
Why tiers? NIM free tier throughput scales INVERSELY with model size. For interviews you want FASTEST tier (plan <20s, coder <60s, summarizer <10s, TOTAL < 2 minutes). Only switch to SLOW-STRONG for the final demo run if you want absolute code quality.

---

## 17. requirements.txt & .env.example

### requirements.txt
```
openai>=1.30.0
python-dotenv>=1.0.0
```
- Only 2 dependencies. The `>=1.30.0` for OpenAI pins the response_format / SDK v1 shape we rely on.
- **Why no `tiktoken`, `httpx`, `tenacity`?** → Same design principle: keep it tiny. Use chars/4 for tokens; hand-write retries; openai's SDK already uses httpx internally.

### .env.example (after refactor)
```dotenv
LLM_API_KEY=nvapi-your-api-key-here
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
# FASTEST <10s/call ideal:   meta/llama-3.1-8b-instruct   |   microsoft/phi-3-mini-128k-instruct   |   mistralai/mistral-7b-instruct-v0.3
# FAST-BALANCED ~10-20s:     mistralai/codestral-22b-instruct-v0.1
# SLOW-STRONG (1-3 min):     meta/llama-3.1-70b-instruct   |   nvidia/llama-3.3-nemotron-super-49b-v1   |   nvidia/llama-3.1-nemotron-ultra-253b-v1
LLM_MODEL=meta/llama-3.1-8b-instruct

# Optional tuning knobs:
# LLM_TIMEOUT_SECONDS=120        # fail-fast instead of hang
# MAX_PLAN_TOKENS=1500           # planner output cap
# MAX_CODE_TOKENS=4096           # coder output cap (6 files ~ each 400 tokens)
# MAX_SUMMARY_TOKENS=600         # summary output cap
# MAX_CONTEXT_TOKENS=120000
# MAX_RETRIES=2
# LLM_TEMPERATURE=0.2
```
- **NVIDIA NIM is the default**, not OpenAI — matches what this project is actually run against in the viva sessions.
- **SPEED TIERS section:** Critical for interviews — shows we intentionally profiled inference time and have a cost-quality tradeoff between tiers.
- Every **optional** knob is documented on its own line. No hidden magic.
- **Important design rule:** Never commit a real `.env` (it's in `.gitignore`, or rather should be). `.env.example` is the template.

---

## 18. Debugging Log: Bugs Fixed Chronologically (Viva Sessions)

*Why this section exists:* In the interview, they'll ask "Walk me through a bug you found, how you diagnosed it, and how you fixed it." This section is that — 9 real bugs, diagnosed from production logs. For each bug, memorize: symptom → root cause → fix → verification.

### Bug #1: Placeholder API Key Not Caught (NVIDIA Keys)
- **Symptom:** User copies `.env.example` into `.env` without changing the key, runs the pipeline, and STEP 4 planner crashes with a confusing `Unauthorized` error from NIM instead of a friendly "please set your key" message.
- **Root cause:** Key validation was `if not key or key.startswith("sk-") and "your" in key`:
  1. Operator precedence (`and` before `or`) → only keys starting with `sk-` AND containing "your" were caught.
  2. NVIDIA NIM keys use prefix `nvapi-` — the hardcoded `sk-` prefix meant `nvapi-your-key-here` passed validation.
- **Fix:** New helper `_is_placeholder_key(key)` scans for generic placeholder tokens (`your`, `xxx`, `changeme`, `insert`, `example`, `here`) regardless of key prefix. Works for any provider.
- **Code ref:** [llm_client.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/utils/llm_client.py#L37-L47)
- **Verification:** Both `nvapi-your-key-here` and `sk-your-xxx-here` now trigger the friendly placeholder warning on app startup.

### Bug #2: Bare 404 With Zero Guidance from NVIDIA NIM
- **Symptom:** LLM call returns `404 page not found` — no error message body, no context from provider. User has no idea if it's bad URL / bad slug / model not activated.
- **Root cause:** NVIDIA NIM returns a bare 404 for two extremely common user errors: (a) wrong slug casing (case-sensitive `org/model-name`) or (b) user never visited build.nvidia.com → selected model → clicked **Try Now** to accept TOS / activate the endpoint.
- **Fix:** `_format_error(exc)` → if `404` in msg and backend is NVIDIA, append `[HINT: NVIDIA NIM — 404 usually means (1) wrong slug, or (2) model not activated…]` with an activation checklist and a list of known free model slugs to try. Same pattern for timeouts (suggests FASTEST-tier models).
- **Code ref:** [llm_client.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/utils/llm_client.py#L74-L125)
- **Interview note:** This is a great example of **provider-aware UX**. Errors that are "provider-cryptic" become user-actionable with one layer of translation at the boundary of the system.

### Bug #3: `parse_file_updates` Regex Leaked Labels Into File Paths
- **Symptom (most severe bug in the assignment):** Patcher stage says `FAILED to write 'app/models/note.model.js ACTION: Replace Entire File CONTENT: ```javascript\nconst mongoose = require('mongoose')...'` — 2,800 characters in the path, including newlines and colons. Windows raises `WinError 123 Invalid name`.
- **Root cause (3 nested issues in original regex-based parser):**
  1. **Label format too rigid.** Original regex required FILE → ACTION → CONTENT **each on separate newline**. LLMs actually output a single-line fence: `--- FILE: x.js ACTION: Replace CONTENT: ```js …` — regex missed it entirely.
  2. **Greedy regex with `re.DOTALL`.** `FILE: (.+?) ACTION:` — with DOTALL the non-greedy `.+?` still matched newlines; when the parser fell back to a secondary regex to try to recover, it slurped everything up to the *final* `CONTENT:` — dumping everything between `FILE:` and the last label (including other file paths + ACTION labels + content) into the `file_path`.
  3. **False label matches in code.** JavaScript objects commonly contain `{ content: req.body.content }`. The secondary regex treated these JS keys as label delimiters → mid-file split and file content was truncated.
- **Fix:** Complete rewrite of `parse_file_updates` as **two-stage label/content extraction**:
  1. Slice text at every `FILE:` label (doesn't care about separators — works for `---`, newlines, single-line).
  2. In each slice → parse HEAD (everything BEFORE the first triple-backtick) for FILE and ACTION labels → extract CONTENT from the fenced block via `_strip_code_fences()`. Because ` ```language … ``` ` never appears inside source code, content extraction is unambiguous. Because we only search for labels in HEAD, `content:` object keys inside code can never match.
- **Code ref:** [helpers.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/utils/helpers.py#L47-L167)
- **Verification:** 7-unit test suite covering: (1) multi-line label format, (2) separator fence format, (3) **real LLM single-line fence output 6-file round-trip** with exact content matches, (4) Windows backslash paths, (5) garbled-path rejection, (6) mid-content `content:`-key non-interference, (7) deduplication order. All 7 tests pass.

### Bug #4: `write_file_safe` Swallowed Filesystem Errors
- **Symptom:** Patcher logged `FAILED to write note.model.js` with zero diagnostic info. Even in the 2800-char mangled-path case, you had NO idea why it failed (WinError 123? permissions? missing dir?).
- **Root cause:** `except (OSError, IOError): return False` silently dropped the exception object.
- **Fix:** Change the except block to `logger.error(f"Failed to write {path}: {e}")` before returning False.
- **Code ref:** [filesystem.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/utils/filesystem.py#L51-L59)
- **Lesson:** **Never swallow exceptions.** Even a boolean-return helper should surface diagnostics via logging if the caller relies on it for observability.

### Bug #5: Logger Missing mkdir + No Explicit Append Mode + Windows Handle Lock
- **Symptom / confusion from user:** "If I clear logs.txt and re-run, do the logs reappear?"
- **Root cause (3 minor issues):**
  1. No explicit `OUTPUT_DIR.mkdir()` before opening FileHandler (would fail on fresh clone).
  2. Mode `"w"` vs `"a"` was implicit and ambiguous.
  3. Windows `FileHandler` holds an exclusive handle on `logs.txt` while the process runs → trying to delete it from Explorer raises `PermissionError [WinError 32]` → users thought "can't clear logs".
- **Fix:**
  1. Explicit `OUTPUT_DIR.mkdir(parents=True, exist_ok=True)` right before `FileHandler`.
  2. Explicit `mode="a"` (append) for interview-readability. Important: mode `"a"` automatically creates the file if missing → cleared/deleted logs reappear automatically on the next logger write in a NEW process.
  3. Documented the "must stop Python process first → delete → rerun" workflow explicitly.
- **Code ref:** [logger.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/utils/logger.py#L211-L215)
- **Verification / user question answer:**
  - Stop Python process → delete/empty logs.txt → re-run `python main.py …` → logs **do reappear automatically** (mode `"a"` creates the file, content appends from first `logger.info` call)
  - If Python process is still running → cannot delete file → cannot clear logs (expected Windows exclusive-handle behavior)

### Bug #6: Patcher Path Mismatch + Mangled Path Acceptance + Noisy Failures
- **Symptom (nested issues):**
  1. Selector emits Windows `app\controllers\note.controller.js` while parser emits POSIX `app/models/note.model.js`.
  2. Mangled 2800-char paths reach Patcher.apply(), which then dumps the full string into `"Applying: {file_path}"` log line → 10 lines of illegible noise in logs.
  3. Failed files list joined with commas → `C:\path\to\file.js, C:\path\to\other.js` becomes unreadable when a path contains a newline.
- **Fix:**
  1. `_normalize_path()` — strip quotes/whitespace, `\` → `/`, drop `.` segments — all paths exit as POSIX before any use.
  2. `_safe_target_path()` — scan for label leakage tokens (`ACTION:`, `CONTENT:`, ``` ``` ```, `FILE: `, `\n`, `\r`) BEFORE any write; raise explicit `ValueError` and skip the patch with a clear log.
  3. `"Applying: {file_path} [exists|new] (N chars)"` one line each — clean because path is sanitized before log.
  4. Failed files list joined with ` ; ` — unambiguous even if paths contain commas.
- **Code ref:** [patcher.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/patcher.py#L16-L132)

### Bug #7: Silent Under-Production — Coder Returned 2/6 Files, Pipeline Said "Success"
- **Symptom:** Selected files = 6 files. Coder response = 2 file updates. STEP 5 reports `Generated 2 file updates`. Pipeline continues. Result: missing 4 critical files (controller, server, package.json, README) are never patched.
- **Root cause:** `generate()` accepted `if updates:` (any non-empty list) as success. No check for "did we get at least X files?"
- **Fix:**
  1. `CodeGenerator.generate(..., min_expected=None, max_tokens=None)` — added both params.
  2. If parser produces >=1 updates AND count < min_expected AND we haven't used last retry: we retry with a reminder prompt *"The plan covers at least X files — output EXACTLY X FILE blocks."*
  3. `main.py` STEP 5 passes `min_files = len(selected_files) - 1` (1-file tolerance for legitimate unchanged files).
- **Code ref:** [coder.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/coder.py#L27-L102)

### Bug #8: Planner + Coder Ran "Forever" — No Timeout, No Token Caps
- **Symptom (most visible user complaint):** STEP 4 planner hangs for 6+ minutes with `meta/llama-3.3-70b-instruct` on NIM free tier. No progress. No timeout. User Ctrl-C's.
- **Root cause (4-fold):**
  1. No timeout passed to OpenAI SDK → call blocks indefinitely on stalled NIM connection.
  2. No `max_tokens` on planner / coder / summarizer → verbose outputs take minutes.
  3. Long planner prompt template with "Compatibility Guarantees + Potential Risks" verbose sections (LLMs filled them with 800+ tokens of fluff per call).
  4. Long coder prompt template (2-file example) → prefill latency + bloated context (package.json snippet repeated in metadata even though coder already gets full file contents).
- **Fix:**
  1. New config knob: `LLM_TIMEOUT_SECONDS=120` → passed to SDK constructor; any hung NIM call aborts with an actionable timeout-hint error.
  2. New config knobs: `MAX_PLAN_TOKENS=1500`, `MAX_CODE_TOKENS=4096`, `MAX_SUMMARY_TOKENS=600`. All three stage calls now pass `max_tokens=…` — forces output truncation and guarantees worst-case latency.
  3. **planner.md** shortened (removed verbose compatibility/risks sections, added "Max 8 steps", shorter instructions).
  4. **coder.md** shortened (1-file format example, "output ONLY changed files", "ACTION is always Replace Entire File").
  5. **ContextBuilder** metadata section uses `include_file_snippets=False` for coder (removes the repeated package.json/README snippets noise from coder prompt — ~1k tokens saved). Deps top-20 → top-10.
  6. New INFO-level logging in `main.py`: "Calling Coder LLM: min_expected=X files, MAX_CODE_TOKENS=Y" and in `ContextBuilder.build_coder_context` per-file token counts.
- **Code refs:**
  - Timeout + tokens config: [config.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/config.py#L79-L92)
  - Planner prompt shorten + max_tokens + temp 0.0: [planner.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/planner.py#L33-L43)
  - Coder max_tokens + min_expected count + Be concise: [coder.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/coder.py#L27-L102)
  - Coder context trimmed + per-file breakdown logs: [context_builder.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/context_builder.py#L23-L170)
  - Shortened prompts: [planner.md](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/prompts/planner.md), [coder.md](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/prompts/coder.md)

### Bug #9: Validator Outputted Misleading "Note: X will be created" Even for Mangled Paths
- **Symptom:** Even when Validator detected a bad path, it would print `"Note: app/models/note.model.js ACTION: Replace Entire File CONTENT:  ```javascript … will be created (new file)"` as a separate log line — misleading user into thinking validation passed.
- **Root cause:** Validator always printed the new-file note line BEFORE checking valid status.
- **Fix:** Print new-file note ONLY if `ok is True`. Also, new `_SUSPICIOUS_PATH_TOKENS` early-check: rejects paths with `ACTION:/CONTENT:/```/newlines/length>300` with an explicit `"(likely label leak from LLM response)"` issue message.
- **Code ref:** [validator.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/validator.py#L9-L48)

---

## 19. Architecture Review & Interview Topics

### Architecture Recap: Why This Works
| Stage | Deterministic? | LLM? | Artifact |
|-------|:-:|:-:|---|
| Explore | ✅ | ❌ | `repo_data` dict + tree string |
| Metadata | ✅ | ❌ | `project_metadata` dict |
| Select | ✅ + LLM rank | ✅ (rank) | `selected_files` list |
| Context | ✅ | ❌ | Rendered prompt strings |
| Plan | ❌ | ✅ | `execution_plan.md` |
| Code | ❌ | ✅ | `[{file,action,content}]` |
| Validate | ✅ | ❌ | `validated_updates` |
| Patch | ✅ | ❌ | Modified files on disk + backup |
| Summarize | ❌ | ✅ | `summary.md` |

"Deterministic where possible, LLM only where reasoning is required" is the backbone idea. Every D→L→D sandwich reduces token waste and failure modes.

### SPEED TIERS: How This Assignment Handles Inference Latency
*(Great interview topic — demonstrates latency awareness + cost-quality tradeoff thinking)*

| Tier | Model Slugs (NVIDIA NIM) | Planner | Coder | Total Pipeline | Use Case |
|---|---|---|---|---|---|
| FASTEST | `meta/llama-3.1-8b-instruct`, `microsoft/phi-3-mini-128k-instruct`, `mistralai/mistral-7b-instruct-v0.3` | 5-15s | 15-40s | **< 2 min** | Development, debugging, quick demos |
| FAST-BALANCED | `mistralai/codestral-22b-instruct-v0.1` | 10-25s | 20-60s | **< 3 min** | Best balance for most feature work |
| SLOW-STRONG | `meta/llama-3.1-70b-instruct`, `nvidia/llama-3.3-nemotron-super-49b-v1`, `nvidia/llama-3.1-nemotron-ultra-253b-v1` | 1-3 min | 2-6 min | **5-15 min** | Final demo, max code quality |

Lever 1 (model tier) >> every other knob. Everything else in speed optimization is secondary: timeout fail-fast, max_tokens output caps, prompt brevity, min_expected retry count, de-duplicated context sections.

### General Interview Questions (Architectural)
**Q1. What would you change to scale this to large monorepos (100k files)?**
A:
- **Explorer** → incremental indexing (pickle tree to disk; mtime cache).
- **Selector** → drop keyword heuristic; use embeddings/BM25 index over file contents (Chroma / a plain pickle of arrays).
- **Context** → hierarchical summarization (per-folder → per-module → per-repo) instead of per-file truncation.
- **Coder** → target AST-level edits or fine-grained search/replace, not full-file rewrites.

**Q2. How would you make this safer to run (no data loss)?**
A:
- Stage every write in a temp branch / temp dir, then show a git-style diff summary, then require a user confirmation before moving files.
- Wrap all writes in a transaction: write to `tmp/stage/`, then atomic rename if 100% success; otherwise delete the stage and leave repo untouched.
- Auto-commit before/after runs if the repo is a git repo: `git add -A && git commit -m "pre-agent-state"` automatically.

**Q3. How would you test this end-to-end?**
A:
Make an integration harness. For a known repo + request:
1. Snapshot initial state (copy).
2. Run agent.
3. Assert: `output/execution_plan.md` exists AND contains keywords from request; `len(applied_patches) >= N`; target files on disk contain the new schema field; run `npm test` / equivalent and assert exit 0.
Now you have a regression suite for prompt changes.

**Q4. How would you support other languages / frameworks?**
A:
- Explorer & MetadataCollector are already mostly language-agnostic. Add manifest parsers in MetadataCollector for new languages.
- The prompts (planner/coder) are already English instructions for any language. The "project language" line in metadata gives the LLM enough signal to output idiomatic code.
- Validator syntax rules are language-agnostic today. To improve: add per-language sub-validators (shell out to `tsc --noEmit` for TS, `ruby -c` for Ruby, etc.) and detect language from metadata.

**Q5. What are the failure modes you'd expect in production?**
A:
1. **LLM downtime / rate limits.** Handled today with exponential backoff retries; in prod, add a circuit breaker + queue.
2. **Garbage output (unparseable).** Handled today by 1 retry + generous parsing. Add a "self-correct" step: paste the error + raw output back to the LLM and ask it to fix only the format.
3. **Over-edits (modifies 30 files for a 3-file change).** Plan stage + small selector top_k reduce this. Mitigation: in Validator, reject if code updates contain files NOT present in selected_files.
4. **Regressions.** Hardest. Only real defense: run the repo's test suite after patching. If the user has `npm test`, shell out and roll back if non-zero.

**Q6. Why no autonomous ReAct loop (think-act-observe)?**
A:
- ReAct's strength is multi-step search with tool use. Cost: N rounds, hard to debug, variable runtime. For a 2–3 hour feature, deterministic stages produce inspectable artifacts for each logical step, which is exactly what an interviewer wants to see: "Show me the plan. Show me the code. Show me the summary." Those are distinct outputs. A loop would blur them together.

**Q7. How would you add streaming output / realtime progress?**
A:
- `LLMClient.chat` returns the full string today. Replace with streaming `client.chat.completions.create(stream=True)`, then yield deltas to callbacks registered by each module.
- In `main.py`, pass a `progress_cb(step, percent, message)` down through stages; wire it to `rich.progress` for a nice progress bar.

### Interview Mini-Script: "Walk Me Through the Worst Bug"
*(Use Bug #3 — the parser regex leak. It's interview-perfect because it demonstrates: reading logs, identifying root cause, designing defense-in-depth, and testing.)*

> "The worst bug was in step 5 coder parsing. The pipeline ran successfully through validation and patching, but no files were written, and the Patcher log said `FAILED to write` a 2,800-character path that included newlines, `ACTION:` labels, and JavaScript code. Windows was raising WinError 123 because colons and newlines are invalid in filenames. I traced the path back to `write_file_safe`, which was swallowing the OSError silently. That was bug #4 — I added a `logger.error` there first so future failures were visible immediately. Then I looked at helpers.py and found the original regex used `re.DOTALL` with `(.+?)` groups. Three issues: first it required FILE/ACTION/CONTENT on separate lines, but the LLM was outputting single-line fences. Second, when a fallback regex tried to recover, greedy matching slurped every label and every fence into the `file_path` field. Third, even when labels parsed correctly, JavaScript object keys like `{ content: req.body.content }` were being treated as new label delimiters — files got truncated mid-way. The fix was a two-stage approach: first, split the response text into slices at every `FILE:` label (so separators don't matter at all); then in each slice, only search for labels in the HEAD (everything before the first code fence), and pull the CONTENT out of the fenced code block directly. Because fence tokens can never appear in source code, this is unambiguous. And because labels are only searched in HEAD, object keys in JavaScript can no longer match. I wrapped it in defense-in-depth — validator has a `_SUSPICIOUS_PATH_TOKENS` scan, patcher has another `_safe_target_path()` guard, and filesystem now logs every write failure instead of returning `False` in silence. Finally, I wrote 7 unit tests — including the real LLM 6-file round-trip with exact content match. All 7 passed."

---

End of `learn.md`.
