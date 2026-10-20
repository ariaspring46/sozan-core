---
name: sozan-review
display-name: Sozan Review & Merge
description: Reviewer (role R) protocol for Sozan-Core pull requests: scope, tests, contracts, secrets, gates, green CI, then squash merge.
---

Use when you are role **R** and a `## <ROLE> → R: review <PR>` request is in `talk-r.md`, or the owner asks for a review.
Your full harness is `docs/agents/R.md`; this skill is the short form.

## Per PR
```
gh pr view <N> --json title,author,headRefName,files,body | head -80
gh pr diff <N> --name-only        # every file must be in the author's docs/agents/<ROLE>.md §6
gh pr diff <N> | head -400
gh pr checks <N>                  # all green on the head commit
```

## Checklist (all must hold)
1. Scope: files belong to the author's role (regenerated `docs/agents/` and one `CHANGELOG.md` bullet excepted).
2. A test covers the change and fails on the old code; no test skipped, deleted or loosened.
3. A changed contract in `docs/agents/contracts.json` has an acknowledged request in each consumer role's report file.
4. No token, key, OTP, `.env` value, phone number or customer text in the diff, PR body or commit message.
5. Nothing real in tests or scripts: no message, SMS, call, payment, post, publish or live-shop rebuild.
6. The author's merge gates hold, with evidence (battery line, harness verdict from Q, screenshots).
7. One topic; the diff matches the PR text.

## Verdict
- Changes needed: `gh pr review <N> --request-changes -b '<file:line — exact change>'`, and the same list as `## R → <ROLE>: PR <N>` in the author's report file. Never push to their branch.
- Approved: `gh pr review <N> --approve`, then `gh pr merge <N> --squash` only when every check is green. New commits after your review are reviewed first.
- After merging: one entry in `talk-r.md` (PR, role, merged commit, deploy needed?). A deploy is a request to X5; X5 deploys only with the owner's go.

## Never
- Merge a red or pending PR, or bypass a required check.
- Print, commit or paste the GitHub token.
- Deploy, restart hub services, or edit product code.
