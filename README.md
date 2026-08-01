# AI Coding Agent

A lightweight, deterministic AI coding agent that implements feature requests automatically. It explores a target repository, generates an implementation plan, writes the code changes, and summarizes the result.

## Philosophy

> **Use deterministic programming wherever possible. Use the LLM only for reasoning.**

The agent follows a strict sequential pipeline rather than autonomous loops. Traditional code handles file I/O, validation, and orchestration; the LLM handles planning, code generation, and summarization.

## Architecture

```
User Request
    │
    ▼
Repository Explorer ─ Deterministic filesystem scan
    │
    ▼
Metadata Collector ─ Deterministic config/package parsing
    │
    ▼
Relevant File Selector ─ Heuristic + LLM ranking
    │
    ▼
Context Builder ─ Deterministic prompt assembly
    │
    ▼
Planner ─ LLM reasoning → Markdown plan
    │
    ▼
Code Generator ─ LLM reasoning → Structured file updates
    │
    ▼
Validator ─ Deterministic checks (paths, braces, non-empty)
    │
    ▼
Patcher ─ Deterministic file write with backup
    │
    ▼
Summary Generator ─ LLM reasoning → Markdown summary
```

## Project Structure

```
ai-coding-agent/
├── main.py                  # Pipeline entry point & CLI
├── config.py                # Constants, env vars, paths
├── requirements.txt
├── .env.example
├── agent/
│   ├── explorer.py          # Repo scan + tree building
│   ├── metadata_collector.py# package.json / README parsing
│   ├── selector.py          # File ranking (heuristic + LLM)
│   ├── context_builder.py   # Prompt assembly from templates
│   ├── planner.py           # Generates implementation plan
│   ├── coder.py             # Generates code changes
│   ├── validator.py         # Pre-write validation
│   ├── patcher.py           # Applies file updates with backup
│   └── summarizer.py        # Generates final summary
├── prompts/
│   ├── planner.md           # Planner prompt template
│   ├── coder.md             # Code generator prompt template
│   └── summary.md           # Summary generator prompt template
├── utils/
│   ├── filesystem.py        # Path, read/write, ignore helpers
│   ├── logger.py            # Dual console + file logger
│   ├── helpers.py           # Parsing, token counting
│   └── llm_client.py        # OpenAI-compatible SDK wrapper
└── output/
    ├── execution_plan.md    # Written by planner
    ├── summary.md           # Written by summarizer
    └── logs.txt             # Written by logger
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Key

```bash
cp .env.example .env
```

Edit `.env`:

```
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o
```

Works with any OpenAI-compatible endpoint (Groq, OpenRouter, Together, local vLLM, etc.).

### 3. Run the Agent

```bash
python main.py --repo /path/to/node-easy-notes-app \
               --request "Improve the application so users can better organise and search their notes."
```

Or use interactive mode:

```bash
python main.py --repo /path/to/node-easy-notes-app --interactive
```

## Outputs

- `output/execution_plan.md` — Step-by-step implementation plan generated before any code is written.
- `output/summary.md` — Summary of changes, affected files, API changes, and compatibility.
- `output/logs.txt` — Full debug log for the run.
- **Repository files** are modified in place. Backups are created in `.agent_backup/` inside the target repo.

## Design Decisions

**Why a sequential pipeline instead of ReAct / agent loops?**
Predictable, debuggable, and fits within a 2–3 hour assignment. Each stage produces an inspectable artifact.

**Why replace entire files instead of unified diffs?**
LLMs frequently make trivial diff format errors (offsets wrong, hunk failures). Full-file replacement is simpler and far more reliable. The trade-off is acceptable for small repos.

**Why heuristic + LLM ranking instead of embeddings?**
No vector database needed. A keyword/structure-based heuristic produces a short candidate list; the LLM ranks just those candidates. Lower token cost than sending a whole repo listing to the LLM, and simpler than embeddings.

**Why no AST analysis?**
Would be language-specific and break generality. The LLM reads source code directly and is quite good at making schema/API changes correctly.

## Intentionally Not Included

Multi-agent systems, vector DBs / RAG, long-term memory, Docker/K8s, web UI, databases, autonomous self-improving loops.

## Customization

- **Swap prompts:** Edit files in `prompts/` to change output style or rigor.
- **Swap model:** Change `LLM_MODEL` / `LLM_BASE_URL` in `.env` (any OpenAI-compatible API works).
- **Tune heuristics:** Edit keyword list in `selector.py::_heuristic_select`.
- **Tune ignore lists:** Edit `config.py::IGNORED_DIRS` / `IGNORED_FILES`.
