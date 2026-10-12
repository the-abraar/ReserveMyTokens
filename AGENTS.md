# AGENTS.md

- Run `scripts/check.sh` before finishing; `scripts/check.sh --fast` (lint, stray files, retired claims, unsafe HTML) is the pre-commit hook.
- Hooks: `.githooks/` is wired with `git config core.hooksPath .githooks` (local config; re-run after a fresh clone).
- Python 3.11 or 3.12 only (set `$PYTHON` to override). The venv lives at `~/.cache/ReserveMyTokens-check-venv` (`$CHECK_VENV`), never in the repo.
- Test dependencies are in `backend/requirements-dev.txt`. `worker/` has only a `pyproject.toml` and no dev extra; the check runs it with `PYTHONPATH=worker/src`. Its `build/` and `egg-info` are stale artifacts.
- Every Python suite also runs in reverse file order to expose order dependence.
- Docker is not used by the checks; do not make them depend on it.
- Known failures today: `ruff` (default rules: B008 FastAPI `Depends` defaults, I001 import order, RUF100, UP017) and `web-lint` (react-hooks/set-state-in-effect in `web/app`). Real findings, left visible.
- `check.sh` fails if README or the landing page reuse the retired claims ("unused AI subscription", "share your subscription", "API key pooling", "Network is Live"); `docs/` and `judge.md` are exempt.
- Landing page HTML sinks need `// safe-html: <reason>` on the line or the line above.
- Supply or marketing changes: read `docs/provider-terms.md` first. Launch scope and open blockers: read `judge.md`.
- Review standard: `CODING_STANDARDS.md`.
