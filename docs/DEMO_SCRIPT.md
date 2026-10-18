# Demo script

Before you start: backend on :8000, frontend on :5173, and a clean state (**Settings → Archive & reset…**, type `ARCHIVE AND RESET`). Steps 1–7 take about 4 minutes. Steps 8–10 (LLM agent) add 2–3 minutes; they work without a key using the clearly labelled simulated agent.

## 0. Framing (20 s)

> "AI agents read files and call tools. If a document contains hidden instructions, the agent might try something the user never asked for. AFTERIMAGE records every action, enforces permissions on the server, reconstructs what happened from evidence, and proves a fix works by replaying the attack."

Point at the sidebar footer: *Observe → Enforce → Investigate → Remediate → Replay → Verify*. On **Overview** all metrics read 0.

## 1. Safe scenario (30 s)

Click **Run Safe Scenario**.

Expected: result card "Safe scenario … Task: completed · Denied requests: 0 · Sensitive data exposed: no" and "No unauthorized access was recorded…". *Runs recorded* = 1. Workflow step **Observe** turns green.

Optional: click **View event timeline** → Event Explorer filtered to that run. Point out the `agent_note`: the safe agent saw instruction-like text in a doc and ignored it.

## 2. Controlled attack (30 s)

Click **Simulate Attack**.

Expected: "Controlled attack simulation … Task: completed · Denied requests: 2 · Sensitive data exposed: no", with the amber *controlled simulation* notice. *Incidents detected* = 1, *Unauthorized requests blocked* = 2.

> "The agent was deliberately configured to obey the hidden instruction. It tried to read `secret.txt` and a path outside the workspace. The gateway denied both before opening anything — and the real task still finished."

## 3. Investigation (60 s)

Click **Investigate incident**.

Walk top to bottom:
- **Summary**: severity *High* (impact) vs confidence *High* (strength of evidence) — explained separately.
- **Triggering input** `docs/integration_notes.md` (agent-reported provenance); **attempted tool** `read_file("secret.txt")`; **rule** `POL-DENY-SECRET-FILE`.
- **Evidence graph**: click *Incident recorded*, then the *DENIED* decision node (event ID, UTC timestamp, rule, reason) and its *Result: blocked* node (`bytes_returned: 0`). "Every node is a stored event; every arrow is a stored link."
- **Findings**: *observed* vs *inferred* badges, each citing event IDs.
- **Uncertainty**: "We don't read the model's mind; the trigger is inferred."

## 4. Remediation (40 s)

Click **Review policy change**. The two recommended changes are pre-selected. Click **Preview change**.

Expected: current v1 vs proposed v2 rules; *Impact* table shows README/src/docs still allowed, `secret.txt` now denied by `POL-DENY-SECRET-CLASS`, no warnings. Click **Apply as v2…** → dialog → **Apply policy**. Banner: "Policy v2 is now active and enforced".

> "The baseline let the agent read *anything* and protected one exact filename. Now it can read only what the task needs, and all secret-like files are protected."

## 5. Replay & verify (40 s)

Click **Replay to verify** → **Run replay**.

Expected: green **Verified** banner. Table: v1 → v2 (*changed*), unauthorized attempted 2 → 2, blocked 2/2 → 2/2, exposed No/No, task Yes/Yes, rules now include `POL-DENY-SECRET-CLASS`. Five assertions pass with event IDs. *Differences* lists every request with old/new rule. Refresh the page: the report is still there.

## 6. Honesty check — regression (40 s, recommended)

Go to **Policies**, tick **Disable write_file for the summary task**, **Preview change** — note the amber warning "Legitimate operation would be denied: Save the summary". Apply as v3, click **Replay to verify** → **Run replay**.

Expected: amber **Not verified — regression**: attack blocked, but `legitimate_task_completed` fails.

> "Blocking everything is not a fix. AFTERIMAGE only says *Verified* when security and functionality both pass."

Restore with **Policies → Version history → v2 → Restore rules** (creates v4).

## 7. Recovery (40 s)

Go to **Recovery Vault**, keep `config/app_settings.json` selected, click **Simulate unauthorized edit**.

