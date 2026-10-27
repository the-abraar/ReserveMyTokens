# ReserveMyTokens: Launch-Readiness Judgment

> **Current go-to-market score: 15%.** The verdict below is the original 2026-10-12 audit. See *Update 8* at the bottom for the current score, gaps and next steps, and `../GO_TO_MARKET_SCORECARD.md`.

Audited 2026-10-12 against git HEAD `84e1aee` (8 commits). Every file in backend/, worker/, web/, landing-page/, scripts/ and data/ was read.

## Verdict

**Readiness: ~3%.** What exists is a set of docs (`idea.md`, `TODO.md`) and an empty scaffold. None of the core product loop has been built: contribute capacity, verify it, issue credits, spend credits, settle once. The backend has two endpoints, and both return `[]`. The worker fakes its jobs with `random.random()` and fakes inference. The web app is the unchanged `create-next-app` template. Every box in `TODO.md` is unchecked. There are zero tests, no auth and no deploy path. The ledger schema cannot express double-entry accounting. The landing page shows invented live metrics ("Network is Live", "240k+ community nodes"), and it promises to share "unused AI subscription" capacity, which `idea.md` itself says breaks provider terms. The bigger problem is not code. Nobody has answered three questions: who pays or consumes, how a contribution gets verified when a worker can lie, and whether any upstream provider allows this. Treat the repo as a pre-prototype. Don't launch it, and don't show the landing page publicly in its current form.

---

## Critical blockers (ranked)

### 1. The core loop doesn't exist: every runtime path is a stub or mock
- **Evidence**
  - `backend/app/routers/users.py:5-7` and `backend/app/routers/transactions.py:5-7` both return `[]`, and they are the only endpoints.
  - There are no `workers`, `jobs`, `job_attempts`, `projects`, `donation_allocations` or `policies` tables (`backend/app/models/ledger.py`), even though `idea.md` section 4 requires them.
  - `worker/.../polling_client.py:32-45`: `_mock_poll_job` returns a random hard-coded job, and `_mock_submit_result` does nothing (`pass`). It never sends an HTTP request, even though `requests` is a declared dependency.
  - `worker/.../ollama_adapter.py:9-19`: `detect_models` returns the hard-coded `["llama2","mistral"]`, and `run_inference` returns a fake string.
  - `worker/.../cli.py:11` defaults to `localhost:8080`, but the backend listens on `8000` (`backend/docker-compose.yml:18`).
  - `web/app/page.tsx` is the default Next.js page ("To get started, edit the page.tsx file"), and `layout.tsx:16` still has the title "Create Next App". The dashboard and projects pages contain only an `<h1>`.
