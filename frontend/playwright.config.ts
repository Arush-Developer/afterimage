import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// The e2e suite starts its own backend (port 8001, throw-away data dir) and frontend (port 5174),
// so it never touches your development database.
const dataDir = mkdtempSync(join(tmpdir(), "afterimage-e2e-"));
const python = process.env.AFTERIMAGE_PYTHON ?? (process.platform === "win32" ? "..\\backend\\.venv\\Scripts\\python" : "../backend/.venv/bin/python");
// The mock server runs from frontend/, so resolve the venv python relative to this file.
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_PATH; // optional: use a pre-installed Chromium

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    viewport: { width: 1440, height: 900 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, launchOptions: executablePath ? { executablePath } : {} } }],
  webServer: [
    {
      // Mock Gemini + Ollama APIs (no real model, no key). See e2e/mock_providers.py.
      command: `${python} e2e/mock_providers.py 8099`,
      url: "http://127.0.0.1:8099/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `${python} -m uvicorn afterimage.main:create_app --factory --port 8001`,
      cwd: "../backend",
      url: "http://127.0.0.1:8001/api/health",
      env: {
        AFTERIMAGE_DATA_DIR: dataDir,
        AFTERIMAGE_CORS_ORIGINS: "http://127.0.0.1:5174",
        // Point the real Gemini SDK and the Ollama adapter at the local mock.
        AFTERIMAGE_GEMINI_BASE_URL: "http://127.0.0.1:8099",
        GEMINI_API_KEY: "AIzaFAKE-e2e-key",
        AFTERIMAGE_GEMINI_RATE_LIMIT_RETRIES: "0",
        AFTERIMAGE_OLLAMA_HOST: "http://127.0.0.1:8099",
        ANTHROPIC_API_KEY: "",
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx vite --host 127.0.0.1 --port 5174",
      url: "http://127.0.0.1:5174",
      env: { AFTERIMAGE_API_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
