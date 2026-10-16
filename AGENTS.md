# AGENTS.md

- Run `scripts/check.sh` before finishing; `scripts/check.sh --fast` (lint, stray files, retired claims, unsafe HTML) is the pre-commit hook.
- Hooks: `.githooks/` is wired with `git config core.hooksPath .githooks` (local config; re-run after a fresh clone).
- Python 3.11 or 3.12 only (set `$PYTHON` to override). The venv lives at `~/.cache/ReserveMyTokens-check-venv` (`$CHECK_VENV`), never in the repo.
- Test dependencies are in `backend/requirements-dev.txt`. `worker/` has only a `pyproject.toml` and no dev extra; the check runs it with `PYTHONPATH=worker/src`. Its `build/` and `egg-info` are stale artifacts.
- Every Python suite also runs in reverse file order to expose order dependence.
- Docker is not used by the checks; do not make them depend on it.
- Postgres run (manual, needs Docker): start `backend/docker-compose.yml` with a throwaway `POSTGRES_PASSWORD` and the db port published to 127.0.0.1, create an empty database, then `TEST_DATABASE_URL=postgresql://rmt:<pw>@127.0.0.1:<port>/<db> pytest` in `backend/`. The fixture DROPS that database's public schema before every test. The SKIP LOCKED and row-lock tests skip on SQLite.
- Known failures: none as of 2026-10-16 (all `scripts/check.sh` steps pass). Keep it that way.
- `backend/tests/test_e2e.py` starts the API with uvicorn on a free 127.0.0.1 port (no Docker); it also runs on Postgres via `TEST_DATABASE_URL`.
- `check.sh` fails if README or the landing page reuse the retired claims ("unused AI subscription", "share your subscription", "API key pooling", "Network is Live"); `docs/` and `judge.md` are exempt.
- Landing page HTML sinks need `// safe-html: <reason>` on the line or the line above.
- Supply or marketing changes: read `docs/provider-terms.md` first. Launch scope and open blockers: read `judge.md`.
- Review standard: `CODING_STANDARDS.md`.
