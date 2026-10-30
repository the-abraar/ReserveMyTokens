# Verifying workers' reported completion_tokens

Status: design (2026-10-25). Only layer 3 (known-answer probes) is implemented. Credits are test-only and have no cash value; this must be solved before any payout is real (judge.md blocker 2).

## Problem

A worker reports `completion_tokens` and the coordinator charges `min(tokens, max_tokens)`. The worker is paid from that charge, so it can inflate the count. Today the only defences are the `max_tokens` cap, the optional redundancy re-run (temperature 0 only) and Ed25519 receipts.

## Layers

| # | Layer | Stops | Does not stop | Cost | Status |
|---|---|---|---|---|---|
| 1 | Signed receipts | Repudiation, tampering after signing, consumer/worker disputes about what was claimed | A lie signed by the worker | Done | Implemented (`app/receipts.py`) |
| 2 | Server-side metering | Inflated counts, if the coordinator counts tokens itself | Needs the tokenizer for each model, so it is approximate. Cannot see inside the worker, so it cannot catch padding that tokenizes to fewer tokens | Medium | Design only |
| 3 | Known-answer probe jobs | A worker that cheats on output or token count in general | A worker that detects probes (for example by remembering prompts), or cheats only on some jobs | Small | Implemented (basic) |
| 4 | Redundancy re-run | Wrong output at temperature 0 | Colluding workers, sampled jobs | 2x compute on sampled jobs | Implemented (`REDUNDANCY_PROB`) |
| 5 | Stake / reputation | Sybil cheating that is profitable once | Needs value to stake; credits are not money | Large | Design only |

No layer is enough alone. Use 2 as the cheap broad check, 3 and 4 as sampled audits, 5 as the deterrent that makes audits pay off.

### 1. Signed receipts
Done. A receipt binds (job, worker, output, tokens, duration) to the worker's key. It gives evidence, not truth.

### 2. Server-side metering (design)
- Coordinator recomputes completion tokens from `output` with the model's tokenizer and compares with the report. Tolerance band (for example 5% or 2 tokens); outside it, charge the server count and add a strike.
- Needs a tokenizer per advertised model (`tiktoken` or `tokenizers`). Models without one are not metered and fall back to layers 3-5.
- Caveat: `output` is only the visible text. Hidden reasoning tokens are generated but not returned, so a server count undercounts honest workers. Decide first whether hidden tokens are billable (probably not).
- Streaming relay (coordinator proxies the stream and counts chunks) is the only true metering, but it breaks the "prompt never leaves the worker's machine" boundary and the long-poll design. Not recommended now.

### 3. Known-answer probe jobs (implemented)
- Admin creates a probe with `POST /admin/probes` (model, prompt, max_tokens, `expected_output`, `expected_tokens`). It is a temperature-0 job owned by the system user `rmt-probe`, and goes through the normal queue and lease. Its reservation (`max_tokens` test credits) is minted from issuance at creation, like `/admin/fund`.
- On result, the coordinator compares output and `completion_tokens` exactly. A correct answer settles exactly like a paid job (same reply, same payout, a receipt), so a worker cannot tell a probe from a paid job by the lease body, the result reply or its owner's balance. A mismatch pays nothing, refunds the reservation, flags the attempt and adds a dispute strike; `DISPUTE_SUSPEND_AFTER` strikes suspend the worker. (Until 2026-10-30 a probe never paid and replied `settled: false`, which told a worker afterwards which prompts were probes.)
- Limits (kept visible on purpose):
  - Exact match assumes the model is deterministic at temperature 0 on the worker's hardware and build. If it is not, honest workers take strikes; use short prompts and re-check expected values per model.
  - Probes are created by hand. There is no scheduler or per-worker sampling rate. A cheater who sees the same prompt twice could cache it; vary prompts.
  - A probe is only leased when a worker advertises its model and has budget (`max_tokens`).
  - A worker that is wrong on probes is caught only on probes. It is a sample, not a proof about each paid job.
  - A failed probe replies `settled: false`, so a caught worker learns that prompt was a probe. Hiding that would mean paying wrong answers.
  - Passing probes mint test credits. Fine while credits have no cash value; revisit with the cash-value decision.
- Next steps: a sampler that injects probes at a rate per worker, a pool of probe prompts per model, and a read-only count of probe passes and fails per worker.

### 4. Redundancy
Already live for temperature-0 jobs (see `judge.md`). It pays on the lower of two reported counts. Same-owner workers cannot verify each other.

### 5. Stake / reputation (design)
- Reputation: per-worker score from probe results, redundancy agreement and strikes. Lease priority and the redundancy rate depend on it; new workers start low and get more probes.
- Stake: a worker owner locks credits in a `worker_stake` account (ledger, balanced, idempotent). A confirmed lie slashes part of it to the consumer. This only deters if the stake can be worth more than one cheat, so it needs the cash-value decision and legal review first (CODING_STANDARDS "No cash value"). Do not build it before that.
- Sybil: owners can register 20 workers each; reputation and stake must be per owner, not per worker id.

## Decisions needed from a human
1. Are hidden reasoning tokens billable?
2. Tolerance band for server-side metering.
3. Whether credits will ever have cash value (gates stake).
