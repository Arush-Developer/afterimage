// Typed client for the AFTERIMAGE REST API. All data shown in the UI comes from here.

export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type Category = "allowed" | "denied" | "suspicious" | "info";

export interface AfterEvent {
  event_id: string;
  run_id: string | null;
  incident_id: string | null;
  timestamp: string;
  event_type: string;
  actor: string;
  action: string;
  resource_id: string | null;
  source_event_id: string | null;
  policy_decision_id: string | null;
  outcome: string;
  severity: Severity;
  summary: string;
  evidence_metadata: Record<string, unknown>;
  prev_hash: string;
  event_hash: string;
  evidence_role?: string;
}

export interface RunResult {
  files_read: string[];
  failed_required_reads: string[];
  output_written: boolean;
  output_path: string;
  followed_instructions: string[];
  tool_calls: number;
  denied_calls: number;
  exposure_event_ids: string[];
}

export interface Run {
  run_id: string;
  scenario: "benign" | "attack";
  scenario_title: string;
  kind: "scenario" | "replay";
  status: string;
  policy_version: number;
  started_at: string;
  completed_at: string | null;
  task_completed: boolean | null;
  sensitive_exposed: boolean | null;
  output_summary: string | null;
  result: RunResult | null;
  incident_id: string | null;
  simulated_attack: boolean;
}

export interface Incident {
  incident_id: string;
  run_id: string;
  created_at: string;
  incident_type: string;
  title: string;
  severity: Severity;
  confidence: "high" | "medium" | "low";
  status: string;
  resource_id: string | null;
  rule_id: string | null;
  trigger_resource: string | null;
  first_event_at: string;
  last_event_at: string;
  scenario?: string;
  run_kind?: string;
  evidence_count?: number;
  investigation_available?: boolean;
}

export interface Attempt {
  tool: string;
  resource_id: string;
  requested_path: string;
  sensitivity: string;
  agent_reported_provenance: string | null;
  requested_at: string;
  decision: string;
  decision_id: string | null;
  rule_id: string | null;
  reason: string | null;
  matched_rules: string[];
  policy_version: number | null;
  content_returned: boolean;
  bytes_returned: number | null;
  request_event_id: string;
  decision_event_id: string | null;
  result_event_id: string | null;
}

export interface Finding {
  kind: "observed" | "inferred";
  statement: string;
  evidence_event_ids: string[];
  basis?: string;
}

export interface PolicyChange {
  change_id: string;
  title: string;
  explanation: string;
  category: string;
  already_applied?: boolean;
}

export interface IncidentReport {
  incident: Incident;
  severity_meaning: string;
  confidence_meaning: string;
  summary: string;
  trigger: { resource_id: string; event_id: string; basis: string; content_flagged: boolean } | null;
  attempts: Attempt[];
  sensitive_data_exposed: boolean;
  findings: Finding[];
  uncertainties: string[];
  recommendation: { change_ids: string[]; already_applied: string[]; changes: PolicyChange[]; rationale: string[]; next_step: string };
  evidence_event_ids: string[];
  simulated: boolean;
}

export interface GraphNode {
  id: string;
  label: string;
  event_type: string;
  category: Category;
  outcome: string;
  severity: Severity;
  timestamp: string;
  resource_id: string | null;
  actor: string;
  summary: string;
  policy_decision_id: string | null;
  evidence_metadata: Record<string, unknown>;
  column: number;
  row: number;
}

export interface IncidentGraph {
  incident_id: string;
  nodes: GraphNode[];
  edges: { source: string; target: string; relation: string }[];
  derived_from: string;
  is_dag: boolean;
}

export interface Rule {
  rule_id: string;
  description: string;
  effect: "allow" | "deny" | "require_approval";
  actions: string[];
  resources: string[];
  agents: string[];
  tasks: string[];
}

export interface PolicyDocument {
  name: string;
  disabled_tools: string[];
  rules: Rule[];
}

export interface ProbeDecision {
  tool: string;
  path: string;
  purpose: "legitimate" | "attack";
  label: string;
  resource_id: string;
  allowed: boolean;
  decision: string;
  rule_id: string;
}

