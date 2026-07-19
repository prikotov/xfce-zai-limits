# xfce-zai-limits

An **XFCE panel widget** that shows your **z.ai usage limits** (the rolling
5-hour / weekly caps that [OpenAI Codex CLI][codex] reports when pointed at
[z.ai][zai]) as a progress bar with a detailed hover tooltip.

```
 ┌───────────────────────────┐
 │ z.ai  75%  ▮▮▮▮▯          │   ← progress bar + compact label on the panel
 └───────────────────────────┘
            ↓ hover
 ┌─────────────────────────────────────────────┐
 │ z.ai limits                                 │
 │                                             │
 │ weekly:  75%   resets in 5d 22h  (Jul 25)   │
 │ 5h:      42%   resets in 3h 9m   (Jul 19)   │
 │                                             │
 │ credits: balance 12.50                      │
 │                                             │
 │ updated 3m ago                              │
 │ read from Codex logs — refreshes as you use │
 └─────────────────────────────────────────────┘
```

## Why

When you run Codex (or `pi`) against z.ai, you periodically hit the rolling
rate limits with no easy way to glance at *how much you have left* without
opening a terminal and starting a session. This widget puts that number on the
panel — green / orange / red, with a full breakdown on hover.

## How it works (and why it costs you **zero quota**)

Codex already receives a `rate_limits` snapshot from z.ai on every model turn
and **writes it into its rollout logs** at
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
window. This widget simply finds the freshest such snapshot and renders it.
No API call, no token spent, no key required.

The trade-off: the number only refreshes when Codex actually makes a request —
which is exactly when the limit changes anyway. The tooltip always shows the
snapshot age so you know how live it is.

## Requirements

- `xfce4-genmon-plugin` ≥ 4.18 (4.20 recommended). It ships the `<bar>` /
  `<tooltip>` support this widget uses.
- Python 3.8+ (standard library only).
- OpenAI Codex CLI configured against z.ai (the thing producing the logs).

Install the plugin if you don't have it:

| Distro | Command |
| --- | --- |
| Fedora | `sudo dnf install xfce4-genmon-plugin` |
| Debian / Ubuntu | `sudo apt install xfce4-genmon-plugin` |
| Arch | `sudo pacman -S xfce4-goodies` |

## Install

```bash
git clone https://github.com/<you>/xfce-zai-limits.git ~/src/xfce-zai-limits
cd ~/src/xfce-zai-limits
./bin/zai-limits-genmon.sh        # sanity check: prints genmon XML
```

## Add to the panel

1. Right-click the XFCE panel → **Add new items…** → **Generic Monitor** → **Add**.
2. Right-click the new item → **Properties**.
3. **Command** — call **`python3` directly** (do **not** point this at the
   `bin/*.sh` wrapper):
   ```
   /usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
   ```
   Why not the shell wrapper: `xfce4-genmon-plugin` spawns its command in a
   restricted environment where a bash script that uses `$(...)` command
   substitution hangs forever (verified with `strace`). A direct `exec` to an
   absolute `python3` with an absolute script path has no such problem. See
   [docs/genmon-spawn-notes.md](docs/genmon-spawn-notes.md).
4. **Period (s)**: `30` (limits don't change faster; log reads are cheap).
5. **Label**: leave empty (the label is already in the output).
6. Tick **Use a progress bar** if you also want the genmon bar on top of the
   in-text one (both are fine).
7. Close. You should see `z.ai  NN% ▮▮▮▯` within one period (~30s).

## Customize

Environment variables (set them in `bin/zai-limits-genmon.sh` or your session):

| Variable | Default | Meaning |
| --- | --- | --- |
| `ZAI_LIMITS_WARN` | `70` | `% used` at which the bar turns orange |
| `ZAI_LIMITS_CRIT` | `90` | `% used` at which the bar turns red |
| `ZAI_LIMITS_STALE_SEC` | `21600` | snapshot age considered "stale" (informational) |
| `ZAI_LIMITS_COLOR_OK` | `#26a269` | green |
| `ZAI_LIMITS_COLOR_WARN` | `#e09b24` | orange |
| `ZAI_LIMITS_COLOR_CRIT` | `#e01b24` | red |
| `ZAI_LIMITS_COLOR_LABEL` | `#c0bfbc` | label / window names |
| `ZAI_LIMITS_COLOR_DIM` | `#888888` | secondary info |

## CLI (for scripting / other panels / Waybar)

```bash
python3 zai_limits.py --format text   # human-readable
python3 zai_limits.py --format json   # structured (for Waybar/polybar/i3blocks)
python3 zai_limits.py --format genmon # default: for xfce4-genmon-plugin
```

Example JSON:

```json
{
  "ok": true,
  "source": "codex:rollout-2026-07-19T...jsonl",
  "age_sec": 36,
  "primary":   { "used_percent": 75.0, "label": "weekly", "resets_in_sec": 514812 },
  "secondary": null,
  "credits":   { "balance": 0.0, "unlimited": false }
}
```

## Limitations & roadmap

- **Codex / z.ai rolling limits (gpt-5.x via ChatGPT login): fully covered.**
  These are the limits you most often run out of.
- **GLM models via z.ai API key (e.g. `pi` using `glm-5.2`)**: `pi` does not
  log rate-limit info today, and z.ai exposes GLM usage through a different
  mechanism (API credits / dashboard). A `--source zai-api` collector that
  queries the z.ai usage endpoint directly is the planned next step — see
  [docs/zai-api.md](docs/zai-api.md) for the investigation notes. Contributions
  welcome.
- The dominant bar shows the window *closest to its cap* (typically weekly),
  because that's the one that bites first.

## Files

```
zai_limits.py              # the whole thing (stdlib only)
bin/zai-limits-genmon.sh   # optional shell wrapper — see WARNING above
                             (prefer pointing genmon straight at python3)
docs/                      # investigation notes & source research
```

## License

MIT — see [LICENSE](LICENSE).

[codex]: https://github.com/openai/codex
[zai]: https://z.ai
