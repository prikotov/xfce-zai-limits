#!/usr/bin/env python3
"""
xfce-zai-limits — XFCE panel widget for z.ai usage limits (codex / pi).

It reads the freshest data source that already exists on disk (no API calls,
no quota spent) and prints output for the xfce4-genmon-plugin:

    <txt>...</txt>      compact label (Pango markup)
    <bar>N</bar>        progress bar 0..100 (the dominant limit window)
    <tooltip>...</tooltip>   details on hover (Pango markup)

Currently supported data sources
--------------------------------
- codex rollout logs (``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl``):
  OpenAI Codex CLI writes a ``rate_limits`` snapshot into every ``token_count``
  event when running against z.ai. This contains the rolling windows
  (``primary`` = weekly, ``secondary`` = 5-hour) and the credits snapshot.

  These are the *ChatGPT-plan style* rolling limits that z.ai exposes for the
  ``gpt-5.x`` models used by Codex. They are the most common reason users hit
  "out of limits", so they make a good primary indicator.

Future / optional sources
-------------------------
- ``--source zai-api``: query z.ai directly for the GLM (API-key) usage.
  Not implemented yet — see README "Limitations".

Exit codes
----------
0  data collected (even if stale)
1  no data found at all
2  bad CLI usage
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

DEFAULT_CODEX_DIR = "~/.codex/sessions"

# Color thresholds for the *used* percentage of the dominant window.
WARN_PCT = float(os.environ.get("ZAI_LIMITS_WARN", "70"))
CRIT_PCT = float(os.environ.get("ZAI_LIMITS_CRIT", "90"))
COLOR_OK = os.environ.get("ZAI_LIMITS_COLOR_OK", "#26a269")     # green
COLOR_WARN = os.environ.get("ZAI_LIMITS_COLOR_WARN", "#e09b24")  # orange
COLOR_CRIT = os.environ.get("ZAI_LIMITS_COLOR_CRIT", "#e01b24")  # red
COLOR_DIM = os.environ.get("ZAI_LIMITS_COLOR_DIM", "#888888")
COLOR_LABEL = os.environ.get("ZAI_LIMITS_COLOR_LABEL", "#c0bfbc")

# A rollout log is considered "fresh" if its rate-limit event is newer than this.
STALE_AFTER_SEC = int(os.environ.get("ZAI_LIMITS_STALE_SEC", str(6 * 3600)))

# How many recent rollout files to scan before giving up.
MAX_FILES_TO_SCAN = 25


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Window:
    used_percent: float
    window_minutes: int
    resets_at: int  # unix seconds

    @property
    def is_weekly(self) -> bool:
        # 7d +/- a few minutes (z.ai uses 10080 for the weekly window).
        return 9900 <= self.window_minutes <= 10300

    @property
    def is_five_hour(self) -> bool:
        return 250 <= self.window_minutes <= 350

    @property
    def label(self) -> str:
        if self.is_weekly:
            return "weekly"
        if self.is_five_hour:
            return "5h"
        days = self.window_minutes / 60 / 24
        if days >= 1:
            return f"{days:g}d"
        hours = self.window_minutes / 60
        return f"{hours:g}h"


@dataclass
class Credits:
    has_credits: bool
    unlimited: bool
    balance: float

    @classmethod
    def from_raw(cls, raw: Optional[dict]) -> Optional["Credits"]:
        if not raw:
            return None
        try:
            balance = float(raw.get("balance", 0) or 0)
        except (TypeError, ValueError):
            balance = 0.0
        return cls(
            has_credits=bool(raw.get("has_credits", False)),
            unlimited=bool(raw.get("unlimited", False)),
            balance=balance,
        )


@dataclass
class LimitSnapshot:
    """A single point-in-time view of the z.ai limits."""

    source: str
    ts: float  # unix seconds, when the snapshot was observed
    primary: Optional[Window] = None
    secondary: Optional[Window] = None
    credits: Optional[Credits] = None
    limit_id: Optional[str] = None
    plan_type: Optional[str] = None

    @property
    def dominant(self) -> Optional[Window]:
        """The window to drive the progress bar: the one closer to the cap."""
        windows = [w for w in (self.primary, self.secondary) if w]
        if not windows:
            return None
        return max(windows, key=lambda w: w.used_percent)


# --------------------------------------------------------------------------- #
# Collectors
# --------------------------------------------------------------------------- #
def _iter_rollouts_newest_first(codex_dir: str):
    pattern = os.path.join(codex_dir, "*", "*", "*", "rollout-*.jsonl")
    files = glob.glob(os.path.expanduser(pattern))
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def _last_rate_limit_in_file(path: str):
    """Return (timestamp_unix, rate_limits_dict) for the last event that has it.

    Reads the file once, keeping the freshest rate_limits seen. Codex appends
    events, so the last one in the file is normally the latest — but we scan
    defensively in case of partial writes.
    """
    best = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"rate_limits"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "event_msg":
                    continue
                payload = obj.get("payload") or {}
                rl = payload.get("rate_limits")
                if not rl:
                    continue
                ts_raw = obj.get("timestamp")
                ts = _parse_iso(ts_raw)
                if ts is None:
                    continue
                if best is None or ts > best[0]:
                    best = (ts, rl)
    except OSError:
        return None
    return best


def _parse_iso(ts_raw) -> Optional[float]:
    if not ts_raw or not isinstance(ts_raw, str):
        return None
    # Codex timestamps look like "2026-07-19T07:18:26.257Z".
    try:
        s = ts_raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt.timestamp()
    except ValueError:
        return None


def collect_codex(codex_dir: str = DEFAULT_CODEX_DIR) -> Optional[LimitSnapshot]:
    """Collect the freshest rate-limit snapshot from Codex rollout logs."""
    files = _iter_rollouts_newest_first(codex_dir)
    for path in files[:MAX_FILES_TO_SCAN]:
        hit = _last_rate_limit_in_file(path)
        if not hit:
            continue
        ts, rl = hit
        snap = _snapshot_from_codex_rate_limits(rl, ts)
        if snap:
            snap.source = f"codex:{os.path.basename(path)}"
            return snap
    return None


def _snapshot_from_codex_rate_limits(
    rl: dict, ts: float
) -> Optional[LimitSnapshot]:
    primary = _window_from_raw(rl.get("primary"))
    secondary = _window_from_raw(rl.get("secondary"))
    if not primary and not secondary:
        return None
    return LimitSnapshot(
        source="codex",
        ts=ts,
        primary=primary,
        secondary=secondary,
        credits=Credits.from_raw(rl.get("credits")),
        limit_id=rl.get("limit_id"),
        plan_type=rl.get("plan_type"),
    )


def _window_from_raw(raw) -> Optional[Window]:
    if not raw:
        return None
    try:
        return Window(
            used_percent=float(raw.get("used_percent", 0) or 0),
            window_minutes=int(raw.get("window_minutes", 0) or 0),
            resets_at=int(raw.get("resets_at", 0) or 0),
        )
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _color_for(pct: float) -> str:
    if pct >= CRIT_PCT:
        return COLOR_CRIT
    if pct >= WARN_PCT:
        return COLOR_WARN
    return COLOR_OK


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )



def _human_remaining(resets_at: int, now: float) -> str:
    if not resets_at or resets_at <= now:
        return "now"
    delta = resets_at - now
    days, rem = divmod(int(delta), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if not days:  # don't bother with minutes when days are shown
        parts.append(f"{minutes}m")
    return " ".join(parts) or "<1m"


def _human_age(ts: float, now: float) -> str:
    delta = max(0, int(now - ts))
    if delta < 60:
        return f"{delta}s ago"
    minutes, sec = divmod(delta, 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m ago"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h ago"


def _fmt_ts(resets_at: int) -> str:
    if not resets_at:
        return "—"
    try:
        return datetime.fromtimestamp(resets_at).strftime("%b %d, %H:%M")
    except (OSError, ValueError, OverflowError):
        return "—"


def _pango(color: str, text: str) -> str:
    return f'<span foreground="{color}">{_xml_escape(text)}</span>'


NBSP = "\u00a0"


def _pad_right(text: str, width: int) -> str:
    """Right-pad with non-breaking spaces so Pango doesn't collapse them."""
    if len(text) >= width:
        return text
    return text + NBSP * (width - len(text))


