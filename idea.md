# Product blueprint: a shared AI capacity cooperative

I'd build this as a new product under the broader BlankFrame Technologies infrastructure philosophy: make idle resources useful, reduce the cost of building software, and let people contribute without surrendering control of their machines or data.

The working concept is an AI Capacity Cooperative. The name can come later; the important thing is getting the accounting, security and exchange model right.

**Visual direction:** an infrastructure network, not a crypto exchange or token trading app.

## Supply policy
MVP supply is donor-run local open-weight models under permissive licenses (Apache 2.0 or MIT) only, allowlisted per model license, with the license text passed to consumers. Llama and Gemma are deferred pending counsel. Basis: `docs/provider-terms.md`. Credits are test-only with no cash value until legal and payment review.

**Out of scope and why**
- Consumer-subscription sharing (Claude, ChatGPT, Gemini plans): barred or very likely barred by provider terms.
- Pooled or donated API keys: barred or restricted (Anthropic, Mistral; OpenAI likely, unconfirmed). Needs written provider approval before it is ever revisited.
- Hosted-API adapters and OpenRouter/LiteLLM routing of donated keys: same reason.
- Cash redemption and trading: payment and legal review pending.

## 1. Product definition
**Mission:** let people contribute spare AI capacity, earn a claim on future capacity, and donate resources to open-source work.

The product has three actors:
- **Contributor:** makes local open-weight model inference available.
- **Consumer:** spends earned credits to run AI tasks using capacity supplied by the network.
- **Project maintainer:** submits eligible work and receives donated capacity from the community.

*One person can fill all three roles.*

**The first release**
*Include in v1:*
- Account and contributor enrollment
- Local-model worker using Ollama
- Local-model metering
- Reserve credits and donation pool
- Open-source project registry
- Usage ledger and audit history
- Rate limits and spending caps

*Defer until later:*
- Subscription sharing and API-key pooling (out of scope, see Supply policy)
- Arbitrary remote code execution
- General-purpose GPU job scheduling
- Cash redemption and trading
- Public, unrestricted project marketplace
- Blockchain or cryptocurrency
- Automatic agent execution on donor machines

The first release should be a working capacity exchange for inference, not a universal cloud-computing platform.

## 2. Product flows

**A contributor's journey**
1. Install the worker and register a local model (no API keys or subscriptions).
2. Choose an allocation, such as 70% of eligible capacity for personal reserve credits and 30% for public-good donations.
3. Set limits: maximum monthly spend, maximum compute, permitted models and allowed operating hours.
4. Run the worker. It reports completed jobs and signed usage receipts to the coordinator.
5. See earned credits, donations, task history and outstanding balances on the dashboard.

**A consumer's journey**
1. Request a model, context window, output limit and task type.
2. See the estimated credit cost and available compatible capacity.
3. Approve the request, or set an explicit budget cap for a batch.
4. Receive the output and a receipt showing actual usage, provider/model and credits charged.

**An open-source project's journey**
1. Submit a public repository, license, maintainer identity and proposed tasks.
2. Pass basic moderation and receive a donation budget.
3. Run approved inference jobs within that budget.
4. Publish usage statistics and task outcomes without exposing private donor prompts or credentials.

**The key product promise**
A contributor is not selling their password, account or computer. They are authorizing a narrowly scoped resource contribution under limits they control.
That distinction needs to be enforced by the architecture, not merely written in the terms of service.

## 3. Technical architecture
I recommend a central coordinator with outbound-connected workers for the MVP. This is much easier to secure and operate than a fully peer-to-peer network.

**Component choices**
- **User interface:** Next.js web dashboard
- **Contributor CLI/worker:** Python, packaged for macOS and Linux first
- **Coordinator API:** FastAPI
- **Identity:** Managed OIDC authentication with MFA support
- **Primary database:** PostgreSQL
- **Job queue:** PostgreSQL-backed queue initially; Redis only if needed
- **Model interface:** Provider-specific adapters behind a common internal interface
- **Local inference:** Ollama
- **Secrets:** OS keychain for worker credentials; managed secrets service for server secrets
- **Deployment:** Docker Compose for development; managed hosting for the coordinator
- **Monitoring:** Structured metadata logs, metrics, alerts and append-only audit events

Ollama exposes local model APIs and OpenAI-compatible interfaces, making it a practical starting point for the local inference worker. Its default local endpoint is 127.0.0.1:11434; keep it bound to loopback rather than exposing it directly to the internet.

**Why the worker connects outbound**
The worker should establish an authenticated outbound connection to the coordinator and poll for eligible jobs or use a persistent outbound channel.
This means:
- No inbound port forwarding on a contributor's home router.
- The coordinator cannot browse the contributor's filesystem.
- The worker accepts only signed, authorized job descriptions.
- The user can pause the worker or revoke its registration.
- The coordinator doesn't receive shell access to the donor's computer.
- The worker is a restricted inference gateway, not a remote administration agent.

For v1, it should accept model-inference requests only. Do not allow callers to submit shell commands, install packages, mount directories or request arbitrary files.

