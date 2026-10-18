import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { EventGraph } from "./EventGraph";
import type { IncidentGraph } from "../api";

const node = (id: string, column: number, category: "denied" | "suspicious", label: string) => ({
  id, label, event_type: "policy_decision", category, outcome: "denied", severity: "high" as const, timestamp: "2026-01-01T00:00:00Z",
  resource_id: "secret.txt", actor: "gw", summary: "", policy_decision_id: null, evidence_metadata: {}, column, row: 0,
});

describe("EventGraph", () => {
  it("renders one node per event with a non-colour category label and reports clicks", async () => {
    const graph: IncidentGraph = {
      incident_id: "inc_x", derived_from: "test", is_dag: true,
      nodes: [node("evt_a", 0, "suspicious", "Request read_file secret.txt"), node("evt_b", 1, "denied", "DENIED (POL-X)")],
      edges: [{ source: "evt_a", target: "evt_b", relation: "evaluated by gateway" }],
    };
    const onSelect = vi.fn();
    render(<EventGraph graph={graph} onSelect={onSelect} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[1]).toHaveAccessibleName(/^Denied: DENIED \(POL-X\)/);
    await userEvent.click(buttons[1]);
    expect(onSelect).toHaveBeenCalledWith("evt_b");
  });
});
