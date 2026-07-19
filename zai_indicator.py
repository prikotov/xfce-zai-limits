#!/usr/bin/env python3
"""
zai_indicator — z.ai limits indicator via AppIndicator3.

This is the variant that appears in xfce4-statusnotifier-plugin, which (unlike
the legacy systray) can sit on ANY panel. Put statusnotifier on your left
monitoring panel and this indicator lands there — graphical bar icon + a hover
tooltip (set_title) with the numbers, plus a click menu.

Compared to zai_tray.py (Gtk.StatusIcon → goes to the legacy systray), this one
honors "I want it on the left panel". They reuse the same cairo icon rendering.

Run:
    python3 zai_indicator.py
Autostart: see examples/zai-tray.autostart.desktop (point Exec at this file).
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from zai_limits import (  # noqa: E402
    _fmt_balance,
    _fmt_ts,
    _human_remaining,
    collect_codex,
    show_notify,
)
from zai_tray import _color_for, _window_windows, render_bar_icon  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import AppIndicator3, GLib, Gtk  # noqa: E402

REFRESH_SEC = int(os.environ.get("ZAI_TRAY_REFRESH", "30"))


def _title_and_desc(snap, now: float) -> tuple[str, str]:
    """Return (title, icon_desc). Both become visible in the SNI tooltip."""
    if not snap or not snap.dominant:
        return ("z.ai limits: no data", "no data")

    dom = snap.dominant
    weekly, five_h = _window_windows(snap)

    # Title: one compact line shown as the tooltip headline.
    title_bits = [f"z.ai · {dom.used_percent:.0f}% used ({dom.label})"]
    if weekly:
        title_bits.append(
            f"weekly {weekly.used_percent:.0f}% · resets in {_human_remaining(weekly.resets_at, now)}"
        )
    if five_h:
        title_bits.append(
            f"5h {five_h.used_percent:.0f}% · resets in {_human_remaining(five_h.resets_at, now)}"
        )
    title = "\n".join(title_bits)

    # Desc: fuller accessibility/tooltip text.
    desc_lines = [title, ""]
    if snap.credits:
        if snap.credits.unlimited:
            desc_lines.append("credits: unlimited")
        else:
            desc_lines.append(f"credits: balance {_fmt_balance(snap.credits.balance)}")
    age = int(now - snap.ts)
    desc_lines.append(f"updated {max(0, age)}s ago")
    return title, "\n".join(desc_lines)


class ZaiIndicator:
    def __init__(self) -> None:
        self.ind = AppIndicator3.Indicator.new(
            "zai-limits",
            "dialog-information",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.ind.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.ind.set_title("z.ai limits (loading…)")
        self._icon_file: str | None = None

        menu = Gtk.Menu()
        item = Gtk.MenuItem(label="Refresh now")
        item.connect("activate", lambda *_: self.refresh())
        menu.append(item)
        item = Gtk.MenuItem(label="Send notification")
        item.connect("activate", lambda *_: show_notify(collect_codex()))
        menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem(label="Quit")
        item.connect("activate", lambda *_: Gtk.main_quit())
        menu.append(item)
        menu.show_all()
        self.ind.set_menu(menu)

        self.refresh()
        GLib.timeout_add_seconds(REFRESH_SEC, self.refresh)

    def refresh(self) -> bool:
        snap = collect_codex()
        now = time.time()
        pct = snap.dominant.used_percent if snap and snap.dominant else 0.0
        path = render_bar_icon(pct, 22)
        title, desc = _title_and_desc(snap, now)
        try:
            self.ind.set_icon_full(path, desc)
        except TypeError:
            self.ind.set_icon_full(path, "")
        self.ind.set_title(title)

        if self._icon_file and self._icon_file != path and os.path.exists(self._icon_file):
            try:
                os.unlink(self._icon_file)
            except OSError:
                pass
        self._icon_file = path
        return True


def main() -> int:
    ZaiIndicator()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