# --------------------------------------------------------------------------- #
# Output formatters
# --------------------------------------------------------------------------- #
def format_genmon(snap: Optional[LimitSnapshot], now: Optional[float] = None) -> str:
    now = now or time.time()
    parts = []

    if not snap or not snap.dominant:
        parts.append("<bar>0</bar>")
        parts.append(f"<click>{_notify_click_command()}</click>")
        parts.append("<tool>z.ai — no data\nStart a Codex session, then click to retry.</tool>")
        return "\n".join(parts)

    dom = snap.dominant
    pct = dom.used_percent

    # Panel shows ONLY the graphical <bar> (no <txt> label — per request).
    # Numbers live in <tool>, which is genmon's REAL hover-tooltip tag.
    # (Not <tooltip> — that tag does not exist; verified against
    # xfce4-genmon-plugin 4.3.0 source: it parses <tool>.)
    parts.append(f"<bar>{_clamp_bar(pct)}</bar>")
    parts.append(f"<click>{_notify_click_command()}</click>")

    # Rich tooltip. Everything is monospace so NBSP padding lines up.
    NL = chr(10)
    tip: list[str] = ["<tt><b>z.ai limits</b></tt>", ""]

    def window_line(name: str, w: Optional[Window]) -> str:
        name_part = _pad_right(f"{name}:", 8)
        if not w:
            return _pango(COLOR_DIM, name_part) + NBSP + _pango(COLOR_DIM, "n/a")
        c = _color_for(w.used_percent)
        remain = _human_remaining(w.resets_at, now)
        pct_part = _pad_right(f"{w.used_percent:.0f}%", 5)
        return (
            _pango(COLOR_LABEL, name_part)
            + NBSP
            + _pango(c, pct_part)
            + NBSP
            + _pango(COLOR_DIM, f"resets in {remain}")
            + NBSP
            + _pango(COLOR_DIM, f"({_fmt_ts(w.resets_at)})")
        )

    # Pick the right labels for whatever windows z.ai returned.
    weekly = snap.primary if snap.primary and snap.primary.is_weekly else (
        snap.secondary if snap.secondary and snap.secondary.is_weekly else None
    )
    five_h = snap.primary if snap.primary and snap.primary.is_five_hour else (
        snap.secondary if snap.secondary and snap.secondary.is_five_hour else None
    )
    tip.append(window_line("weekly", weekly))
    tip.append(window_line("5h", five_h))
    # Surface any window we couldn't classify by name.
    for w in (snap.primary, snap.secondary):
        if w and not w.is_weekly and not w.is_five_hour:
            tip.append(window_line(w.label, w))

    # Credits.
    if snap.credits:
        tip.append("")
        if snap.credits.unlimited:
            cred = _pango(COLOR_OK, "unlimited")
        elif snap.credits.has_credits:
            cred = _pango(COLOR_OK, f"balance {_fmt_balance(snap.credits.balance)}")
        else:
            cred = _pango(COLOR_DIM, f"balance {_fmt_balance(snap.credits.balance)}")
        tip.append(_pango(COLOR_LABEL, _pad_right("credits:", 8)) + NBSP + cred)

    # Provenance — important: data is read from a log, not live.
    tip.append("")
    tip.append(_pango(COLOR_DIM, f"updated {_human_age(snap.ts, now)}"))
    if snap.source:
        tip.append(_pango(COLOR_DIM, f"source: {snap.source}"))
    tip.append(_pango(COLOR_DIM, "read from Codex logs — refreshes as you use Codex"))

    parts.append(f"<tool>{NL.join(tip)}</tool>")
    return "\n".join(parts)


