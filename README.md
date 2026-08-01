# AI Coding Agent — Pre-Interview Assignment

A lightweight, deterministic AI coding agent that implements feature requests automatically against a target repository.

It explores a target repo, builds a plan, writes code changes, validates them, applies them with backups, and summarizes the result.

All filesystem and validation logic is **deterministic Python**; Large Language Models are used **only for reasoning** (planning, code generation, summarization). Works with any OpenAI-compatible endpoint including NVIDIA NIM, Groq, Together, OpenRouter, or a local vLLM server.

---

## Architecture

### High-Level Pattern: Deterministic → LLM → Deterministic "Sandwich"

The project is intentionally a **strict sequential 9-stage pipeline**, not a ReAct / autonomous-agent loop. Each stage has one responsibility and one output artifact:

```
┌─────────────────────────────────────────────────────────────────────┐
│  User Request + Target Repo Path (CLI)                              │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ▼
   ┌─── DETERMINISTIC PHASE (pure Python, no LLM) ─────────────────┐
   │  1. Repository Explorer        → file tree + raw file list    │
   │  2. Metadata Collector         → language, framework, deps    │
   │  3. Relevant File Selector     → top-10 candidate files       │
   │  4. Context Builder            → prompt assembly              │
   └───────────────────────────────────┬───────────────────────────┘
                                       ▼
   ┌─── LLM REASONING PHASE ───────────────────────────────────────┐
   │  5. Planner                    → execution_plan.md             │
   │  6. Coder                      → structured FILE updates       │
   │  9. Summarizer                 → summary.md                   │
   └───────────────────────────────────┬───────────────────────────┘
                                       ▼
   ┌─── DETERMINISTIC PHASE (safety + I/O) ────────────────────────┐
   │  7. Validator                  → per-file pass/fail + issues   │
   │  8. Patcher                    → .agent_backup/ + overwrite    │
   └───────────────────────────────────┬───────────────────────────┘
                                       ▼
                              summary.md + modified files in-repo
```

The sandwich matters: **no LLM ever touches the filesystem directly**. The Patcher writes only files that the Validator signed off on, and the Patcher backs up every target file before overwriting it.

### Project Layout

```
ai-coding-agent/
├── main.py                  # Pipeline entry point + CLI (argparse)
├── config.py                # Constants, env-vars, ignore lists, output paths
├── requirements.txt
├── .env.example             # NVIDIA NIM default + speed tiers + tuning knobs
├── agent/
│   ├── explorer.py          # Repo scan, tree building, ignore filtering
│   ├── metadata_collector.py# Repo metadata (language/framework/ORM/tests)
│   ├── selector.py          # Heuristic scoring → top-K (no LLM)
│   ├── context_builder.py   # Prompt templates → planner/coder strings
│   ├── planner.py           # LLM → execution plan
│   ├── coder.py             # LLM → structured file updates
│   ├── validator.py         # Pre-write path/content/action checks
│   ├── patcher.py           # Backups + writes (nothing escapes validation)
│   └── summarizer.py        # LLM → final summary
├── prompts/
│   ├── planner.md           # Planner system prompt + format
│   ├── coder.md             # Coder system prompt + format
│   └── summary.md           # Summarizer system prompt + format
├── utils/
│   ├── filesystem.py        # safe read/write, ignore helpers, backups
│   ├── logger.py            # Dual console+file logger (output/logs.txt)
│   ├── helpers.py           # parse_file_updates, approx token counting
│   └── llm_client.py        # OpenAI-compatible SDK + error hints
└── output/
    ├── .gitkeep             # Folder is git-tracked; contents are .gitignored
    ├── execution_plan.md    # Written by planner (LLM Stage 5)
    ├── raw_coder_response_attempt{N}.txt
    ├── summary.md           # Written by summarizer (LLM Stage 9)
    └── logs.txt             # Full debug log
```

---

## Agent Workflow (9 Stages, Sequential)

The pipeline runs exactly once per `main.py` invocation — there are no "try-again-on-failure" loops between stages (the only retry is an internal Coder underproduction guard inside Stage 6 to catch "LLM returned 2 of 6 files").

