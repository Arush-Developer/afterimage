# Demo script

Before you start: backend on :8000, frontend on :5173, and a clean state (**Settings → Archive & reset…**, type `ARCHIVE AND RESET`). Total time ≈ 4 minutes.

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

## 8. Close (10 s)

**Event Explorer** → *Hash chain intact · N events*. **Settings** shows local SQLite, cloud sync *not configured*.

> "Every AI action leaves a trace. Every incident deserves an answer."

## Re-running the demo

**Settings → Reset demo…** (`RESET DEMO`) resets policy and vault files but keeps the evidence; **Archive & reset…** gives an empty dashboard.
