# xfce-zai-limits

An **XFCE panel indicator for z.ai usage limits** — the rolling 5-hour / weekly
caps that [OpenAI Codex CLI][codex] reports when pointed at [z.ai][zai].

The recommended mode is **`zai_indicator.py`** (AppIndicator3). You put
`xfce4-statusnotifier-plugin` on whichever panel you like (e.g. your left
monitoring dock, next to cpugraph/systemload), and the indicator lands there
with:

- a compact **graphical progress-bar icon** (no text cluttering the panel),
- a **hover tooltip with the full breakdown** — weekly %, 5-hour %, resets-in,
  credits balance, snapshot age,
- a **click menu** (Refresh / Send notification / Quit),
- color shifts green → orange → red as you approach the cap.

```
 panel:       hover tooltip:
 ┌─────┐      z.ai · 75% used (weekly)
 │ ▬▬▬ │      weekly 75% · resets in 5d 21h
 └─────┘
             credits: balance 0
             updated 1h ago
```

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

- Python 3.8+ with `pygobject` + `cairo` (pre-installed on any XFCE system).
- **`xfce4-statusnotifier-plugin`** on the panel where you want the indicator.
  Fedora: `sudo dnf install xfce4-statusnotifier-plugin`.
- OpenAI Codex CLI configured against z.ai (the thing producing the logs).

## Quick start

```bash
git clone https://github.com/<you>/xfce-zai-limits.git ~/src/xfce-zai-limits
python3 ~/src/xfce-zai-limits/zai_indicator.py &
```

If your panel doesn't already have a "StatusNotifier" item, add one: panel →
**Add new items…** → **StatusNotifier**. The icon appears there. Hover it → see
the limits.

### Autostart on login (systemd user unit)

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/zai-indicator.service <<'EOF'
[Unit]
Description=z.ai limits panel indicator
After=graphical-session.target
[Service]
ExecStart=/usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_indicator.py
Restart=on-failure
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now zai-indicator.service
```

(There's also `examples/zai-tray.autostart.desktop` for the classic XDG
autostart path — point `Exec=` at `zai_indicator.py`.)

### Configure

Environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ZAI_TRAY_REFRESH` | `30` | refresh interval, seconds |
| `ZAI_LIMITS_WARN` | `70` | `% used` at which the bar turns orange |
| `ZAI_LIMITS_CRIT` | `90` | `% used` at which the bar turns red |

## CLI (for scripting / other panels / Waybar)

```bash
python3 zai_limits.py --format text   # human-readable one-shot
python3 zai_limits.py --format json   # structured (for Waybar/polybar/i3blocks)
python3 zai_limits.py --notify        # fire a desktop notification
```

## Alternative modes

- **`zai_tray.py`** — legacy `Gtk.StatusIcon`. Goes into the old XEmbed
  systray plugin (so it lands wherever that plugin is, often the bottom bar).
  Useful if you can't add StatusNotifier where you want. Same tooltip+menu.
- **`zai_limits.py --format genmon`** — for `xfce4-genmon-plugin`. Caveat:
  genmon has **no `<tooltip>` tag**, so hover always shows the command string;
  it can only show a compact `z.ai NN%` label + graphical `<bar>` + a
  click-to-notify popup. See [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md).

## Limitations & roadmap

- **Codex / z.ai rolling limits (gpt-5.x via ChatGPT login): fully covered.**
- **GLM models via z.ai API key (e.g. `pi` using `glm-5.2`)**: `pi` does not
  log rate-limit info today, and z.ai exposes GLM usage through a different
  mechanism (API credits / dashboard). A `--source zai-api` collector that
  queries the z.ai usage endpoint directly is the planned next step — see
  [docs/zai-api.md](docs/zai-api.md). Contributions welcome.

## Files

```
zai_indicator.py           # PRIMARY — AppIndicator3 (statusnotifier panel plugin)
zai_tray.py                # ALTERNATIVE — Gtk.StatusIcon (legacy systray)
zai_limits.py              # data collection + text/json/genmon/notify formatters
bin/zai-limits-genmon.sh   # optional genmon wrapper (see docs/genmon-spawn-notes.md)
docs/                      # investigation notes & source research
```

## License

MIT — see [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
