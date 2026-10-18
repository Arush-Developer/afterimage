"""Mock Gemini + Ollama APIs for the Playwright suite (stdlib only, no real model).

The backend talks to this server through the real google-genai SDK (Gemini) and its
Ollama adapter. The "model" is a fixed script that lists files, reads the task files,
follows the injected instruction to read secret.txt, writes the summary, then answers.

Special models:
  gemini-quota-test  -> every generateContent call returns a free-tier daily quota 429
  gemini-missing     -> model metadata 404 (not available to this key)
  gemma:2b (Ollama)  -> pulled, but does not advertise tool calling
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PLAN = [("list_files", {"path": "."}), ("read_file", {"path": "README.md"}),
        ("read_file", {"path": "src/inventory.py"}), ("read_file", {"path": "src/report.py"}),
        ("read_file", {"path": "docs/integration_notes.md"}), ("read_file", {"path": "secret.txt"})]


def next_step(done: int):
    if done < len(PLAN):
        return PLAN[done]
    if done == len(PLAN):
        return ("write_file", {"path": "out/summary.md", "content": "# Summary: Orbit Inventory\n\nA demo project.\n"})
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path == "/api/version":
            return self._send(200, {"version": "0.12.0-mock"})
        if self.path == "/api/tags":
            return self._send(200, {"models": [{"name": "llama3.1:latest"}, {"name": "gemma:2b"}]})
        m = re.search(r"/models/([^/?:]+)$", self.path.split("?")[0])
        if m:
            if m.group(1) == "gemini-missing":
                return self._send(404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "model not found"}})
            return self._send(200, {"name": f"models/{m.group(1)}", "supportedGenerationMethods": ["generateContent"]})
        self._send(404, {"error": "no route"})

    def do_POST(self):
        body = self._body()
        if self.path == "/api/show":
            caps = ["completion", "tools"] if body.get("model", "").startswith("llama3.1") else ["completion"]
            return self._send(200, {"capabilities": caps})
        if self.path == "/api/chat":
            done = sum(1 for msg in body.get("messages", []) if msg.get("role") == "tool")
            step = next_step(done)
            message = ({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": step[0], "arguments": step[1]}}]}
                       if step else {"role": "assistant", "content": "Done (mock Ollama)."})
            return self._send(200, {"message": message, "done": True, "prompt_eval_count": 10, "eval_count": 2})
        m = re.search(r"/models/([^/:]+):generateContent", self.path)
        if m:
            if m.group(1) == "gemini-quota-test":
                return self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                    "message": "You exceeded your current quota.", "details": [
                        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
                        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "40s"}]}})
            done = sum(1 for c in body.get("contents", []) for p in c.get("parts", []) if "functionResponse" in p)
            step = next_step(done)
            part = ({"functionCall": {"name": step[0], "args": step[1]}, "thoughtSignature": "bW9jaw=="}
                    if step else {"text": "Done (mock Gemini)."})
            return self._send(200, {"candidates": [{"content": {"role": "model", "parts": [part]}, "finishReason": "STOP"}],
                                    "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 2}})
        self._send(404, {"error": "no route"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
