# ReserveMyTokens: post-mortem

**Status: stopped. Nothing was ever deployed, no outside worker or consumer ever used it, and no credit has cash value.**
Built 2026-10-09 to 2026-10-30. Demo of the ledger and the flaw that killed it: [`demo/index.html`](demo/index.html).
Every number below comes from `judge.md` (the audit and round log), `docs/`, the tests, or `demo/data/jobs.json`.

## What it was

A coordinator (FastAPI + Postgres), a worker CLI (Ollama) and a Next.js dashboard. Consumers reserve test credits and
submit a prompt; a volunteer's worker leases the job, runs a local open-weight model, and is paid per completion token
out of the reservation. The unused part goes back to the consumer.

## Why it stopped

1. **Terms read too late.** The first landing page (2026-10-09, `f506163`) said "Turn your unused AI subscription ...
   into a shared public good". `docs/provider-terms.md` was written on 2026-10-12, after the page and the roadmap.
   It found subscription sharing barred (Anthropic consumer terms: "You also may not make your Account available to
   anyone else"), API-key transfer barred (Mistral s2.2(h)), and OpenAI's pages unreadable to the fetcher
   (UNCONFIRMED). That left one legal supply: donor-run local Apache-2.0 or MIT models. That is the supply that
   costs the least to get elsewhere.
2. **Demand was never asked.** `judge.md` Update 8 put "talk to 5-10 people who would consume or donate inference
   capacity" first, before more code. It is still open in Update 16. Nobody said they would consume or pay.
3. **A worker can lie and get paid.** Payouts rest on the worker's own `completion_tokens`, capped at the
   reservation (`backend/app/routers/jobs.py`: `charge = min(tokens, j.max_tokens)`). Signing the receipt proves
   *which* worker made a claim, not that the claim is true. Replaying the real job below with an empty output and a
   claim of 64 tokens: the receipt verifies and the worker is paid 64 (`demo/data/jobs.json`, job 2). Redundancy and
   known-answer probes (`docs/worker-verification.md`) only sample; colluding or sybil workers pass.
4. **Prior art was found too late.** [AI Horde](https://github.com/Haidra-Org/AI-Horde) (accessed 2026-11-10) is a
   "free, community-run service for AI image generation and text generation". Volunteers run workers on their own
   GPUs and earn kudos, which "cannot be bought or sold". It is AGPL-3.0, and KoboldCpp ships a built-in Horde
   worker. That is this project's model, already running. A search on day one would have found it.

## What held up (the part worth keeping)

- **Zero-sum ledger.** Every transaction's postings sum to zero in integer units (`backend/app/ledger.py` asserts
  it). Reserve moves credits from `available` to `held`; settle drains `held` to the worker and refunds the rest.
  Each write takes a fixed idempotency key (`job:{id}:settle`), so a retry is a no-op.
- **Races, on SQLite and Postgres 15** (`backend/tests/test_concurrency.py`, judge.md Updates 10, 12 and the
  2026-10-27 round): two workers racing one job, exactly one gets the lease; 6 identical results fired together,
  exactly one settles and 5 are no-ops; 6 sessions posting the same settle key, one gets through; a late result
  racing the lease reaper either settles or refunds, never both; a second spender blocks on the row lock and is
  refused. Mutation checks: removing the result compare-and-set, or making the key unique per call, fails the tests.
  The whole backend suite passed on Postgres 15 (38 tests) in both file orders.
- **The real Ollama run** (judge.md Update 13, 2026-10-21, Ollama 0.40.6, `qwen2.5:0.5b`): "What is the capital
  of France? Answer in one word.", `max_tokens` 64. Reserved 64, Ollama answered "Paris" with 41 prompt and 2
  completion tokens, settle charged 2 and refunded 62. Consumer 998, contributor 2, held 0. Both receipts verified
  (Ed25519). No prompt or output in the API or worker logs.
- **Docker smoke test** (2026-10-27): 56 ledger postings, sum 0.

## What to do differently

- Read the provider terms and search for prior art before writing a landing page. Each one alone
  changes the plan.
- Ask five possible consumers before building a supply side. Idle GPUs are plentiful; demand is the scarce side.
- If a payout depends on a number, decide how the server checks that number before building the ledger around it.
- Keep marketing copy behind the code: "Network is Live" and "240k+ community nodes" were on the page on day one
  with nothing running.

## Loose ends

- `web/` pins Next.js 16.4.0, which `next build` refuses as a known-vulnerable version (judge.md Update 15).
  Archiving the repo makes it moot; if it is kept, the upgrade is the one allowed change.
- `blankframe.tech/reserve-my-tokens/` is replaced by this post-mortem on the landing-page branch
  `agent/rm-postmortem` (not pushed).
