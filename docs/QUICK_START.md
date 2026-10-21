# AFTERIMAGE — Quick start for teammates

The short version. For explanations, Windows steps, providers and troubleshooting, see the full [User Manual](USER_MANUAL.md).

**You need:** Python **3.12+**, Node.js **22.12+** (with npm), git, and free ports **8000** and **5173**. No API key is needed for the demo.

> Tested by the project on Linux only. macOS uses the same commands (not tested on a Mac). Windows: see [Chapter 4 of the manual](USER_MANUAL.md#chapter-4--installation-on-windows-unverified).

## Fastest: one command (macOS / Linux)

After cloning (step 1), from the `afterimage` folder:

```bash
./run.sh
```

It installs what is missing, starts both servers and opens the dashboard. **Ctrl+C** stops everything. Skip to [step 4](#4-check-it-works). For a real model, add your key in **Settings → LLM agent configuration → Add API key**.

## 1. Get the code

```bash
git clone https://github.com/Arush-Developer/afterimage.git
```

```bash
cd afterimage
```

## 2. Backend (Terminal 1)

```bash
cd backend
```

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

Optional: make the simulated agent the default provider (useful without API keys):

```bash
cp ../.env.example .env
```

Then edit `backend/.env` and set `AFTERIMAGE_LLM_PROVIDER=simulated`.

Start the backend:

```bash
uvicorn afterimage.main:create_app --factory --reload --port 8000
```

Wait for `Uvicorn running on http://127.0.0.1:8000`.

## 3. Frontend (Terminal 2)

```bash
cd afterimage/frontend
```

```bash
npm ci
```

```bash
npm run dev
```

## 4. Check it works

1. Open <http://localhost:5173>. The top-right corner should say **Backend connected**.
2. On **Overview**, click **Run Safe Scenario**. The result card should say *Task: completed*.
3. Click **Simulate Attack**. You should see *Denied requests: 2* and *Sensitive data exposed: no*.

## 5. Using a real model (optional)

Easiest: open **Settings → LLM agent configuration**, click **Add API key** next to the provider, paste the key and click **Save key**, then click **Check**. Or, instead, export the key in the terminal:

Export the key in **Terminal 1** before starting the backend. Never put keys in files you commit; `backend/.env` is **not** read for keys.

```bash
export GEMINI_API_KEY="paste-your-key-here"
```

Then, in the app, open **Settings** and click **Check** next to the provider. In the **Injection Lab**, select that provider and keep **1** trial. Free-tier quotas are small. Details: [manual Chapter 5](USER_MANUAL.md#chapter-5--configuration-and-ai-providers).

## 6. Stop

Press **Ctrl+C** in both terminals. Leave the Python environment with `deactivate`.

## 7. Next time

- Terminal 1: `cd afterimage/backend`, `source .venv/bin/activate`, then the `uvicorn …` command.
- Terminal 2: `cd afterimage/frontend`, then `npm run dev`.

## 8. Before a demo

**Settings → Archive & reset…**, type `ARCHIVE AND RESET`. Then follow [manual Chapter 12](USER_MANUAL.md#chapter-12--hackathon-demonstration-script).

## Stuck?

| Problem | Fix |
|---|---|
| `Could not import module "afterimage.main"` | Run `uvicorn` from inside `backend/`. |
| `uvicorn: command not found` | Activate the venv: `source .venv/bin/activate`. |
| `pip` fails on `networkx==3.7` | Your Python is older than 3.12. Recreate the venv with Python 3.12+. |
| **Backend unreachable** in the app | Start the backend (Terminal 1). |
| `Port 5173 is already in use` | Stop the other `npm run dev`. |

Everything else: [manual Chapter 13](USER_MANUAL.md#chapter-13--troubleshooting).
