# xfce4-genmon-plugin 4.3.0 — output tags (verified from source)

Pulled from `panel-plugin/main.c` of the `xfce4-genmon-plugin-4.3.0` tag
(what Fedora 43 ships). This is the authoritative list — the README at
`/usr/share/doc/` doesn't document them.

| Tag | Closes | Offset | Purpose |
| --- | --- | --- | --- |
| `<img>` | `</img>` | `+5` | image from a **file path** |
| `<click>` | `</click>` | `+7` | shell command run on click (makes the image a button) |
| `<icon>` | `</icon>` | `+6` | themed **icon name** |
| `<iconclick>` | `</iconclick>` | `+11` | shell command run on icon click |
| `<txt>` | `</txt>` | `+5` | text label (Pango markup) shown on the panel |
| `<txtclick>` | `</txtclick>` | `+10` | shell command run on text click |
| `<bar>` | `</bar>` | `+5` | integer 0–100 → graphical progress bar |
| `<tool>` | `</tool>` | `+6` | **hover tooltip** (Pango markup) |
| `<css>` | `</css>` | `+5` | CSS applied to the plugin (style the bar!) |

## xfconf properties (config — NOT output tags)

These live under `/plugins/plugin-<N>/...` on the `xfce4-panel` channel:

| Property | C | Purpose |
| --- | --- | --- |
| `/command` | string | the script genmon spawns |
| `/text` | string | **the on-panel LABEL** (genmon calls it "Title"/`acTitle` internally — `CONF_LABEL_TEXT`) — confusingly NOT `/label` or `/title` |
| `/use-label` | bool | show the `/text` label at all |
| `/update-period` | int (ms) | spawn interval (default 30000) — genmon uses this, not `/period` |
| `/font` | string | label font |
| `/enable-single-row` | bool | layout |

To set the panel label, write `/text` (and ensure `/use-label=true`). genmon
reads `/text` only at **init** (and on its GUI Apply) — it has **no xfconf
property-changed handler**. Worse: genmon is hooked to the panel's `"save"`
signal (`g_signal_connect(plugin, "save", genmon_write_config)`), so on
quit/restart it writes its in-memory `acTitle` back to `/text`, clobbering an
`xfconf-query` set you did while it was running.

**Recipe that actually sticks:** `xfce4-panel -q` → `xfconf-query … /text -s …`
→ start the panel. With the panel down there's no genmon to overwrite it, and
the fresh genmon init reads your value.

## The two gotchas everyone hits

1. **The tooltip tag is `<tool>`, not `<tooltip>`.** No `<tooltip>` tag exists.
   If you find snippets online using `<tooltip>`, they're wrong for 4.3.0.
2. **`<txt>` is optional.** Omit it to show only `<bar>` / `<img>` / `<icon>` on
   the panel (no text label). This is what zai-limits does.

## Coloring the `<bar>` (green / orange / red)

`<bar>` uses the GTK theme's `@theme_selected_bg_color` by default (blue on
Adwaita). Override per-call with `<css>`:

```
<bar>75</bar>
<css>progressbar progress { background-color: #e09b24; }</css>
<tool>…</tool>
```

The CSS is applied to the plugin's widget tree, so you can target
`progressbar progress` (the fill), `progressbar trough` (the track), etc.

zai-limits computes the color in Python from `WARN`/`CRIT` thresholds when you
set `ZAI_BAR_COLOR=threshold` (planned; today the bar is theme-colored).

## Click command

`<click>` runs synchronously on button press via `xfce_spawn_command_line`. To
avoid blocking the panel, point it at something that forks fast — e.g. our
`zai_limits.py --notify` (fires `notify-send` and returns).

## Source reference

```
https://gitlab.xfce.org/panel-plugins/xfce4-genmon-plugin/-/raw/xfce4-genmon-plugin-4.3.0/panel-plugin/main.c
```

DisplayCmdOutput() is the function that parses these tags (lines ~170–360).
