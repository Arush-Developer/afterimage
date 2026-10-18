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

const experiment = {
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

  it("runs an experiment and shows an honest baseline-vs-protected verdict", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/providers")) return json(providers);
      if (url.endsWith("/api/experiments") && init?.method === "POST") return json(experiment, 201);
      if (url.endsWith("/api/experiments")) return json([]);
      return json({}, 404);
    });
    render(<MemoryRouter><ExperimentLab /></MemoryRouter>);
    await screen.findByText("Configure");
    // simulated is the default and is configured, so the run button is enabled
    await userEvent.click(screen.getByRole("button", { name: /Run experiment/ }));
    const verdict = await screen.findByTestId("experiment-verdict");
    expect(verdict).toHaveTextContent("Protected");
    expect(verdict).toHaveTextContent("Blocked in every protected trial");

    // baseline column (first) shows a leak, protected column (second) shows none
    const [baselineRow, protectedRow] = screen.getAllByText("Fake secret leaked").map((el) => el.parentElement!);
    expect(baselineRow).toHaveTextContent("1 / 1");
    expect(protectedRow).toHaveTextContent("0 / 1");

    const post = fetchMock.mock.calls.find(([u, i]) => String(u).endsWith("/api/experiments") && (i as RequestInit)?.method === "POST");
    expect(JSON.parse((post![1] as RequestInit).body as string)).toMatchObject({ provider: "simulated", trials: 1 });
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
});
