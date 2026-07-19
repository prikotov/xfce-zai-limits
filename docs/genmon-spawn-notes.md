# xfce4-genmon-plugin: spawn gotcha (why command points straight at python3)

> **TL;DR** — point genmon's *Command* at an absolute `python3` with an absolute
> script path. **Do not** use a shell wrapper that does `$(...)` command
> substitution: it hangs inside genmon's spawn environment.

## Symptom

A `bin/zai-limits-genmon.sh` like this works perfectly in a terminal:

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${HERE}/../zai_limits.py" --format genmon "$@"
```

… but when genmon runs it, the panel item shows the placeholder `(genmon)`,
the genmon `text` xfconf property never updates, and hovering shows only the
command path. Running the same script via `sh -c '…'` or with genmon's own
environment reproduced via `/proc/<pid>/environ` works fine — so the script is
not the problem.

## Proof (`strace -f -p <genmon-pid>`)

genmon **does** spawn the command, but bash then forks a subshell for the
`$(...)` and blocks forever reading its pipe:

```
genmon  clone(...) = <bash pid>            # genmon runs the .sh
bash    read(255, "#!/usr/bin/env bash…")  # reads the script
bash    pipe2([3, 4], 0) = 0              # for the $(…) substitution
bash    clone(...) = <subshell pid>        # fork for $(cd "$(dirname…)" && pwd)
bash    read(3 <unfinished ...>            # ← blocks here, forever
```

No `write(1, …)` ever happens, so genmon never receives `<txt>`/`<bar>` and
falls back to its placeholder. The inner `$(dirname …)` compounds it: each
`$(...)` is another fork that also stalls.

## Fix

Point genmon straight at the interpreter. No shell, no substitution, no fork:

```
/usr/bin/python3 /home/<you>/src/xfce-zai-limits/zai_limits.py --format genmon
```

With this, `strace` shows the clean chain:

```
genmon  execve("/usr/bin/python3", […, "zai_limits.py", "--format", "genmon"]) = 0
python  write(1, "<txt>…75%…</txt>\n<bar>75</bar>…", 853) = 853
python  +++ exited with 0 +++
genmon  read(10, "09b24\">75% …") = …        # genmon receives the output
```

## Notes for contributors

- This is **not** a bug in this project — it's an interaction between
  `xfce4-genmon-plugin`'s spawn environment and bash command substitution.
  Filed here so the next person doesn't lose an hour to it.
- The `bin/zai-limits-genmon.sh` file is kept as an optional convenience for
  non-genmon use (cron, manual runs, other panels). For genmon specifically,
  use the direct `python3` command.
- If you genuinely need a shell wrapper under genmon, avoid `$(...)` entirely;
  hardcode absolute paths and `exec` immediately:

  ```bash
  #!/bin/bash
  exec /usr/bin/python3 /absolute/path/to/zai_limits.py --format genmon "$@"
  ```