- **Why it blocks:** No user can do anything. There is no product to launch.
- **Fix system (build in this order):**
  1. Write the schema with Alembic migrations, and remove `create_all` at `main.py:7`. Tables: users, accounts, workers, jobs, job_attempts, usage_receipts, ledger_transactions, ledger_postings, projects, donation_allocations.
  2. Worker API:
     - `POST /workers` registers a worker and returns a worker token plus the server's public key.
     - `DELETE /workers/{id}` revokes it.
     - `POST /workers/{id}/lease` long-polls and claims a job with `SELECT ... FOR UPDATE SKIP LOCKED`, under a lease TTL.
     - `POST /jobs/{id}/result` takes the output and a receipt.
  3. Consumer API: `POST /jobs` (estimate, then reserve credits, then enqueue) and `GET /jobs/{id}`.
  4. Real Ollama adapter: `GET /api/tags`, `POST /api/generate` with `stream=false`, and read `prompt_eval_count`, `eval_count` and `eval_duration` from the response.
  5. A minimal web app: login, balance, a job submission form, and a worker list.
  6. One end-to-end test of the core loop (see #6).

### 2. Contribution verification is unsolved, so credits can be farmed
- **Evidence:** `idea.md` section 5 admits "Malicious worker: ... validate usage independently where possible". There is no receipt signature, no job ID linkage, no verification state machine and no worker identity in `UsageReceipt` (`ledger.py:43-54`, which holds only `service_id` and `tokens_consumed`). Local inference produces no third-party proof, so a worker can report any token count or return garbage.
- **Why it blocks:** Credits are the product. If anyone can mint them by running a fake worker or many Sybil workers, the reserve becomes worthless on day one, and honest contributors are diluted.
- **Fix system:**
  1. Credits are earned only for jobs the coordinator dispatched with real consumer demand. Never pay for self-reported "idle capacity".
  2. Meter on the server side: the coordinator counts tokens on the prompt and output itself with the model's tokenizer, and ignores the counts the worker claims.
  3. Each worker holds an Ed25519 keypair. It signs `job_id || hash(output) || counts`, and the coordinator stores the signature.
  4. Re-run a 2-5% sample of jobs on a trusted worker or with deterministic seeds, and compare. A mismatch triggers slashing and suspension.
  5. Settle with a delay (held balance for N days), with per-account issuance caps and reputation tiers.
  6. Anti-Sybil gate: OIDC plus phone or GitHub-age checks, with a cap on workers per identity.

### 3. Provider terms: the pitch is reselling or pooling API and subscription access
- **Evidence**
  - The landing page hero says "Turn your unused AI subscription ... into a shared public good". The routing section shows "Consuming donated API credits (Claude 3.5 Sonnet)", and the ticker lists `Claude-3.5`.
  - The README "Vision" says "Contribute your spare API quota".
  - `idea.md` section 1 defers subscription sharing and section 6 says "verify", but nothing was verified. `TODO.md` Phase 1 still plans OpenRouter, LiteLLM and SpareCycles adapters that route third-party traffic.
- **Why it blocks:** Consumer subscriptions (Claude Pro/Max, ChatGPT Plus, Gemini) are for personal use. Routing other people's prompts through them breaks the terms and gets accounts banned. API terms generally prohibit sharing, selling or transferring keys or access to third parties. OpenAI's terms say so explicitly. Anthropic's commercial terms restrict making the service available to third parties outside your own product. The platform would induce users to breach their contracts, which exposes it to account bans for every contributor and to inducement-of-breach claims.
- **Fix system:**
  1. Remove every subscription and Claude/OpenAI reference from the landing page and README now.
  2. Launch with **local open-weight models only** (Ollama). Keep an allowlist of models whose licenses permit serving third parties: Apache-2.0 or MIT models such as Qwen and Mistral. Llama goes on the list only if its community license and AUP pass-through are honored.
  3. Any hosted API path must be the platform's own enterprise or reseller account, paid by the platform, under a written agreement. Never contributor keys.
  4. Get written confirmation from SpareCycles and Agentic Commons before claiming integrations (see #8).

### 4. The ledger schema can't do correct double-entry accounting, idempotency or concurrency
- **Evidence:** `backend/app/models/ledger.py`
  - `LedgerPosting.account_id` is an FK to `users.id` (line 35). There is no `accounts` table, so the system accounts required by `idea.md` section 4/8 can't exist: network obligation, donation pool, platform reserve, held/pending.
  - Nothing enforces that a transaction's postings sum to zero.
  - `amount`, `transaction_id` and `account_id` are nullable.
  - `LedgerTransaction.status` is mutable PENDING/COMMITTED/ROLLED_BACK (line 25). That contradicts "append-only".
  - There are no idempotency-key columns or unique constraints.
  - There is no balance check or lock, so concurrent spends can drive a balance negative.
  - `datetime.utcnow` is naive and deprecated.
  - Credits are labelled `currency="TOKENS"`, which mixes up units.
- **Why it blocks:** `idea.md`'s MVP acceptance criteria are "no double settlement" and "no negative balance from concurrent requests". The schema fails both by construction.
- **Fix system:**
  1. Tables:
     - `accounts(id, owner_user_id NULL, type ENUM(user_available, user_held, donation_pool, network_obligation, platform_reserve, project_budget), unit)`
     - `ledger_transactions(id, kind, idempotency_key UNIQUE NOT NULL, ref_job_id, created_at timestamptz)` with no status column
     - `ledger_postings(tx_id NOT NULL, account_id NOT NULL, amount NUMERIC NOT NULL CHECK <> 0)`
  2. A Postgres DEFERRABLE constraint trigger that checks `SUM(amount)=0` per tx. Revoke `UPDATE` and `DELETE` on ledger tables from the app role.
  3. Spending uses a single DB transaction: `SELECT ... FROM account_balances WHERE account_id=? FOR UPDATE`, check `>= amount`, then insert postings. Or keep a cached balance row with `CHECK (balance >= 0)`, updated in the same transaction.
  4. Job lifecycle postings:
     - On submit: reserve (available → held).
     - On a verified result: settle (held → contributor, plus the donation split).
     - On failure or lease expiry: release (held → available).
     - Use the idempotency key `job:{id}:settle` and similar.
  5. Property tests: N concurrent spends never go negative, a replayed settle is a no-op, and the global sum is always 0.

### 5. No authentication or authorization anywhere
- **Evidence:** No auth dependency or middleware exists in `backend/app`. `TODO.md` Phase 1 "Managed OIDC" is unchecked. The web app has no login. The worker has no token.
- **Why it blocks:** Anyone could read or modify anyone's ledger and jobs once endpoints exist. It fails the acceptance criterion "No ability for a consumer to read another consumer's job history".
- **Fix system:**
  1. Users authenticate through managed OIDC (Clerk, Auth0 or WorkOS). The backend validates JWTs through JWKS.
  2. Workers get scoped, revocable tokens, stored hashed on the server and in the OS keychain on the worker (`keyring` library).
  3. Every query filters by `owner_id`, through a dependency that injects `current_user`.
  4. Admin routes require MFA.
  5. Write authz tests for each route.

### 6. Zero tests and no CI
- **Evidence:** There are no test files or CI config anywhere in the repo.
- **Why it blocks:** A credit ledger without invariant tests will silently corrupt balances.
- **Fix system:** Set up pytest with a real Postgres via testcontainers, add GitHub Actions to run lint and tests on every PR, and block merges that fail. Start with three tests:
  1. Ledger invariants and concurrency.
  2. End-to-end: register worker → submit job → lease → result → settle once.
  3. Authz isolation.

### 7. Privacy and security of consumer prompts on untrusted home machines
- **Evidence**
  - The worker logs full prompts and outputs at INFO level: `ollama_adapter.py:18`, `polling_client.py:21,23`. That breaks the project's own Boundary C (`idea.md` section 5).
  - Postgres is published on the host at `5432:5432` with `user/password` (`docker-compose.yml:7-11`).
  - The DB URL default in `database.py:6` contains credentials.
  - Dependencies are unpinned (`requirements.txt`).
  - The API container runs `--reload` with a source bind mount.
  - There is no rate limiting, size limits, CORS policy or HTTPS.
  - `web/.npmrc` sets `allow-scripts=true`.
- **Why it blocks:** Sending a consumer's prompt to an anonymous stranger's GPU is a data-protection problem under GDPR/CCPA. The platform would need to be a processor with sub-processors it can't vet. With no privacy policy and with prompts being logged, this is a liability.
- **Fix system:**
  1. Stop logging prompt and output content. Log only IDs and counts.
  2. Product rule for v1: only **public-good or non-sensitive tasks** go to community workers, and the UI warns about this explicitly. Private inference runs only on platform-operated workers.
  3. Publish a ToS, privacy policy and AUP before any signup.
  4. Production config: secrets come from a secrets manager, the DB is never exposed, deps are pinned with hashes, TLS is on, rate limits use slowapi, and request/output caps are enforced on the server.

### 8. Deceptive marketing and an unverified partner integration
- **Evidence**
  - `landing-page/index.html` says "Network is Live" (~line 76) and "Simulating ... 240,000+ DAU" (line 103). It shows random tickers and random fake "ledger settlements" with `0x` hashes (lines 214-293), and the footer says "Powered by 240k+ community nodes".
  - The project cards show fake progress: "430 distributed local workers", "SpareCycles API Failover Active".
  - The CTA buttons (Connect Worker, Download Worker CLI, Browse Projects) have no `href` or handler.
  - The README claims "we seamlessly failover to SpareCycles", but there is no code for it.
  - `data/seed_projects.json` holds 50 projects scraped from agentic-commons.org with a spoofed `Mozilla/5.0` User-Agent (`scripts/fetch_agentic_commons.py:6`). All 50 have `can_create_task: false`, one is only `acg_self_declared`, and there is no license or permission on record.
- **Why it blocks:** Fake usage metrics count as misleading advertising (FTC and consumer-protection exposure), and they destroy trust for a product whose whole pitch is trustworthy accounting. Named projects such as MetaBrainz, OpenLibrary and OSM appear to endorse a product they never agreed to.
- **Fix system:**
  1. Replace the simulation with a waitlist (email capture) and an honest "pre-launch" banner.
  2. Show real metrics only, read from a public read-only stats endpoint once one exists.
  3. Remove project names until each project opts in. Build a maintainer opt-in flow: verify repo ownership through a GitHub OAuth org check, then accept the terms.
  4. Contact Agentic Commons and SpareCycles for API terms and a partnership before naming them.

### 9. No demand side and no unit economics
- **Evidence:** No consumer persona, pricing or credit-conversion policy exists anywhere. `idea.md` section 4 says "published schedule", but none was published. `TODO.md` Phase 5 tests "10 dummy contributor nodes and 2 active consumer nodes".
- **Why it blocks:** Small local models on consumer GPUs are cheap and commodity, and hosted open-model APIs (Groq, Together, OpenRouter free tiers) cost near zero. So who spends credits here, and on what? Supply of idle GPUs is plentiful but demand is not. Without consumers no jobs get dispatched, and without dispatched jobs no credits can be earned honestly (see #2). The open-source projects in the seed list run human translation and dedup tasks, not LLM batch jobs, and none of them can create tasks (`can_create_task: false` across all 50).
- **Fix system:**
  1. Before writing more code, run 10 interviews with OSS maintainers who need bulk LLM work (translation, triage, labeling). Get 3 committed design partners with real task queues.
  2. Publish a conversion policy: credits per 1k output tokens by model class, and a floor-adjusted price for verification overhead.
  3. Model the economics in a spreadsheet. Measure cost per verified job (including the sampled re-runs), contributor electricity cost against credit value, and the platform's hosting cost. Kill or pivot if the cost per verified token exceeds the Groq/OpenRouter price.

### 10. No deploy path
- **Evidence:**
  - There is only a dev `docker-compose.yml` (with `--reload` and a bind mount).
  - There is no production Dockerfile hardening: it runs as root, has no healthcheck, and dependencies are unpinned.
  - There is no IaC, staging environment, backups, migrations, observability or root `.gitignore`.
  - The worker has no packaging or release (no brew or pipx publish) and no signed binaries.
  - `web/package.json` pins `next 16.4.0` and `react 19.3.0`, and `next.config.ts` uses experimental flags (`cacheComponents`, `partialPrefetching`).
- **Why it blocks:** There is nothing to put in front of pilot users.
- **Fix system:**
  1. Run Postgres on a managed service (Neon, RDS or Supabase) with PITR backups.
  2. Run the API container on Fly, Render or Cloud Run with a non-root user, a healthcheck, and `alembic upgrade` as a release step.
  3. Host the web app on Vercel.
  4. Release the worker to PyPI with `pipx install`, and sign releases with Sigstore.
  5. Use Sentry with structured logs, and alert on ledger invariant violations through a nightly reconciliation job.

---

## Major gaps

- **Worker safety controls missing:** There is no keychain storage, no limits enforcer (hours, caps, kill switch), no job signature verification (Boundary D), and no pause/revoke handling. Ollama's default bind should be checked so it stays on loopback.
- **No job lifecycle state machine:** States proposed → reserved → completed → verified → settled (`idea.md` section 4), plus retries, lease expiry and dead-letter handling. None of these exist.
- **No donation and project-budget accounting:** The allocation split (for example 70/30) is unmodeled. Donations are meant to be irrevocable, and the separation between the donation pool and the reserve pool is unenforced.
- **Credit liability modeling:** Credits are "claims on future capacity". Outstanding claims need a backing policy, an expiry policy and a redemption-availability disclosure. Keep credits **non-purchasable and non-cashable**, so the product avoids stored-value, money-transmission and securities exposure. Get a lawyer's memo before anyone can buy credits.
- **Charity and "donation" language:** Calling credits "donations" to projects implies charitable giving and possible tax claims. Use the word "allocation" or explain in the ToS that donations are not tax-deductible.
- **Abuse and content moderation:** There is no AUP enforcement, prompt filtering or abuse reporting. Workers could be made to generate prohibited content, and contributors carry that risk.
- **Governance and legal entity:** The README says "In formation". There is no entity, license file or trademark check, and `pyproject.toml` lists the placeholder author `blackbird@example.com`.
- **Scope creep in the roadmap:** `TODO.md` plans the OpenRouter, LiteLLM and SpareCycles adapters in Phase 1, before the ledger works. Cut them from v1.
- **Data script hygiene:** `fetch_agentic_commons.py` writes to a relative path, swallows every exception, and checks no schema.

---

## Launch path (ordered)

1. **Week 0, stop the bleeding:** Take down or replace the landing page with an honest waitlist. Remove subscription, Claude and partner claims from the README and landing page. Stop logging prompts in the worker.
2. **Weeks 0-2, validate:** Get 3 OSS design partners with real LLM task queues. Publish a credit conversion policy. Pick the local-only open-weight model allowlist. Get legal review of ToS, privacy, AUP and the non-cash credit structure. Email Agentic Commons and SpareCycles.
3. **Weeks 2-4, ledger first:** Build the accounts/transactions/postings schema with Alembic, the zero-sum trigger, append-only grants, idempotency keys, and locked spends. Test with concurrency and replay property tests. Set up CI.
4. **Weeks 4-6, auth and worker protocol:** OIDC for users, keychain-stored scoped tokens for workers, registration and revocation, `SKIP LOCKED` leasing with TTL, the real Ollama adapter, signed receipts, and server-side token metering.
5. **Weeks 6-7, job lifecycle and settlement:** Reserve, settle and release postings tied to job states. Add held balances, sampled re-execution verification, and slashing.
6. **Weeks 7-8, minimal web:** Login, balance and ledger history, worker management, job submission (public-good only), and project opt-in and allocations.
7. **Weeks 8-9, harden and deploy:** Managed Postgres with backups, a hardened container, staging, Sentry, rate limits, a nightly ledger reconciliation, and the worker on PyPI with signed releases.
8. **Weeks 9-12, closed pilot:** 10-30 trusted contributors and 3 design-partner projects. The pass criteria are `idea.md`'s acceptance list, a reconciled ledger with zero drift, and cost per verified token compared against market price. Decide go, pivot or kill on that number.


---

## Progress log (2026-10-12, Claude session)

**Done:** nothing changed in this session. No edits made.

**Next, in value order:**
1. Remove the fake live metrics ("Network is Live", "240k+ community nodes") and the "unused AI subscription" claim from the landing page.
2. Answer the three open questions in the verdict (who pays, how contributions are verified, whether providers allow it) before any more code.
3. Then the schema, the worker API and one end-to-end test, in the order given in blocker 1.


### Update 2 (supersedes "nothing changed" above; agent-made, not reviewed by a human)

**Done (edited, not rendered):** `landing-page/index.html` now says "Concept Preview - Not Live"; the "unused AI subscription" claim is reworded to pooling donated capacity; "Live" headings, DAU line, "240k+ community nodes" and "Network Healthy" are labelled simulated or illustrative.

**Next:** unchanged from above. Answer the three open questions (who pays, how contributions are verified, whether providers allow it) before building.


### Update 3 (agent-made; results are the agents' own reports unless stated)

**Done (`pytest`: 1 passed on SQLite; worker never run against a real server or Ollama):** SQLAlchemy models plus hand-written Alembic migration `0001_init.py` (`create_all` removed). `app/ledger.py` enforces integer amounts and zero-sum postings, with a unique idempotency key. Worker register, revoke, lease and result routes; consumer job submit and status; bearer tokens stored hashed; `/admin/fund` only with `ADMIN_TOKEN` set. Lease uses `FOR UPDATE SKIP LOCKED` plus compare-and-set. One balanced transaction per job; double-submit settles once. Worker `polling_client.py` and `ollama_adapter.py` are real (port 8000; `/api/tags`, `/api/generate`). Compose requires `POSTGRES_PASSWORD` and no longer exposes the DB port. Root `.gitignore` added.

**Still open (important):** untrusted-worker verification is unsolved. Credits are paid on the worker's self-reported `completion_tokens`, capped at the reservation, so a dishonest worker can inflate payouts. No signing, server-side metering, re-run sampling or sybil gate. Postgres, `SKIP LOCKED` and concurrent settlement untested. No lease-expiry release, no max attempts or dead letter, no long-poll, no rate limiting, simple API keys only. Docker compose not run. The web app (`web/`) is still the create-next-app template. Provider terms question is still unanswered.

### Update 4 (agent-made; verified by `pytest` on SQLite: 4 passed; `npm run build` in web/ passes)

**Done:** (1) Lease expiry: expired leases requeue; after `max_attempts` (default 3, per job) the job becomes terminal `failed` and the reservation is refunded by a balanced `refund` ledger transaction (idempotent). Reaping runs lazily inside each lease call, there is no background sweeper. (2) Sampled redundancy: `REDUNDANCY_PROB` (default 0 = off). For a sampled temperature-0 job, a second, different worker re-runs it; credits are paid only on an exact output match (first worker paid, on the lower of the two self-reported token counts; the verifier earns nothing yet). Mismatch -> status `disputed`, no payout, both attempts flagged, consumer refunded. (3) In-memory per-token rate limit on `POST /jobs` and worker lease (single-process only). (4) `web/` minimal client: API-key login, balance, job submit and list, worker list; `GET /jobs`, `GET /workers` and CORS added for it.

**This is a mitigation, not a solution to untrusted workers.** It only catches disagreement: two colluding or sybil workers (same owner, or one operator with two tokens) agree on a fake output and both pass; both can inflate token counts together; sampling at p<1 means cheating is profitable when the chance of being checked is low; non-zero-temperature jobs get no check at all. Workers currently do not pass `temperature` to Ollama (the lease response carries it). Still no signing, server-side metering, or sybil gate.

**Not run:** Postgres (Docker daemon not running), `SKIP LOCKED` and concurrent settlement, worker against a live server or Ollama, web UI in a browser against the API. Migration 0002 only exercised on SQLite.


### Update 4 (agent-made; agents' own reports, not yet independently re-run)

**Update 4b:** see Update 4 above for what was built (lease expiry and refunds, sampled redundancy, rate limit, web UI). Extra gaps the agent reported: lease reaping runs only when a worker polls (no sweeper); the worker does not yet pass `temperature` to Ollama; `test_core_loop` depends on running before `test_hardening` (it asserts an exact ledger transaction count); the web UI was never loaded in a browser; Docker daemon was off, so Postgres, `SKIP LOCKED` and migration `0002` are untested off SQLite.


### Update 5 (agent-made, round 6; agents' own reports unless marked)

**Done (agent runs: backend pytest 6 passed in normal order, in reversed file order and with `-p no:cacheprovider`; worker tests 4 passed):** the order-dependence defect found by independent verification is fixed (`tests/conftest.py` autouse fixture gives each test a fresh temp SQLite DB, runs `alembic upgrade head`, clears the rate limiter; ledger count assertion is now relative). Background sweeper in the app lifespan reaps expired leases (`SWEEP_INTERVAL_SECONDS`, default 30). Worker passes `temperature` to Ollama (tests mock HTTP). `REDUNDANCY_VERIFIER_PCT` (default 0) pays the verifier within the balanced settle transaction (tested at 25%). `TODO.md` updated (3 items ticked, caveats on others). **`docs/provider-terms.md`** written from primary sources with quotes and access dates.

**Provider findings (UNCONFIRMED parts marked in the doc; counsel must confirm):** subscription sharing is clearly barred (Anthropic: "may not make your Account available to anyone else"); Mistral bars selling or transferring API keys; Apache 2.0 and MIT weights are clear to serve; Llama 3.1 and Gemma allowed with conditions. OpenAI pages returned 403 so those claims rest on search snippets. **Recommended MVP supply: donor-run local Apache or MIT weights only. No subscriptions, no pooled API keys.**

**Still open:** worker trust is still only mitigated, not solved; Postgres, `SKIP LOCKED` and concurrency untested; web UI never loaded against the API; landing page and idea.md should be reconciled with the provider-terms findings.


### Update 6 (agent-made: independent verification, security review, fixes; agents' own reports unless marked)

**Independent re-run confirmed:** backend 6 tests (also in reversed order), worker 4, web build. Worker has no requirements file (only `pyproject.toml`; run `pip install -e .`). Docs edits to `idea.md`, landing page, README and `docs/open_questions.md` were made by an agent that did not re-read them; unverified.

**Security review found (fixed; 9 tests pass in both orders per the agent):** one owner could register two workers and run both redundant runs, bypassing verification and collecting the verifier share; junk answers on redundant jobs were free; `/admin/fund` used a random idempotency key so a retry double-funded, and a non-ASCII token caused a 500. Fixes: the verifier must belong to a different owner than the first worker and the consumer cannot verify their own job; `Worker.disputes` counter (migration `0003`), worker revoked after `DISPUTE_SUSPEND_AFTER` strikes (default 3), which is a mitigation only (both workers get a strike, and the owner can re-register); `/admin/fund` requires an `Idempotency-Key` header (400 without), token compared as bytes. **Behaviour change:** a wrong or missing admin token now returns 401 (was 403; 403 only if `ADMIN_TOKEN` is unset).

**Still open:** migrations 0002 and 0003 not run on Postgres; TODO.md still lists API adapters and SpareCycles; `idea.md` was not fully audited for loose pooling language; worker trust remains a mitigation, not a solution.


---

## Update 8: go-to-market scoring (2026-10-12)

**Score: 15% (was 3%).** Stage: Backend prototype.

**Cap:** 15: worker honesty is unsolved so payouts rest on self-reported numbers, demand is unvalidated, nothing is deployed.

**Dimension scores (0-10):** Product 4, Quality 6, Security 5, Legal 3, Market 1, Ops 2, Honesty 6. Rubric and the other five projects: `../GO_TO_MARKET_SCORECARD.md`.

**Basis and limits:** my judgement from this file's audit, the agents' reports, and independent re-runs of tests and builds. No real-device, real-user or real-host testing has happened, and nothing is committed. Agent-written code has had no human review. Treat the score as +/- 10 points.

### Gaps and flaws, ranked

1. **Worker trust is not solved.** Credits are paid on the worker's own reported `completion_tokens`. Sampled redundancy is a mitigation only: colluding or sybil workers, token inflation by both workers, and unlucky honest workers (both get a dispute strike) remain. Redundancy is off by default.
2. **Demand is unvalidated.** No one has said they would consume or pay for this capacity.
3. **Provider terms limit supply.** Subscription sharing is barred (Anthropic) and key transfer is barred (Mistral). OpenAI terms returned 403, so those findings are UNCONFIRMED, as are Google consumer plans, per-model Qwen and Mistral weight licences and Gemma's prohibited-use policy. Quotes came through a summarising fetch tool and must be re-checked on the live pages. MVP supply should be donor-run local models under Apache 2.0 or MIT only.
4. **Credits behave like money** (ledger, balances, payouts) with no payment or regulatory review. Copy now says credits are test-only; keep it that way until reviewed.
5. **Postgres, `SKIP LOCKED`, concurrent settlement and migrations 0002 and 0003 are untested**; only SQLite ran. The Docker stack was never run.
6. **Web UI never loaded against the API.** `TODO.md` still lists API adapters and SpareCycles; `idea.md` was not fully audited for loose pooling language after the rewrite, and the agent did not re-read its own edits.
7. **Smaller defects:** in-memory rate limits; simple API keys, no OIDC; no long-poll; no max-attempt dead-letter beyond `failed`; worker reads its token from an environment variable; a wrong admin token now returns 401 (was 403).

### What to do next, in order

1. **You:** before more code, talk to 5-10 people who would consume or donate inference capacity; write down who pays and for what.
2. **You:** have counsel confirm `docs/provider-terms.md`; re-check every quote on the live pages and resolve the UNCONFIRMED items.
3. **Code:** design real verification (signed receipts, server-side metering where possible, known-answer probe jobs, stake or reputation) before any payout is real; keep redundancy as one layer.
4. **Code:** run the whole suite on Postgres (docker compose with `POSTGRES_PASSWORD`), including a concurrent-lease test; move rate limiting to a shared store.
5. **Code:** run the worker against a real Ollama and the real API; load the web UI in a browser and test the job and worker pages.
6. **Cleanup:** audit `idea.md`, `TODO.md` and the landing page once more for pooling or live-network claims.
7. **You:** decide whether credits will ever have cash value; if yes, get legal and payment review first.

### Update 9 (2026-10-12, stopped at the 70% usage ceiling)

**Done this round:** retro guardrails (`scripts/check.sh`, pre-commit hook `.githooks/pre-commit`, CI workflow, `AGENTS.md`, `CODING_STANDARDS.md`); orphaned worktrees removed (Suggest.Bike); all work committed and pushed to `origin/main`. Usage mirror `../usage.md` is live (status line writes the 5-hour and 7-day percentages); read it before starting a round.

**I was in the middle of:** nothing half-done. The last action was this log. No uncommitted work remains apart from this file.

**Not verified:** the GitHub CI workflows have never run; the pre-commit hook has never blocked a real commit; no real-device, real-user or real-host testing.
**Next, first:** talk to prospective consumers and donors before more code; counsel review of `docs/provider-terms.md`; see Update 8.

### Update 10 (2026-10-15, agent round)

**Done, and verified by me in this round:**
- **Postgres.** Started `backend/docker-compose.yml` with a throwaway `POSTGRES_PASSWORD` (Postgres 15). The first boot failed: `alembic upgrade head` could not import `app` in the container. Fixed with `prepend_sys_path = .` in `alembic.ini`, and the db got a healthcheck so the api waits for it. Migrations 0001-0004 apply on Postgres; downgrade to 0001 and back up also works. The whole backend suite (14 tests) passes on Postgres in both normal and reversed file order (`TEST_DATABASE_URL`, see AGENTS.md), and also on SQLite.
- **Concurrency tests** (`tests/test_concurrency.py`): two workers race one job through the lease endpoint and exactly one wins (any DB); two reservations race one balance and only one succeeds; on Postgres, a worker cannot see a job whose row another transaction holds (`SKIP LOCKED`); and a second spender blocks on the account row lock and then gets refused. A mutation check showed the threaded overdraw race does NOT catch a removed lock (the window is too small); the deterministic row-lock test does.
- **Rate limit** now lives in a `rate_hits` table (migration 0004, atomic `INSERT ... ON CONFLICT` upsert), so every API process shares it. The sweeper prunes old windows. Tested on both databases.
- **Web UI** loaded in headless Chrome against the local API on Postgres: login, balance, job submit, job completing after a worker lease plus result, and the worker list all work. I added worker register (token shown once) and revoke, labelled the job form inputs, and deleted the two empty `/dashboard/*` stub routes. `next dev` was writing `web/AGENTS.md`; `agentRules: false` turns that off.
- **Cleanup:** the landing page no longer shows a "SpareCycles-Pool" provider, SpareCycles failover or "Built for the Agentic Commons", and the worker buttons say the worker is not released. README drops "cryptographically verifiable claim" and the SpareCycles failover claim. In idea.md, LiteLLM and OpenRouter are marked deferred and the reserve example is marked illustrative. The TODO adapter items are struck as out of scope. Credits remain test-only.
- `scripts/check.sh`: every step passes, including ruff and web-lint, which were previously listed as known failures.

**Still open:** worker trust (the payout still rests on self-reported tokens), demand, counsel review, and the cash-value decision. Those are unchanged from Update 8 items 1-3 and 7. Not done: running the worker against real Ollama, racing two concurrent settles, and running the Postgres suite in CI (it is manual and needs Docker). The web app is one page with no job polling and no receipts view. Nothing is deployed.

### Update 11 (2026-10-16, agent round; nothing committed)

**Done, and verified by me in this round** (`scripts/check.sh` passes all steps: backend 32 passed and 2 Postgres-only skips, in both file orders; worker 20 passed; web lint and build. On Postgres 15 in Docker the backend suite gives 34 passed in both orders, and migration 0005 downgrades and re-applies on Postgres and SQLite):
- **OIDC.** The coordinator accepts an RS256 ID token from `OIDC_ISSUER` as a bearer token, verified against the issuer's JWKS (refetched at most hourly), and maps (iss, sub) to a user on first login. A dev-only stub issuer (`app/oidc.py`, code + PKCE) answers 404 unless `OIDC_STUB=1` and `RMT_ENV=dev`. Outside dev, a plain-http issuer is refused and API-key signup (`POST /users`) closes once `OIDC_ISSUER` is set. Tests cover forged, unsigned, wrong-audience and replayed-code cases. The web app logs in through the same flow, checked in headless Chrome. No real managed provider is wired yet, and there is no MFA or refresh token.
- **Worker CLI.** `rmt-worker login` stores the token and a new Ed25519 signing key in the OS keychain (one real macOS Keychain round-trip, then deleted) and registers the public key. `start` long-polls (`?wait=`, at most 25 s) and enforces local limits: compute hours and completion tokens per rolling 24 h, plus a kill-switch file (`rmt-worker stop`). The wheel builds and runs from a clean venv. There is no brew formula.
- **`ModelProvider`** is an ABC in `worker/.../provider.py` that the Ollama adapter implements. Pricing stays on the server (`GET /estimate`).
- **Signed receipts.** Once a worker has a key, an unsigned or mismatched result gets a 400 before the job is claimed, and signed numbers cannot be inflated. `GET /jobs/{id}/receipt` returns the payload, signature and key. This proves who made the claim. It does not prove the claim is true: payouts still rest on self-reported tokens (blocker 2 is unchanged).
- **Dashboard.** Worker online status, last seen time, models and jobs settled; a cost estimate with the count of online workers; auto-refresh while jobs run; a receipt view; and a `/projects` registry with donations. Donations are idempotent, irrevocable transfers to a per-project ledger account, and an admin verifies projects. All of this was clicked through in headless Chrome against a local API: OIDC login, worker register, estimate, job, receipt, propose, verify, donate, and the final balance.
- **Boundaries.** A: a test runs login and serve with host API-key environment variables set and asserts that only the worker token, the public key and the result leave the machine. D: the worker refuses jobs with unknown fields, wrong types or an unoffered model, and an AST test bans exec-style calls in the worker package. B and C: see the table. The e2e test asserts that the prompt and output do not appear in the coordinator's debug log or the worker's logs, and a mutation that logs the prompt fails it.
- **Races.** Concurrent duplicate results settle exactly once, and a late result racing the lease reaper either settles or refunds, never both. Both run on SQLite and Postgres. A mutation that removes the settle compare-and-set fails the duplicate race test.
- **End to end.** `tests/test_e2e.py` starts real uvicorn and covers OIDC over HTTP, the CLI, an HTTP fake of the Ollama API, the ledger checks and the dashboard's API calls. The pilot simulation runs 10 dummy contributor nodes and 2 consumers: all 20 jobs settle once, consumer spend equals contributor earnings, and the ledger balances. The test is in check.sh, and it needs a free localhost port.

**Endpoint audit (Boundary B/C):**

| Endpoint | Auth | Rate limit | Idempotency | Cap |
|---|---|---|---|---|
| `POST /users` | none (closed when OIDC is set outside dev) | **none** | n/a | username 64 |
| `GET /users/me`, `/users/me/balance` | user | none | read | - |
| `POST /admin/fund`, `/admin/projects/{id}/verify` | admin token | none | key required / compare-and-set | - |
| `POST /jobs` | user | 30/min | `Idempotency-Key` (new; optional) | prompt 20k, max_tokens 4096 |
| `GET /jobs`, `/jobs/{id}`, `/jobs/{id}/receipt`, `/estimate` | user (own jobs only) | none | read | list 50 |
| `POST /workers` | user | none | n/a | **20 active per user (new)** |
| `GET /workers`, `DELETE /workers/{id}` | user (own) | none | revoke is idempotent | list 200 |
| `PUT /workers/{id}/public_key` | worker | none | set once (compare-and-set) | 100 chars |
| `POST /workers/{id}/lease` | worker | 120/min | lease compare-and-set | wait 25 s, models 100 |
| `POST /jobs/{id}/result` | worker holding the lease | none | compare-and-set + ledger key | output 200k, 1 receipt per job |
| `GET /projects` | none (public registry) | none | read | list 100 |
| `POST /projects` | user | **none** | name unique | name 100, description 1000 |
| `POST /projects/{id}/donations` | user | none | key required | amount 1e9 |
| `/oidc-stub/*` | none (it is the IdP; dev only) | none | single-use codes | form 10 KB |

**Not done, and why:** the Ollama adapter has never run against real Ollama, because Ollama is not installed here; it ran only against mocks and an HTTP fake. Staging deploy, beta-tester packaging and distribution, a real OIDC provider, and reconciling real provider bills all need a human or an outside account.

**Still open:** worker trust (blocker 2), demand, counsel review and the cash-value decision are unchanged. `POST /users` and `POST /projects` have no rate limit. Prompts are stored until the job finishes and outputs are kept, so Boundary C ("do not persist") is only partly met. Limit counters reset when the worker restarts. Long-poll holds one server thread per waiting worker. The stub's signing key and auth codes are per process, which is fine only for dev. A user's own worker can serve that user's non-redundant jobs, which nets to zero credits. Spending a project's donated budget is not built.

### Update 12 (2026-10-16, agent round)

**Done, and verified by me in this round** (`scripts/check.sh` passes all steps: backend 33 passed and 2 Postgres-only skips, in both file orders; worker 20; web lint and build. On Postgres 15 in a throwaway Docker container the backend suite gives 35 passed in both orders):
- **Flaky pilot test fixed.** The 10-node pilot simulation failed "work was spread over several nodes" (`assert 1 >= 2`) in 3 of 30 runs: with an instant dummy model the first node drained all 20 jobs before the others' 0.5 s long-poll step came round. The dummy now takes 0.1 s per job, like a real run. After the fix: 30 of 30 passed.
- **Several settles of one job at once.** The duplicate-result race now fires 6 identical results together (was 2): exactly one settles, the other 5 get a no-op 200, held ends at 0 and the contributor is paid once. A new test goes below the API: 6 sessions post the same `job:{id}:settle` ledger key at once, and the unique key lets exactly one through, so the held reservation is drained once and never overdrawn. Both run on SQLite and Postgres. Mutation checks on Postgres: removing the result compare-and-set fails the first test, and making the key unique per call (6 settles posted) fails the second.
- **Postgres in CI.** `.github/workflows/check.yml` has a second job, `postgres`, with a `postgres:15` service container that runs the backend suite on Postgres in both file orders. Its install and test commands were rerun from a clean venv against local Postgres 15 (35 passed, both orders). It is in its own commit, the last one of this round.

**CI result (after push):** GitHub Actions run 38930066284 on `e48455f` passed both jobs, `check` and `postgres`. The previous run, on `1f4f050`, had failed on the same pilot-test flake fixed above.

**Not verified:** one green CI run is not proof that the Postgres job is stable. The Ollama adapter still has never run against real Ollama: Ollama is not installed on this machine, and this round did not install it.

**Still open:** worker trust (blocker 2), demand, counsel review and the cash-value decision are unchanged from Update 11, as are the other items in its "Still open" list.

### Update 13 (2026-10-21, agent round): first run against real Ollama

**Done, and verified by me in this round:** Ollama 0.40.6 (Homebrew) with `qwen2.5:0.5b`, the smallest common chat model (about 400 MB, Apache 2.0). The worker only calls `/api/tags` and `/api/generate`, so any model works; this one keeps the download and RAM small. Coordinator: uvicorn on SQLite (`alembic upgrade head` to 0005), `RMT_ENV=dev`, an admin token. Steps: two API-key users; the consumer funded 1000 test credits; the contributor registered a worker; `rmt-worker login` stored the token and signing key in the real macOS Keychain; `rmt-worker start --model qwen2.5:0.5b`.
- Job 1, "What is the capital of France? Answer in one word.", `max_tokens` 64: reserve moved 64 to held, the worker leased it, Ollama answered "Paris" with 41 prompt and 2 completion tokens (a direct `/api/generate` call gave the same counts), settle charged 2 and refunded 62. Consumer 998, contributor 2, held 0.
- Job 2, a long story capped at `max_tokens` 8: output was cut at 8 tokens, charged 8. Final balances: consumer 990, contributor 10.
- Both receipts are signed and verify (Ed25519). All 5 ledger transactions sum to 0, and so does the whole ledger. Both job prompts are blank after settlement. Neither the API log nor the worker log contains a prompt or an output. `rmt-worker stop` ended the worker after its long-poll; `logout` removed the Keychain entry.

**Bugs found:** none. Minor: on SQLite, `created_at` in the job view carries `+00:00` in the `POST /jobs` response but not on later reads (SQLite drops tzinfo); Postgres is unaffected. Not fixed.

**Not verified:** larger models, GPU contention, a long (minutes) generation against the 600 s adapter timeout, and the web dashboard against real Ollama. Token counts are still self-reported (blocker 2 unchanged).

**2026-10-21, independent re-run (second agent, own backend and DB):** CI run 39080812004 on `0162929` (checkout v5, setup-python v6, setup-node v5, ubuntu-24.04) passed both jobs, `check` and `postgres`; nothing to fix. Same stack, Ollama 0.40.6 + `qwen2.5:0.5b`: a one-word question at temperature 0 (`max_tokens` 64) answered "Jupiter" and charged 3 (41 prompt / 3 completion tokens, identical to a direct `/api/generate` call); a poem at temperature 0.7 capped at 10 charged 10. Consumer 987, contributor 13, held 0; all 5 ledger transactions sum to 0; both receipts verify; prompts blank; no prompt or output in the API, worker or Ollama logs; `rmt-worker stop` ended the worker in 11 s and `logout` cleared the Keychain. Bugs: none. Disk: model 379 MB in `~/.ollama`; Homebrew added about 330 MB (ollama 51 MB, mlx 164 MB, python@3.15 88 MB, openssl@4 24 MB). The install relinked Homebrew's default `openssl` to openssl@4; formulae that depend on openssl@3 still use its keg.

### Update 14 (2026-10-22, agent round)

**Done, and verified by me in this round** (`scripts/check.sh` passes all steps: backend 35 passed and 2 Postgres-only skips, in both file orders; worker 20; web lint and build. On Postgres 15 in a throwaway Docker container the backend suite gives 37 passed in both orders):
- **Rate limits on `POST /users` and `POST /projects`.** Both use the existing database-backed limiter (`app/ratelimit.py`), so it works on SQLite and Postgres and across API processes. Signup is counted per client IP (5/min, `RATE_SIGNUP_PER_MIN`), because it is unauthenticated and a per-header key could be dodged by sending a new header each time; project submit is per user token (5/min, `RATE_PROJECT_PER_MIN`). Behind a reverse proxy, uvicorn must run with `--proxy-headers` and `--forwarded-allow-ips`, or every client shares the proxy's IP. Test: `test_signup_and_project_submit_are_rate_limited`.
- **Timestamps.** Every timestamp column now reads back as aware UTC (a `TypeDecorator` in `app/models/ledger.py`), so `GET /jobs`, `/jobs/{id}`, `/workers` and receipts carry `+00:00` like the `POST /jobs` response did. This fixes the SQLite issue from Update 13 and replaces the `_aware` helper in `workers.py`. Test: `test_timestamps_read_back_in_utc` (it fails with the old column type).
- TODO.md: the Ollama adapter is ticked (verified in Update 13).

**Still open:** unchanged from Update 13, except for the two items above.

### Update 15 (2026-10-25, agent round)

**Done:** `docs/worker-verification.md` designs five layers for checking reported `completion_tokens` (signed receipts, server-side metering, known-answer probes, redundancy, stake and reputation). Layer 3 is implemented: `POST /admin/probes` (admin token) makes a temperature-0 job owned by the system user `rmt-probe` with `expected_output` and `expected_tokens` (migration 0006). A probe settles nothing (no reservation, receipt or ledger posting); a wrong output or token count flags the attempt and adds a dispute strike, and `DISPUTE_SUSPEND_AFTER` strikes suspend the worker. The worker gets the same reply as for any unpaid job. The strike code is now one helper shared with the redundancy dispute path. Test: `test_probe_job_grades_without_paying`. Backend 36 passed, 2 skipped, both file orders; worker 20; ruff and web-lint pass.

**Not done / not verified:** blocker 2 is unchanged (paid jobs still rest on self-reported tokens; probes only sample). No probe scheduler, no prompt pool, exact-match grading assumes determinism. Not run on Postgres this round. `check.sh` `web-build` failed here: `next build` compiled and then stopped on a Next.js known-vulnerability notice from the npm advisory check (it also printed instructions to upgrade). Not touched this round; upgrading Next.js is a decision for a human.

**2026-10-27, agent round (Update 8 items 4-6):** Item 4: the whole backend suite ran on Postgres 15 (`docker compose` db service, throwaway password, port on 127.0.0.1, torn down with its volume after): 38 passed in both file orders, including the concurrent-lease race (`test_two_workers_one_job_exactly_one_lease`, already there) and the Update 15 probe test; migration 0006 downgrades and re-applies on Postgres. Rate limiting was already on a shared store (`rate_hits` table, Update 10), so nothing to move. Item 5: real Ollama 0.40.6 + `qwen2.5:0.5b`, SQLite coordinator, worker CLI with `RMT_WORKER_TOKEN` (unsigned; the Keychain path was covered in Update 13): three probes passed exact-match grading (each prompt gave identical output and token count in 3 direct temperature-0 calls and in the worker run, including a 32-token sentence), a probe with a wrong answer key was flagged and gave one strike, a paid job ("Tokyo.") charged 4 and refunded 60, ledger sums to 0, prompts blank, no prompt or output in the API or worker logs. Web UI not re-checked in a browser. Item 6: idea.md, TODO.md, README and the landing page no longer say peer-to-peer, network capacity, donation pool, provider-backed pricing or planned SpareCycles failover; the landing page's pinging and green "live" dots are gone. `check.sh`: every step passes except `web-build` (the Next.js 16.4.0 vulnerability stop from Update 15; not upgraded, human decision).

### Update (2026-10-27, agent round 2)

Continues the 2026-10-27 run above (Update 8 gaps 5 and 6); did not redo the Ollama run.
- **Postgres (re-run at `4c63795`):** throwaway `postgres:15` container on 127.0.0.1:55432. The backend suite gives 38 passed, 0 skipped, in both file orders, so the `SKIP LOCKED`, row-lock, concurrent-lease and concurrent-settle tests (`tests/test_concurrency.py`: 6 duplicate results, 6 same-key ledger settles, result vs lease reaper) all ran on Postgres. No new concurrency test was needed. Migrations `base -> 0006 -> base -> 0006` on an empty Postgres database: clean.
- **Docker stack:** `docker compose -p rmt up --build` (Postgres 15 + API image). The api waits for the db healthcheck and runs `alembic upgrade head` to 0006. Smoke test over HTTP: signup, admin fund, worker register, job (reserve 50), lease, result (charged 7, refund 43), a duplicate result is a no-op, receipt, worker list (online, 1 settled), project propose, verify and donate, a bad admin token gets 401, CORS preflight. All 56 ledger postings sum to 0. Settled prompts are blank. Neither prompt nor output appears in the API log. Torn down with its volume and image.
- **Web UI against the compose API:** `next dev` with `NEXT_PUBLIC_API_URL`, Playwright Chromium at 375x812 and 1280x800 (screenshots read). Covered: API-key login, estimate, submit, auto-refresh to completed after a lease and result, receipt, balances, worker register and revoke, project propose, donate, logout, wrong key. No console errors and no horizontal scroll on mobile.
- **Bugs fixed (`4eda5de`):** (1) Compose hard-coded port 8000 and passed no `CORS_ORIGINS`, so the web app could only reach the stack from `localhost:3000`. Now `API_PORT` and `CORS_ORIGINS` are set from the environment. (2) Tailwind's preflight stripped every border and heading size: the login page's API key field was invisible, and buttons looked like text. Base styles are restored in `globals.css`. (3) A long worker token made the mobile dashboard scroll sideways. (4) A wrong or expired key left the user on a dashboard showing `...` forever. A 401 now returns to the login form with the error.
- **Next.js notice:** `next dev` and `next build` stop on every other run with the 16.4.0 vulnerability notice, then continue on the next run. This round `check.sh` failed only at that `web-build` stop, then passed every step on the re-run (backend 36 passed and 2 skipped in both orders, worker 20). The upgrade is still not done, because it is a human decision.

**Still unverified:** the UI was not tested with OIDC login against compose (compose does not pass `RMT_ENV` or `OIDC_STUB`; Update 11 covered OIDC in the browser against uvicorn), in dark mode, or with the real worker CLI against the containerised API (the e2e test covers the CLI against uvicorn). The UI is still minimal. Blockers 1-4 are unchanged.
