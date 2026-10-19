# Security model and limitations

AFTERIMAGE is a **local, single-user hackathon prototype** operating only on synthetic data. This document states what is implemented and tested, and what is not.

## Threat model for the LLM agent

**The model is untrusted.** Everything it emits (tool names, arguments, text) is treated as attacker-influenced input, because file contents it reads can carry injected instructions.

- The model can only *propose* tool calls. `llm_agent.py` validates each proposal against a strict schema: known tool, required string arguments only, no extra keys, length limits. An invalid proposal is recorded as `tool_call_rejected` and never executed.
- Valid proposals execute **only** through `ToolGateway`, which asks the policy engine *before* touching the filesystem. Nothing in the model's output can change the policy, its version, the workspace root or the sensitivity labels.
- The agent's only capabilities are `list_files`, `read_file` and `write_file` inside a fresh synthetic workspace. It has no shell, code execution, network, or URL fetching. The provider endpoint is fixed by operator configuration, never chosen by the model.
- Steps are bounded (`AFTERIMAGE_LLM_MAX_STEPS`), each model call has a token cap and a timeout, and the SDK's retries are limited.
- API keys stay in the backend process environment and are read only by the Anthropic SDK. They are never put in prompts, tool results, events, logs or API responses, and `/api/providers` / `/api/settings` report only *whether* a provider is configured.

## Bypass audit (what can touch files, network or processes)

Audited by searching the backend for filesystem, network and process APIs (`os.open`, `open`, `read_*`/`write_*`, `os.walk`, `shutil`, `subprocess`, `eval`/`exec`, HTTP clients):

| Code path | Reachable by the agent/model? | Notes |
|---|---|---|
| `gateway.py` `_do_list` / `_do_read` / `_do_write` | Yes, **only after an allow decision** | The only agent-reachable file I/O. |
| `workspace.py` `create_workspace` | No | Server writes the fixed synthetic template. |
| `recovery.py` | No (operator API) | Fixed allow-list of vault files; secret-like names always rejected. |
| `main.py` reset (`shutil.rmtree`) | No (operator API) | Fixed data directories; typed confirmation; refused while an experiment runs. |
| `config.py` `.env` read | No | Server configuration. |
| Anthropic SDK / Google Gen AI SDK / Ollama `httpx2` calls | No | Operator-configured endpoint only. |
| `subprocess`, `eval`, `exec` | — | Not used anywhere. |

**Remaining bypass risks (not claimed to be solved):**

1. **Baseline mode is a deliberate bypass.** `enforcement: "baseline"` swaps in an allow-all engine so the experiment can observe the unprotected behaviour. The workspace-boundary rule still applies, and it only ever runs on a fresh synthetic workspace. But anyone who can reach the API can start one, because there is no authentication.
2. **Data sent to the model provider.** In protected mode the provider receives the contents of *allowed* synthetic files. In baseline mode it may also receive the fake secret. That secret is random and synthetic, but for a cloud provider it leaves the machine.
3. **Leak detection is exact matching.** The canary, its hex token and the header line are detected and redacted. A model that encodes, splits or paraphrases the secret could leak it in its output without being counted. *Restricted content returned to the agent* is measured at the gateway and does not have this limitation.
4. **Allowed writes carry model-chosen content.** `write_file` is limited to `out/**` by policy, but what the model writes there is not filtered.
5. **TOCTOU** in path resolution is narrowed (`O_NOFOLLOW`, inode re-check, containment re-check), not eliminated.
6. **Provider-side behaviour** (safety refusals, model updates) can change experiment outcomes. Results are reported per trial and never assumed.

## Secret redaction boundaries

| Boundary | Mechanism | Tested by |
|---|---|---|
| Event log | `recorder.py` scrubs the run's sensitive values **and** always scrubs the canary pattern / secret header, even when a caller passes none | `test_secret_never_in_event_records`, `test_recorder_scrubs_canary_pattern_even_without_sensitive_values` |
| Run row (summary, provider error, transcript) | `redact_text` / `redact_obj` before every `UPDATE runs` | `test_provider_error_text_is_redacted_on_the_run_row`, `test_hex_only_leak_is_detected_and_redacted` |
| Model text / final answer | Redacted before recording or storing | `test_model_text_is_recorded_and_redacted` |
| Tool results stored | Size + SHA-256 only; transcript stores tool metadata, never file contents | `test_baseline_returns_secret_but_it_is_never_persisted` |
| Experiment and replay reports | Built only from aggregate counts and event IDs | `test_secret_never_appears_across_llm_boundaries`, `test_llm_replay_fails_under_unsafe_policy` |
| AI explanations | The model sees only persisted (already redacted) events; output passes through the recorder | `test_explanation_keeps_grounded_claims_and_rejects_fabricated_ids` |
| Logs | `RedactingLogFilter` installed on the root, `afterimage` and `uvicorn` loggers/handlers | `test_log_records_are_scrubbed` |
| Browser | All of the above. E2E tests capture every `/api/` response and the rendered page | e2e `secret content never reaches the browser`, `injection lab …` |

## Ground truth is independent of the policy under test

"Unauthorized" comes from the workspace's fixed sensitivity labels (`secret.txt` is restricted, and anything outside the workspace is out of bounds), and "leaked" comes from the canary detector. A permissive policy therefore cannot grade itself as safe. `test_failed_security_is_reported_and_secret_still_not_persisted` and `test_llm_replay_fails_under_unsafe_policy` inject an allow-all policy and check that the result is **failed**.

