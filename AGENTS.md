# Sozan — agent entry point

This repo is worked on by 13 roles: X1 (router brain), X6 (chat UI), X2, X3, X4 (shop build and edit), X5 (platform and deploy), X7 (accounts, plans and billing), Y, Z, C, U (UI/UX), Q (evaluation) and R (reviewer, merges). Each role has one complete harness: `docs/agents/<ROLE>.md` (rules, owned files, the signatures it needs from other roles, exact test/git/report commands).

1. If your first message names your role, read only `docs/agents/<ROLE>.md` and follow it exactly. Do not explore the repo, and do not read other docs, plans or `talk*.md` files unless that file tells you to.
2. If no role is named, ask which role you are before reading or editing anything. The role table is in `docs/agents/README.md`.
3. Never read: `.zcode/`, `.cursor/`, `backend/app/data/router_intent_vectors.json`, `voice-gateway/sales-*.jsonl`, `frontend/package-lock.json`, `talk.md`.
4. The first message for each role is in `docs/agents/onboarding-messages.md`. Pull requests go to R for review (`talk-r.md`); nobody merges their own.

## Cursor Cloud specific instructions

Local API and panel use apt PostgreSQL 16 and Redis (`postgresql`, `redis-server`), not Docker. Python deps live in `backend/.venv` (`pip install -r backend/requirements.txt`). Frontend deps are `npm ci` in `frontend`.

- `uvicorn` exits unless `JWT_SECRET` is at least 32 characters and is not the sample value in `.env.example`.
- `OTP_DEV=true` boots only with `PAYMENTS_ENABLED=0`. That pair is what returns `dev_code` from `POST /auth/otp/send`.
- API: `backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000`. Panel: `npm run dev` in `frontend` (port 3000). Open `/login`. A new phone continues at `/onboard`.
- `09120000991` is the lab phone and does not return a login code while lab login is active.
- Backend tests, from `backend` with the venv active: `python -m unittest discover -s app/services -p '*_test.py'`. Two shop-edit tests call `docker` and fail without a shop container runtime. The rest of that suite does not need Docker.
