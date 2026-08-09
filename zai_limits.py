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
import fcntl
import glob
import json
import math
import os
import select
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import cairo
from datetime import datetime, timezone
from typing import Optional

DEFAULT_CODEX_DIR = "~/.codex/sessions"
CODEX_USAGE_CACHE_PATH = os.environ.get("CODEX_USAGE_CACHE", "/tmp/codex-usage-cache.json")
CODEX_USAGE_CACHE_TTL = int(os.environ.get("CODEX_USAGE_CACHE_TTL", "25"))
CODEX_USAGE_LOCK_PATH = CODEX_USAGE_CACHE_PATH + ".lock"

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
    # Per-model buckets returned alongside the account-wide ``codex`` bucket
    # by Codex's app-server (for example GPT-5.3-Codex-Spark).
    model_limits: dict[str, Window] = field(default_factory=dict)
    # z.ai account usage (GLM / pi plan) — a SEPARATE provider from codex.
    # codex talks to OpenAI/ChatGPT; this is the z.ai/GLM subscription quota.
    zai_tokens: Optional[Window] = None
    zai_weekly: Optional[Window] = None
    zai_time: Optional[Window] = None
    zai_level: Optional[str] = None
    zai_ts: Optional[float] = None

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
    """Collect the current main Codex limit, falling back to rollout logs.

    Recent Codex versions log the rate limit for the model used in a turn.  For
    example, GPT-5.3-Codex-Spark has its own 100%-remaining bucket, while the
    account-wide ``codex`` bucket is the weekly figure shown on the Usage page.
    The app-server exposes the latter through its supported local protocol.
    """
    live = _collect_codex_live()
    if live:
        return live

    # Older Codex installations have no app-server endpoint.  Their rollout
    # logs are still useful as a no-network fallback.
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


def _codex_bin() -> Optional[str]:
    """Find the Codex CLI even when genmon starts with a reduced PATH."""
    candidates = [
        os.environ.get("CODEX_BIN"),
        shutil.which("codex"),
        os.path.expanduser("~/.npm-global/bin/codex"),
    ]
    return next((path for path in candidates if path and os.path.isfile(path)), None)


def _read_json_cache(path: str, ttl: int, allow_stale: bool = False) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            cached = json.load(fh)
        if allow_stale or time.time() - float(cached.get("ts", 0)) <= ttl:
            return cached
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return None


def _snapshot_from_app_server(payload: dict, ts: float) -> Optional[LimitSnapshot]:
    """Convert ``account/rateLimits/read``'s camelCase response."""
    rl = payload.get("rateLimits") or {}
    if not rl:
        return None

    def window(raw: Optional[dict]) -> Optional[Window]:
        if not raw:
            return None
        try:
            return Window(
                used_percent=float(raw.get("usedPercent", 0) or 0),
                window_minutes=int(raw.get("windowDurationMins", 0) or 0),
                resets_at=int(raw.get("resetsAt", 0) or 0),
            )
        except (TypeError, ValueError):
            return None

    primary, secondary = window(rl.get("primary")), window(rl.get("secondary"))
    if not primary and not secondary:
        return None
    credits_raw = rl.get("credits")
    credits = None
    if credits_raw:
        credits = Credits.from_raw(
            {
                "has_credits": credits_raw.get("hasCredits"),
                "unlimited": credits_raw.get("unlimited"),
                "balance": credits_raw.get("balance"),
            }
        )
    model_limits = {}
    for limit_id, model_rl in (payload.get("rateLimitsByLimitId") or {}).items():
        if limit_id == "codex" or not isinstance(model_rl, dict):
            continue
        model_window = window(model_rl.get("primary"))
        name = model_rl.get("limitName") or limit_id
        if model_window and isinstance(name, str):
            model_limits[name] = model_window

    return LimitSnapshot(
        source="codex:live",
        ts=ts,
        primary=primary,
        secondary=secondary,
        credits=credits,
        limit_id=rl.get("limitId"),
        plan_type=rl.get("planType"),
        model_limits=model_limits,
    )


