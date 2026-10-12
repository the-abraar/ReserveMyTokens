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

- [ ] Initialize the Python FastAPI project and PostgreSQL database using Docker Compose.
- [ ] Implement Managed OIDC authentication (with mock/stub for local dev).
- [x] Design and implement the double-entry PostgreSQL ledger schema (`users`, `ledger_transactions`, `ledger_postings`, `usage_receipts`).
- [x] Create the Worker registration and revocation API endpoints.
- [x] Create the Job queue and polling endpoints for the outbound workers. (short poll, SQLite tests only; Postgres/SKIP LOCKED untested)
- [ ] Implement the core `ModelProvider` adapter interface.
- [ ] Build the OpenRouter / LiteLLM adapter for fallback API inference.
- [ ] **SpareCycles Integration**: Add an adapter for the SpareCycles OpenAI-compatible endpoint (route donated capacity to/from their network).

## Phase 2: The Contributor CLI Worker (Weeks 3-5)
**Assigned to: @agent/worker-cli**

- [ ] Scaffold the Python CLI application (installable via pip/brew).
- [ ] Implement secure credential storage using OS keychain for provider keys.
- [ ] Build the outbound long-polling client (short-poll client exists, unit-tested with mocked HTTP only; never run against a live server) to connect to the Coordinator API.
- [ ] Implement the **Ollama Adapter**: detect local models, parse tasks, run inference, and collect metrics. (code + mocked unit test incl. temperature; never run against real Ollama)
- [ ] Implement Signed Usage Receipts (generate cryptographically signed payload of task completion).
- [ ] Implement the local limits enforcer (max compute hours, spending caps, kill switch).

## Phase 3: The Web Dashboard (Weeks 5-8)
**Assigned to: @agent/frontend-ui**

- [ ] Initialize the Next.js frontend application.
- [ ] Build the **Contributor Dashboard**: view earned credits, registered workers, and connection status.
- [ ] Build the **Consumer Dashboard**: input prompts, estimate credit costs, and view task outputs/receipts.
- [ ] Build the **Donation & Open-Source Registry**: list verified projects, show funding budgets, and allow users to allocate their reserve credits.
- [ ] Integrate OIDC login with the FastAPI coordinator.

## Phase 4: Integration & Security Hardening (Weeks 9-10)
**Assigned to: @agent/security-auditor**

- [ ] Verify Boundary A: Ensure no local API keys are transmitted to the coordinator.
- [ ] Verify Boundary B & C: Audit FastAPI endpoints for rate-limiting, idempotency keys, and prompt-leakage (ensure prompts aren't logged).
- [ ] Verify Boundary D: Ensure the worker only accepts inference jobs (rejects arbitrary shell execution).
- [ ] Test double-entry ledger constraints (no negative balances from concurrent requests, no double settlement). (balanced postings, double settle, overdraw tested sequentially on SQLite; concurrency untested)
- [ ] Write integration tests for the end-to-end flow: `CLI -> Coordinator -> Ledger -> Web Dashboard`.

## Phase 5: The Pilot (Weeks 11-12)
**Assigned to: All Agents**

- [ ] Deploy Coordinator and Web UI to a staging environment.
- [ ] Package CLI for initial beta testers.
- [ ] Run end-to-end simulation with 10 dummy contributor nodes and 2 active consumer nodes.
- [ ] Reconcile provider costs against the internal ledger.
