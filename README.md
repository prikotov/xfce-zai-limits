# xfce-zai-limits

An **XFCE panel widget** showing usage limits from **two** AI providers, as
native `xfce4-genmon-plugin` items (like cpugraph/systemload — no systray,
no SNI, no compiled plugin):

- **codex** (OpenAI/ChatGPT) — the rolling 5-hour / weekly caps the
  [OpenAI Codex CLI][codex] hits. Read from Codex rollout logs (zero quota).
- **z.ai / GLM** (pi) — the 5-hour rolling `TOKENS_LIMIT`, the weekly
  `TOKENS_LIMIT`, and the MCP-tools `TIME_LIMIT` from the [z.ai][zai] account
  API (the "plan usage" you see in the web cabinet).

Each is its own panel bar, colored green → orange → red by threshold, with a
hover tooltip scoped to that provider. Click → desktop notification.

```
 panel:            hover (codex):             hover (z.ai):
 ┌───┐ codex        codex (ChatGPT)            z.ai (GLM, pro)
 └───┘              weekly  75% resets in 5d    weekly  16% resets in 6d
 ┌───┐ z.ai         credits balance 0          5h      80% resets in 59m
 └───┘                                          MCP      2% resets in 23d
```

## How the hover tooltip works (the key insight)

`xfce4-genmon-plugin` parses output tags — and its **tooltip tag is `<tool>`,
not `<tooltip>`**. Many docs/snippets get this wrong. Verified against the
4.3.0 source (`panel-plugin/main.c`):

```c
begin = strstr(value, "<tool>");
end   = strstr(value, "</tool>");
acToolTips = g_strndup(begin + 6, end - begin - 6);
gtk_widget_set_tooltip_markup(eventbox, acToolTips);
```

This widget emits: `<bar>N</bar>` (graphical bar) + `<click>…</click>` (notify)
+ `<tool>…Pango markup with the numbers…</tool>`. No `<txt>`, so the panel
shows only the bar.

## How the data is obtained (zero quota cost)

The widget reads the account-wide Usage bucket through the local `codex
app-server` protocol — the same supported protocol used by Codex itself. This
keeps the value aligned with the Usage page even when the active model has a
separate limit, such as GPT-5.3-Codex-Spark. The response is cached for 25
seconds. If app-server is unavailable, the widget falls back to the freshest
`rate_limits` snapshot in
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.

## Requirements

- `xfce4-genmon-plugin` (Fedora: `sudo dnf install xfce4-genmon-plugin`)
- Python 3.8+ (stdlib only; `pygobject`/`cairo` not needed for genmon mode)
- OpenAI Codex CLI — for the **codex** metric (reads its rollout logs)
- z.ai API key — for the **z.ai / GLM** metric: pi's `~/.pi/agent/auth.json`
  (`zai.key`), or `$ZAI_API_KEY`. Without it, only the codex bar works.

## Setup — two bars (codex + z.ai)

genmon's `<bar>` renders only one bar, so add **two Generic Monitor** items to
the panel — one per metric:

1. **codex** item — Command:
   ```
   /usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```
   If Codex needs a proxy, set it explicitly in this widget's environment so
   it does not depend on any running Codex process:
   ```
   env ALL_PROXY=https://user:password@proxy.example:443 /usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```
2. **z.ai** item — Command (note the `ZAI_BAR_METRIC=zai` env):
   ```
   env ZAI_BAR_METRIC=zai /usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```

   Want the z.ai bar driven by the **weekly** window instead of the 5-hour one?
   Set `ZAI_BAR_METRIC=zai-weekly`. Either way the hover tooltip shows all
   three windows (weekly / 5h / MCP).

Period `30` for both. Each item's hover tooltip shows only its own provider's
breakdown; the `<bar>` is colored green/orange/red by threshold automatically
(via genmon's `<css>` tag).

> **Call `python3` directly** — do not point genmon at `bin/*.sh`; a bash
> wrapper using `$(...)` hangs in genmon's spawn environment
> ([docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md)).

### Panel labels (genmon gotcha)

genmon's on-panel label is the **`/text`** xfconf property (not `/label` or
`/title`), and genmon overwrites it from memory on panel-save. Set it while
the panel is down, else it gets clobbered:

```bash
xfce4-panel -q
xfconf-query -c xfce4-panel -p /plugins/plugin-<N>/text -s "codex"
xfconf-query -c xfce4-panel -p /plugins/plugin-<M>/text -s "z.ai"
# then start xfce4-panel again
```

Full tag/property reference: [docs/genmon-tags.md](docs/genmon-tags.md).

## Customize

Environment variables (set them in the genmon Command via `env … && …`, or
systemd/env.d):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ZAI_LIMITS_WARN` | `70` | `% used` → orange |
| `ZAI_LIMITS_CRIT` | `90` | `% used` → red |
| `ZAI_LIMITS_STALE_SEC` | `21600` | snapshot age considered stale (informational) |

## CLI

```bash
python3 zai_limits.py --format text   # human-readable one-shot
python3 zai_limits.py --format json   # structured (for waybar/polybar/i3blocks)
python3 zai_limits.py --notify        # fire a desktop notification
```

## Alternatives (kept in the repo)

- `zai_tray.py` — `Gtk.StatusIcon` (lands in the legacy systray, not a chosen
  panel). Useful if you can't or don't want to use genmon.
- `zai_indicator.py` — `AppIndicator3` (lands in `xfce4-statusnotifier-plugin`,
  but that drags the whole SNI tray onto that panel — usually not wanted).

genmon is the recommended path on XFCE.

## Limitations & roadmap

- **Codex / z.ai rolling limits (gpt-5.x via ChatGPT login): fully covered.**
- **GLM models via z.ai API key (e.g. `pi` on `glm-5.2`)**: `pi` does not log
  rate-limit info today, and z.ai exposes GLM usage through a different
  mechanism (API credits / dashboard). A `--source zai-api` collector is the
  planned next step — see [docs/zai-api.md](docs/zai-api.md).

## License

MIT — see [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
