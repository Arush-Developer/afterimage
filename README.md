# AFTERIMAGE

**Every AI action leaves a trace. Every incident deserves an answer.**

AFTERIMAGE is a hackathon prototype for **AI-agent incident forensics, security and recovery**. It records every tool call an agent makes (a deterministic scripted agent, or a **real LLM agent**), enforces resource-level permissions in a server-side policy gateway, reconstructs suspicious activity from recorded evidence, recommends a corrective policy, and proves the fix works by **replaying the attack** in a fresh workspace. A **prompt-injection experiment** runs the same model and task with enforcement off (baseline) and on (protected) and reports what actually happened.

```
Observe → Enforce → Investigate → Remediate → Replay → Verify
```

Everything runs locally and all data is synthetic. **No API key is needed** for the scripted demo or for the *simulated* LLM-style agent (a rule-based stand-in, always labelled "simulated"). Set `ANTHROPIC_API_KEY` (or run a local Ollama server) to use a real model.

> **Honesty notes.** AFTERIMAGE reconstructs the *observable* event chain (tool calls, policy decisions, timestamps, provenance links). It does not read a model's reasoning and does not claim causality as fact — trigger attribution is labelled *inferred*. The scripted attack is a **controlled simulation**: that agent is deliberately configured to obey an instruction hidden in a synthetic document. With a real model, whether it follows the injected instruction is measured, never assumed — the experiment reports "attack not reproduced" when the baseline model ignores it.

---

## Quick start

Requirements: **Python 3.12+** (the pinned `networkx==3.7` requires it) and **Node.js 22.12+** (required by Vitest 5; tested with Python 3.13 and Node 22). Tested on Linux; macOS and Windows have not been tested by the project.

> **New here?** Read the **[User Manual](docs/USER_MANUAL.md)**: installation on macOS and Windows, every page of the dashboard, a first-time tutorial, the demo script, troubleshooting and limitations. Teammates in a hurry: **[Quick start](docs/QUICK_START.md)**.

### 1. Backend (FastAPI, port 8000)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn afterimage.main:create_app --factory --reload --port 8000
```

On first start the backend creates `backend/data/` (SQLite DB, synthetic workspaces, recovery vault) and seeds the baseline policy. API docs: <http://127.0.0.1:8000/docs>.

#### Optional: a real LLM provider

```bash
# Google Gemini (a free-tier key from Google AI Studio works if the model is available to it)
export GEMINI_API_KEY=...                      # in the shell that starts the backend
AFTERIMAGE_LLM_PROVIDER=gemini uvicorn afterimage.main:create_app --factory --port 8000
#   default model gemini-2.5-flash; override with AFTERIMAGE_GEMINI_MODEL=<model>

# Anthropic Claude (paid API; default model claude-opus-5-5)
export ANTHROPIC_API_KEY=sk-ant-...
uvicorn afterimage.main:create_app --factory --reload --port 8000

# a local Ollama model (inference stays on this machine)
ollama pull llama3.1 && ollama serve
AFTERIMAGE_LLM_PROVIDER=ollama uvicorn afterimage.main:create_app --factory --port 8000
#   override with AFTERIMAGE_OLLAMA_MODEL=<tool-capable model>, AFTERIMAGE_OLLAMA_HOST=http://127.0.0.1:<port>

# no key at all: make the simulated (non-LLM) agent the default
AFTERIMAGE_LLM_PROVIDER=simulated uvicorn afterimage.main:create_app --factory --port 8000
```

Several providers can be configured at once; you pick one per experiment in the **Injection Lab**. **Settings → LLM agent configuration** shows each provider's status, and its **Check** button verifies three things without generating content:
- the key is accepted
- the model is available to that key
- for Ollama, whether the model supports tool calling

Credential values are never shown, and AFTERIMAGE **never falls back** from one provider to another.

**Usage limits.** One experiment trial makes up to 2 × 12 model calls. Gemini free-tier limits are per Google project and per model, and they change over time; per-minute limits are low.
- A per-minute **rate limit** (HTTP 429) is retried a bounded number of times, honouring Google's retry delay.
- A **daily quota exhausted** error is not retried. The experiment stops early and reports **inconclusive**, with guidance in the UI.

### 2. Frontend (React + Vite, port 5173)

```bash
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` to `http://127.0.0.1:8000` (override with `AFTERIMAGE_API_URL`).