| Step | Name | Type | What it does | Output |
|------|------|------|--------------|--------|
| **1** | Explorer | D | Recursively walks `--repo`, applies `IGNORED_DIRS` / `IGNORED_FILES`, reads file size, returns `(file_tree, all_files)`. | `repo_structure` dict |
| **2** | Metadata Collector | D | Parses `package.json` / `pyproject.toml` / `requirements.txt` / `go.mod` / `Cargo.toml` + README to detect Language, Framework, ORM, Test runner, Top dependencies. | `metadata` dict |
| **3** | Selector | D | Scores each file by heuristic: (a) filename keyword match (`controller`, `model`, `route`, `schema`, `service`, `handler` …) (b) matches request keywords (c) location in source root (d) readme/cfg hints. Returns top-N files, capped by `MAX_SELECTED_FILES`. | `selected_files` list |
| **4** | Context Builder | D | Reads prompt templates from `prompts/planner.md` + `prompts/coder.md`, fills in: user request, repo metadata, file tree, selected file paths + full contents (planner gets snippets; coder gets full contents with token breakdown). Outputs two prompt strings. | `planner_prompt`, `coder_prompt` |
| **5** | Planner | LLM | Calls LLM with planner prompt + `max_tokens=MAX_PLAN_TOKENS`, `temperature=0.0`. Writes the result verbatim to `output/execution_plan.md`. | Plan Markdown |
| **6** | Coder | LLM | Calls LLM with coder prompt + plan + `max_tokens=MAX_CODE_TOKENS`. If underproduction detected (`0 < len(parsed_updates) < min_expected` and attempt remaining), retries once with a hard reminder: "The plan covers at least X files — output EXACTLY X FILE blocks." Raw LLM response dumped as `raw_coder_response_attempt*.txt`; structured via `parse_file_updates`. | `List[FileUpdate]` — each has `path`, `action`, `content` |
| **7** | Validator | D | For every FileUpdate, checks: (1) path is in the allowed selected-set (wrong-language hallucinations are caught here), (2) no suspicious label tokens leaked into path (e.g. `ACTION:`, `CONTENT:`, `` ``` ``, newlines) → explicit `"likely label leak from LLM response"` issue, (3) content non-empty and (4) action `"Replace Entire File"` (per prompt contract). New-file note only printed if valid=True. | `(validated_updates, bool_all_ok, per-file issues)` |
| **8** | Patcher | D | For every validated update: (a) `_normalize_path` (Windows `\` → `/`, drop `.`/empty segments), (b) `_safe_target_path` (forbidden-token scan → raise `ValueError` if parser leakage), (c) copy original file into `<target_repo>/.agent_backup/<relative path>` (first time only), (d) write with `write_file_safe`. Returns `(applied_count, failed_count, failed_paths joined with ;)`. | Modifies in-repo files; writes `.agent_backup/` |
| **9** | Summarizer | LLM | Feeds (plan + file updates + success counts) to a small short LLM call with `max_tokens=MAX_SUMMARY_TOKENS`, `temperature=0.0`. Writes `output/summary.md`. | Final summary Markdown |

### CLI Invocation

```bash
# Non-interactive (recommended for scripts / assignment grading)
python main.py --repo /path/to/node-easy-notes-app \
               --request "Improve the application so users can better organise and search their notes."

# Interactive (enter request via prompt)
python main.py --repo /path/to/target-repo --interactive
```

### Quick Start

1. `pip install -r requirements.txt`
2. Copy `.env.example` → `.env` and set `LLM_API_KEY=nvapi-…` (or any OpenAI-compatible provider key). Defaults are NVIDIA NIM + fast 8B model.
3. Run one of the CLI commands above.

---

## How the Repository is Explored

Exploration is a **3-stage deterministic pipeline** (Stages 1-3). No LLM is used — everything is O(N) heuristics, which keeps it fast and reproducible.

### Stage 1: `Explorer.build_tree()` → physical scan

In [agent/explorer.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/explorer.py):

1. **Walk**: `pathlib.Path(repo_path).rglob("*")` — any file not in `IGNORED_DIRS` (`.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, `build`, `.idea`, `.vscode`, `.agent_backup`, …) or matching `IGNORED_FILES` (binary blobs: `.png`, `.jpg`, `.woff`, `.exe`, `.so`, `.pyc`, `.class`, `.lock`, `package-lock.json`) is kept.
2. **Size caps**: Each file's raw bytes are read up to `MAX_FILE_SIZE_BYTES` (prevents accidental multi-MB fixtures from bloating prompts).
3. **Tree formatting**: Results are formatted into a compact `tree` string (directory collapse via `/…` prefix) for the LLM to see structure without the LLM doing any I/O.

Output:
```
repo_structure = {
  "file_tree": str,            # compact tree for prompts
  "all_files": list[dict],     # {path, size, ext, exists}
}
```

### Stage 2: `MetadataCollector.collect()` → repo fingerprint

In [agent/metadata_collector.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/metadata_collector.py):

Strategy: **parse the most standard project config file first**, then confirm by extension distribution if configs are absent.

