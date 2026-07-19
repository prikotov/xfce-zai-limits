# xfce-zai-limits

An **XFCE panel widget for z.ai usage limits** — the rolling 5-hour / weekly
caps that [OpenAI Codex CLI][codex] reports when pointed at [z.ai][zai].

It runs as a native `xfce4-genmon-plugin` item (just like cpugraph/systemload —
no systray, no SNI, no compiled plugin):

- a **graphical progress bar** on the panel (no text label by default),
- a **hover tooltip with the full breakdown** — weekly %, 5-hour %, resets-in,
  credits balance, snapshot age,
- **click → desktop notification** with the same details,
- the bar is green → orange → red as you approach the cap (see CSS note below).

```
 panel:     hover tooltip:
 ┌───┐      z.ai · weekly 75% used
 │ ▮ │      weekly  75.0%  resets in 5d 18h (Jul 25)
 └───┘      5h       n/a
            credits  balance 0
            updated 1h ago
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

Codex already receives a `rate_limits` snapshot from z.ai on every model turn
and writes it into its rollout logs at
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`. This tool finds the freshest
snapshot and renders it — **no API call, no token spent, no key**. The number
refreshes when Codex makes a request (which is when the limit actually
changes); the tooltip always shows the snapshot age.

## Requirements

- `xfce4-genmon-plugin` (Fedora: `sudo dnf install xfce4-genmon-plugin`)
- Python 3.8+ (stdlib only)
- OpenAI Codex CLI configured against z.ai

## Setup

1. Add a **Generic Monitor** item to the panel where you want it
   (panel → Add new items… → Generic Monitor).
2. In its Properties, set **Command** to call `python3` **directly**
   (do **not** point it at `bin/zai-limits-genmon.sh` — a bash wrapper using
   `$(...)` hangs inside genmon's spawn environment; see
   [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md)):

   ```
   /usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```

3. **Period (s)**: `30`. Label: whatever you like (e.g. "LLM"). That's it.

## Coloring the bar green/orange/red

genmon's `<bar>` uses the GTK theme color by default (blue on Adwaita). To get
threshold colors, emit a `<css>` tag (also supported by genmon 4.3.0) styling
the progressbar — see [docs/genmon-tags.md](docs/genmon-tags.md). Optional.

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
