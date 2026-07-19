#!/usr/bin/env bash
# xfce4-genmon-plugin entry point for z.ai limits.
#
# Point your "Generic Monitor" panel item's Command at this file, set the
# period to ~30s, enable "Show label" off, and check "Use a progress bar".
#
# Env overrides (see zai_limits.py for the full list):
#   ZAI_LIMITS_WARN     % at which the bar turns orange   (default 70)
#   ZAI_LIMITS_CRIT     % at which the bar turns red       (default 90)
#   ZAI_LIMITS_STALE_SEC  consider data older than this stale (default 21600)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${HERE}/../zai_limits.py" --format genmon "$@"
