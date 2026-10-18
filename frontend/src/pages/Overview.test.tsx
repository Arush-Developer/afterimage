import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { Overview } from "./Overview";

const dashboard = (incidents: number, blocked: number) => ({
  metrics: { runs: incidents ? 1 : 0, scenario_runs: incidents ? 1 : 0, replay_runs: 0, incidents, unauthorized_blocked: blocked,
    denied_total: blocked, exposures: 0, verified_replays: 0, replays: 0, events: 0 },
  recent_incidents: [], recent_runs: [],
  policy: { version: 1, name: "Baseline demo policy", rule_count: 3, disabled_tools: [], change_summary: "Baseline demo policy", created_at: "2026-01-01T00:00:00Z" },
  sync: { local: { status: "ok", label: "Local SQLite database" }, cloud: { status: "not_configured", label: "Cloud sync not configured" } },
});

const attackRun = {
  run_id: "run_0123456789abcdef", scenario: "attack", scenario_title: "Controlled attack simulation", kind: "scenario",
  status: "completed", policy_version: 1, started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:01Z",
  task_completed: true, sensitive_exposed: false, output_summary: "", incident_id: "inc_0123456789abcdef", simulated_attack: true,
  result: { files_read: [], failed_required_reads: [], output_written: true, output_path: "out/summary.md", followed_instructions: [], tool_calls: 9, denied_calls: 2, exposure_event_ids: [] },
};

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

describe("Overview", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders metrics from the backend and runs the attack through the API", async () => {
    let calls = 0;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/dashboard")) return json(calls++ === 0 ? dashboard(0, 0) : dashboard(1, 2));
      if (url.endsWith("/api/runs/attack") && init?.method === "POST") return json(attackRun, 201);
      return json({}, 404);
    });
    render(<MemoryRouter><Overview /></MemoryRouter>);
    expect(await screen.findByText("No incidents yet")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Simulate Attack" }));
    expect(await screen.findByText("Controlled attack simulation")).toBeInTheDocument();
    expect(screen.getByText(/Denied requests/)).toHaveTextContent("Denied requests: 2");
    expect(screen.getByRole("button", { name: /Investigate incident/ })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Unauthorized requests blocked").parentElement?.parentElement).toHaveTextContent("2"));

    const post = fetchMock.mock.calls.find(([u]) => String(u).endsWith("/api/runs/attack"));
    expect((post?.[1]?.headers as Record<string, string>)["Idempotency-Key"]).toMatch(/^ui-[0-9a-f]{24}$/);
  });

  it("shows an error state when the backend is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network"));
    render(<MemoryRouter><Overview /></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot reach the AFTERIMAGE backend");
  });
});
