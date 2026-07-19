# z.ai GLM (API-key) usage — investigation notes

Status: **hypothesis, not verified**. This file collects what was observed so
the planned `--source zai-api` collector can be implemented without re-doing
the research.

## Background

There are two distinct ways to consume z.ai, and they have **different**
limit models:

| Path | Auth | Models | Limit shape | Reported by |
| --- | --- | --- | --- | --- |
| ChatGPT-plan style | ChatGPT OAuth (`auth_mode=chatgpt`) | `gpt-5.x` (e.g. `gpt-5.6-sol`) | rolling 5-hour + weekly windows | Codex, in every `token_count` event |
| z.ai API | API key (provider `zai`) | `glm-*` (e.g. `glm-5.2`) | API credits / balance | **nobody locally** today |

This widget currently covers the first row by reading Codex's rollout logs.

The second row is what `pi` uses when configured with `defaultProvider=zai`,
`defaultModel=glm-5.2` — and it is **not** logged anywhere on disk that this
project could find.

## Observations (verified on the machine this was built on)

- `pi` stores its provider config in `~/.pi/agent/`:
  - `settings.json` → `defaultProvider: "zai"`, `defaultModel: "glm-5.2"`
  - `auth.json` → `zai: { type: "api_key", key: <masked> }`
  - `models-store.json` → z.ai base URL: **`https://api.z.ai/api/coding/paas/v4`**
- `pi`'s session logs (`~/.pi/agent/sessions/**/*.jsonl`) do **not** contain a
  structural rate-limit field (no `used_percent`, `rate_limits`, `remaining`).
  The only matches for those strings were inside bash tool output, not events.
- `pi`'s bundled JS (`dist/`) contains no rate-limit parsing logic at all — it
  does not surface z.ai quota info in its footer today.

## Conclusions

- Reading GLM limits from `pi`'s own logs is **not** possible without patching
  `pi`.
- The only realistic source is **querying z.ai directly**.

## Hypotheses to verify (next steps before coding `--source zai-api`)

1. **z.ai exposes usage on the API response headers.** OpenAI-compatible
   gateways often return `x-ratelimit-*` or a vendor header. A single cheap
   request (`/v4/models` or a 1-token `/chat/completions`) captured with
   `curl -D -` would reveal the exact header names. **Do this first** — it's
   the least invasive and costs ~1 token.
2. **z.ai has a dedicated usage/quota endpoint** on `https://api.z.ai/`
   (e.g. `/api/paas/v4/usage` or a dashboard API). Check z.ai docs /
   `https://docs.z.ai` for an "API usage" / "balance" endpoint. This would be
   ideal: zero model tokens, authoritative balance.
3. **The dashboard at `https://z.ai`** shows credits/usage via an internal
   API that could be reverse-engineered from the browser devtools network
   tab. Last resort (fragile, may need cookies).

## If you implement it

- Keep it behind `--source zai-api` (default stays `codex` — zero-cost).
- Read the key from `~/.pi/agent/auth.json` (`zai.key`) and/or
  `ZAI_API_KEY` env var. Never print the key.
- Make one network call per genmon tick (30s) max, and cache the result to a
  file so the widget survives being polled more often.
- Treat a missing/empty header gracefully — fall back to the codex source.

## Security note

Do **not** store the API key in any file that gets committed. The collector
should read it from the existing `auth.json` at runtime only.