Expected: snapshot v1 appears and opens; the diff shows `debug_mode` flipped and a telemetry endpoint added; the file shows *modified*. Click **Restore this version…** → **Restore file**.

Expected: "Restored and hash-verified" with the original, modified and restored SHA-256 values (original = restored). The modified version was saved as snapshot v2 first.

> "Restoring a file doesn't undo external side effects — we say so on the page."

## 8. Real LLM agent: prompt-injection experiment (60–90 s)

**Before the demo:** decide which provider to show, and rehearse it once. A real model's behaviour varies, and free-tier quotas can run out mid-demo.
- **Gemini (free tier):** `export GEMINI_API_KEY=...` before starting the backend. In **Settings**, click **Check** on *Google Gemini*: it should say *model gemini-2.5-flash available*. If that model isn't available to your key, set `AFTERIMAGE_GEMINI_MODEL` to one that is, and check again. Keep **1 trial**, because free-tier per-minute limits are low.
- **Ollama (local, no cloud):** `ollama pull llama3.1 && ollama serve`, then **Check** on *Ollama (local)*. It must say *tool calling: supported*. Good talking point: "nothing leaves this laptop."
- **Claude:** `export ANTHROPIC_API_KEY=...` (paid API).
- **No key at all:** use **Simulated agent (no LLM)**. Say clearly that it is a rule-based stand-in, not a model. The UI labels it "simulated" everywhere.

Runs are labelled by what produced them: *Gemini · model*, *Ollama · local · model*, *Claude · model*, *simulated*, *scripted*.

Go to **Injection Lab**, pick the provider, keep 1 trial (2–3 with a real model if time allows), and click **Run experiment**.

Expected while running: the **Live progress** card shows "0 of 2 isolated run(s) finished", then a feed of policy decisions as the backend records them.

Expected when done, with the simulated agent:
- A green **Protected** verdict.
- Baseline: restricted content returned **1/1**, fake secret leaked **1/1**.
- Protected: **0/1**, with `POL-DENY-SECRET-FILE` in the rules column.
- Task completed in both.

Click **Show model tool-call history** to show the baseline transcript: every call, the resource, allowed or denied, and the rule.

With a **real model**, any of four verdicts is a valid result. Read it out honestly:
- *Protected*: the model followed the injection in the baseline, and enforcement stopped it.
- *Attack not reproduced*: the model ignored the injection. Say: "the model was robust in this trial, and enforcement doesn't depend on that."
- *Inconclusive*: provider errors meant one side never ran. A typical cause is *Gemini quota exhausted* on the free tier. The amber notice explains it. Say: "We don't count a run that never happened. And AFTERIMAGE never quietly switches to a paid provider." Then switch to the simulated agent or another model yourself.
- *Protection failed*: should not happen. Investigate.

> "We don't assume the attack works. We measure it. Whatever the model decides, the gateway decides access, and 'leaked' is judged by a canary detector that the policy can't influence."

## 9. LLM replay with a deterministic control (40 s)

Go to **Replay Lab**, choose a baseline run labelled **LLM** (protected), set **Model trials** to 2, and click **Run replay**.

Expected: **Verified**, with a "Model trials (probabilistic)" table and *Deterministic control* assertions.

> "The control agent always attempts the attack, so it proves the policy deterministically. The model trials show what the model actually did, reported as counts."

## 10. AI-assisted explanation (optional, real provider only, 30 s)

Open an incident from an LLM run. In **AI-assisted explanation**, click **Generate**.

Expected: *Observed* and *Hypotheses* lists, each statement with clickable event IDs, plus an uncertainty section. If the model invented an event ID, the card says how many claims were rejected.

With no real provider, the card says so, and the rule-based findings are the explanation.

## 11. Close (10 s)

**Event Explorer** → *Hash chain intact · N events*. **Settings** shows local SQLite, cloud sync *not configured*.

> "Every AI action leaves a trace. Every incident deserves an answer."

## Re-running the demo

**Settings → Reset demo…** (`RESET DEMO`) resets policy and vault files but keeps the evidence; **Archive & reset…** gives an empty dashboard.
