# z.ai (GLM) account usage — RESOLVED

Status: **implemented** in `collect_zai()` (`zai_limits.py`).

## Endpoint

```
GET https://api.z.ai/api/monitor/usage/quota/limit
Authorization: Bearer <zai api key>
```

The key is the one pi stores at `~/.pi/agent/auth.json` → `zai.key` (or
`$ZAI_API_KEY`). It authorizes both chat (`/api/coding/paas/v4`) **and** this
account-usage endpoint.

## Response

```json
{
  "code": 200,
  "msg": "Operation successful",
  "data": {
    "limits": [
      { "type": "TIME_LIMIT",  "percentage": 0,  "nextResetTime": 1785148414994 },
      { "type": "TOKENS_LIMIT","percentage": 22, "nextResetTime": 1784480862439 }
    ],
    "level": "pro"
  },
  "success": true
}
```

- `TOKENS_LIMIT.percentage` = the weekly plan-usage % shown in the z.ai web
  cabinet.
- `TIME_LIMIT.percentage` = the 5-hour rolling window %.
- `level` = plan tier (pro, etc.).

## How the endpoint was found

By searching GitHub for existing z.ai-usage tools. The
[`shaftoe/pi-zai-usage`](https://github.com/shaftoe/pi-zai-usage) pi-extension
uses exactly this URL (`src/api.ts`). Related projects:
`melon-hub/zai-usage-tracker` (VS Code), `guyinwonder168/opencode-glm-quota`,
`slkiser/opencode-quota`.

My earlier guesses (`/users/user/plan-usage`, `/dashboard/feature-quota/summary`)
were frontend SPA routes, not API endpoints — z.ai returned `code:500/msg:404`
on them. The real one is `/api/monitor/usage/quota/limit`.

## Note: codex ≠ z.ai

`codex` (OpenAI Codex CLI with `auth_mode=chatgpt`) talks to **OpenAI/ChatGPT**
(strace: TCP to AWS/CloudFront 8.x, not z.ai). Its `rate_limits` (75% weekly)
is the **ChatGPT-plan** rolling limit. The z.ai number above (12–28%) is the
**GLM/pi** subscription — a different account. The widget shows both.
