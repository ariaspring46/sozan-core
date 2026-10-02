---
name: sozan-frontend
display-name: Sozan Frontend
description: Frontend work in Sozan-Core: RTL Persian UI, the U1-U7 rules enforced by tools/ui_check.py, npm deps owned by role U.
---

Use for any change under `frontend/`.

## Hard rules (checked by `python3 tools/ui_check.py`; must print 0 problems)
- U1: `frontend/app/layout.tsx` renders `<html lang="fa" dir="rtl">`.
- U2: every `<img>` has an `alt` attribute (empty string for decoration).
- U3: every `<a target="_blank">` has `rel` with `noopener` or `noreferrer`.
- U4: no `console.log` / `debugger` in `app/`, `components/`, `lib/`.
- U5: hex colours only in the design-token files; use Tailwind tokens elsewhere.
- U6: the API host appears only in `lib/api.ts` and `lib/site-host.ts`; pages call `api()` / `getApiBase()`.
- U7: an icon-only `<button>` (no text child) has `aria-label` or `title`.

## Conventions
- Persian user-facing text, RTL layout; match the existing component style, naming, and comment density.
- New npm dependency: request from role U (owner of `frontend/package.json` and `package-lock.json`) with the reason and pinned version. If the network blocks `npm ci`, do not edit the lockfile — say so in your report and rely on CI.
- Backend endpoints you call: routes are listed in your harness §7; ask the owner role for the response shape, do not read their files.

## Design work
For visual or UX questions (layout, hierarchy, color, motion, component design), trigger the Bionic skills `ui-ux-pro-max` (searchable design data) and `impeccable` (frontend critique and optimization) before making the change, then still satisfy U1–U7.