export interface PolicyDescription {
  version: number;
  is_active: boolean;
  created_at: string;
  change_summary: string;
  applied_changes: string[];
  document: PolicyDocument;
  builtin_rules: { rule_id: string; effect: string; description: string }[];
  rule_impact: Record<string, string[]>;
  probe_decisions: ProbeDecision[];
}

export interface PoliciesResponse {
  active: PolicyDescription;
  history: { version: number; change_summary: string; applied_changes: string[]; created_at: string }[];
  catalog: PolicyChange[];
}

export interface PolicyPreview {
  base_version: number;
  change_ids: string[];
  changes: PolicyChange[];
  current_document: PolicyDocument;
  proposed_document: PolicyDocument;
  diff: { added_rules: Rule[]; removed_rules: Rule[]; changed_rules: Rule[]; disabled_tools_before: string[]; disabled_tools_after: string[] };
  no_op: boolean;
  impact: {
    probes: (ProbeDecision & { before: { allowed: boolean; decision: string; rule_id: string }; after: { allowed: boolean; decision: string; rule_id: string }; changed: boolean })[];
    legitimate_operations_broken: number;
    attack_operations_opened: number;
    warnings: string[];
  };
}

export interface Assertion {
  id: string;
  title: string;
  passed: boolean;
  required: boolean;
  detail: string;
  evidence_event_ids: string[];
}

export interface RunEvaluation {
  run_id: string;
  scenario: string;
  policy_version: number;
  unauthorized_attempted: number;
  unauthorized_blocked: number;
  unauthorized_allowed: number;
  sensitive_data_exposed: boolean;
  exposure_event_ids: string[];
  task_completed: boolean;
  required_reads: Record<string, boolean>;
  output_written: boolean;
  rules_responsible: string[];
  run_completed_event_id: string | null;
  assertions?: Assertion[];
  status?: string;
}

export interface Replay {
  replay_id: string;
  baseline_run_id: string;
  replay_run_id: string;
  scenario: string;
  baseline_policy_version: number;
  replay_policy_version: number;
  status: "verified" | "regression" | "failed";
  verified: boolean;
  created_at: string;
  report: {
    status: string;
    verified: boolean;
    scenario: string;
    assertions: Assertion[];
    baseline: RunEvaluation;
    replay: RunEvaluation;
    differences: {
      tool: string;
      resource_id: string;
      unauthorized: boolean;
      baseline: { decision: string; rule_id: string } | null;
      replay: { decision: string; rule_id: string } | null;
      changed: boolean;
      baseline_event_id: string | null;
      replay_event_id: string | null;
    }[];
    policy_changed: boolean;
    notes: string[];
  };
}

export interface Dashboard {
  metrics: {
    runs: number;
    scenario_runs: number;
    replay_runs: number;
    incidents: number;
    unauthorized_blocked: number;
    denied_total: number;
    exposures: number;
    verified_replays: number;
    replays: number;
    events: number;
  };
  recent_incidents: Incident[];
  recent_runs: Run[];
  policy: { version: number; name: string; rule_count: number; disabled_tools: string[]; change_summary: string; created_at: string };
  sync: { local: { status: string; label: string }; cloud: { status: string; label: string } };
}

export interface VaultFile {
  path: string;
  sha256: string;
  size_bytes: number;
  snapshot_count: number;
  matches_original: boolean;
  matching_snapshot_ids: string[];
}

export interface Snapshot {
  snapshot_id: string;
  file_path: string;
  version: number;
  sha256: string;
  size_bytes: number;
  reason: string;
  created_at: string;
  content?: string;
  store_integrity_ok?: boolean;
  current_sha256?: string;
  diff_to_current?: string;
}

export interface RestoreResult {
  snapshot: Snapshot;
  path: string;
  before_sha256: string;
  expected_sha256: string;
  restored_sha256: string;
  verified: boolean;
  pre_restore_backup: Snapshot;
  note: string;
}

export interface EventPage {
  total: number;
  limit: number;
  offset: number;
  events: AfterEvent[];
}