**Use a common model interface, not a common assumption**
Internally, define an adapter contract such as:
```python
class ModelProvider: 
    async def list_capabilities(self): ... 
    async def estimate_cost(self, request): ... 
    async def execute(self, request): ... 
    async def verify_usage(self, response): ...
```
Each adapter should return normalized metadata alongside the output:
- Provider and model identifier
- Input, output and cached-token counts, when available
- Actual provider cost, when available
- Latency and completion status
- Provider request ID
- Usage-verification confidence

A local model might not report token counts or costs in the same way as a hosted API. The interface must allow estimates and distinguish them from provider-verified usage.

## 4. The credit ledger: the most important subsystem
Do not store just a mutable field like `users.balance = 120`.
Build an append-only, double-entry ledger. Every transfer of value is recorded as balanced postings, and corrections are new transactions rather than edits to historical records.

**Example: how the reserve bank works** (illustrative; credits are test-only and no conversion policy exists)
Suppose a contributor provides a verified unit of eligible capacity worth 100 credits under the published conversion policy.
- *Contribution settled:* +100 to Contributor's available balance, +100 to Network's outstanding obligation.
- *Consumer spends 30 credits:* +100 for contributor, Reduced by 30 of the settled reserve obligation, with 30 credited to the consumed-resource account.
- *Contributor redeems 20 credits:* +80 balance, Reduced by the settled redemption amount.

These are conceptual events; the actual accounting entries depend on whether capacity has been consumed, is still reserved, or has been redeemed. The critical invariant is that every credit movement has an equal and opposite posting.

**Recommended database entities**
- `users`: Identity, account status, reputation and access level.
- `workers`: Worker identity, supported models, health, userconfigured limits and revocation state.
- `jobs` and `job_attempts`: Task status, resource requirements, provider, retries, idempotency keys and results metadata.
- `usage_receipts`: Reported and verified input/output usage, provider IDs, measured local inference metrics and evidence source.
- `ledger_transactions` and `ledger_postings`: Immutable business events, debit/credit postings, account IDs, currency/resource units and idempotency keys.
- `projects`, `donation_allocations` and `policies`: Verified projects, funding budgets, allowed workloads, moderation decisions and policy versions.

**Don't issue credits for unverified promises**
A contribution should move through explicit states: proposed → reserved → completed → verified → settled.
A failed or cancelled job should release unused capacity reservations. A successful task settles only the amount supported by its usage receipt and the applicable conversion policy.

**What exactly is one credit worth?**
For the first release, I would use a common internal accounting unit with resource-specific pricing. For example, a provider-backed task could be priced from its actual eligible cost, while local inference is priced using a published schedule based on model class, throughput and compute time. 
*Rules:*
1. Credits are not cash. No transfers to bank accounts, trading or secondary markets in v1.
2. Credits are claims on future eligible capacity, not guaranteed inventory. Redemption is subject to availability and published rules.
3. Donations are irrevocable allocations. Donated capacity cannot silently become a contributor's repayable balance.

## 5. Security architecture and threat model
Your differentiator should be that the platform can coordinate capacity without requiring users to trust every other participant.
*Limitation:* We can reduce unnecessary access, but we cannot promise that all prompts are invisible to every party (e.g. host provider logs, compromised local workers).

**Define the trust boundaries**
- **Boundary A: contributor credentials.** The MVP accepts no provider credentials. Worker credentials stay on the device in the OS keychain; the coordinator never receives them.
- **Boundary B: untrusted consumers.** Authenticate each request, enforce request-size and output-token limits, reject prohibited tool calls, and apply per-user quotas. Never trust a client-supplied credit cost or usage count.
- **Boundary C: coordinator and logs.** Store job metadata separately from prompt content. By default, do not persist raw prompts or model responses in the coordinator's database.
- **Boundary D: local model worker.** Run only inference workloads in v1. Do not grant filesystem access, arbitrary shell execution, host credentials or unrestricted network access.

**Security controls required before public beta**
- *Stolen worker credential:* Local-only storage, key rotation and immediate revocation
- *Malicious worker:* Treat outputs as untrusted; validate usage independently where possible
- *Prompt leakage:* No default content logging, strict access control and documented provider retention
- *Credit manipulation:* Server-side pricing, immutable ledger, idempotent settlement
- *Replay or duplicate jobs:* Unique job IDs, signed receipts, idempotency keys
- *Abuse and prohibited requests:* Usage policies, rate limits, abuse reporting and suspension
- *Malicious project submission:* Verified maintainers, moderation, repository/license checks
- *Coordinator compromise:* Least privilege, database backups, encryption, admin MFA and audit trails

**One additional design decision: who can see the code?**
For the MVP, I'd support two task modes:
1. **Private inference:** the consumer sends a prompt to a selected local-model worker. The worker can process the plaintext; the platform avoids retaining it unnecessarily.
2. **Public-good inference:** an open-source project explicitly submits content it is authorized to share. The project may expose task inputs and results publicly if it chooses, but donor data and unrelated user data remain private.

