# AFTERIMAGE

**Every AI action leaves a trace. Every incident deserves an answer.**

AFTERIMAGE is a hackathon prototype for **AI-agent incident forensics, security and recovery**. It records every tool call a demo agent makes, enforces resource-level permissions in a server-side policy gateway, reconstructs suspicious activity from recorded evidence, recommends a corrective policy, and proves the fix works by **replaying the attack** in a fresh workspace.

```
Observe → Enforce → Investigate → Remediate → Replay → Verify
```

Everything runs locally. No LLM, cloud account or API key is required: the demo agent is deterministic, and all data is synthetic.

> **Honesty notes.** AFTERIMAGE reconstructs the *observable* event chain (tool calls, policy decisions, timestamps, provenance links). It does not read a model's reasoning and does not claim causality as fact — trigger attribution is labelled *inferred*. The attack is a **controlled simulation**: the demo agent is deliberately configured to obey an instruction hidden in a synthetic document.

---

## Quick start

Requirements: **Python 3.11+** and **Node.js 20+** (tested with Python 3.13 and Node 22).

### 1. Backend (FastAPI, port 8000)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn afterimage.main:create_app --factory --reload --port 8000
```

On first start the backend creates `backend/data/` (SQLite DB, synthetic workspaces, recovery vault) and seeds the baseline policy. API docs: <http://127.0.0.1:8000/docs>.

### 2. Frontend (React + Vite, port 5173)

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to `http://127.0.0.1:8000` (override with `AFTERIMAGE_API_URL`).

### 3. Tests

```bash
# Backend: 51 pytest tests
cd backend && .venv/bin/pytest -q

# Frontend unit tests (Vitest + React Testing Library) and type check
cd frontend && npm test && npm run typecheck

# Browser end-to-end (Playwright). Starts its own backend on :8001 and frontend on :5174
# with a throw-away data directory, so it never touches your dev database.
cd frontend && npx playwright install chromium   # once, if you don't have a Playwright browser
npm run test:e2e
# Optional: PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome to use an existing Chromium,
#           AFTERIMAGE_PYTHON=/path/to/python if your venv lives elsewhere.
```

### 4. Reset the demo

In the UI: **Settings → Reset demo…** (type `RESET DEMO`) restores the baseline policy and vault files and removes run workspaces — **evidence is kept**. **Archive & reset…** (type `ARCHIVE AND RESET`) copies the database to `backend/data/archives/` and starts empty.

From the command line:

```bash
curl -X POST localhost:8000/api/settings/reset -H 'Content-Type: application/json' \
     -d '{"mode":"demo","confirm_text":"RESET DEMO"}'
# or, with the backend stopped, delete everything:  rm -rf backend/data
```

---

## The demo (≈4 minutes)

See [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) for exact clicks, expected results and talking points. Summary:

| Step | Where | What happens |
|---|---|---|
| A. Safe run | Overview → **Run Safe Scenario** | Agent reads README/src/docs, writes `out/summary.md`. All requests allowed, no incident. It notices instruction-like text in a doc and ignores it. |
| B. Attack | Overview → **Simulate Attack** | Agent obeys the injected text in `docs/integration_notes.md`, requests `secret.txt` and `../host-credentials.txt`. Gateway denies both (`POL-DENY-SECRET-FILE`, `AI-BOUNDARY-001`) before any read. Task still completes. Incident opened: severity *high*, confidence *high*, status *contained*. |
| C. Investigate | **Investigate incident** | Summary, trigger input, attempted tool, rule, evidence graph (built from stored events), timeline, observed vs inferred findings, uncertainty. |
| D. Remediate | **Review policy change** | Preview least-privilege read scope + deny secret-like file class. See old vs new rules and impact on the scenario's requests. Confirm to apply as v2. |
| E. Replay | **Replay to verify** → **Run replay** | Same scenario, fresh workspace, policy v2. 5 assertions pass → **Verified**. Report saved. |
| E′. Regression | Policies → *Disable write_file* → replay | Attack blocked but summary can't be written → **Not verified — regression**. |
| F. Recovery | Recovery Vault → **Simulate unauthorized edit** → **Restore** | Auto-snapshot, simulated edit, restore, SHA-256 verified. |

---

## Repository layout

```
backend/
  afterimage/
    config.py         settings from env vars, validated at startup
    db.py             SQLite schema (append-only events table enforced by triggers)
    common.py         IDs, UTC timestamps, hashing, typed errors
    workspace.py      synthetic project, per-run workspace, safe path resolution
    policy.py         deterministic policy engine + catalogue of safe policy changes
    policy_store.py   versioned policies, preview/impact, apply, revert
    gateway.py        the only path from agent to files: request → decision → result events
    agent.py          deterministic demo agent (benign / deliberately susceptible)
    recorder.py       structured, hash-chained event recorder + chain verification
    runs.py           scenario execution and policy-independent run evaluation
    investigator.py   incident detection, evidence report, NetworkX evidence graph
    replay.py         replay engine, assertions, run diff, saved reports
    recovery.py       snapshot vault with content hashes and verified restore
    main.py           FastAPI app, REST endpoints, idempotency, CORS, resets
  tests/              pytest suite (51 tests)
frontend/
  src/api.ts          typed API client
  src/pages/          Overview, Incidents, Investigation, Replay Lab, Policies,
                      Recovery Vault, Event Explorer, Settings
  src/components/     layout, UI kit, SVG evidence graph
  e2e/                Playwright end-to-end tests
docs/                 architecture, API, security, demo script
```

## Documentation

- [Architecture & module guide](docs/ARCHITECTURE.md) — how the pieces fit, explained for beginners
- [API reference](docs/API.md)
- [Security model & limitations](docs/SECURITY.md)
- [Demo script](docs/DEMO_SCRIPT.md)

## Configuration

All settings are optional; see [`.env.example`](.env.example). Put them in `backend/.env` or export them.

| Variable | Default | Meaning |
|---|---|---|
| `AFTERIMAGE_DATA_DIR` | `backend/data` | DB, workspaces, vault, archives |
| `AFTERIMAGE_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins (no wildcards) |
| `AFTERIMAGE_MAX_READ_BYTES` | `65536` | Max bytes the agent may read per file |

Invalid values stop the backend at startup with a clear validation error.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI says *Backend unreachable* | Start the backend on port 8000, or set `AFTERIMAGE_API_URL` before `npm run dev`. |
| `Port 5173 is already in use` | Stop the other Vite process (the port is strict so the CORS origin stays correct). |
| `ValidationError` on backend start | Check `AFTERIMAGE_*` variables — e.g. CORS origins must be full `http(s)://host:port` without wildcard or trailing slash. |
| 409 *policy changed since preview* | Another tab changed the policy. Refresh Policies and preview again. |
| 409 *another run is already in progress* | Wait for the current run to finish (runs take well under a second). |
| Playwright cannot find a browser | `npx playwright install chromium`, or set `PLAYWRIGHT_CHROMIUM_PATH`. |
| Want a clean slate | Settings → Archive & reset, or stop the backend and delete `backend/data/`. |

## Known limitations

- The agent is a scripted simulation, not an LLM; the optional model integration is not implemented.
- Cloud sync (Supabase) is **not implemented**; the UI states this. All data stays local.
- No user authentication: this is a single-user local prototype. Do not expose it on a network.
- The hash chain is tamper-*evident* for casual row edits, not tamper-proof (see `docs/SECURITY.md`).
- Exposure detection covers content that passes through the instrumented gateway only.
- File recovery restores bytes only; it cannot undo external side effects.
