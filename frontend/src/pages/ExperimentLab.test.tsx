import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ExperimentLab } from "./ExperimentLab";

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

const providers = {
  providers: [
    { provider: "anthropic", label: "Anthropic Claude", real: true, configured: false, default_model: "claude-opus-5-5", detail: "Set ANTHROPIC_API_KEY." },
    { provider: "simulated", label: "Simulated agent (no LLM)", real: false, configured: true, default_model: "simulated-agent", detail: "Rule-based stand-in." },
  ],
  default_provider: "simulated", default_models: { anthropic: "claude-opus-5-5", simulated: "simulated-agent" },
  configured_model: null, max_trials: 5, max_steps: 12,
};

const progress = { total_runs: 2, runs: [
  { run_id: "run_000000000000000a", enforcement: "baseline", status: "completed", started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:01Z" },
  { run_id: "run_000000000000000b", enforcement: "protected", status: "completed", started_at: "2026-01-01T00:00:02Z", completed_at: "2026-01-01T00:00:03Z" },
] };

const experiment = {
  progress,
  experiment_id: "exp_0123456789abcdef", created_at: "2026-01-01T00:00:00Z", provider: "simulated",
  model: "simulated-agent", provider_real: false, trials: 1, status: "protected", task: "t",
  report: {
    verdict: "protected", headline: "Blocked in every protected trial.", provider: "simulated",
    model: "simulated-agent", provider_real: false, trials: 1, attack_reproduced_in_baseline: true,
    protection_held: true,
    baseline: { trials: 1, completed_trials: 1, errored_trials: 0, restricted_file_requested: 1, restricted_content_returned: 1, secret_leaked: 1, legitimate_task_completed: 1, run_ids: ["run_000000000000000a"] },
    protected: { trials: 1, completed_trials: 1, errored_trials: 0, restricted_file_requested: 1, restricted_content_returned: 0, secret_leaked: 0, legitimate_task_completed: 1, run_ids: ["run_000000000000000b"] },
    baseline_trials: [], protected_trials: [], notes: ["simulated agent used"], ground_truth: "judged independently",
  },
};

describe("ExperimentLab", () => {
  afterEach(() => vi.restoreAllMocks());

  it("runs in the background, shows live progress, then an honest verdict", async () => {
    const running = {
      ...experiment, status: "running", report: {},
      progress: { total_runs: 2, runs: [{ ...progress.runs[0], status: "running", completed_at: null }] },
    };
    const decision = {
      event_id: "evt_0000000000000001", run_id: "run_000000000000000a", incident_id: null, timestamp: "2026-01-01T00:00:00Z",
      event_type: "policy_decision", actor: "policy-gateway", action: "read_file", resource_id: "secret.txt",
      source_event_id: null, policy_decision_id: "dec_0000000000000001", outcome: "allowed", severity: "high",
      summary: "", evidence_metadata: { rule_id: "BASELINE-ALLOW-ALL" }, prev_hash: "", event_hash: "",
    };
    let gets = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/providers")) return json(providers);
      if (url.endsWith("/api/experiments") && init?.method === "POST") return json(running, 201);
      if (url.endsWith("/api/experiments")) return json([]);
      if (url.endsWith(`/api/experiments/${experiment.experiment_id}`)) return json(gets++ === 0 ? running : experiment);
      if (url.endsWith("/api/runs/run_000000000000000a/events")) return json([decision]);
      return json({}, 404);
    });
    render(<MemoryRouter><ExperimentLab /></MemoryRouter>);
    await screen.findByText("Configure");
    // simulated is the default and is configured, so the run button is enabled
    await userEvent.click(screen.getByRole("button", { name: /Run experiment/ }));
    // Live progress shows only backend-recorded state: the running run and its persisted decision.
    const live = await screen.findByTestId("live-progress");
    expect(live).toHaveTextContent("0 of 2 isolated run(s) finished");
    expect(await screen.findByText("BASELINE-ALLOW-ALL")).toBeInTheDocument();
    expect(screen.queryByTestId("experiment-verdict")).toBeNull(); // no result before the backend has one
    const verdict = await screen.findByTestId("experiment-verdict", {}, { timeout: 4000 });
    expect(verdict).toHaveTextContent("Protected");
    expect(verdict).toHaveTextContent("Blocked in every protected trial");

    // baseline column (first) shows a leak, protected column (second) shows none
    const [baselineRow, protectedRow] = screen.getAllByText("Fake secret leaked").map((el) => el.parentElement!);
    expect(baselineRow).toHaveTextContent("1 / 1");
    expect(protectedRow).toHaveTextContent("0 / 1");

    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/api/experiments") && (i as RequestInit)?.method === "POST");
    expect(JSON.parse((post![1] as RequestInit).body as string)).toMatchObject({ provider: "simulated", trials: 1, background: true });
  });

  it("disables the run button when the chosen provider is not configured", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/providers")) return json(providers);
      if (url.endsWith("/api/experiments")) return json([]);
      return json({}, 404);
    });
    render(<MemoryRouter><ExperimentLab /></MemoryRouter>);
    await screen.findByText("Configure");
    await userEvent.click(screen.getByRole("button", { name: /Anthropic Claude/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Run experiment/ })).toBeDisabled());
    expect(screen.getByText(/is not configured/)).toBeInTheDocument();
  });
  it("shows an inconclusive verdict, not a security claim, when every trial errored", async () => {
    const errored = { ...experiment.report.baseline, completed_trials: 0, errored_trials: 1, restricted_file_requested: 0,
      restricted_content_returned: 0, secret_leaked: 0, legitimate_task_completed: 0 };
    const inconclusive = { ...experiment, status: "inconclusive", report: { ...experiment.report, verdict: "inconclusive",
      headline: "Inconclusive: 1 baseline and 1 protected trial(s) ended with a provider error.",
      attack_reproduced_in_baseline: false, protection_held: false, baseline: errored, protected: errored } };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/api/providers")) return json(providers);
      if (url.endsWith("/api/experiments")) return json([]);
      if (url.endsWith(`/api/experiments/${experiment.experiment_id}`)) return json(inconclusive);
      return json({}, 404);
    });
    render(<MemoryRouter initialEntries={[`/experiment?id=${experiment.experiment_id}`]}><ExperimentLab /></MemoryRouter>);
    const verdict = await screen.findByTestId("experiment-verdict");
    expect(verdict).toHaveTextContent("Inconclusive");
    expect(verdict).not.toHaveTextContent("Attack not reproduced");
    expect(verdict).not.toHaveTextContent("Protected");
  });
});
