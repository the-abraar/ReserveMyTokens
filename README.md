# ReserveMyTokens - An AI Capacity Cooperative

> Give when idle. Use when needed. Donate what matters.

**ReserveMyTokens** is a planned cooperative (central coordinator, outbound-polling workers; nothing is deployed) for saving and donating spare local compute running open-weight models. 

Instead of letting your local GPU sit idle, you can run an open-weight model (Apache 2.0 or MIT licensed) and contribute that capacity to the network. Subscription sharing and pooled API keys are not supported (see `docs/provider-terms.md`). In return, you earn credits to borrow capacity later, or you can explicitly donate your compute to verified open-source projects that need it.

---

## 🌟 The Vision

*   **Reserve:** Contribute local open-weight inference capacity today, and earn test credits toward future capacity. Contributions are not yet verified: credits are paid on worker-reported token counts. Workers sign their usage receipts (Ed25519), which shows who claimed what but does not make the numbers true.
*   **Donate:** Directly fund public-good projects (examples only, no partnership: Wikipedia maintainers, Open Food Facts) by routing your spare local capacity to their tasks.
*   **Interoperate:** We aren't trying to replace OpenRouter or LiteLLM. We act as a cooperative ledger layer. 

Deferred, out of v1 scope: failover to [SpareCycles](https://sparecycles.io) or any other third-party capacity, which `docs/provider-terms.md` does not allow. The seed project list is fetched from the public [Agentic Commons](https://agentic-commons.org) directory; there is no partnership.

---

> **Disclaimer:** Credits are test-only and have no cash value until legal and payment review is complete. This is a concept; see `docs/open_questions.md`.

---

## 🏗️ Architecture

The MVP is split into three core components:

1.  **`backend/` (The Coordinator & Ledger)**
    *   A Python FastAPI application that acts as the central coordinator.
    *   A PostgreSQL database maintaining an immutable, double-entry ledger for credit accounting.
    *   Handles job queueing, leasing and worker registration. No hosted-API providers or failover.
2.  **`worker/` (The Contributor CLI)**
    *   A lightweight Python CLI that contributors run on their local machines.
    *   Establishes an outbound connection to the Coordinator (no inbound port forwarding required).
    *   Integrates with local models (via Ollama) and manages usage receipts safely.
3.  **`web/` (The Next.js Dashboard)**
    *   The frontend interface for Contributors, Consumers, and Open-Source Projects.
    *   Today: OIDC or API-key login, test-credit balance, cost estimate, job submit with live status, usage receipts, worker register/revoke with online status, and the open-source project registry with donations. Spending a project's donated budget is not built.

---

## 🚀 Getting Started (Development)

This repository contains the full monorepo for the cooperative.

### 1. Backend (FastAPI + PostgreSQL)
Navigate to the `backend/` directory and use Docker Compose to spin up the API and the database:
```bash
cd backend
docker-compose up --build
```
The API will be available at `http://localhost:8000`.

### 2. Frontend (Next.js)
Navigate to the `web/` directory, install dependencies, and run the development server:
```bash
cd web
npm install
npm run dev
```
The dashboard will be available at `http://localhost:3000`.

### 3. CLI Worker
Navigate to the `worker/` directory and install the CLI in editable mode:
```bash
cd worker
pip install -e .
```
Register a worker on the dashboard, then store its token in the OS keychain and start serving local Ollama models:
```bash
rmt-worker login --worker-id <id>      # prompts for the token; also registers a receipt-signing key
rmt-worker start --worker-id <id> --max-compute-hours 2 --max-tokens-per-day 50000
rmt-worker stop                        # kill switch, from another terminal
```

#### Run with Ollama locally (no Docker)
The smallest end-to-end loop: SQLite coordinator, one worker, one small model (`qwen2.5:0.5b`, about 400 MB).
```bash
ollama serve &                                  # API on localhost:11434 (RMT_OLLAMA_URL to change)
ollama pull qwen2.5:0.5b
cd backend && pip install -r requirements.txt   # Python 3.11/3.12 venv outside the repo
DATABASE_URL=sqlite:////tmp/rmt.db alembic upgrade head
DATABASE_URL=sqlite:////tmp/rmt.db RMT_ENV=dev ADMIN_TOKEN=<pick one> uvicorn app.main:app --port 8000
```
Then: `POST /users` twice (consumer and contributor), `POST /admin/fund` the consumer (`X-Admin-Token`, `Idempotency-Key`), `POST /workers` as the contributor, `rmt-worker login` and `rmt-worker start --model qwen2.5:0.5b`, and `POST /jobs` as the consumer. The job reserves `max_tokens` credits, the worker runs it, and settlement charges the reported completion tokens and refunds the rest. `GET /jobs/{id}/receipt` shows the signed usage.

### 4. Local OIDC login (dev only)
The coordinator ships a stub identity provider for local development. It answers 404 unless both variables below are set:
```bash
RMT_ENV=dev OIDC_STUB=1 OIDC_ISSUER=http://localhost:8000/oidc-stub uvicorn app.main:app   # in backend/
NEXT_PUBLIC_OIDC_ISSUER=http://localhost:8000/oidc-stub npm run dev                        # in web/
```
For a real provider, set `OIDC_ISSUER` (https only outside dev) and `OIDC_AUDIENCE` (its client id) on the coordinator, and `NEXT_PUBLIC_OIDC_ISSUER` / `NEXT_PUBLIC_OIDC_CLIENT_ID` on the web app. With `OIDC_ISSUER` set outside dev, API-key signup (`POST /users`) is closed.

---

## 📄 License & Governance
*In formation.* The brand and protocol are intended to operate as a transparent, open-source public good.
