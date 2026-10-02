---
name: sozan-session-boot
display-name: Sozan Session Boot
description: Session-start protocol for Sozan-Core programmer sessions: 5-tool-call budget, load only the role harness, restate task before editing.
---

Use at the start of every programmer-agent session in Sozan-Core.

## First 5 tool calls (maximum), in this order
```
git status --short | head -20          # uncommitted work from someone else? leave it alone
git log --oneline -5
git fetch -q origin main && git log --oneline HEAD..origin/main | head
tail -n 60 <your report file>          # requests addressed to you; never read the whole file
```
Your report file is in the table in `docs/agents/README.md`.

## Then, before touching any file
1. Read `docs/agents/<ROLE>.md` once — it is the complete harness. Never read other docs, plans, or report files unless a step in it or the task tells you to.
2. Restate the task in one sentence.
3. List the 1–3 files from §6 you expect to change, and which flow in §16 they belong to.
4. If the task needs a file you do not own: go to §13 now (request in the owner's report file). Do not start.

## Context discipline (harness §5, non-negotiable)
- Never read: the never-read list in the harness; report files only via `tail -n 60`, append only.
- Locate with `grep -n` inside your files; read ranges with `sed -n 'a,bp' file`, not whole files above 5k.
- Cut tool output: `| tail -5`, `| head -40`, `git diff --stat` before `git diff`, `--quiet` flags.
- Signatures of other roles' code are in §7 (with their `changed` date); do not open their files.
- Conversation getting long: finish the current step, commit, append a short report, continue in a new session from these steps.