| If this file exists | Detected |
|----------------------|----------|
| `package.json`       | language = JavaScript, framework = dependencies[express/nest/fastify], ORM = mongoose/prisma/sequelize, test = jest/mocha/vitest, top_deps = up-to-10 most-imported |
| `pyproject.toml` / `requirements.txt` | language = Python, framework = fastapi/flask/django, ORM = sqlalchemy/django/ormar, test = pytest/unittest |
| `go.mod`             | language = Go |
| `Cargo.toml`         | language = Rust |
| None of the above    | Fallback: count `*.py / *.js / *.ts / *.go / *.rs / *.java / *.rb / *.php` extensions → pick plurality language |

Additionally, if a `README.md` exists, its first ~80 lines are included as a "description hint" (helps planner understand project purpose without sending the full README).

Output:
```
metadata = {
  "language", "framework", "orm", "test_runner",
  "top_dependencies": [...], "readme_hint": str,
  "file_ext_counts": dict,
}
```

### Stage 3: `Selector.select_files()` → relevance ranking

In [agent/selector.py](file:///C:/Users/hamza/Downloads/Pre-Interview/AI%20Coding%20Agent%20Assignment/agent/selector.py):

Every file in `all_files` gets a score on 4 dimensions (higher = more relevant):

1. **Structural roles** (30–80 pts each if filename or parent dir contains):
   - `model`, `schema`, `entity`, `models/` → data layer
   - `route`, `router`, `routes/` → API layer
   - `controller`, `handler`, `service`, `manager`, `controllers/`, `services/` → business logic
   - `server`, `app`, `main`, `index` → entry point
   - `db`, `database`, `config` → wiring/config
2. **Request-keyword overlap** (40 pts per match): tokenize user request → lowercase → match against file path (filename + parent). A request like "add search and tags to notes" matches files whose paths/filenames include `note`, `search`, `tag`, `controller`, `model`, `route`.
3. **Location bonus** (20 pts): files under `<repo_root>/app`, `<repo_root>/src`, or files at repo root depth 0–1 (prevents deep test fixtures floating to top).
4. **Extension bonus** (15 pts): files matching `metadata["language"]`'s main extension (`.js` for Node, `.py` for Python, etc.).

Top `MAX_SELECTED_FILES` (default: 10, configurable via `config.py`) are kept. The most-likely entry-point file is prepended automatically if it scored below the cutoff (so `server.js` / `main.py` is always visible in the Coder context).

### Why no LLM / embeddings / AST in Exploration?

It's faster, reproducible, and fits the assignment scope. The actual ranking work in this repo is ~30 lines of straightforward Python. An AST-based approach would be language-specific (defeating the agent's language-agnostic stance), and embeddings would require a vector DB (adding infrastructure without a correctness gain for the 200–1000 file repos this agent is sized for).

---

## Assumptions & Trade-offs

### Scope / target-repo assumptions

The agent is intentionally built for a pre-interview assignment, so it targets **small-to-medium repos** (~50–2000 files, < 200 MB on disk):

1. **Single repo, single feature, one-shot.** The agent runs once per CLI call; there's no multi-request conversation, no memory between calls, and no self-improve loop. If a feature needs two iterations, the human re-runs the CLI with an updated request.
2. **The target repo has a standard structure.** For a Node.js backend: `package.json` + `app/{models,controllers,routes}/…` or `src/{routes,services}/…`. For a Python backend: `requirements.txt`/`pyproject.toml` + `app/` or `{package_name}/`. Unusual folder layouts still work (Stage 3 heuristics fall back to extension+keyword matches), but feature completion accuracy falls.
3. **File contents fit in an LLM prompt window.** Stage 4 ContextBuilder caps individual files and uses `MAX_SELECTED_FILES` to avoid prompt overflow. On very large repos you must rely on the Selector ranking correctly.
4. **No test runner is executed by the agent** after the patch. The human must run `npm test`, `pytest`, etc., to close the correctness loop. This keeps the agent environment-independent (it never installs Node/Python toolchains in the target repo).

### Explicit trade-offs in design

