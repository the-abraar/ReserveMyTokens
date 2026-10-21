# ReserveMyTokens - MVP Development Roadmap & TODOs

This document breaks down the MVP development plan from `idea.md` into actionable TODOs and assigns them to specialized custom agents that will execute them.

## Custom Agent Roster

The development of this cooperative will be orchestrated by the following specialized agents:

1. **@agent/backend-coordinator**: Specialist in Python, FastAPI, and PostgreSQL. Responsible for the central API, the double-entry credit ledger, and API provider adapters.
2. **@agent/worker-cli**: Specialist in Python CLI applications and local AI model integrations. Responsible for building the outbound-polling worker and integrating with Ollama.
3. **@agent/frontend-ui**: Specialist in Next.js, React, and TailwindCSS. Responsible for the user dashboard and project registry.
4. **@agent/security-auditor**: Specialist in application security, penetration testing, and access control. Responsible for verifying trust boundaries and threat models.

---

## Phase 1: The Coordinator & Ledger (Weeks 1-4)
**Assigned to: @agent/backend-coordinator**

- [x] Initialize the Python FastAPI project and PostgreSQL database using Docker Compose. (compose stack run locally 2026-10-15: migrations 0001-0004 apply on Postgres 15, API answers)
- [x] Implement Managed OIDC authentication (with mock/stub for local dev). (coordinator verifies RS256 ID tokens against the issuer's JWKS and maps (iss, sub) to a user; dev-only stub issuer with code + PKCE in `app/oidc.py`, 404 unless `OIDC_STUB=1` and `RMT_ENV=dev`; tested via TestClient and over real HTTP. No real managed provider wired yet: needs an account)
- [x] Design and implement the double-entry PostgreSQL ledger schema (`users`, `ledger_transactions`, `ledger_postings`, `usage_receipts`).
- [x] Create the Worker registration and revocation API endpoints.
- [x] Create the Job queue and polling endpoints for the outbound workers. (short poll; suite passes on SQLite and Postgres, incl. a two-worker lease race and a SKIP LOCKED test)
- [x] Implement the core `ModelProvider` adapter interface. (`worker/.../provider.py` ABC; Ollama implements it; result keys are checked against the coordinator's `Result`. Cost estimate is server-side (`GET /estimate`), and there is no `verify_usage`: local usage is self-reported)
- ~~Build the OpenRouter / LiteLLM adapter for fallback API inference.~~ Deferred, out of v1 scope: routes hosted-API or third-party capacity, which `docs/provider-terms.md` does not allow (judge.md blocker 3).
- ~~**SpareCycles Integration**: Add an adapter for the SpareCycles OpenAI-compatible endpoint (route donated capacity to/from their network).~~ Deferred, out of v1 scope: routes hosted-API or third-party capacity, which `docs/provider-terms.md` does not allow (judge.md blocker 3).

## Phase 2: The Contributor CLI Worker (Weeks 3-5)
**Assigned to: @agent/worker-cli**

- [x] Scaffold the Python CLI application (installable via pip/brew). (pip only: the wheel builds and `rmt-worker` runs from a clean venv. No brew formula: that needs a tap, an outside account)
- [x] Implement secure credential storage using OS keychain for provider keys. (stores the worker token and receipt-signing key via `keyring`; there are no provider keys to store in v1 (Boundary A). Round-tripped once against the real macOS Keychain; tests use an in-memory backend)
- [x] Build the outbound long-polling client to connect to the Coordinator API. (`?wait=` up to 25 s on the lease endpoint; run against a live uvicorn server in `tests/test_e2e.py`. The server holds a threadpool thread per waiting worker)
- [x] Implement the **Ollama Adapter**: detect local models, parse tasks, run inference, and collect metrics. (verified 2026-10-21 against real Ollama 0.40.6 with `qwen2.5:0.5b`, twice by separate agents: token counts match direct `/api/generate` calls, ledger balances, receipts verify; judge.md Update 13. Larger models and long generations not tried)
- [x] Implement Signed Usage Receipts (generate cryptographically signed payload of task completion). (Ed25519; the key is registered once per worker, and results must be signed once a key exists; `GET /jobs/{id}/receipt` returns the payload, signature and public key. Signing proves who claimed the numbers, not that they are true)
- [x] Implement the local limits enforcer (max compute hours, spending caps, kill switch). (compute hours and completion tokens per rolling 24 h; "spending cap" is read as the token cap, since a worker spends no credits; `rmt-worker stop` kill file. Counters reset when the worker restarts)

## Phase 3: The Web Dashboard (Weeks 5-8)
**Assigned to: @agent/frontend-ui**

- [x] Initialize the Next.js frontend application. (single page; loaded in headless Chrome against the local API 2026-10-15)
- [x] Build the **Contributor Dashboard**: view earned credits, registered workers, and connection status. (online/offline from the last poll, models, jobs settled, signing key; earned credits show in the balance, with no per-source breakdown. Checked in headless Chrome)
- [x] Build the **Consumer Dashboard**: input prompts, estimate credit costs, and view task outputs/receipts. (estimate with online-worker count, auto-refresh while jobs run, receipt view; checked in headless Chrome)
- [x] Build the **Donation & Open-Source Registry**: list verified projects, show funding budgets, and allow users to allocate their reserve credits. (`/projects` page; admin verifies after moderation; donations are idempotent, irrevocable ledger transfers to a per-project account. Spending a project budget is not built)
- [x] Integrate OIDC login with the FastAPI coordinator. (web code + PKCE flow, ID token as the bearer; checked in headless Chrome against the stub. No refresh token)

## Phase 4: Integration & Security Hardening (Weeks 9-10)
**Assigned to: @agent/security-auditor**

- [x] Verify Boundary A: Ensure no local API keys are transmitted to the coordinator. (worker test runs login + serve with host API-key env vars set and asserts that every request carries only the worker token, and never those values or the private signing key)
- [x] Verify Boundary B & C: Audit FastAPI endpoints for rate-limiting, idempotency keys, and prompt-leakage (ensure prompts aren't logged). (endpoint table in judge.md Update 11. Fixed: job submit takes an Idempotency-Key, workers per user capped, prompt dropped once a job is terminal; e2e asserts the prompt and output are absent from the coordinator's debug log and the worker's logs. `POST /users` is limited per client IP and `POST /projects` per user (5/min each, 2026-10-22). Open: outputs stay in the DB)
- [x] Verify Boundary D: Ensure the worker only accepts inference jobs (rejects arbitrary shell execution). (strict job schema; unknown fields or an unoffered model are refused without running; an AST test bans subprocess/exec/eval-style calls in the worker package)
- [x] Test double-entry ledger constraints (no negative balances from concurrent requests, no double settlement). (concurrent duplicate results and result-vs-lease-expiry are raced on SQLite and Postgres; a mutation check showed the duplicate race catches a removed compare-and-set)
- [x] Write integration tests for the end-to-end flow: `CLI -> Coordinator -> Ledger -> Web Dashboard`. (`backend/tests/test_e2e.py`: real uvicorn, CLI login/start, OIDC over HTTP, ledger checks, and the dashboard's API calls; the UI itself was checked by hand in headless Chrome, not by a test)

## Phase 5: The Pilot (Weeks 11-12)
**Assigned to: All Agents**

- [ ] Deploy Coordinator and Web UI to a staging environment. (needs a hosting account and a human)
- [ ] Package CLI for initial beta testers. (the wheel builds locally; picking testers and distributing it need a human)
- [x] Run end-to-end simulation with 10 dummy contributor nodes and 2 active consumer nodes. (`test_pilot_simulation_10_contributors_2_consumers`: 20 jobs, each settled once, consumer spend = contributor earnings, ledger balanced; passes on SQLite and Postgres)
- [ ] Reconcile provider costs against the internal ledger. (no real provider bills: v1 supply is local models. Receipts vs settle postings are reconciled inside the pilot simulation only)