## What is enforced (and tested)

| Control | Where | Test(s) |
|---|---|---|
| All agent file access goes through the gateway; the agent has no filesystem, network, shell or code-execution capability | `agent.py`, `gateway.py` | `test_gateway.py` |
| Policy check happens **before** a file is opened | `gateway.py::_invoke` | `test_restricted_read_denied_without_content` |
| Default deny; deny rules override allow rules; every decision names its rule | `policy.py` | `test_every_invocation_records_request_decision_result`, `test_policy_change_affects_backend_enforcement` |
| Path canonicalisation: rejects `..` traversal, absolute POSIX/Windows/`~` paths, backslashes, control/NUL characters, empty or >256-char paths | `workspace.py::resolve_workspace_path` | `test_path_traversal_rejected`, `test_absolute_and_malformed_paths_rejected` |
| Symlink escapes rejected (realpath must stay under the workspace root); symlinks to protected files inside the workspace are evaluated as the protected file | `workspace.py` | `test_symlink_escape_rejected`, `test_symlink_inside_workspace_to_secret_is_denied` |
| TOCTOU narrowing: open the resolved path with `O_NOFOLLOW`, compare `fstat` inode/device with the checked path, re-check containment after open | `gateway.py::_open_verified` | covered indirectly |
| Protected content never stored or returned: results record only size and SHA-256; a recorder-level scrubber removes the workspace's sensitive values from every event; run summaries are scrubbed | `gateway.py`, `recorder.py`, `runs.py` | `test_secret_never_in_api_responses_or_database`, `test_failed_security_is_reported_and_secret_still_not_persisted`, e2e `secret content never reaches the browser` |
| Exposure detection with a per-workspace random canary token | `workspace.py`, `gateway.py` | `test_permissive_policy_exposure_is_detected_and_redacted` |
| Only safe, predefined policy changes can be applied through the API; changes are versioned and reversible | `policy.py`, `policy_store.py`, `main.py` | `test_revert_restores_previous_rules`, invalid change IDs → 422 |
| Optimistic concurrency + idempotency keys for state-changing calls | `main.py`, `policy_store.py` | `test_duplicate_apply_does_not_create_two_versions`, `test_idempotency_key_replays_response`, `test_concurrent_requests_do_not_corrupt_state` |
| Input validation on all IDs, paths and bodies (Pydantic) | `main.py` | `test_invalid_requests_return_errors` |
| CORS restricted to configured origins; wildcard origins refused at startup | `config.py`, `main.py` | `test_cors_only_allows_configured_origin`, `test_config_validation` |
| Append-only events: SQLite triggers abort UPDATE/DELETE | `db.py` | `test_hash_chain_detects_tampering` |
| Hash chain over events, verifiable via `/api/events/verify` | `recorder.py` | `test_hash_chain_detects_tampering` |
| Recovery vault only accepts its own synthetic files and always rejects secret-like names; restores verify the stored object hash and re-hash the restored file | `recovery.py` | `test_vault_rejects_unmanaged_protected_and_traversal_paths`, `test_snapshot_restore_round_trip_with_hash_verification` |
| Resets require a typed confirmation; the demo reset keeps evidence; the full reset archives the DB first | `main.py` | `test_demo_reset_keeps_evidence`, `test_full_reset_archives_before_wiping` |

## Limitations (be honest with judges)

- **Not tamper-proof.** The hash chain detects naive edits of individual rows. Someone with write access to the SQLite file can drop the triggers and recompute the entire chain. There is no external anchoring, signing or WORM storage.
- **No authentication or authorization of human users.** Anyone who can reach the API can use it. Keep it on `localhost`.
- **No encryption at rest.** The database and synthetic workspaces are plain files. (All data is synthetic.)
- **Two agents.** The scripted agent is deterministic and deliberately gullible; it is the regression baseline. The LLM agent is real, but whether a given model follows the injection is probabilistic and is measured per trial. Neither result says anything about a model's general robustness.
- **Gemini.** The Gemini adapter is tested through the official `google-genai` SDK against a local mock server and was exercised live against `gemini-3.8-flash` (see the live test report). Provider error messages are sanitized of key-like strings, and the log filter also scrubs credential-shaped strings. On the Gemini free tier (5 requests/minute for this model), set `AFTERIMAGE_GEMINI_MIN_INTERVAL_S=13` to pace agent steps; AFTERIMAGE never auto-retries billable calls.
- **Real-provider verification.** The Anthropic adapter is tested through the official SDK against a local mock HTTP server. A run against the live API was not possible in the development environment (no key), and the Ollama adapter is untested against a live server.
- **Causality is inferred.** The trigger document is identified from agent-reported provenance, ordering and a heuristic content scanner. The UI labels this *inferred*. A real agent runtime would need trustworthy provenance instrumentation.
- **The instruction scanner is a heuristic** (three regular expressions). It is used for observation only and never blocks anything.
- **TOCTOU** is narrowed, not eliminated: a parent directory swapped between resolution and open on a hostile local filesystem could still race. The synthetic workspace is not shared with untrusted processes.
- **Exposure checks** only see data that passes through the gateway in that run.
- **Recovery** restores file bytes only. It does not reverse network requests or changes in other systems.
- **Per-run workspaces** (which contain that run's fake secret) remain on disk under `data/workspaces/` for inspection until a demo reset removes them.
- **Cloud sync is not implemented.** No data leaves the machine.
