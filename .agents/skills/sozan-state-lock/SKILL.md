---
name: sozan-state-lock
display-name: Sozan State Lock
description: Correct read/write/lock patterns for tenant JSON state files in Sozan-Core; build.py --check fails on unlocked multi-writer files.
---

Use whenever touching files under `STATE_DIR` (tenant JSON state) or any `read_json` / `write_json` / `update_json` call.

## Rules
1. Each runtime state file has one writer role unless the README table says otherwise. Multi-writer files (`shop.json`, `campaign-ids.json`, `channel-scan.json`, `channels.json`, `inbox.json`, `pay-orders.json`, `support-tickets.json`, `voice.json`) are listed in `docs/agents/README.md` §Shared files.
2. Every write to a multi-writer file must be:
   - `state_store.update_json(name, mutate, default, lock=...)` — preferred; read-modify-write under `tenant_file_lock`, or
   - an explicit `with tenant_file_lock(name):` around the read-modify-write.

   A bare `write_json` to a multi-writer file is a CI failure: `build.py --check` reports `قفل: ...`.
3. `shared=True` / `shared_lock()` is for the few global (non-tenant) files; `write_json(..., shared=True)` takes the lock automatically.
4. Never delete, rewrite, or migrate a real seller's files under `STATE_DIR`. Tests always run with a temporary `STATE_DIR`.
5. New state file: declare its writer in `tools/agent_context/roles.json` (ask the owner), run `python3 tools/agent_context/build.py`, commit `docs/agents/`.

## Correct vs wrong
```python
# wrong: unlocked write to a multi-writer file
data = read_json("shop.json", {})
data["x"] = 1
write_json("shop.json", data)

# right: update_json takes the lock for you
update_json("shop.json", lambda d: d.__setitem__("x", 1), {}, lock="shop")

# right: explicit lock when you need several keys
with tenant_file_lock("shop"):
    d = read_json("shop.json", {})
    ...
    write_json("shop.json", d)
```
Verify the exact signatures in `backend/app/state_store.py` via the harness §7 listing (it carries the `changed` date) before writing code.