### 3. Tests

```bash
# Backend: 137 pytest tests (+6 optional live-provider tests, skipped by default).
# No network or API key needed: local mock HTTP servers stand in for the Anthropic and
# Gemini APIs (exercising the real official SDKs) and for a local Ollama server.
cd backend && .venv/bin/pytest -q

# Optional live smoke tests, one opt-in flag per provider (real requests; may use quota or money):
AFTERIMAGE_RUN_REAL_GEMINI=1 GEMINI_API_KEY=... .venv/bin/pytest tests/test_real_provider_smoke.py -k gemini -s
AFTERIMAGE_RUN_REAL_OLLAMA=1 AFTERIMAGE_OLLAMA_MODEL=llama3.1 .venv/bin/pytest tests/test_real_provider_smoke.py -k ollama -s
AFTERIMAGE_RUN_REAL_LLM=1 ANTHROPIC_API_KEY=sk-ant-... .venv/bin/pytest tests/test_real_provider_smoke.py -k anthropic -s

# Frontend unit tests (Vitest + React Testing Library), type check and production build
cd frontend && npm test && npm run typecheck && npm run build

# Browser end-to-end (Playwright, 6 tests incl. Injection Lab, LLM replay, Gemini/Ollama
# provider flows and phone-width layout). Starts its own backend on :8001, frontend on :5174,
# and a mock Gemini/Ollama API on :8099 (e2e/mock_providers.py), with a throw-away data
# directory. No key or local model needed.
cd frontend && npx playwright install chromium   # once, if you don't have a Playwright browser
npm run test:e2e
# Optional: PLAYWRIGHT_CHROMIUM_PATH=/path/to/chrome to use an existing Chromium,
#           AFTERIMAGE_PYTHON=/path/to/python if your venv lives elsewhere.
```

### 4. Reset the Demo

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
| G. Injection experiment | **Injection Lab** → pick provider/model → **Run experiment** | Same task + model, enforcement **off** (baseline) vs **on** (protected), repeated trials. Reports whether the restricted file was requested, whether its content was returned, whether the fake secret leaked, and whether the task succeeded. Says "attack not reproduced" when it wasn't. |
| H. LLM replay | Replay Lab → pick an **LLM** baseline run → trials → **Run replay** | N model trials + 1 deterministic scripted control under the active policy; verified / regression / failed / inconclusive. |
| I. AI explanation | Investigation → **AI-assisted explanation → Generate** (real provider only) | LLM explanation from persisted evidence. Statements citing unknown or no event IDs are rejected. |

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
    agent.py          deterministic scripted agent (benign / deliberately susceptible)
    llm_agent.py      LLM agent: bounded tool loop, strict tool-call validation, gateway-only execution
    providers/        LLM provider abstraction: Anthropic (anthropic SDK), Gemini (google-genai SDK),
                      Ollama (local HTTP), simulated/mock; no cross-provider fallback
    experiment.py     baseline (enforcement off) vs protected prompt-injection experiment
    explainer.py      AI-assisted incident explanation, validated against persisted event IDs
    recorder.py       structured, hash-chained event recorder + chain verification
    runs.py           run execution (scripted or LLM, protected or baseline) + policy-independent evaluation
    investigator.py   incident detection, evidence report, NetworkX evidence graph
    replay.py         replay engine (scripted, or LLM trials + deterministic control), assertions, diffs
    recovery.py       snapshot vault with content hashes and verified restore
    main.py           FastAPI app, REST endpoints, idempotency, CORS, resets
  tests/              pytest suite (137 tests + 6 optional live-provider tests)
