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
      { "type": "TIME_LIMIT",  "percentage": 0,  "nextResetTime": 1785148414994,
        "usageDetails": [{"modelCode":"search-prime",...},{"modelCode":"web-reader",...},{"modelCode":"zread",...}] },
      { "type": "TOKENS_LIMIT","percentage": 22, "nextResetTime": 1784480862439 }
    ],
    "level": "pro"
  },
  "success": true
}
```

## What each limit is (per official z.ai docs, NOT interpretation)

Source: **`docs.z.ai/devpack/faq`** + **`docs.z.ai/devpack/usage-policy`**.

### `TOKENS_LIMIT` → the 5-hour prompt/token cycle ("plan usage")

Official FAQ:
> «Lite Plan: Up to ~80 prompts every 5 hours. Pro Plan: Up to ~400 prompts
> every 5 hours. Max Plan: Up to ~1600 prompts every 5 hours… wait until the
> **5-hour cycle** for it to refresh.»

This is the percentage shown as "plan usage" in the z.ai web cabinet. Labeled
**`5h`** in the widget.

### `TIME_LIMIT` → the weekly quota for MCP-tools only

`TIME_LIMIT` carries `usageDetails` = `search-prime`, `web-reader`, `zread` —
i.e. the MCP tools (Vision / Web Search / Web Reader). FAQ:
> «The MCP quotas for the … Pro Plan: Include a total of 1,000 web searches and
> web readers per month, along with the 5-hour maximum prompt resource pool of
> the package for vision understanding.»

It resets on a 7-day cycle. Labeled **`MCP`** in the widget. This is **not** the
main subscription quota — it's the MCP-tools weekly quota.

### Weekly subscription quota

FAQ mentions a weekly quota «refreshed/reset on a 7-day cycle» from order time,
but `/quota/limit` does **not** return it as a separate entry. To see 7-day /
30-day *usage* (not a limit), z.ai exposes `/api/monitor/usage/model-usage
?startTime=…&endTime=…` (used by `melon-hub/zai-usage-tracker`).

## `nextResetTime`

Both limits return `nextResetTime` (unix ms). The widget uses it **directly**
(no computation) as the reset instant: `resets_at = nextResetTime // 1000`,
and "resets in Xh" = `resets_at - now`. So the reset time is exact, from z.ai.

## How the endpoint was found

GitHub search → [`shaftoe/pi-zai-usage`](https://github.com/shaftoe/pi-zai-usage)
(`src/api.ts` uses exactly this URL). My earlier guesses
(`/users/user/plan-usage`, `/dashboard/feature-quota/summary`) were frontend
SPA routes and returned `code:500/msg:404`.

## Note: codex ≠ z.ai

`codex` (OpenAI Codex CLI with `auth_mode=chatgpt`) talks to **OpenAI/ChatGPT**
(strace: TCP to AWS/CloudFront 8.x, not z.ai). Its `rate_limits` (75% weekly)
is the **ChatGPT-plan** rolling limit. The z.ai number above is the **GLM/pi**
subscription — a different account. The widget shows both.
