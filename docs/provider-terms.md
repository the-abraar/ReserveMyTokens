# Provider terms: can capacity be pooled, shared or donated?

Accessed: 2026-10-12. Quotes are short and come from the fetched page text (WebFetch returns model-summarised text, so re-verify wording against the live page). Anything not confirmed from a primary source is marked UNCONFIRMED.

**Not legal advice. Counsel must confirm every conclusion here before launch.** Terms change; re-check before relying on them.

## (a) Consumer subscriptions (Claude Pro/Max, ChatGPT Plus, Gemini consumer)

| Provider | Finding | Source |
|---|---|---|
| Anthropic | Sharing and making the account available are both barred. "You may not share your Account login information, Anthropic API key, or Account credentials with anyone else." and "You also may not make your Account available to anyone else." | https://www.anthropic.com/legal/consumer-terms (2026-10-12) |
| Anthropic | Automated access is barred, except via an API key: "to access the Services through automated or non-human means, whether through a bot, script, or otherwise." | same |
| Anthropic | Resale and proxying are barred, including through consumer subscriptions. "Resell, proxy, or otherwise provide access to Claude through unauthorized means." (fetch summary says routing via consumer subscriptions is covered; exact wording on that point UNCONFIRMED) | https://www.anthropic.com/legal/aup (2026-10-12) |
| OpenAI | Terms of Use pages returned 403 to our fetcher. A search snippet says OpenAI's business terms prohibit giving login credentials to third parties and reselling or leasing account access. No clause quoted from the consumer Terms of Use. **UNCONFIRMED from primary text.** | https://openai.com/policies/business-terms (403, not read); https://openai.com/policies/terms-of-use/ (403) |
| Google | Gemini API terms are developer terms and do not address consumer Google AI plans. Consumer-plan sharing rules **UNCONFIRMED** (not fetched). | https://ai.google.dev/gemini-api/terms |

Conclusion: subscription sharing, pooling or donation is clearly prohibited by Anthropic and very likely by OpenAI (UNCONFIRMED). Treat as disallowed.

## (b) API keys, shared or pooled across users

| Provider | Finding | Source |
|---|---|---|
| Anthropic (consumer terms) | Key sharing barred: "...Anthropic API key, or Account credentials with anyone else." | https://www.anthropic.com/legal/consumer-terms |
| Anthropic (commercial terms) | "resell the Services except as expressly approved by Anthropic" (D.4(a)); "Customer is responsible for all activity under its account" (D.5). Customers may build products: "to power products and services Customer makes available to its own customers and end users" (A.1). No explicit key-sharing clause found in the fetched text. | https://www.anthropic.com/legal/commercial-terms |
| Mistral | "buy, sell, or transfer API keys or any type of Mistral AI account from, to, or with a third party" (s2.2(h)); no third-party access "without our prior written authorization" (s2.2(i)). | https://legal.mistral.ai/terms/commercial-terms-of-service |
| OpenAI | Search snippet of help center says sharing keys violates the Terms and is unsupported. Page returned 403. **UNCONFIRMED from primary text.** | https://help.openai.com/en/articles/5112595 (403) |
| Google Gemini API | No key-sharing or general resale clause in fetched text. Users of apps you build must be served under rules: "You may use only Paid Services when making API Clients available to users" (EEA/CH/UK). Also bars building competing models. | https://ai.google.dev/gemini-api/terms |

Conclusion: handing one owner's key to other people (pooling or donating a key) is barred or restricted by Anthropic, Mistral and (likely) OpenAI. A different pattern, an owner calling the API themselves and serving end users inside their own product, is permitted for Anthropic and Google, but that is a normal reseller-of-an-app model, not key donation. Whether a marketplace of third-party consumers counts is UNCONFIRMED; needs written approval from each provider.

## (c) Locally run open-weight models served to third parties

