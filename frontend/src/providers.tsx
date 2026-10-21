import { AlertTriangle } from "lucide-react";
import { Badge } from "./components/ui";

/** Display metadata per provider. "cloud" providers send prompts off this machine. */
export const PROVIDER_META: Record<string, { short: string; where: "cloud" | "local" | "simulated"; billing: string }> = {
  anthropic: { short: "Claude", where: "cloud", billing: "paid API" },
  gemini: { short: "Gemini", where: "cloud", billing: "free tier or paid (per Google project)" },
  ollama: { short: "Ollama", where: "local", billing: "runs locally" },
  simulated: { short: "simulated", where: "simulated", billing: "no model" },
};

export function ProviderWhereBadge({ provider }: { provider: string }) {
  const meta = PROVIDER_META[provider];
  if (!meta) return null;
  if (meta.where === "simulated") return <Badge tone="warn">simulated · not an LLM</Badge>;
  if (meta.where === "local") return <Badge tone="good">local inference</Badge>;
  return <Badge tone="accent">cloud · {meta.billing}</Badge>;
}

interface Explanation {
  title: string;
  tips: string[];
}

/** Turn a provider error code (e.g. "provider_quota_exhausted" or "quota_exhausted") into
 *  plain-language guidance. Returns null for codes that need no extra help. */
export function explainProviderError(code?: string | null, provider?: string | null, retryAfterS?: number | null): Explanation | null {
  const kind = (code ?? "").replace(/^provider_/, "");
  const name = PROVIDER_META[provider ?? ""]?.short ?? "The provider";
  const noFallback = "AFTERIMAGE never switches to a different provider automatically.";
  switch (kind) {
    case "quota_exhausted":
      return {
        title: `${name} quota exhausted`,
        tips: [
          provider === "gemini"
            ? "Gemini free-tier quotas are counted per Google project and per model, and daily quotas reset once a day."
            : "The provider reports that your usage quota is used up.",
          "Wait for the quota to reset, pick a different model in the Model field, or enable billing on your project.",
          noFallback,
        ],
      };
    case "rate_limit":
      return {
        title: `${name} rate limit reached`,
        tips: [
          `Too many requests per minute.${retryAfterS ? ` The provider asked to wait about ${Math.ceil(retryAfterS)}s.` : ""}`,
          "Free-tier per-minute limits are low; one experiment trial can make up to two dozen model calls. Use fewer trials or wait and retry.",
          noFallback,
        ],
      };
    case "missing_credentials":
      return { title: `${name} is not configured`, tips: ["Add the API key in Settings → LLM agent configuration, or set it in the backend environment and restart the backend.", noFallback] };
    case "invalid_credentials":
      return { title: `${name} rejected the API key`, tips: ["Check that the key (added in Settings or set in the backend environment) is valid and not revoked."] };
    case "model_unavailable":
      return {
        title: "Model not available",
        tips: [provider === "ollama"
          ? "Pull the model first (ollama pull <model>) or choose an installed one."
          : "This model is not available to your key, project or tier. Choose another model and use Check to verify it."],
      };
    case "tools_unsupported":
      return { title: "Model cannot call tools", tips: ["AFTERIMAGE's agent needs tool calling. Choose a tool-capable model (for Ollama, e.g. llama3.1 or qwen2.5)."] };
    case "account_unsupported":
      return { title: "Not available for this account or region", tips: ["The provider refused the request for this account or location."] };
    case "connection":
      return {
        title: `Cannot reach ${name}`,
        tips: [provider === "ollama" ? "Start the local server with `ollama serve` and check AFTERIMAGE_OLLAMA_HOST." : "Check the backend's network access to the provider."],
      };
    case "timeout":
      return { title: `${name} timed out`, tips: ["Retry, or raise AFTERIMAGE_LLM_TIMEOUT_S for slow models."] };
    default:
      return null;
  }
}

export function ProviderErrorNotice({ message, code, provider, retryAfterS }: {
  message: string; code?: string | null; provider?: string | null; retryAfterS?: number | null;
}) {
  const help = explainProviderError(code, provider, retryAfterS);
  return (
    <div role="alert" data-testid="provider-error" className="mt-3 rounded-lg border border-amber-400/30 bg-amber-500/10 p-3 text-sm text-amber-50">
      <div className="flex items-center gap-2 font-medium">
        <AlertTriangle className="size-4 shrink-0 text-amber-300" aria-hidden />
        {help?.title ?? "Provider error"}
      </div>
      <p className="mt-1 text-amber-100/90">{message}</p>
      {help && <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs text-amber-100/80">{help.tips.map((t) => <li key={t}>{t}</li>)}</ul>}
    </div>
  );
}
