import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Settings } from "./Settings";

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

const FAKE_KEY = "fake-gemini-key-for-tests-0123456789";

function settingsResponse(geminiSource: "saved" | null) {
  const provider = (name: string, label: string, configured: boolean, key_source: string | null = null) => ({
    provider: name, label, real: name !== "simulated", local: name === "ollama" || name === "simulated", billing: "none",
    configured, default_model: "m", detail: `${label} detail`, key_source,
  });
  return {
    version: "0.1.0",
    database: { engine: "SQLite", file: "afterimage.db", size_bytes: 1024, events: 0,
      hash_chain: { valid: true, checked: 0, first_invalid_event_id: null, reason: null } },
    demo_environment: { synthetic_only: true, vault_files: [], scenarios: [], policy_changes: [], run_workspaces: 0,
      scripted_agent: "deterministic" },
    llm: {
      default_provider: "anthropic", default_model: null,
      models: { anthropic: "claude-opus-5-5", gemini: "gemini-3.8-flash", ollama: "llama3.1", simulated: "simulated-agent" },
      ollama_host: "http://127.0.0.1:11434", ollama_local_only: true, effort: "medium", max_steps: 12, max_tokens: 16000,
      timeout_s: 120, max_trials: 5, note: "",
      providers: [
        provider("anthropic", "Anthropic Claude", false),
        provider("gemini", "Google Gemini", geminiSource !== null, geminiSource),
        provider("ollama", "Ollama (local)", false),
        provider("simulated", "Simulated agent (no LLM)", true),
      ],
    },
    cors_origins: [], cloud_sync: { status: "not_configured", detail: "" }, archives: [],
    incident_statuses: [], reset_phrase: "ARCHIVE AND RESET",
  };
}

describe("Settings API key entry", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends a Gemini key to the backend once, then shows only its status", async () => {
    let saved = false;
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/keys/gemini" && init?.method === "POST") {
        saved = true;
        return json({ provider: "gemini", present: true, source: "saved" });
      }
      return json(settingsResponse(saved ? "saved" : null));
    });
    const user = userEvent.setup();
    render(<Settings />);

    await user.click(await screen.findAllByRole("button", { name: "Add API key" }).then((b) => b[1]));
    const input = screen.getByLabelText("Google Gemini API key");
    expect(input).toHaveAttribute("type", "password");
    await user.type(input, FAKE_KEY);
    await user.click(screen.getByRole("button", { name: "Save key" }));

    await waitFor(() => expect(screen.getByText(/key saved on this computer/)).toBeInTheDocument());
    const post = fetchMock.mock.calls.find(([url]) => String(url) === "/api/keys/gemini")!;
    expect(JSON.parse(String(post[1]!.body))).toEqual({ api_key: FAKE_KEY, remember: true });
    expect(screen.queryByLabelText("Google Gemini API key")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(FAKE_KEY);
    expect(screen.getByRole("button", { name: "Replace API key" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove key" })).toBeInTheDocument();
  });

  it("shows the backend's validation error and keeps the form open", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) =>
      String(input) === "/api/keys/anthropic" && init?.method === "POST"
        ? json({ detail: "that does not look like an API key (expected 20-512 characters)", code: "invalid_request" }, 400)
        : json(settingsResponse(null)));
    const user = userEvent.setup();
    render(<Settings />);

    await user.click((await screen.findAllByRole("button", { name: "Add API key" }))[0]);
    await user.type(screen.getByLabelText("Anthropic Claude API key"), "short");
    await user.click(screen.getByRole("button", { name: "Save key" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/does not look like an API key/);
    expect(screen.getByLabelText("Anthropic Claude API key")).toBeInTheDocument();
  });
});
