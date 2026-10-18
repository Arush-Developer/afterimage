import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ProviderPicker } from "./components/ProviderPicker";
import { RunKindBadge } from "./components/ui";
import { ExperimentLab } from "./pages/ExperimentLab";
import { explainProviderError } from "./providers";

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

const providers = {
  providers: [
    { provider: "anthropic", label: "Anthropic Claude", real: true, local: false, billing: "paid", configured: false, default_model: "claude-opus-5-5", detail: "Set ANTHROPIC_API_KEY." },
    { provider: "gemini", label: "Google Gemini", real: true, local: false, billing: "free tier or paid", configured: true, default_model: "gemini-2.5-flash", detail: "GEMINI_API_KEY detected (value never shown)." },
    { provider: "ollama", label: "Ollama (local)", real: true, local: true, billing: "local", configured: false, default_model: "llama3.1", detail: "not reachable" },
    { provider: "simulated", label: "Simulated agent (no LLM)", real: false, local: true, billing: "none", configured: true, default_model: "simulated-agent", detail: "Not a language model." },
  ],
  default_provider: "gemini",
  default_models: { anthropic: "claude-opus-5-5", gemini: "gemini-2.5-flash", ollama: "llama3.1", simulated: "simulated-agent" },
  configured_model: null, max_trials: 5, max_steps: 12,
} as const;

describe("provider error explanations", () => {
  it("explains Gemini quota exhaustion and promises no silent fallback", () => {
    const help = explainProviderError("provider_quota_exhausted", "gemini")!;
    expect(help.title).toBe("Gemini quota exhausted");
    expect(help.tips.join(" ")).toMatch(/free-tier quotas/);
    expect(help.tips.join(" ")).toMatch(/never switches to a different provider/);
  });
  it("includes the retry delay for rate limits", () => {
    expect(explainProviderError("rate_limit", "gemini", 37)!.tips[0]).toMatch(/about 37s/);
  });
  it("explains Ollama models without tool support", () => {
    expect(explainProviderError("tools_unsupported", "ollama")!.title).toBe("Model cannot call tools");
  });
  it("returns null for unknown codes", () => {
    expect(explainProviderError("internal_error", "gemini")).toBeNull();
  });
});

describe("RunKindBadge", () => {
  it.each([
    [{ agent_kind: "llm", provider: "gemini", model: "gemini-2.5-flash", provider_real: true }, "Gemini · gemini-2.5-flash"],
    [{ agent_kind: "llm", provider: "ollama", model: "llama3.1", provider_real: true }, "Ollama · local · llama3.1"],
    [{ agent_kind: "llm", provider: "anthropic", model: "claude-opus-5-5", provider_real: true }, "Claude · claude-opus-5-5"],
    [{ agent_kind: "llm", provider: "simulated", model: "simulated-agent", provider_real: false }, "simulated · simulated-agent"],
    [{ agent_kind: "scripted" }, "scripted"],
  ])("labels %o", (run, label) => {
    render(<RunKindBadge run={run} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});

describe("ProviderPicker", () => {
  afterEach(() => vi.restoreAllMocks());

  it("lists Gemini with its cloud/billing label and runs a live check without exposing secrets", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => json({
      provider: "gemini", label: "Google Gemini", model: "gemini-2.5-flash", configured: true, reachable: true,
      model_available: true, tool_calling: "unknown", detail: "Model 'gemini-2.5-flash' is available to this key.",
      checked_at: "2026-01-01T00:00:00Z",
    }));
    const onChange = vi.fn();
    render(<ProviderPicker data={providers as never} value={{ provider: "gemini", model: "gemini-2.5-flash" }} onChange={onChange} />);
    expect(screen.getByRole("button", { name: /Google Gemini/ })).toHaveTextContent("cloud · free tier or paid");
    expect(screen.getByRole("button", { name: /Ollama \(local\)/ })).toHaveTextContent("local inference");
    expect(screen.getByRole("button", { name: /Simulated agent/ })).toHaveTextContent("simulated · not an LLM");

    await userEvent.click(screen.getByRole("button", { name: "Check" }));
    const result = await screen.findByTestId("provider-check");
    expect(result).toHaveTextContent("model gemini-2.5-flash available");
    expect(result).toHaveTextContent("tool calling: unknown");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/providers/gemini/check?model=gemini-2.5-flash");

    await userEvent.click(screen.getByRole("button", { name: /Ollama \(local\)/ }));
    expect(onChange).toHaveBeenCalledWith({ provider: "ollama", model: "llama3.1" });
  });
});

describe("ExperimentLab quota handling", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows an understandable quota notice when Gemini refuses to start", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/api/providers")) return json(providers);
      if (url.endsWith("/api/experiments") && init?.method === "POST") {
        return json({ detail: "Gemini quota exhausted for model 'gemini-2.5-flash'.", code: "provider_quota_exhausted", retry_after_s: 40 }, 429);
      }
      if (url.endsWith("/api/experiments")) return json([]);
      return json({}, 404);
    });
    render(<MemoryRouter><ExperimentLab /></MemoryRouter>);
    await screen.findByText("Configure");
    await userEvent.click(screen.getByRole("button", { name: /Run experiment/ }));
    const notice = await screen.findByTestId("provider-error");
    expect(notice).toHaveTextContent("Gemini quota exhausted");
    expect(notice).toHaveTextContent(/enable billing/);
    expect(notice).toHaveTextContent(/never switches to a different provider/);
    expect(screen.queryByTestId("experiment-verdict")).toBeNull();
  });
});