frontend/
  src/api.ts          typed API client
  src/pages/          Overview, Incidents, Investigation, Replay Lab, Injection Lab,
                      Policies, Recovery Vault, Event Explorer, Settings
  src/components/     layout, UI kit, SVG evidence graph, provider picker, transcript,
                      AI explanation card
  e2e/                Playwright end-to-end tests
docs/                 architecture, API, security, demo script
```

## Documentation

- **[User Manual](docs/USER_MANUAL.md)**: complete step-by-step guide (start here)
- [Quick start](docs/QUICK_START.md): short setup guide for teammates
- [Architecture & module guide](docs/ARCHITECTURE.md) — how the pieces fit, explained for beginners
- [API reference](docs/API.md)
- [Security model & limitations](docs/SECURITY.md)
- [Demo script](docs/DEMO_SCRIPT.md)

## Configuration

All settings are optional; see [`.env.example`](.env.example). Put `AFTERIMAGE_*` settings in `backend/.env` (e.g. `cp .env.example backend/.env`) or export them. API keys are read from the process environment only.

| Variable | Default | Meaning |
|---|---|---|
| `AFTERIMAGE_DATA_DIR` | `backend/data` | DB, workspaces, vault, archives |
| `AFTERIMAGE_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Allowed browser origins (no wildcards) |
| `AFTERIMAGE_MAX_READ_BYTES` | `65536` | Max bytes the agent may read per file |
| `AFTERIMAGE_LLM_PROVIDER` | `anthropic` | Default provider: `anthropic`, `gemini`, `ollama` or `simulated` |
| `AFTERIMAGE_LLM_MODEL` | provider default | Model for the **default** provider only |
| `AFTERIMAGE_ANTHROPIC_MODEL` / `_GEMINI_MODEL` / `_OLLAMA_MODEL` | `claude-opus-5-5` / `gemini-2.5-flash` / `llama3.1` | Per-provider models; never applied to another provider |
| `AFTERIMAGE_GEMINI_RATE_LIMIT_RETRIES` / `_MAX_RETRY_WAIT_S` | `2` / `30` | Bounded retries for per-minute 429s (quota exhaustion is never retried) |
| `AFTERIMAGE_OLLAMA_ALLOW_REMOTE` | off | Ollama host must be loopback unless this is `1` |
| `AFTERIMAGE_LLM_EFFORT` | `medium` | Anthropic effort level; empty = not sent |
| `AFTERIMAGE_LLM_TIMEOUT_S` / `_MAX_STEPS` / `_MAX_TOKENS` / `_MAX_TRIALS` | `120` / `12` / `16000` / `5` | Per-request timeout, agent step bound, tokens per model call, experiment trial cap |
| `AFTERIMAGE_OLLAMA_HOST` | `http://127.0.0.1:11434` | Local Ollama server (loopback only by default) |
| `GEMINI_API_KEY` | — | Read from the **process environment** only (not `backend/.env`, not `GOOGLE_API_KEY`). Never returned by the API. |
| `ANTHROPIC_API_KEY` | — | Read by the Anthropic SDK from the **process environment** (export it; it is not read from `backend/.env`). Never returned by the API. |

Invalid values stop the backend at startup with a clear validation error.

## Troubleshooting

