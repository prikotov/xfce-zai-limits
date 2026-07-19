# xfce-zai-limits

An **XFCE panel indicator for z.ai usage limits** — the rolling 5-hour / weekly
caps that [OpenAI Codex CLI][codex] reports when pointed at [z.ai][zai].

**Recommended: the system-tray indicator** (`zai_tray.py`). It gives you:

- a compact **graphical progress-bar icon** in the panel's system tray (no text
  cluttering the panel),
- a **hover tooltip with the full breakdown** — weekly %, 5-hour %, resets-in,
  credits balance, snapshot age,
- **left-click → desktop notification** with the same details,
- **right-click → menu** (Refresh / Quit),
- color shifts green → orange → red as you approach the cap.

```
 tray icon:       hover tooltip:
 ┌─────┐          z.ai · weekly 75% used
 │ ▬▬▬ │          ────────────────────────────
 └─────┘          weekly   75.0%  resets in 5d 21h (Jul 25)
                 5h        n/a
                 credits   balance 0
                 updated 1h ago · click for details
```

There is also a `xfce4-genmon-plugin` mode (`zai_limits.py --format genmon`),
but **genmon can't show numbers in the hover tooltip** (its tooltip is always
the command string — see [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md)).
Use the tray indicator if you want numbers on hover; genmon is kept as a
fallback for panels without a system tray.

## How it works (zero quota cost)

Codex already receives a `rate_limits` snapshot from z.ai on every model turn
and writes it into its rollout logs at
`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`:

```json
{
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "rate_limits": {
      "primary":   { "used_percent": 75.0, "window_minutes": 10080, "resets_at": 1784962527 },
      "secondary": { "used_percent": 42.0, "window_minutes": 300,   "resets_at": 1784453927 },
      "credits":   { "has_credits": true, "unlimited": false, "balance": "12.5" }
    }
  }
}
```

`window_minutes == 10080` is the **weekly** window; `300` is the **5-hour**
window. This tool finds the freshest snapshot and renders it. **No API call,
no token spent, no key required.** The trade-off: the number only refreshes
when Codex actually makes a request — which is exactly when the limit changes
anyway. The tooltip always shows the snapshot age so you know how live it is.

## Requirements

- Python 3.8+ (standard library only for data; the tray icon also needs
  `pygobject` + `cairo` — both pre-installed on any XFCE system).
- An XFCE panel with the **Status Tray** plugin (the default `xfce4-panel`
  ships one; it renders both legacy `Gtk.StatusIcon`s and appindicators).
- OpenAI Codex CLI configured against z.ai (the thing producing the logs).

On Fedora: `sudo dnf install python3-gobject python3-cairo`.

## Quick start — tray indicator

```bash
git clone https://github.com/<you>/xfce-zai-limits.git ~/src/xfce-zai-limits
# run it now
python3 ~/src/xfce-zai-limits/zai_tray.py &
```

An icon should appear in your panel's system tray. Hover it → see the limits.

### Autostart on login

```bash
cp ~/src/xfce-zai-limits/examples/zai-tray.autostart.desktop \
   ~/.config/autostart/zai-tray.desktop
# edit the Exec= path inside if you cloned elsewhere
```

### Configure

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ZAI_TRAY_REFRESH` | `30` | refresh interval, seconds |
| `ZAI_TRAY_ICON_SIZE` | `24` | base icon size (auto-adjusts to the tray) |
| `ZAI_LIMITS_WARN` | `70` | `% used` at which the bar turns orange |
| `ZAI_LIMITS_CRIT` | `90` | `% used` at which the bar turns red |

## CLI (for scripting / other panels / Waybar)

```bash
python3 zai_limits.py --format text   # human-readable one-shot
python3 zai_limits.py --format json   # structured (for Waybar/polybar/i3blocks)
python3 zai_limits.py --format genmon # for xfce4-genmon-plugin (no tooltip numbers)
python3 zai_limits.py --notify        # fire a desktop notification
```

## Alternative: xfce4-genmon-plugin

If you'd rather have a panel item than a tray icon, `zai_limits.py --format
genmon` emits genmon markup. **Caveat: genmon's tooltip is always the command
string** (it has no `<tooltip>` tag), so you can't see the numbers on hover —
only the compact `z.ai NN%` label, the graphical `<bar>`, and a click-to-notify
popup. See [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md) for the
gotchas (in particular: point genmon straight at `python3`, **not** at the
shell wrapper — `$(...)` hangs in genmon's spawn environment).

## Limitations & roadmap

- **Codex / z.ai rolling limits (gpt-5.x via ChatGPT login): fully covered.**
  These are the limits you most often run out of.
- **GLM models via z.ai API key (e.g. `pi` using `glm-5.2`)**: `pi` does not
  log rate-limit info today, and z.ai exposes GLM usage through a different
  mechanism (API credits / dashboard). A `--source zai-api` collector that
  queries the z.ai usage endpoint directly is the planned next step — see
  [docs/zai-api.md](docs/zai-api.md). Contributions welcome.

## Files

```
zai_tray.py                # the tray indicator (recommended) — StatusIcon + cairo icon
zai_limits.py              # data collection + genmon/text/json/notify formatters
bin/zai-limits-genmon.sh   # optional genmon wrapper (see WARNING in genmon-spawn-notes.md)
examples/zai-tray.autostart.desktop   # copy to ~/.config/autostart/
docs/                      # investigation notes & source research
```

## License

MIT — see [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
