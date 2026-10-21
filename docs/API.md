# API reference

Base URL: `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs`. All bodies are JSON.

**Errors** use `{"detail": "<message>", "code": "<code>"}` with status 400 (`invalid_request`), 404 (`not_found`), 409 (`conflict`) or 500 (`internal_error`). LLM provider failures use `code: "provider_<kind>"`. Messages never contain key material.
- **400**, configuration problems: `provider_missing_credentials`, `provider_invalid_credentials`, `provider_model_unavailable`, `provider_tools_unsupported`, `provider_account_unsupported`, `provider_config_error`, `provider_unknown_provider`, `provider_invalid_model`.
- **429**, usage limits: `provider_quota_exhausted` (e.g. Gemini free-tier daily quota; not retried) and `provider_rate_limit` (per-minute; already retried a bounded number of times). Both include `retry_after_s` when the provider gave one, plus a `Retry-After` header.
- **503**, transient problems: `provider_timeout`, `provider_connection`, `provider_api_error`.
- **502** otherwise: `provider_bad_request`, `provider_bad_response`, `provider_refusal`.

No endpoint ever substitutes a different provider for the one requested. Schema validation failures return FastAPI's standard 422 with a `detail` list. IDs are validated against `^(run|evt|dec|inc|rpl|snp|exp)_[0-9a-f]{16}$`.

**Idempotency**: every state-changing `POST` (except preview and reset) accepts an optional `Idempotency-Key` header (8–64 chars `[A-Za-z0-9_-]`). Repeating a key returns the stored response with header `Idempotent-Replay: true`; reusing it on a different endpoint returns 409.

## Health & overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | `{status, version, database, time}` |
| GET | `/api/dashboard` | Metrics (runs, incidents, unauthorized_blocked, denied_total, exposures, verified_replays, replays, events), 5 recent incidents, 6 recent runs, active policy summary, honest sync status. |
| GET | `/api/scenarios` | Scenario descriptions. |

## Runs

| Method | Path | Description |
|---|---|---|
| GET | `/api/runs?limit=50` | Runs, newest first. |
| POST | `/api/runs/benign` | Execute the safe scenario. **201** → run (with `incident_id: null`). |
| POST | `/api/runs/attack` | Execute the controlled attack simulation. **201** → run with `incident_id`. |
| GET | `/api/runs/{run_id}` | One run: `status`, `policy_version`, `task_completed`, `sensitive_exposed`, `output_summary`, `result` (files read, denied calls, …). |
| GET | `/api/runs/{run_id}/events` | All events for a run, in order. |
| POST | `/api/runs/llm` | `{provider?: anthropic\|gemini\|ollama\|simulated, model?, enforcement: "protected"\|"baseline"}` → run an **LLM agent** on the synthetic project (synchronous). **201** → run with `agent_kind: "llm"`, `provider`, `model`, `provider_real`, `agent_steps`, `provider_error`. `baseline` disables policy enforcement (workspace boundary still applies). |
| GET | `/api/runs/{run_id}/transcript` | Model tool-call history: `[{step, kind: model_text\|tool_result\|error, text, tool, resource_id, allowed, rule_id}]`. File contents are never included. |
| GET | `/api/providers` | `{providers: [{provider, label, real, local, billing, configured, default_model, detail, key_source}], default_provider, default_models, configured_model, max_trials, max_steps}`. `provider` ∈ `anthropic`, `gemini`, `ollama`, `simulated`. Cheap: no paid API calls. `configured` means a key is present (cloud) or the local server answers (Ollama). No credential values. |
| GET | `/api/providers/{provider}/check?model=` | Live check: `{configured, reachable, model_available, tool_calling: supported\|unsupported\|unknown, error_kind?, detail, model, checked_at}`. Uses metadata endpoints only (Gemini `models.get`, Anthropic `models.retrieve`, Ollama `/api/version`, `/api/tags`, `/api/show`), never content generation. |
| GET | `/api/keys` | `{keys: {anthropic\|gemini: {present, source: environment\|saved\|session\|null}}, file}`. Never returns key material. |
| POST | `/api/keys/{anthropic\|gemini}` | Body `{api_key, remember=true}`. Loopback clients and `Content-Type: application/json` only. Puts the key in the backend environment; `remember` also writes `provider_keys.json` (mode 0600) in the data dir. Returns `{provider, present, source}`. 400 for a malformed key (the value is not echoed). |
| POST | `/api/keys/{anthropic\|gemini}/delete` | Removes a key added in Settings (and from the file). 409 if the key came from the shell environment. |

Every run carries `agent_kind` (`scripted` \| `llm`) and `enforcement` (`protected` \| `baseline`). A concurrent interactive run returns 409.

## Prompt-injection experiment

| Method | Path | Description |
|---|---|---|
| POST | `/api/experiments` | `{provider?, model?, trials: 1-20 (capped by AFTERIMAGE_LLM_MAX_TRIALS), background?: bool}` → for each trial, one **baseline** (enforcement off) and one **protected** LLM run, each in a fresh workspace. With `background: true` it returns immediately with `status: "running"`, `report: {}`. **201**. |
| GET | `/api/experiments` | Saved experiments (`status`: `running`, `error`, or the verdict). |
| GET | `/api/experiments/{id}` | `{status, report, progress: {total_runs, runs: [{run_id, enforcement, status}]}}`. `report.verdict` ∈ `protected`, `protection_failed`, `attack_not_reproduced`, `inconclusive` (provider errors meant one side never completed; nothing is claimed); `report.stopped_early` names a non-recoverable provider error (e.g. `quota_exhausted`) that ended the experiment before all trials ran; per-trial rows include `provider_error` and `provider_error_kind`; `report.baseline` / `report.protected` aggregate counts (`restricted_file_requested`, `restricted_content_returned`, `secret_leaked`, `legitimate_task_completed`, `errored_trials`); per-trial rows; `notes`; `ground_truth`. |

