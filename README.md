# ReserveMyTokens - An AI Capacity Cooperative

> Give when idle. Use when needed. Donate what matters.

**ReserveMyTokens** is a peer-to-peer cooperative for sharing, saving, and donating unused AI model capacity and local compute. 

Instead of letting your monthly AI subscription quotas go to waste or your local GPU sit idle, you can contribute that capacity to the network. In return, you earn credits to borrow capacity later, or you can explicitly donate your compute to verified open-source projects that need it.

---

## 🌟 The Vision

*   **Reserve:** Contribute your spare API quota or local inference capacity today, and earn a cryptographically verifiable claim on future network capacity.
*   **Donate:** Directly fund public-good projects (like Wikipedia maintainers, Open Food Facts, etc.) by routing your unused capacity to their tasks.
*   **Interoperate:** We aren't trying to replace OpenRouter or LiteLLM. We act as a cooperative ledger layer. 

We play well with others! If a project runs out of donated capacity in our network, we seamlessly failover to [SpareCycles](https://sparecycles.io) to keep their tasks alive. We also source our verified open-source projects directly from the [Agentic Commons](https://agentic-commons.org) directory.

---

## 🏗️ Architecture

The MVP is split into three core components:

1.  **`backend/` (The Coordinator & Ledger)**
    *   A Python FastAPI application that acts as the central coordinator.
    *   A PostgreSQL database maintaining an immutable, double-entry ledger for credit accounting.
    *   Handles Job queueing, worker registration, and API provider failovers.
2.  **`worker/` (The Contributor CLI)**
    *   A lightweight Python CLI that contributors run on their local machines.
    *   Establishes an outbound connection to the Coordinator (no inbound port forwarding required).
    *   Integrates with local models (via Ollama) and manages usage receipts safely.
3.  **`web/` (The Next.js Dashboard)**
    *   The frontend interface for Contributors, Consumers, and Open-Source Projects.
    *   View your reserve balance, manage your worker nodes, and allocate donations to the public-good pool.

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