| Symptom | Fix |
|---|---|
| UI says *Backend unreachable* | Start the backend on port 8000, or set `AFTERIMAGE_API_URL` before `npm run dev`. |
| `Port 5173 is already in use` | Stop the other Vite process (the port is strict so the CORS origin stays correct). |
| `ValidationError` on backend start | Check `AFTERIMAGE_*` variables — e.g. CORS origins must be full `http(s)://host:port` without wildcard or trailing slash. |
| 409 *policy changed since preview* | Another tab changed the policy. Refresh Policies and preview again. |
| 409 *another run is already in progress* | Wait for the current run to finish (scripted runs take well under a second; LLM runs take as long as the model). |
| 400 `provider_missing_credentials` | Export `ANTHROPIC_API_KEY` before starting the backend, choose another provider, or use `simulated`. |
| 400 `provider_config_error` *model not found* | Check `AFTERIMAGE_LLM_MODEL` / the model field; for Ollama run `ollama pull <model>`. |
| 429 `provider_quota_exhausted` | Gemini daily/free-tier quota used up for that model. Wait for the reset, pick another model, or enable billing on your Google project. Nothing falls back to another provider. |
| 429 `provider_rate_limit` | Per-minute limit; AFTERIMAGE already retried with the server's delay. Wait, or use fewer trials. |
| 400 `provider_model_unavailable` | The model is not available to your key/project/tier (or, for Ollama, not pulled). Use **Check** to test another model. |
| 400 `provider_tools_unsupported` | The Ollama model cannot call tools. Choose a tool-capable model (e.g. `llama3.1`, `qwen2.5`). |
| 400 `provider_invalid_credentials` / `provider_account_unsupported` | Key rejected, or the provider refuses this account/region. |
| Backend refuses to start: *must be a loopback address* | `AFTERIMAGE_OLLAMA_HOST` points off-machine. Use localhost, or set `AFTERIMAGE_OLLAMA_ALLOW_REMOTE=1` deliberately. |
| 503 `provider_timeout` / `provider_connection` | Transient provider problem; retry later or raise `AFTERIMAGE_LLM_TIMEOUT_S`. The run is recorded as failed, not faked. |
| Experiment says *attack not reproduced* | The model ignored the injected instruction in every baseline trial. That is a valid result; the gateway is still tested by the deterministic control in Replay Lab. |
| Playwright cannot find a browser | `npx playwright install chromium`, or set `PLAYWRIGHT_CHROMIUM_PATH`. |
| Want a clean slate | Settings → Archive & reset, or stop the backend and delete `backend/data/`. |

## Known limitations

- **No live provider has been verified.** The Gemini and Anthropic adapters are tested through their official SDKs against local mock HTTP servers. The Ollama adapter is tested against a mocked local server. The browser suite drives Gemini and Ollama through a mock API. No Gemini key, Anthropic key or Ollama install was available in the development environment. Use the opt-in smoke tests in `tests/test_real_provider_smoke.py` to verify against a real provider.
- **Gemini default model.** `gemini-2.5-flash` is a model Google has offered on the free tier. Availability varies by account, region and over time, so it is configurable and checked, not assumed. Gemini model metadata does not report function-calling support, so the check shows *tool calling: unknown* until the first real run.
- Experiments run in the background, and the Injection Lab polls real progress: the runs created so far and the policy decisions already persisted for the run in progress. LLM *replays* and single `POST /api/runs/llm` calls are still synchronous, so they show only a pending state until they finish. Background jobs are in-process threads: if the backend restarts mid-experiment, that experiment stays marked `running`.
- LLM behaviour is probabilistic. The experiment and LLM replays report counts across trials. Leak detection is exact matching on the canary and its hex token, so a model that *transforms* the secret (encodes or splits it) could leak without being counted. "Restricted content returned to agent" is measured at the gateway and is not affected by this.
- In the baseline (enforcement-off) run, the fake secret is sent to the configured LLM provider. It is random and synthetic, but it does leave the machine for a cloud provider.
- Cloud sync (Supabase) is **not implemented**; the UI states this. All data stays local.
- No user authentication: this is a single-user local prototype. Do not expose it on a network.
- The hash chain is tamper-*evident* for casual row edits, not tamper-proof (see `docs/SECURITY.md`).
- Exposure detection covers content that passes through the instrumented gateway only.
- File recovery restores bytes only; it cannot undo external side effects.
