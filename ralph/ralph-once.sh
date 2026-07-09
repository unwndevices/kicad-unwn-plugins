#!/bin/bash
# Ralph — single iteration, on the host (assisted: a human is watching).
# Works the next ready-for-agent GitHub issue whose blockers are all closed,
# commits on a branch, and STOPS for you to review and open the PR. For the
# autonomous looped variant (sandboxed; closes issues to flow through their
# dependencies) see afk-ralph.sh.

claude --dangerously-skip-permissions "/implement @CLAUDE.md @docs/plan-v2.md @progress.txt \
You are working the kicad-unwn-plugins issue tracker (unwndevices/kicad-unwn-plugins) autonomously. \
The implementation flow above — TDD at agreed seams, run typechecking and the pytest suite, /code-review, \
then commit — governs step 4; the steps below wrap it with issue selection and logging. \
1. PICK (use '-R unwndevices/kicad-unwn-plugins' on every gh command): run 'gh issue list -R unwndevices/kicad-unwn-plugins --state open --label ready-for-agent'; choose the LOWEST-numbered open issue whose 'Blocked by' issues are ALL closed. Read it with 'gh issue view <n> -R unwndevices/kicad-unwn-plugins --json number,title,body,labels,comments'. If none are eligible, say so and stop. \
2. GROUND: read that issue fully, plus CLAUDE.md and the docs under docs/ it references, and 'git log -8 --oneline'. \
3. BRANCH: never commit to main — 'git checkout -b issue-<n>-<slug>'. \
4. IMPLEMENT exactly that issue's scope via the flow above. Do nothing beyond the acceptance criteria. Commit at meaningful checkpoints, conventional-commit style, with 'Refs #<n>' in the body, each message ending with the line 'Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>'. \
5. LOG: append a dated entry (newest first) to progress.txt describing what you did. \
6. ONE issue only. Stop after committing and leave the issue OPEN for human review — do not close or merge."