| Item | Finding | Source |
|---|---|---|
| Ollama (runtime) | MIT: "Permission is hereby granted, free of charge, to any person obtaining a copy". Runtime itself is no obstacle. Model weights carry their own licenses. | https://raw.githubusercontent.com/ollama/ollama/main/LICENSE |
| Apache 2.0 (Qwen repo code license; also used by many Mistral open models, UNCONFIRMED per model) | Broad grant: "perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license". Conditions on redistribution: "You must give any other recipients of the Work or Derivative Works a copy of this License." and modified files carry notices. No MAU cap, no field-of-use limit. Note: the Qwen repo LICENSE is Apache 2.0, but individual Qwen model licenses vary (some are the Tongyi Qianwen license with a MAU cap); per-model check UNCONFIRMED. | https://www.apache.org/licenses/LICENSE-2.0 ; https://raw.githubusercontent.com/QwenLM/Qwen/main/LICENSE |
| Llama 3.1 | MAU cap: licensee must seek a license if "greater than 700 million monthly active users in the preceding calendar month". Redistribution: "If you distribute or make available the Llama Materials" include the agreement; display "Built with Llama". Use must "adhere to the Acceptable Use Policy for the Llama Materials". Agreement has no explicit hosting clause (serving an API is arguably "make available"; UNCONFIRMED). Later Llama versions may differ; not checked. | https://raw.githubusercontent.com/meta-llama/llama-models/main/models/llama3_1/LICENSE (the official llama.com URL redirected and failed) |
| Gemma | Hosted API access counts as Distribution: "including by providing or making Gemma or its functionality available as a hosted service via API". Must give recipients the agreement and "include the use restrictions referenced in Section 3.2 as an enforceable provision in any agreement". Google may "restrict (remotely or otherwise) usage". Prohibited Use Policy text not read (UNCONFIRMED). | https://ai.google.dev/gemma/terms |
| Mistral open weights | Not checked per model. Weights licenses UNCONFIRMED (some Apache 2.0, some research-only). Mistral's commercial terms above cover the hosted API, not weights. | n/a |

Conclusion: serving permissively licensed (Apache 2.0, MIT) weights to third parties is clear with notice/license pass-through. Llama and Gemma are allowed with conditions (attribution or downstream pass-through of use restrictions, AUP, 700M MAU cap for Llama), which a donor-to-consumer relay makes operationally heavier because the platform becomes the distributor of terms.

## (d) What this means for the product

- **Clearly allowed:** donors running Apache 2.0 / MIT weights locally (e.g. Qwen Apache-licensed checkpoints, Mistral Apache-licensed checkpoints, after a per-model license check) and serving them through the platform. Condition: license text passed to users.
- **Allowed with conditions:** Llama (attribution, AUP, MAU cap) and Gemma (hosted use is Distribution, must flow down use restrictions to every end user).
- **Clearly disallowed:** sharing, pooling, or donating consumer-subscription access (Anthropic consumer terms and AUP quoted above; OpenAI likely, UNCONFIRMED).
- **Disallowed or needs written approval:** donating or pooling raw API keys (Anthropic consumer terms, Mistral s2.2(h), OpenAI likely). Resale without approval barred by Anthropic commercial terms D.4(a).
- **Unclear:** a donor using their own API key to serve third parties through the platform as a metered service (provider-by-provider written approval needed); whether platform-operated API accounts under commercial agreements could be sold as pooled capacity; per-model licenses for Qwen and Mistral weights; Llama versions after 3.1.

## Proposed MVP supply model

Limit supply to **donor-run local open-weight models under Apache 2.0 or MIT only** (allowlist by model license; reject any weight whose license is not on the list). Include a license-notice pass-through to consumers. Defer Llama and Gemma until counsel signs off on the flow-down and attribution duties. Exclude subscription access and API keys entirely, at both the protocol level (no credential fields) and in marketing copy. Seek written approval from any provider before ever adding an API-key or reseller supply type.

Open items for counsel: OpenAI Terms of Use and Services Terms (blocked to our fetcher), Google consumer plan terms, Mistral and Qwen per-model weight licenses, Llama AUP and current Llama version, Gemma Prohibited Use Policy text.
