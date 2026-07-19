#!/usr/bin/env python3
"""
zai_tray — XFCE system-tray indicator for z.ai usage limits.

Unlike xfce4-genmon-plugin (which has no <tooltip> tag, so hover always shows
the command), Gtk.StatusIcon gives a *real* tooltip. This indicator shows:

  • a graphical progress-bar icon in the panel's system tray (no text on panel)
  • the full breakdown (weekly / 5h / credits / age) as a hover tooltip
  • left-click  → desktop notification with the same details
  • right-click → menu (Refresh / Quit)

It reads the same Codex rollout-log data as zai_limits.py — zero quota cost.

Run:
    python3 zai_tray.py

For autostart, drop a .desktop in ~/.config/autostart/ (see README).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

# Make the sibling zai_limits.py importable when run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zai_limits import (  # noqa: E402
    COLOR_CRIT,
    COLOR_DIM,
    COLOR_LABEL,
    COLOR_OK,
    COLOR_WARN,
    CRIT_PCT,
    WARN_PCT,
    Window,
    collect_codex,
    show_notify,
    _fmt_balance,
    _fmt_ts,
    _human_remaining,
)

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

REFRESH_SEC = int(os.environ.get("ZAI_TRAY_REFRESH", "30"))
ICON_SIZE = int(os.environ.get("ZAI_TRAY_ICON_SIZE", "24"))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _hex_to_rgb(hexcolor: str) -> tuple[float, float, float]:
    h = hexcolor.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore


def _color_for(pct: float) -> str:
    if pct >= CRIT_PCT:
        return COLOR_CRIT
    if pct >= WARN_PCT:
        return COLOR_WARN
    return COLOR_OK


def _window_windows(snap):
    weekly = None
    five_h = None
    if snap:
        for w in (snap.primary, snap.secondary):
            if not w:
                continue
            if w.is_weekly and not weekly:
                weekly = w
            elif w.is_five_hour and not five_h:
                five_h = w
    return weekly, five_h


# --------------------------------------------------------------------------- #
# Icon rendering (cairo → PNG)
# --------------------------------------------------------------------------- #
def render_bar_icon(pct: float, size: int = ICON_SIZE) -> str:
    """Render a square PNG with a horizontal progress bar (fill = used%).

    Layout: a thin track across the lower-middle of the icon, filled from the
    left by `pct` percent, colored green/orange/red by threshold. Looks like a
    compact progress bar that fits a 22–24px tray cell.
    """
    path = tempfile.NamedTemporaryFile(suffix=".zai.png", delete=False).name
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surf)

    pad = 2
    bar_h = max(5, size // 4)
    bar_y = size - bar_h - pad
    bar_w = size - 2 * pad

    # Track (full width, dim).
    ctx.set_source_rgba(*_hex_to_rgb("#3c3c3c"), 1.0)
    _round_rect(ctx, pad, bar_y, bar_w, bar_h, bar_h / 2)
    ctx.fill()

    # Fill (pct of width, threshold-colored).
    if pct > 0:
        fill_w = max(bar_h, bar_w * max(0.0, min(100.0, pct)) / 100.0)
        ctx.set_source_rgba(*_hex_to_rgb(_color_for(pct)), 1.0)
        _round_rect(ctx, pad, bar_y, fill_w, bar_h, bar_h / 2)
        ctx.fill()

    # Small dot on top to mark which end is "full" (the right edge = cap).
    cx = size - pad - 1
    cy = pad + 1
    ctx.set_source_rgba(*_hex_to_rgb(_color_for(pct)), 0.85)
    ctx.arc(cx, cy, 1.4, 0, 2 * 3.14159)
    ctx.fill()

    surf.flush()
    surf.write_to_png(path)
    return path


def _round_rect(ctx, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -3.14159 / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, 3.14159 / 2)
    ctx.arc(x + r, y + h - r, r, 3.14159 / 2, 3.14159)
    ctx.arc(x + r, y + r, r, 3.14159, 3 * 3.14159 / 2)
    ctx.close_path()


# --------------------------------------------------------------------------- #
# Tooltip
# --------------------------------------------------------------------------- #
def tooltip_markup(snap, now: float) -> str:
    if not snap or not snap.dominant:
        return "<b>z.ai</b>  no data\nStart a Codex session"

    dom = snap.dominant
    out = [f"<b>z.ai · {dom.label} {dom.used_percent:.0f}% used</b>", ""]

    weekly, five_h = _window_windows(snap)

    def line(name: str, w: Window | None) -> str:
        if not w:
            return f"<tt>{name:<7}</tt> n/a"
        remain = _human_remaining(w.resets_at, now)
        c = _color_for(w.used_percent)
        return (
            f"<tt>{name:<7}</tt> "
            f'<span foreground="{c}">{w.used_percent:5.1f}%</span>  '
            f'<span foreground="{COLOR_DIM}">resets in {remain} ({_fmt_ts(w.resets_at)})</span>'
        )

    out.append(line("weekly", weekly))
    out.append(line("5h", five_h))
    for w in (snap.primary, snap.secondary):
        if w and not w.is_weekly and not w.is_five_hour:
            out.append(line(w.label, w))

    if snap.credits:
        out.append("")
        if snap.credits.unlimited:
            cred = '<span foreground="#26a269">unlimited</span>'
        else:
            cred = f"balance {_fmt_balance(snap.credits.balance)}"
        out.append(f"<tt>credits</tt>  {cred}")

    out.append("")
    out.append(f'<span foreground="{COLOR_DIM}">updated {_human_remaining_or_age(snap.ts, now)} · click for details</span>')
    return "\n".join(out)


def _human_remaining_or_age(ts: float, now: float) -> str:
    delta = int(now - ts)
    if delta < 60:
        return f"{delta}s ago"
    m, _ = divmod(delta, 60)
    if m < 60:
        return f"{m}m ago"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h {m}m ago"
    d, h = divmod(h, 24)
    return f"{d}d {h}h ago"


# --------------------------------------------------------------------------- #
# The tray indicator
# --------------------------------------------------------------------------- #
class ZaiTray:
    def __init__(self) -> None:
        self.icon = Gtk.StatusIcon()
        self.icon.set_visible(True)
        self.icon.set_tooltip_text("z.ai limits (loading…)")
        self.icon.connect("activate", self._on_activate)  # left click
        self.icon.connect("popup-menu", self._on_popup)  # right click
        self.icon.connect("size-changed", self._on_size_changed)
        self._icon_file: str | None = None
        self._cur_size = ICON_SIZE
        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SEC, self.refresh)

    # --- update -------------------------------------------------------------
    def refresh(self) -> bool:
        snap = collect_codex()
        now = time.time()
        pct = snap.dominant.used_percent if snap and snap.dominant else 0.0
        path = render_bar_icon(pct, self._cur_size)
        try:
            self.icon.set_from_file(path)
        finally:
            if self._icon_file and os.path.exists(self._icon_file):
                try:
                    os.unlink(self._icon_file)
                except OSError:
                    pass
            self._icon_file = path
        self.icon.set_tooltip_markup(tooltip_markup(snap, now))
        return True  # keep the GLib timeout alive

    # --- events -------------------------------------------------------------
    def _on_activate(self, _icon) -> None:
        # Left click → notification with full details.
        show_notify(collect_codex())

    def _on_popup(self, _icon, button, when) -> None:
        menu = Gtk.Menu()

        item = Gtk.MenuItem(label="Refresh now")
        item.connect("activate", lambda *_: self.refresh())
        menu.append(item)

        item = Gtk.MenuItem(label="Send notification")
        item.connect("activate", lambda *_: self._on_activate(None))
        menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        item = Gtk.MenuItem(label="Quit")
        item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(item)

        menu.show_all()
        menu.popup(None, None, None, None, button, when)

    def _on_size_changed(self, _icon, size) -> bool:
        # Tray asked for a different pixel size — regenerate at that size.
        if size and size != self._cur_size:
            self._cur_size = max(16, min(48, size))
            self.refresh()
        return False  # don't use a stock icon, we provide our own pixbuf


def main() -> int:
    ZaiTray()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