export interface SettingsInfo {
  version: string;
  database: { engine: string; file: string; size_bytes: number; events: number; hash_chain: ChainStatus };
  demo_environment: { synthetic_only: boolean; vault_files: string[]; scenarios: string[]; policy_changes: string[]; run_workspaces: number; llm: string };
  cors_origins: string[];
  cloud_sync: { status: string; detail: string };
  archives: string[];
  reset_phrase: string;
}

export interface ChainStatus {
  valid: boolean;
  checked: number;
  first_invalid_event_id: string | null;
  reason: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function newIdempotencyKey(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return "ui-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method === "POST") headers["Idempotency-Key"] = newIdempotencyKey();
  let response: Response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Cannot reach the AFTERIMAGE backend. Is it running on port 8000?");
  }
  const text = await response.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const message = typeof detail === "string" ? detail
      : Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg ?? "invalid").join("; ")
      : `Request failed (${response.status})`;
    throw new ApiError(response.status, message);
  }
  return data as T;
}

const get = <T,>(path: string) => request<T>("GET", path);
const post = <T,>(path: string, body: unknown = {}) => request<T>("POST", path, body);

export const api = {
  health: () => get<{ status: string; version: string }>("/api/health"),
  dashboard: () => get<Dashboard>("/api/dashboard"),
  runs: () => get<Run[]>("/api/runs"),
  run: (id: string) => get<Run>(`/api/runs/${id}`),
  runEvents: (id: string) => get<AfterEvent[]>(`/api/runs/${id}/events`),
  startRun: (scenario: "benign" | "attack") => post<Run>(`/api/runs/${scenario}`),
  incidents: () => get<Incident[]>("/api/incidents"),
  incident: (id: string) => get<IncidentReport>(`/api/incidents/${id}`),
  incidentEvents: (id: string) => get<AfterEvent[]>(`/api/incidents/${id}/events`),
  incidentGraph: (id: string) => get<IncidentGraph>(`/api/incidents/${id}/graph`),
  annotate: (id: string, text: string, status?: string) => post<AfterEvent>(`/api/incidents/${id}/notes`, { text, status }),
  policies: () => get<PoliciesResponse>("/api/policies"),
  previewPolicy: (change_ids: string[]) => post<PolicyPreview>("/api/policies/preview", { change_ids }),
  applyPolicy: (change_ids: string[], base_version: number) =>
    post<PolicyDescription>("/api/policies/apply", { change_ids, base_version, confirm: true }),
  revertPolicy: (target_version: number, base_version: number) =>
    post<PolicyDescription>("/api/policies/revert", { target_version, base_version, confirm: true }),
  replays: () => get<Replay[]>("/api/replays"),
  replay: (id: string) => get<Replay>(`/api/replays/${id}`),
  createReplay: (body: { incident_id?: string; baseline_run_id?: string }) => post<Replay>("/api/replays", body),
  vaultFiles: () => get<VaultFile[]>("/api/recovery/files"),
  simulateChange: (path: string) => post<{ path: string; snapshot: Snapshot; modified_sha256: string }>("/api/recovery/simulate-change", { path }),
  snapshots: () => get<Snapshot[]>("/api/snapshots"),
  snapshot: (id: string) => get<Snapshot>(`/api/snapshots/${id}`),
  createSnapshot: (path: string, reason: string) => post<Snapshot>("/api/snapshots", { path, reason }),
  restoreSnapshot: (id: string) => post<RestoreResult>(`/api/snapshots/${id}/restore`, { confirm: true }),
  events: (params: Record<string, string | number | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    return get<EventPage>(`/api/events?${qs.toString()}`);
  },
  eventFacets: () => get<{ event_types: string[]; outcomes: string[]; runs: string[]; incidents: string[] }>("/api/events/facets"),
  verifyChain: () => get<ChainStatus>("/api/events/verify"),
  settings: () => get<SettingsInfo>("/api/settings"),
  reset: (mode: "demo" | "full", confirm_text: string) => post<Record<string, unknown>>("/api/settings/reset", { mode, confirm_text }),
};
