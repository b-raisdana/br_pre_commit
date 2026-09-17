# Incremental pre-commit ratchet

The ratchet package implements a two-layer pre-commit gate:

1. **Per-file gate** (`gate.py`) — blocks commit if any touched file regresses relative to its
   pre-commit state (HEAD). New files checked against zero baseline (with LOC cap). Renamed
   files compare against old path at HEAD. This gate **blocks** on regression.

2. **Project-wide trend baseline** (`baseline.py`) — tracks aggregate counts per rule code
   (ruff:E501, mypy:no-any-return, etc.) across the whole project. Baselines are content-addressed
   (SHA-256 hash of sorted JSON), merged on each run (union of keys, minimum value kept),
   and only ratchet down (never up). This layer **never blocks** — it's a long-term trend signal.

3. **Tool runners** (`tools.py`) — stateless linter execution (ruff, mypy, radon/xenon, LOC)
   on both current HEAD and before state (via git worktree). Groups results by rule and by file.

4. **Orchestration** (`main.py`) — coordinates the full run: load baselines → run analyzers →
   evaluate file gate → compute new baseline → write baseline → print trends.

## Module grouping rationale

| Module | Responsibility | Why separate |
|--------|----------------|--------------|
| `baseline.py` | Baseline persistence & merging | Pure data layer, no linter knowledge, testable in isolation |
| `gate.py` | Per-file regression logic | Pure function of (touched files, before/after counts), no I/O |
| `tools.py` | Tool execution & grouping | All subprocess calls, threading, parsing in one place |
| `main.py` | Orchestration & side effects | Only module with stdout, git staging, file writes |

Each module stays under ~300 lines (enforced by pre-commit). The split isolates:
- **I/O** (tools, baseline persistence) from **logic** (gate, baseline math)
- **Blocking decisions** (gate) from **trend tracking** (baseline)
- **Config/state** (main) from **reusable components** (baseline, gate, tools)
