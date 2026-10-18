# API reference

Base URL: `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs`. All bodies are JSON.

**Errors** use `{"detail": "<message>", "code": "<code>"}` with status 400 (`invalid_request`), 404 (`not_found`), 409 (`conflict`) or 500 (`internal_error`). Schema validation failures return FastAPI's standard 422 with a `detail` list. IDs are validated against `^(run|evt|dec|inc|rpl|snp)_[0-9a-f]{16}$`.

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

A concurrent run returns 409.

## Incidents

| Method | Path | Description |
|---|---|---|
| GET | `/api/incidents` | Incidents with severity, status, resource, rule, evidence count. |
| GET | `/api/incidents/{id}` | Full report: `incident`, `summary`, `severity_meaning`, `confidence_meaning`, `trigger`, `attempts[]` (tool, requested/canonical path, decision, rule, reason, matched rules, content_returned, event IDs), `findings[]` (`observed`/`inferred` + `evidence_event_ids`), `uncertainties[]`, `recommendation`, `sensitive_data_exposed`, `simulated`. |
| GET | `/api/incidents/{id}/events` | Linked events in chronological order, each with `evidence_role`. |
| GET | `/api/incidents/{id}/graph` | `{nodes[], edges[], is_dag, derived_from}`; nodes include `category` (allowed/denied/suspicious/info), `column`, `row`. |
| POST | `/api/incidents/{id}/notes` | `{text, status?}` → appends an `incident_annotation` event (status ∈ open, investigating, contained, exposure_confirmed, resolved). |

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
| POST | `/api/replays` | `{incident_id}` or `{baseline_run_id}` → re-runs that run's scenario in a fresh workspace under the active policy. **201** → `{replay_id, status: verified|regression|failed, verified, report: {assertions[], baseline, replay, differences[], policy_changed, notes[]}}` |
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

`run_started`, `task_received`, `tool_call_requested`, `policy_decision`, `tool_result`, `agent_note`, `sensitive_data_exposed`, `run_completed`, `run_error`, `incident_opened`, `incident_annotation`, `policy_changed`, `replay_verified`, `replay_not_verified`, `snapshot_created`, `file_modified`, `file_restored`, `environment_reset`.