def _collect_codex_live() -> Optional[LimitSnapshot]:
    """Serialize overlapping Codex refreshes.

    A slow genmon tick or a manual invocation can overlap the next refresh.
    Avoid starting two app-servers against Codex's coordination files.
    """
    cached = _read_json_cache(CODEX_USAGE_CACHE_PATH, CODEX_USAGE_CACHE_TTL)
    if cached:
        return _snapshot_from_app_server(cached.get("payload") or {}, cached["ts"])
    try:
        with open(CODEX_USAGE_LOCK_PATH, "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            # The other widget may have refreshed while we waited.
            cached = _read_json_cache(CODEX_USAGE_CACHE_PATH, CODEX_USAGE_CACHE_TTL)
            if cached:
                return _snapshot_from_app_server(cached.get("payload") or {}, cached["ts"])
            return _refresh_codex_live()
    except OSError:
        return _refresh_codex_live()


def _refresh_codex_live() -> Optional[LimitSnapshot]:
    """Read the account-wide limit from Codex's local app-server protocol."""
    def stale_snapshot() -> Optional[LimitSnapshot]:
        stale = _read_json_cache(CODEX_USAGE_CACHE_PATH, CODEX_USAGE_CACHE_TTL, allow_stale=True)
        if stale:
            return _snapshot_from_app_server(stale.get("payload") or {}, stale["ts"])
        return None

    cached = _read_json_cache(CODEX_USAGE_CACHE_PATH, CODEX_USAGE_CACHE_TTL)
    if cached:
        return _snapshot_from_app_server(cached.get("payload") or {}, cached["ts"])

    codex = _codex_bin()
    if not codex:
        return stale_snapshot()
    proc = None
    try:
        proc = subprocess.Popen(
            [codex, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

        def send(message: dict) -> None:
            assert proc and proc.stdin
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def receive(request_id: int, timeout: float) -> Optional[dict]:
            assert proc and proc.stdout
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                ready, _, _ = select.select([proc.stdout], [], [], deadline - time.monotonic())
                if not ready:
                    break
                message = json.loads(proc.stdout.readline())
                if message.get("id") == request_id:
                    return message.get("result")
            return None

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "zai-limits", "version": "1.0"},
            "capabilities": {},
        }})
        if receive(1, 5) is None:
            return stale_snapshot()
        send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": None})
        payload = receive(2, 10)
        if not payload:
            return stale_snapshot()
        cached = {"ts": time.time(), "payload": payload}
        try:
            with open(CODEX_USAGE_CACHE_PATH, "w", encoding="utf-8") as fh:
                json.dump(cached, fh)
        except OSError:
            pass
        return _snapshot_from_app_server(payload, cached["ts"])
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        # Do not make the panel appear empty just because Codex was closed or
        # its app-server is momentarily unavailable.  Keep the last known
        # account-wide value; the tooltip makes its age explicit.
        return stale_snapshot()
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()


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
# z.ai account usage (GLM / pi plan) — separate provider from codex
# --------------------------------------------------------------------------- #
ZAI_USAGE_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
ZAI_CACHE_PATH = os.environ.get("ZAI_CACHE", "/tmp/zai-usage-cache.json")
ZAI_CACHE_TTL = int(os.environ.get("ZAI_CACHE_TTL", "25"))


def _read_zai_key() -> Optional[str]:
    """Read the z.ai API key from env or ~/.pi/agent/auth.json."""
    k = os.environ.get("ZAI_API_KEY")
    if k:
        return k
    for path in ("~/.pi/agent/auth.json", "~/.config/pi/agent/auth.json"):
        try:
            with open(os.path.expanduser(path)) as f:
                return (json.load(f).get("zai") or {}).get("key")
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _zai_window_minutes(lim: dict) -> int:
    """Decode a z.ai limit's window length (minutes) from its unit/number.

    z.ai limits now carry ``unit`` (a time-unit enum) and ``number`` (count):
    observed unit=3 → HOUR, unit=6 → WEEK. For an unknown or absent unit we
    fall back to classifying by how far ``nextResetTime`` sits from now (a
    5-hour window always resets within ~5h; a weekly one can be up to 7d out).
    """
    per_unit_min = {3: 60, 4: 1440, 6: 10080}  # hour, day, week
    try:
        unit = int(lim.get("unit")) if lim and lim.get("unit") is not None else None
    except (TypeError, ValueError):
        unit = None
    if unit in per_unit_min:
        try:
            number = int(lim.get("number") or 1)
        except (TypeError, ValueError):
            number = 1
        return per_unit_min[unit] * number
    reset = (int(lim.get("nextResetTime", 0) or 0)) // 1000 if lim else 0
    if reset:
        return 10080 if (reset - time.time()) > 6 * 3600 else 300
    return 300


