# Open questions

Status: concept only. Nothing below is resolved.

## Demand side
- Who pays for or consumes donated capacity is not validated. No consumer interviews or committed users exist. Credits are test-only and have no cash value.

## Verifying contribution value
- Redundancy mitigation (running the same job on more than one worker and comparing) is intended to catch wrong or fabricated outputs.
- It does not cover: workers colluding, consistently wrong but identical outputs, token or compute counts that local models report inconsistently, nondeterministic outputs that legitimately differ, or the extra cost of duplicate runs.
- Usage receipts are signed by the worker, so they prove nothing about what actually ran.

## License compliance if Llama or Gemma are ever added
- Llama 3.1: pass through the agreement, "Built with Llama" attribution, the Acceptable Use Policy; 700M MAU cap. Later versions unchecked.
- Gemma: hosted API access counts as Distribution; use restrictions must be flowed down to every end user; Google may restrict usage remotely. Prohibited Use Policy not read.
- Per-model checks are still needed for Qwen and Mistral weights (some are not Apache 2.0).
- Source: docs/provider-terms.md.

## Counsel review items
- Credits: classification as a stored-value or money-like instrument, consumer protection, and tax, before any cash value or redemption.
- Payment review before any payments or payouts.
- Platform liability as distributor of model license terms.
- Prompt data handling and donor-visible plaintext privacy obligations.
- OpenAI Terms of Use and Services Terms, Google consumer plan terms (not read).
- Brand, domain and trademark availability.
