#!/bin/bash
set -e

if [ -z "$1" ]; then
  echo "Usage: $0 <iterations>"
  exit 1
fi

# Anchor to the repo root regardless of where this was invoked from: the sandbox
# mounts '.' (the whole repo) and the agent prompt references repo-root paths
# (@CLAUDE.md, @docs/, @progress.txt), so CWD must be the toplevel. .env is
# gitignored and lives beside this script (ralph/), so read it by SCRIPT_DIR.
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
ENV_FILE="$SCRIPT_DIR/.env"

# Dependent issues build on one another through the shared (mounted) working
# tree, so run them all on ONE branch — never main.
if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "main" ]; then
  git checkout -B ralph/run
  echo "On branch ralph/run (was main) — Ralph will commit here."
fi

# The loop reads GitHub issues, so gh must be authenticated INSIDE the sandbox.
# `docker sandbox run` can't pass env, so persist the token from .env
# into the sandbox's shell-init (/etc/sandbox-persistent.sh — sourced by login
# shells and, via BASH_ENV, by non-interactive bash too). Idempotent: re-running
# heals a reset/recreated sandbox.
SANDBOX="claude-$(basename "$PWD")"
if [ -f "$ENV_FILE" ]; then
  docker sandbox create claude . >/dev/null 2>&1 || true   # no-op if it exists
  docker sandbox exec --env-file "$ENV_FILE" "$SANDBOX" bash -c '
    if [ -n "$GH_TOKEN" ] && ! grep -q "export GH_TOKEN=" /etc/sandbox-persistent.sh 2>/dev/null; then
      printf "export GH_TOKEN=%s\n" "$GH_TOKEN" >> /etc/sandbox-persistent.sh
    fi' || echo "WARN: could not write GH_TOKEN into the sandbox."
  if docker sandbox exec "$SANDBOX" bash -c 'gh auth status >/dev/null 2>&1'; then
    echo "sandbox gh: authenticated."
  else
    echo "WARN: sandbox gh still NOT authenticated — the loop will stall at step 1."
  fi
else
  echo "WARN: .env missing — sandbox gh will be unauthenticated."
fi

# Claude auth for the `docker sandbox run` loop. Unlike gh (used in the agent's
# bash tool-calls, which DO source the shell-init above), Claude's own startup
# reads neither .env nor /etc/sandbox-persistent.sh, and `docker
# sandbox run` has no --env flag — so Claude authenticates SOLELY from
# ~/.claude/.credentials.json INSIDE the sandbox. Materialise that from the
# long-lived CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`) in .env.
# Idempotent: re-running heals a reset/recreated sandbox (otherwise the agent
# exits 1 with "Not logged in" the moment the sandbox is recreated).
if [ -f "$ENV_FILE" ]; then
  CLAUDE_TOKEN=$(grep -m1 '^CLAUDE_CODE_OAUTH_TOKEN=' "$ENV_FILE")
  CLAUDE_TOKEN=${CLAUDE_TOKEN#CLAUDE_CODE_OAUTH_TOKEN=}
  if [ -n "$CLAUDE_TOKEN" ]; then
    CLAUDE_CREDS=$(printf '{"claudeAiOauth":{"accessToken":"%s","refreshToken":"","expiresAt":1900000000000,"scopes":["user:inference","user:profile","user:sessions:claude_code"],"subscriptionType":"max"}}' "$CLAUDE_TOKEN" | base64 -w0)
    if docker sandbox exec "$SANDBOX" bash -c \
      'mkdir -p ~/.claude && printf "%s" "$1" | base64 -d > ~/.claude/.credentials.json && chmod 600 ~/.claude/.credentials.json' bash "$CLAUDE_CREDS"; then
      echo "sandbox claude: credentials written."
    else
      echo "WARN: could not write Claude credentials into the sandbox — the loop will exit 1 at the agent."
    fi
  else
    echo "WARN: CLAUDE_CODE_OAUTH_TOKEN missing from .env — sandbox claude will be unauthenticated."
  fi
fi

for ((i=1; i<=$1; i++)); do
  result=$(docker sandbox run claude . -- --dangerously-skip-permissions -p "/implement @CLAUDE.md @docs/plan-v2.md @progress.txt \
  You are working the kicad-unwn-plugins issue tracker (unwndevices/kicad-unwn-plugins) autonomously. \
  The implementation flow above — TDD at agreed seams, run typechecking and the pytest suite, /code-review, \
  then commit — governs step 3; the steps below wrap it with issue selection, logging, and closing. \
  1. PICK (use '-R unwndevices/kicad-unwn-plugins' on EVERY gh command): run 'gh issue list -R unwndevices/kicad-unwn-plugins --state open --label ready-for-agent'; choose the LOWEST-numbered open issue whose 'Blocked by' issues are ALL CLOSED. Read it with 'gh issue view <n> -R unwndevices/kicad-unwn-plugins --json number,title,body,labels,comments'. If (and only if) none are eligible, output exactly <promise>COMPLETE</promise> alone on the final line, with nothing after it. \
  2. GROUND: read that issue fully, plus CLAUDE.md and the docs under docs/ it references, and 'git log -8 --oneline'. \
  3. IMPLEMENT exactly that issue's scope via the flow above. Do nothing beyond the acceptance criteria. Commit at meaningful checkpoints, conventional-commit style, with 'Refs #<n>' in the body, each message ending with the line 'Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>'. \
  4. LOG: append a dated entry (newest first) to progress.txt. \
  5. MARK DONE so the next iteration can proceed: comment a short summary on the issue and CLOSE it (this unblocks its dependents). \
  6. Work a SINGLE issue this iteration.")

  echo "$result"

  # Done ONLY when the sentinel stands alone on a line — so an agent merely
  # quoting it in prose (e.g. "I am not emitting <promise>COMPLETE</promise>")
  # cannot end the loop prematurely.
  if printf '%s\n' "$result" | grep -qE '^[[:space:]]*<promise>COMPLETE</promise>[[:space:]]*$'; then
    echo "All eligible ready-for-agent issues complete after $i iteration(s)."
    exit 0
  fi
done