## Incidents

| Method | Path | Description |
|---|---|---|
| GET | `/api/incidents` | Incidents with severity, status, resource, rule, evidence count. |
| GET | `/api/incidents/{id}` | Full report: `incident`, `summary`, `severity_meaning`, `confidence_meaning`, `trigger`, `attempts[]` (tool, requested/canonical path, decision, rule, reason, matched rules, content_returned, event IDs), `findings[]` (`observed`/`inferred` + `evidence_event_ids`), `uncertainties[]`, `recommendation`, `sensitive_data_exposed`, `simulated`. |
| GET | `/api/incidents/{id}/events` | Linked events in chronological order, each with `evidence_role`. |
| GET | `/api/incidents/{id}/graph` | `{nodes[], edges[], is_dag, derived_from}`; nodes include `category` (allowed/denied/suspicious/info), `column`, `row`. |
| POST | `/api/incidents/{id}/notes` | `{text, status?}` → appends an `incident_annotation` event (status ∈ open, investigating, contained, exposure_confirmed, resolved). |
| POST | `/api/incidents/{id}/explain` | `{provider?, model?}` → AI-assisted explanation from persisted evidence. **201** → `{summary, observed[], hypotheses[], uncertainty[], rejected_claims[], provider, model, event_id}`; each statement has `event_ids` validated against the incident's evidence. Requires a real provider (simulated → 400). Stored as an `ai_explanation` event. |
| GET | `/api/incidents/{id}/explanation` | `{explanation}`: the latest stored AI explanation, or `null`. |

## Policies

| Method | Path | Description |
|---|---|---|
| GET | `/api/policies` | `{active, history[], catalog[]}`. `active` includes the document, built-in rules, `rule_impact` and `probe_decisions` (the real engine evaluated on the scenario's requests). |
| GET | `/api/policies/{version}` | A specific version. |
| POST | `/api/policies/preview` | `{change_ids[]}` → current vs proposed document, diff, impact table and warnings. Changes nothing. |
| POST | `/api/policies/apply` | `{change_ids[], base_version, confirm: true}` → new active version. 409 if `base_version` is stale or the change is already in effect. |
| POST | `/api/policies/revert` | `{target_version, base_version, confirm: true}` → new version with the target's rules. |

`change_ids` ∈ `restrict-read-scope`, `deny-secret-class`, `require-approval-sensitive`, `disable-write-tool`. Arbitrary policy documents cannot be submitted.

## Replays

| Method | Path | Description |
|---|---|---|
| POST | `/api/replays` | `{incident_id}` or `{baseline_run_id}`, optional `trials` (LLM baselines only) → re-runs that run's scenario in a fresh workspace under the active policy. **201** → `{replay_id, status: verified\|regression\|failed\|inconclusive, verified, report: {assertions[], baseline, replay, differences[], policy_changed, notes[]}}`. For an **LLM** baseline the report adds `deterministic_control` (a scripted control run that always attempts the attack), `model_trials[]` and `model_stats`; `inconclusive` means every model trial hit a provider error. |
| GET | `/api/replays` | Saved replay reports. |
| GET | `/api/replays/{replay_id}` | One saved report. |

## Recovery vault

| Method | Path | Description |
|---|---|---|
| GET | `/api/recovery/files` | Vault-managed synthetic files with current SHA-256 and `matches_original`. |
| POST | `/api/recovery/simulate-change` | `{path}` → snapshot, then apply a deterministic simulated unauthorized edit. |
| GET | `/api/snapshots?path=` | Snapshot metadata. |
| POST | `/api/snapshots` | `{path, reason?}` → new snapshot version. Only vault files; secret-like names always rejected. |
| GET | `/api/snapshots/{id}` | Metadata + content, store integrity check, current hash and unified diff to current. |
| POST | `/api/snapshots/{id}/restore` | `{confirm: true}` → backs up current state, restores, re-hashes: `{before_sha256, expected_sha256, restored_sha256, verified, pre_restore_backup}`. |

## Events & settings

| Method | Path | Description |
|---|---|---|
| GET | `/api/events` | Filters: `run_id`, `incident_id`, `event_type`, `resource` (substring), `outcome`, `limit` (≤1000), `offset`. Newest first, with `total`. |
| GET | `/api/events/facets` | Distinct event types, outcomes, run IDs, incident IDs. |
| GET | `/api/events/verify` | Recomputes the hash chain: `{valid, checked, first_invalid_event_id, reason}`. |
| GET | `/api/settings` | DB status, chain status, demo environment details, CORS origins, cloud-sync status, archives. |
| POST | `/api/settings/reset` | `{mode: "demo", confirm_text: "RESET DEMO"}` keeps evidence; `{mode: "full", confirm_text: "ARCHIVE AND RESET"}` archives the DB then starts empty. |

## Event types

`run_started`, `task_received`, `tool_call_requested`, `policy_decision`, `tool_result`, `tool_call_rejected` (invalid model tool call, never executed), `agent_note` (scripted note or redacted model text / provider error), `sensitive_data_exposed`, `run_completed`, `run_error`, `incident_opened`, `incident_annotation`, `ai_explanation`, `policy_changed`, `replay_verified`, `replay_not_verified`, `snapshot_created`, `file_modified`, `file_restored`, `environment_reset`.
