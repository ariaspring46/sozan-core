---
name: sozan-contract-change
display-name: Sozan Contract Change
description: Checklist for changing a cross-role signature in Sozan-Core: regenerate docs/agents with build.py and notify every consumer role.
---

Use this skill whenever a task changes anything another role depends on: a function or class signature listed in `docs/agents/contracts.json`, an import across roles, an API route, or a config setting.

## Before the edit
1. Find the contract in `docs/agents/contracts.json`: note `owner`, `users`, and the current `signature` and `since`.
2. Prefer non-breaking changes: add parameters with defaults, keep old call shapes working where possible.
3. If the change requires a file you do not own, it is a request in that role's report file, never an edit (harness §2).

## The change
4. Edit the code.
5. Run `python3 tools/agent_context/build.py`. It regenerates `docs/agents/**`, stamps the `since` date on changed contracts, and prints `اعلام قرارداد` lines naming every consumer role (with its report file) that must be told.
6. For each named role, append a request to its report file (report file per role: table in `docs/agents/README.md`):

   ```
   ## <YOU> → <ROLE>: contract change <file.py::name>
   <old signature> → <new signature> — breaking? yes/no. What you must change in your calls.
   ```

7. If a system flow (F1–F10) changes shape, update the steps in `tools/agent_context/roles.json` (owner's file) and regenerate.

## Done means
- `python3 tools/agent_context/build.py --check` passes.
- `docs/agents/` is committed in the same PR as the code change (CI diffs the contract change).
- Every consumer role has an entry in its report file.
- `CHANGELOG.md`: one bullet under today's dated heading (`head -20` to find it); never edit other bullets.