def collect_zai() -> Optional[dict]:
    """Query the z.ai subscription usage API (with a short on-disk cache).

    Endpoint discovered via the shaftoe/pi-zai-usage extension:
    GET https://api.z.ai/api/monitor/usage/quota/limit  with the zai API key.
    Returns (two TOKENS_LIMIT windows now — 5h + weekly — plus the MCP one)::

        {"data": {"limits": [
            {"type":"TOKENS_LIMIT","unit":3,"number":5,"percentage":79,
             "nextResetTime":1785779102837},            # 5-hour cycle
            {"type":"TOKENS_LIMIT","unit":6,"number":1,"percentage":15,
             "nextResetTime":1786355862998},            # weekly cycle
            {"type":"TIME_LIMIT","unit":5,"number":1,"percentage":2,
             "nextResetTime":1787824662980,...}],        # MCP tools
            "level":"pro"}, "success": true}
    """
    # serve from cache if fresh (genmon ticks every 30s; z.ai needn't be hit
    # that often). Cache stores JSON primitives; Windows are rebuilt on return.
    try:
        with open(ZAI_CACHE_PATH) as f:
            cached = json.load(f)
        if time.time() - float(cached.get("ts", 0)) < ZAI_CACHE_TTL:
            return _build_zai_result(cached)
    except (OSError, ValueError, TypeError):
        pass

    key = _read_zai_key()
    if not key:
        return None
    req = urllib.request.Request(
        ZAI_USAGE_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            payload = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not payload.get("success"):
        return None
    data = payload.get("data") or {}
    limits = data.get("limits") or []

    # z.ai now returns up to two TOKENS_LIMIT windows: a 5-hour rolling
    # cycle (unit=3/HOUR, number=5) and a weekly cycle (unit=6/WEEK,
    # number=1). Tell them apart by window length, not by list order.
    token_limits = [l for l in limits if l.get("type") == "TOKENS_LIMIT"]
    weekly = next(
        (l for l in token_limits if 9900 <= _zai_window_minutes(l) <= 10300),
        None,
    )
    five_h = next(
        (l for l in token_limits
         if l is not weekly and 250 <= _zai_window_minutes(l) <= 350),
        None,
    )
    if five_h is None:  # back-compat: old API with a single TOKENS_LIMIT
        five_h = next((l for l in token_limits if l is not weekly), None)
    time_l = next((l for l in limits if l.get("type") == "TIME_LIMIT"), None)

    def prim(lim):
        return {
            "pct": float(lim.get("percentage", 0) or 0) if lim else None,
            "reset": (int(lim.get("nextResetTime", 0)) // 1000) if lim and lim.get("nextResetTime") else 0,
            "win_min": _zai_window_minutes(lim) if lim else None,
        }

    cached = {
        "tokens": prim(five_h),   # TOKENS_LIMIT 5h rolling ("plan usage")
        "weekly": prim(weekly),   # TOKENS_LIMIT weekly cycle
        "time": prim(time_l),     # TIME_LIMIT  MCP-tools quota
        "level": data.get("level"),
        "ts": time.time(),
    }
    try:
        with open(ZAI_CACHE_PATH, "w") as f:
            json.dump(cached, f)
    except OSError:
        pass
    return _build_zai_result(cached)


def _build_zai_result(cached: dict) -> Optional[dict]:
    def mk(lim: dict, default_win_min: int) -> Optional[Window]:
        if not lim or lim.get("pct") is None:
            return None
        return Window(
            used_percent=float(lim["pct"]),
            window_minutes=int(lim.get("win_min") or default_win_min),
            resets_at=int(lim.get("reset", 0) or 0),
        )

    return {
        "tokens": mk(cached.get("tokens"), 300),    # TOKENS_LIMIT 5h rolling ("plan usage")
        "weekly": mk(cached.get("weekly"), 10080),  # TOKENS_LIMIT weekly cycle
        "time": mk(cached.get("time"), 10080),      # TIME_LIMIT  MCP-tools quota (search/web-reader/zread)
        "level": cached.get("level"),
        "ts": float(cached.get("ts", 0) or 0),
    }


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

    if not snap or not (snap.dominant or snap.zai_tokens or snap.zai_weekly):
        parts.append("<bar>0</bar>")
        parts.append(f"<click>{_notify_click_command()}</click>")
        parts.append("<tool>z.ai — no data\nStart Codex / configure the z.ai key, then click to retry.</tool>")
        return "\n".join(parts)

    codex_pct = snap.dominant.used_percent if snap.dominant else 0.0
    zai_pct = snap.zai_tokens.used_percent if snap.zai_tokens else 0.0
    zai_weekly_pct = snap.zai_weekly.used_percent if snap.zai_weekly else 0.0

    # One native genmon <bar>. To show BOTH metrics as bars, add two genmon
    # items: one with ZAI_BAR_METRIC=codex (default), one with =zai (or
    # =zai-weekly to drive the bar by the weekly window instead of the 5h).
    metric = os.environ.get("ZAI_BAR_METRIC", "codex").strip().lower()
    if metric in ("zai", "z.ai", "glm"):
        bar_pct = zai_pct
    elif metric in ("zai-weekly", "zai_weekly", "weekly"):
        bar_pct = zai_weekly_pct
    else:
        bar_pct = codex_pct

    parts.append(f"<bar>{_clamp_bar(bar_pct)}</bar>")
    # Color the bar by threshold (genmon's <bar> is theme-blue by default).
    # genmon 4.3.0 supports a <css> tag styling the plugin widget tree.
    css_color = _color_for(bar_pct)
    parts.append(
        "<css>"
        f"progressbar progress {{ background-color: {css_color}; }} "
        "progressbar trough { background-color: #3c3c3c; }"
        "</css>"
    )
    parts.append(f"<click>{_notify_click_command()}</click>")

    # Rich tooltip — scoped to THIS bar's metric (codex OR z.ai), so the two
    # genmon items have DIFFERENT tooltips matching their bar.
    NL = chr(10)
    is_zai = metric in ("zai", "z.ai", "glm", "zai-weekly", "zai_weekly", "weekly")

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

    tip: list[str] = []
    if is_zai:
        header = "z.ai (GLM"
        if snap.zai_level:
            header += f", {snap.zai_level}"
        header += ")"
        tip.append(f"<tt><b>{header}</b></tt>")
        tip.append("")
        tip.append(window_line("5h", snap.zai_tokens))      # TOKENS_LIMIT 5h rolling
        tip.append(window_line("weekly", snap.zai_weekly))  # TOKENS_LIMIT weekly cycle
        tip.append(window_line("MCP", snap.zai_time))       # TIME_LIMIT MCP-tools quota (search/web-reader/zread)
        tip.append("")
        tip.append(_pango(COLOR_DIM, f"live API · updated {_human_age(snap.zai_ts or snap.ts, now)}"))
    else:
        tip.append("<tt><b>codex (ChatGPT)</b></tt>")
        tip.append("")
        weekly = snap.primary if snap.primary and snap.primary.is_weekly else (
            snap.secondary if snap.secondary and snap.secondary.is_weekly else None
        )
        five_h = snap.primary if snap.primary and snap.primary.is_five_hour else (
            snap.secondary if snap.secondary and snap.secondary.is_five_hour else None
        )
        tip.append(window_line("weekly", weekly))
        tip.append(window_line("5h", five_h))
        for w in (snap.primary, snap.secondary):
            if w and not w.is_weekly and not w.is_five_hour:
                tip.append(window_line(w.label, w))
        for name, w in snap.model_limits.items():
            tip.append(window_line(name, w))
        if snap.credits:
            tip.append("")
            if snap.credits.unlimited:
                cred = _pango(COLOR_OK, "unlimited")
            elif snap.credits.has_credits:
                cred = _pango(COLOR_OK, f"balance {_fmt_balance(snap.credits.balance)}")
            else:
                cred = _pango(COLOR_DIM, f"balance {_fmt_balance(snap.credits.balance)}")
            tip.append(_pango(COLOR_LABEL, _pad_right("credits:", 8)) + NBSP + cred)
        tip.append("")
        origin = "live Codex usage" if snap.source == "codex:live" else "Codex logs"
        tip.append(_pango(COLOR_DIM, f"updated {_human_age(snap.ts, now)} · {origin}"))

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
    return int(max(0, min(100, round(pct))));


# --------------------------------------------------------------------------- #
# Dual-bar PNG rendering for genmon <img> (two bars: codex + z.ai)
# --------------------------------------------------------------------------- #
_DUAL_BAR_PATH = os.environ.get("ZAI_BARS_PNG", "/tmp/zai-bars.png")


def _hex_to_rgb(hexcolor: str) -> tuple[float, float, float]:
    h = hexcolor.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore


def _round_rect(ctx, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -3.14159 / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, 3.14159 / 2)
    ctx.arc(x + r, y + h - r, r, 3.14159 / 2, 3.14159)
    ctx.arc(x + r, y + r, r, 3.14159, 3 * 3.14159 / 2)
    ctx.close_path()


def _draw_h_bar(ctx, x, y, w, h, pct: float):
    # track
    ctx.set_source_rgba(0.235, 0.235, 0.235, 1.0)
    _round_rect(ctx, x, y, w, h, h / 2)
    ctx.fill()
    # fill
    if pct > 0:
        fw = max(h, w * (max(0.0, min(100.0, pct)) / 100.0))
        ctx.set_source_rgba(*_hex_to_rgb(_color_for(pct)), 1.0)
        _round_rect(ctx, x, y, fw, h, h / 2)
        ctx.fill()


def render_dual_bar_png(
    codex_pct: float,
    zai_pct: float,
    width: int = 20,
    height: int = 40,
    path: str = _DUAL_BAR_PATH,
) -> str:
    """Render a tall PNG with two stacked horizontal bars (codex on top,
    z.ai on bottom). For genmon's <img> tag — genmon's <bar> only does one."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surf)
    gap = 3
    bar_h = (height - gap) // 2
    _draw_h_bar(ctx, 1, 0, width - 2, bar_h, codex_pct)
    _draw_h_bar(ctx, 1, bar_h + gap, width - 2, height - bar_h - gap, zai_pct)
    surf.flush()
    surf.write_to_png(path)
    return path


def format_text(snap: Optional[LimitSnapshot], now: Optional[float] = None) -> str:
    now = now or time.time()
    if not snap or not (snap.dominant or snap.zai_tokens or snap.zai_weekly):
        return "z.ai: no data (start Codex / configure z.ai key)"
    lines = []
    # codex (ChatGPT)
    if snap.dominant:
        dom = snap.dominant
        lines.append(f"codex (ChatGPT)  {dom.label}: {dom.used_percent:.0f}% used")
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
    for name, w in snap.model_limits.items():
        lines.append(
            f"  {name:<20} {w.used_percent:>5.1f}%  "
            f"resets in {_human_remaining(w.resets_at, now)}  "
            f"({_fmt_ts(w.resets_at)})"
        )
    # z.ai (GLM)
    if snap.zai_tokens or snap.zai_weekly or snap.zai_time:
        lines.append("")
        level = f", {snap.zai_level}" if snap.zai_level else ""
        lines.append(f"z.ai (GLM{level})")
        for name, w in (
            ("5h", snap.zai_tokens),
            ("weekly", snap.zai_weekly),
            ("MCP", snap.zai_time),
        ):
            if w:
                lines.append(
                    f"  {name:<7} {w.used_percent:>5.1f}%  "
                    f"resets in {_human_remaining(w.resets_at, now)}  "
                    f"({_fmt_ts(w.resets_at)})"
                )
        if snap.zai_ts:
            lines.append(f"  updated {_human_age(snap.zai_ts, now)} (live API)")
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
            "model_limits": {name: win(w) for name, w in snap.model_limits.items()},
            "zai": (
                None
                if not (snap.zai_weekly or snap.zai_tokens or snap.zai_time)
                else {
                    "level": snap.zai_level,
                    "observed_at": int(snap.zai_ts) if snap.zai_ts else None,
                    "weekly": win(snap.zai_weekly),
                    "tokens_5h": win(snap.zai_tokens),
                    "mcp_time": win(snap.zai_time),
                }
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
        "--skip-zai",
        action="store_true",
        help="do not query the z.ai (GLM) account usage API",
    )
    p.add_argument(
        "--notify",
        action="store_true",
        help="send a desktop notification with full details (for genmon <click>)",
    )
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    metric = os.environ.get("ZAI_BAR_METRIC", "codex").strip().lower()
    zai_metrics = ("zai", "z.ai", "glm", "zai-weekly", "zai_weekly", "weekly")
    # Each genmon item has one provider.  Do not query the unrelated provider:
    # the z.ai widget must never start Codex app-server, and the Codex widget
    # must never call the z.ai API.  Text/JSON modes intentionally report both.
    genmon_zai = args.format == "genmon" and metric in zai_metrics and not args.notify
    genmon_codex = args.format == "genmon" and metric not in zai_metrics and not args.notify

    snap = None if genmon_zai else collect_codex(args.codex_dir)

    # z.ai (GLM) subscription usage — separate provider, live API.
    if not args.skip_zai and not genmon_codex:
        zai = collect_zai()
        if zai:
            if snap is None:
                snap = LimitSnapshot(source="zai", ts=zai["ts"])
            snap.zai_tokens = zai["tokens"]
            snap.zai_weekly = zai["weekly"]
            snap.zai_time = zai["time"]
            snap.zai_level = zai["level"]
            snap.zai_ts = zai["ts"]

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
