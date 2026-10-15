# ReserveMyTokens - An AI Capacity Cooperative

> Give when idle. Use when needed. Donate what matters.

**ReserveMyTokens** is a peer-to-peer cooperative for sharing, saving, and donating unused AI model capacity and local compute. 

Instead of letting your local GPU sit idle, you can run an open-weight model (Apache 2.0 or MIT licensed) and contribute that capacity to the network. Subscription sharing and pooled API keys are not supported (see `docs/provider-terms.md`). In return, you earn credits to borrow capacity later, or you can explicitly donate your compute to verified open-source projects that need it.

---

## 🌟 The Vision

*   **Reserve:** Contribute local open-weight inference capacity today, and earn test credits toward future capacity. Contributions are not yet verified: credits are paid on worker-reported token counts (signed receipts are planned, not built).
*   **Donate:** Directly fund public-good projects (like Wikipedia maintainers, Open Food Facts, etc.) by routing your unused capacity to their tasks.
*   **Interoperate:** We aren't trying to replace OpenRouter or LiteLLM. We act as a cooperative ledger layer. 

Planned, not built: failover to [SpareCycles](https://sparecycles.io) when local capacity runs out, pending their written confirmation and a provider-terms check. The seed project list is fetched from the public [Agentic Commons](https://agentic-commons.org) directory; there is no partnership.

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
    *   Today: view your test-credit balance, submit jobs, and register or revoke workers. Project donations are not built.

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
Run the worker using the mapped entrypoint:
```bash
rmt-worker --help
```

---

## 📄 License & Governance
*In formation.* The brand and protocol are intended to operate as a transparent, open-source public good.
