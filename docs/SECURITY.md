# Security model and limitations

AFTERIMAGE is a **local, single-user hackathon prototype** operating only on synthetic data. This document states what is implemented and tested, and what is not.

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
- **The agent is simulated.** It is deterministic and scripted. The "attack" is a controlled simulation; it demonstrates the enforcement and forensics pipeline, not the robustness of any real model.
- **Causality is inferred.** The trigger document is identified from agent-reported provenance, ordering and a heuristic content scanner. The UI labels this *inferred*. A real agent runtime would need trustworthy provenance instrumentation.
- **The instruction scanner is a heuristic** (three regular expressions). It is used for observation only and never blocks anything.
- **TOCTOU** is narrowed, not eliminated: a parent directory swapped between resolution and open on a hostile local filesystem could still race. The synthetic workspace is not shared with untrusted processes.
- **Exposure checks** only see data that passes through the gateway in that run.
- **Recovery** restores file bytes only. It does not reverse network requests or changes in other systems.
- **Per-run workspaces** (which contain that run's fake secret) remain on disk under `data/workspaces/` for inspection until a demo reset removes them.
- **Cloud sync is not implemented.** No data leaves the machine.
