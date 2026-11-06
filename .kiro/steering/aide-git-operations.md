---
inclusion: always
---

# Git Operations — Use Git Bash Only

All git operations in this workspace MUST be executed through Git Bash, never
through PowerShell or cmd directly. This applies to every team member and
every machine, regardless of Windows username or install location.

## Always discover the Git Bash path first

Before running ANY git command, discover the current Git Bash location on the
machine. Do NOT assume a hardcoded path — installs move between machines and
users, so always search first and use whatever the search resolves to.

Run this discovery step (PowerShell) and use the first path it returns:

```
$candidates = @(
  "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe",
  "$env:ProgramFiles\Git\bin\bash.exe",
  "${env:ProgramFiles(x86)}\Git\bin\bash.exe"
)
$found = $candidates | Where-Object { Test-Path $_ }
if (-not $found) { $found = (where.exe bash 2>$null | Where-Object { $_ -like '*Git*bash.exe' }) }
$found | Select-Object -First 1
```

Notes on discovery:
- Prefer a path under a `Git\bin\bash.exe` (MINGW64 Git Bash). Ignore
  `C:\Windows\System32\bash.exe` and the WindowsApps `bash.exe` (those are WSL,
  not Git Bash).
- If discovery returns nothing, tell the user Git Bash was not found and ask
  how they'd like to proceed — do not silently fall back to PowerShell git.
- Never hardcode a specific user's profile path (e.g. `C:\Users\<name>\...`).
  Every teammate's Git Bash lives under their own `%LOCALAPPDATA%` or
  `%ProgramFiles%`, which the discovery step above already resolves.

## How to run git commands

Invoke git through the discovered Git Bash executable, using the current
workspace root — never a path hardcoded to one person's checkout location.

```
& "<discovered-bash-path>" -c "cd '<workspace-root-as-posix-path>' && <git command>"
```

Notes:
- Derive `<workspace-root-as-posix-path>` from the actual current workspace
  folder (convert the Windows path to POSIX style, e.g. `C:\Users\alice\repo`
  becomes `/c/Users/alice/repo`). Do not reuse a path seen in an example or a
  previous session.
- Use POSIX-style paths inside the `bash -c "..."` string, not Windows
  `C:\...` paths.
- Chain related git steps with `&&` inside the single bash invocation.
- Let bash expand its own variables — do not rely on PowerShell to expand
  anything inside the quoted bash script.

## Rules
- Do NOT run `git ...` directly in PowerShell or cmd for this workspace.
- All git commands (status, fetch, log, diff, add, commit, push, pull, branch,
  merge, rebase, etc.) go through the discovered Git Bash invocation above.
- Continue to honor the existing git-safety constraints: never modify git
  config, avoid destructive commands (force push, reset --hard, clean -fd,
  branch -D) unless explicitly requested, prefer staging specific files over
  `git add .`, and only create commits when explicitly asked.
- Non-git shell commands (build, test, package managers, file operations) are
  not affected by this rule and may run in the default shell.
