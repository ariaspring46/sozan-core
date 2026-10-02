---
name: sozan-verify-and-pr
display-name: Sozan Verify & PR
description: Verification commands, self-review checklist, and append-only report and PR discipline for Sozan-Core roles.
---

Use before committing, before a PR, and when writing a report entry.

## Verify (in order)
1. Tests of your changed modules first (harness §11 has the exact commands), then the full backend and/or frontend suite once before the PR.
2. `python3 tools/agent_context/build.py --check` — ownership, contracts, and locks still valid.
3. Frontend roles only: `python3 tools/ui_check.py` must print `ui_check: 0 problem(s)`, then `cd frontend && npm ci --no-audit --no-fund >/dev/null && npm run build`.
4. Show only the tail of test output (`| tail -5`).

## Self-review before the PR
`git diff --stat`, then `git diff -- <file>` per file. Check:
- no secret, token, OTP, or env value anywhere (never `cat` an env file; `grep -c '^NAME=' file` to check existence)
- no debug print / `console.log`
- no changed contract in §10 without consumer notification (see the `sozan-contract-change` skill)
- no file outside §6 edited
- no real customer message, SMS, call, payment, post, or publish in tests — use the test tenant, mocks, the dry gateway (`edge_dry`), or simulators

## PR rules
- A reviewer (ناظر) merges; you never merge your own PR (squash into `main`).
- `docs/agents/` regenerated and committed in the same PR as any contract or route change.
- `CHANGELOG.md`: append one bullet under today's dated heading; never edit other bullets.

## Report files (append only)
```
cat >> <your-report-file> <<'EOF'
## <YYYY-MM-DD HH:MM Tehran> — <one line>
<what changed, why, tail of verify output>
EOF
```
- A request to another role goes in the **receiver's** file, headed `## <YOU> → <ROLE>: <topic>`.
- Read reports with `tail -n 60` only. Never rewrite, truncate, or reorder.