## 6. Provider terms and commercial feasibility
The fact that a provider offers an API does not automatically mean an account holder can resell, pool or redistribute its capacity through your service.

- **Hosted APIs and subscriptions:** Out of scope for the MVP. See `docs/provider-terms.md`.
- **Ollama and locally hosted models:** This is the most straightforward technical starting point. Verify each model's license, redistribution conditions, acceptable use.

## 7. A realistic 12-week roadmap
**Weeks 1–2: Validate the model**
Select one local model runtime. Define the resource-credit conversion policy. Confirm provider terms. Design the ledger and worker permissions.

**Weeks 3–4: Build the inference path**
Worker registration and revocation. Outbound job polling. Ollama adapter. Job lifecycle and signed usage receipts. Basic limits.

**Weeks 5–6: Implement accounting**
Double-entry ledger. Pending reservations and settlement. Refunds for failed jobs. Idempotency. Contributor balance and usage dashboard.

**Weeks 7–8: Add donations**
Project registry and moderation. Donation allocations.

**Weeks 9–10: Harden security**
Threat-model review. Authentication and authorization tests. Worker isolation tests. Secret-leakage tests. Abuse response procedures.

**Weeks 11–12: Run a controlled pilot**
Invite 10–30 trusted contributors. Add vetted open-source projects. Measure successful jobs and collect feedback.

**MVP acceptance criteria**
- No provider credentials transmitted to the coordinator.
- No credit issuance without a recorded, eligible contribution.
- No double settlement when a job is retried.
- No negative balance caused by concurrent requests.
- No ability for a consumer to read another consumer's job history.
- Immediate worker revocation.
- A complete audit trail for credit adjustments.

## 8. The business and governance model
Start with three ledger pools (account groups, not pooled keys or subscriptions; none is built yet):
1. **Reserve pool:** eligible contributions earn credits redeemable for future capacity.
2. **Public-good pool:** voluntary donations fund approved open-source tasks.
3. **Platform reserve:** capacity or financial resources explicitly set aside to support redemptions and absorb operational failures.

Keep them separately accounted for. Don't treat donated capacity as backing for personal credit claims.

## 9. What I would build first
**Milestone 1:** A web dashboard + Python worker + Ollama + PostgreSQL ledger.

The first demo should prove four things:
1. A contributor registers a worker and contributes inference capacity.
2. A consumer spends reserve credits to submit a job.
3. The ledger settles usage exactly once.
4. A contributor can direct some of their contribution to a verified open-source project instead.

## 1. ReserveMyTokens: product identity
**ReserveMyTokens: An AI capacity cooperative**
*Give when idle. Use when needed. Donate what matters.*

The brand should communicate a reserve of donor-run local capacity, and trust. Minimal technical identity: charcoal, warm amber and off-white.

**The core product language:**
- **Reserve** — contribute local open-weight capacity and earn test credits.
- **Redeem** — spend credits on available network capacity.
- **Donate** — direct capacity to approved public-good projects.
- **Connect** — integrate tools (other resource providers only after policy review; none today).

## 2. Make it play well with existing tools
- **LiteLLM:** Deferred. Its client-side interface may be reused later; routing hosted APIs or donated keys through it is out of scope (see Supply policy).
- **OpenRouter:** Deferred. A possible upstream only on the platform's own paid account under a written agreement, never contributor keys.
- **Ollama:** Use it as the initial local-model worker backend.

*The integration principle is simple: reuse existing interfaces, but keep ReserveMyTokens' ledger and contribution rules independent.*

## 3. The interoperability contract
Publish a small, versioned integration specification from the beginning. None of the items below exists yet.
- **OpenAI-compatible inference API:** Let compatible clients use eligible ReserveMyTokens capacity
- **Worker protocol:** Allow third parties to contribute approved local inference capacity
- **Usage receipt schema:** Standardize job IDs, provider/model identity, metering and settlement evidence
- **Project funding API:** Let approved open-source platforms request and report donated capacity
- **Ledger API:** Let users and integrations inspect balances and transaction history
- **Provider adapter interface:** Allow new eligible sources, only after policy review

## 4. Be cooperative at the governance level, too
- **No lock-in:** users can export their usage history and project contribution records.
- **No forced exclusivity:** a contributor can use other inference providers and cooperative networks.
- **Open protocol:** document the worker and receipt formats, and publish a reference client under a permissive license.
- **Independent accounting:** integrations can route requests, but only the ReserveMyTokens ledger determines its own credit obligations.
- **Provider compliance:** never interpret technical access as permission to resell subscription quota.
- **No double counting:** capacity pledged to another network cannot simultaneously be claimed as a fully available ReserveMyTokens contribution.

## 5. Revised positioning
ReserveMyTokens shouldn't claim to be the cheapest inference provider, the largest GPU network, or a replacement for existing model routers.

Its distinctive promise is:
**A portable reserve of AI capacity, earned through contribution and optionally directed toward public-good software.**

Before settling on the public brand, check domain availability, trademarks and confusingly similar product names. The name is the working product decision; its legal and commercial availability still needs verification.
