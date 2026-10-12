# Coding standards (judgement calls)

Linters and `scripts/check.sh` cover the mechanical rules; these need a reviewer.

- **Balance**: every ledger transaction's postings sum to zero in integer minor units, never floats. A one-sided posting silently mints credits.
- **Idempotent**: ledger writes and job results take a caller-supplied idempotency key, never one generated per request. Retries must not double-post.
- **Compare-and-set**: every state-changing write is `UPDATE ... WHERE id=? AND status=?`; check rowcount, return 409 on conflict. Leases and settlement are raced by design.
- **Separate**: the verifier of a result and the worker that produced it have different owners. Compare owners, not row ids, since one user can run many workers.
- **Explicit auth**: every endpoint states its auth decision; unauthenticated is a commented, deliberate choice.
- **Fail closed**: tokens and secrets reject default or placeholder values outside dev.
- **Cap**: query `limit`, payload size, receipts per job and workers per user have an explicit upper bound.
- **No cash value**: credits are not redeemable, transferable for money, or priced, until legal review lands. Do not add payout, price or "worth" wording or fields.
- **Allowed supply only**: capacity comes from donor-run local open-weight models. Anything else (subscriptions, shared or pooled API keys, resale) needs a matching allowance in `docs/provider-terms.md` first.
- **Derive**: test mocks and fixtures take names and shapes from the real models and schemas; a test fails if they drift.
- **UNVERIFIED**: user-facing claims, metrics and demo numbers that are not measured carry an UNVERIFIED or "illustrative" marker.
- **No prompt logging**: never log prompts, outputs or worker tokens.