def _fmt_balance(b: float) -> str:
    if b == 0 or math.isclose(b, 0.0, abs_tol=1e-9):
        return "0"
    if b >= 1000:
        return f"{b:,.0f}"
    if b >= 1:
        return f"{b:.2f}"
    return f"{b:g}"


def _clamp_bar(pct: float) -> int:
    return int(max(0, min(100, round(pct))))


def format_text(snap: Optional[LimitSnapshot], now: Optional[float] = None) -> str:
    now = now or time.time()
    if not snap or not snap.dominant:
        return "z.ai: no data (start a Codex session)"
    dom = snap.dominant
    lines = [f"z.ai  dominant {dom.label}: {dom.used_percent:.0f}% used"]
    for name, w in (("weekly", snap.primary), ("5h", snap.secondary)):
        if w:
            lines.append(
                f"  {name:<7} {w.used_percent:>5.1f}%  "
                f"resets in {_human_remaining(w.resets_at, now)}  "
                f"({_fmt_ts(w.resets_at)})"
            )
    if snap.credits:
        lines.append(
            f"  credits balance: {_fmt_balance(snap.credits.balance)}"
            + (" (unlimited)" if snap.credits.unlimited else "")
        )
    lines.append(f"  updated {_human_age(snap.ts, now)}")
    lines.append(f"  source: {snap.source}")
    return "\n".join(lines)