| Trade | Decision | Why | Cost |
|-------|----------|-----|------|
| Pipeline vs. ReAct loop | Strict 9-stage pipeline | Predictable, debuggable, fits 20–30 min interview walkthrough; every stage has an inspectable artifact (`execution_plan.md`, `raw_coder_response_*.txt`, `summary.md`, `.agent_backup/`) | No retries after a bad plan. If Stage 5 plan names wrong files, Stage 6 can't course-correct. Human must re-run. |
| Full-file replacement vs. unified diffs | Always replace the whole file | LLMs regularly produce hunk-offset errors in unified diffs; full-file replacement eliminates an entire failure class. Backup + validation mean we don't lose previous state. | Slightly larger writes, worse signal-to-noise on a `git diff`. Fine for small files; becomes awkward for >2000-line files. |
| File selection heuristics vs. embeddings/AST | Pure Python keyword + role scoring (Stage 3) | No vector DB, no language lock-in, ~zero setup, reproducible scores across runs (deteministic with temp=0). | A heavily obfuscated repo (everything named `util1.js`, `handler2.py`) will score poorly. |
| Generic OpenAI SDK vs. per-provider SDKs | Single `llm_client.py` wrapping `openai.OpenAI(base_url=…)` | Works for OpenAI, NVIDIA NIM, Groq, Together, OpenRouter, local vLLM without code changes. | Provider-specific features (structured output mode native types, function calling helpers) aren't exposed. |
| Coder prompt format contract | `FILE:`/`ACTION:`/``` ``` fenced blocks with full file contents; custom `parse_file_updates` in two stages (HEAD label parse + fenced content) | Human-readable LLM format that doesn't require provider-specific JSON-mode; robust against single-line-fence, DOTALL leakage, and `content:` object-key false matches. | If LLM ignores the format completely, Stage 7 Validator rejects it (safe but wastes tokens). |
| Windows path handling | `_normalize_path` + `_safe_target_path` in Patcher + Validator | Selector emits `\` paths on Windows; Coder emits `/` paths. Normalizing everything to POSIX `/` before compare/write removes a common mismatch. | None — a pure win on Windows, a no-op on POSIX. |
| Safety vs. flexibility | Patcher + Validator reject paths containing `ACTION:`, `CONTENT:`, `` ``` ``, `FILE: `, `\r`, `\n`, or not in the selected-file set; max path length 300 chars | Prevents label-leakage from writing files named things like `note.js\r\nACTION: Replace Entire File\r\nCONTENT: …` (real Bug #3 regex failure). | Adding brand-new files outside the selected-file set requires the Selector to have guessed it or the human to include it manually via README hints. |
| `.env` + `.env.example` separation | `.env` is `.gitignore`d; `.env.example` is tracked. NVDIA NIM defaults in `.env.example`. | Prevents accidental API key commits, keeps interview template reproducible. | The human must copy `.env.example → .env` once; failure to do so yields the clear placeholder-key error from `llm_client.py::_is_placeholder_key()`. |
| Prompt brevity vs. rigor | `planner.md` and `coder.md` deliberately stripped of verbose sections. Planner max 8 steps. Coder example uses one file, not two. `MAX_PLAN_TOKENS=1500`, `MAX_CODE_TOKENS=4096`. | On slower 22B/70B models, extra 500-word boilerplate compounds to 40–60 seconds of wasted latency per run. | Very nuanced features may need richer plans; if your request is vague, re-run with a longer request rather than growing the prompts. |
| Model tiers defaulted to FASTEST | Default `LLM_MODEL=meta/llama-3.1-8b-instruct` (NVIDIA NIM) | 8B models stream plans in 5–15s and 4096-token code outputs in 30–90s. End-to-end pipeline < 2 minutes in the common case. | 70B tier produces more-accurate edge-case implementations; switch to FAST-BALANCED or SLOW-STRONG in `.env` if accuracy matters more than latency. |

### What's intentionally out of scope

Multi-agent chats, vector DBs / RAG, Docker / K8s packaging, web UI, test-suite execution inside the agent, database migrations applied against a real DB, rollback of partial multi-file patches (the `.agent_backup/` folder enables manual rollback, but automatic atomic multi-file rollback is not implemented), authentication, secrets scanning beyond basic placeholder key detection, and CI/CD pipeline integration.

---

## Outputs & Artifacts

- `output/execution_plan.md` — Planner output. Inspect this first if results are wrong.
- `output/raw_coder_response_attempt*.txt` — Raw Coder LLM strings. Use this to diagnose Stage 6 parser failures.
- `output/summary.md` — Final natural-language summary of the applied patch.
- `output/logs.txt` — Full debug log (console output duplicate). Includes per-file token counts for coder context, validation issues, applied-vs-failed counts, and individual file write lines.
- `<target_repo>/.agent_backup/` — Pre-patch backups of every modified file, keyed by relative path. Use `fc .agent_backup\app\models\note.model.js app\models\note.model.js` or `git diff --no-index .agent_backup/… …` to review the patch.

## Customization

- **Prompt behavior**: edit files in `prompts/`
- **Swap provider / model**: change `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` in `.env`
- **Tuning knobs** (all with defaults in `config.py`): `MAX_PLAN_TOKENS`, `MAX_CODE_TOKENS`, `MAX_SUMMARY_TOKENS`, `LLM_TIMEOUT_SECONDS`, `MAX_SELECTED_FILES`, `MAX_FILE_SIZE_BYTES`, `IGNORED_DIRS`, `IGNORED_FILES`
- **Heuristic scoring**: keyword lists in `agent/selector.py::_heuristic_score()`
