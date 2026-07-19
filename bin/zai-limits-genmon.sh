#!/bin/bash
# xfce4-genmon-plugin entry point for z.ai limits — OPTIONAL.
#
# WARNING: do NOT point xfce4-genmon-plugin at this file. genmon spawns its
# command in a restricted environment where a bash script using `$(...)`
# command substitution hangs forever (verified with strace). Point genmon
# straight at python3 instead:
#
#     /usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
#
# This wrapper is kept only for non-genmon use (cron, manual runs, other
# panels). See docs/genmon-spawn-notes.md.
#
# Env overrides (see zai_limits.py for the full list):
#   ZAI_LIMITS_WARN     % at which the bar turns orange   (default 70)
#   ZAI_LIMITS_CRIT     % at which the bar turns red       (default 90)

exec /usr/bin/python3 /home/dp/MyProjects/xfce-zai-limits/zai_limits.py --format genmon "$@"