def format_json(snap: Optional[LimitSnapshot], now: Optional[float] = None) -> str:
    now = now or time.time()
    if not snap:
        return json.dumps({"ok": False, "error": "no data"}, ensure_ascii=False)

    def win(w: Optional[Window]):
        if not w:
            return None
        return {
            "used_percent": w.used_percent,
            "window_minutes": w.window_minutes,
            "label": w.label,
            "resets_at": w.resets_at,
            "resets_in_sec": max(0, w.resets_at - int(now)) if w.resets_at else None,
        }

    return json.dumps(
        {
            "ok": True,
            "source": snap.source,
            "observed_at": int(snap.ts),
            "age_sec": int(now - snap.ts),
            "primary": win(snap.primary),
            "secondary": win(snap.secondary),
            "credits": (
                {
                    "balance": snap.credits.balance,
                    "unlimited": snap.credits.unlimited,
                    "has_credits": snap.credits.has_credits,
                }
                if snap.credits
                else None
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------------------------------- #
# Notification (for genmon <click>; genmon 4.3 has no <tooltip>)
# --------------------------------------------------------------------------- #
def _self_path() -> str:
    return os.path.abspath(__file__)


def _notify_click_command() -> str:
    """Command genmon runs on click → fires a desktop notification."""
    return f"/usr/bin/python3 {_self_path()} --notify"


def format_notify(snap: Optional[LimitSnapshot], now: Optional[float] = None):
    """Return (title, body) for notify-send."""
    now = now or time.time()
    if not snap or not snap.dominant:
        return (
            "z.ai limits",
            "No Codex rollout data found.\nStart a Codex session, then click again.",
        )

    dom = snap.dominant
    title = f"z.ai · {dom.label} {dom.used_percent:.0f}% used"

    def line(name: str, w: Optional[Window]) -> str:
        if not w:
            return f"{name:<8} n/a"
        return (
            f"{name:<8} {w.used_percent:>5.1f}%  "
            f"resets in {_human_remaining(w.resets_at, now)}  "
            f"({_fmt_ts(w.resets_at)})"
        )

    weekly = snap.primary if snap.primary and snap.primary.is_weekly else (
        snap.secondary if snap.secondary and snap.secondary.is_weekly else None
    )
    five_h = snap.primary if snap.primary and snap.primary.is_five_hour else (
        snap.secondary if snap.secondary and snap.secondary.is_five_hour else None
    )
    body = [line("weekly", weekly), line("5h", five_h)]
    for w in (snap.primary, snap.secondary):
        if w and not w.is_weekly and not w.is_five_hour:
            body.append(line(w.label, w))

    if snap.credits:
        body.append("")
        if snap.credits.unlimited:
            cred = "unlimited"
        else:
            cred = f"balance {_fmt_balance(snap.credits.balance)}"
        body.append(f"credits  {cred}")

    body.append("")
    body.append(f"updated {_human_age(snap.ts, now)}")
    body.append(f"source: {snap.source}")
    return title, "\n".join(body)


def show_notify(snap: Optional[LimitSnapshot]) -> int:
    """Fire a libnotify notification. Returns notify-send exit code (0=ok)."""
    import subprocess

    title, body = format_notify(snap)
    try:
        return subprocess.call(
            [
                "notify-send",
                "-a", "zai-limits",
                "-i", "org.xfce.genmon",
                "-u", "low",
                title,
                body,
            ]
        )
    except FileNotFoundError:
        sys.stderr.write("notify-send not found; install libnotify.\n")
        print(title)
        print(body)
        return 127


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zai-limits",
        description="Show z.ai usage limits (Codex/pi) for the XFCE panel.",
    )
    p.add_argument(
        "--format",
        choices=("genmon", "text", "json"),
        default="genmon",
        help="output format (default: genmon)",
    )
    p.add_argument(
        "--codex-dir",
        default=DEFAULT_CODEX_DIR,
        help=f"codex sessions dir (default: {DEFAULT_CODEX_DIR})",
    )
    p.add_argument(
        "--notify",
        action="store_true",
        help="send a desktop notification with full details (for genmon <click>)",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    snap = collect_codex(args.codex_dir)

    if args.notify:
        return show_notify(snap)

    if args.format == "json":
        print(format_json(snap))
    elif args.format == "text":
        print(format_text(snap))
        if not snap:
            return 1
    else:
        print(format_genmon(snap))
        if not snap:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
