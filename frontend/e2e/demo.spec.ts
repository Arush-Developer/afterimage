import { expect, test, type Page } from "@playwright/test";

const shots = process.env.E2E_SCREENSHOTS; // optional directory for screenshots

async function snap(page: Page, name: string) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
}

test("full demo: observe → enforce → investigate → remediate → replay → verify → recover", async ({ page }) => {
  // Overview starts empty with backend-derived metrics.
  await page.goto("/");
  await expect(page.getByText("Backend connected")).toBeVisible();
  await expect(page.getByText("No incidents yet")).toBeVisible();

  // Scenario A — safe run.
  await page.getByRole("button", { name: "Run Safe Scenario" }).click();
  const last = page.getByTestId("last-run");
  await expect(last).toContainText("Safe scenario");
  await expect(last).toContainText("completed");
  await expect(last).toContainText("No unauthorized access was recorded");

  // Scenario B — simulated attack.
  await page.getByRole("button", { name: "Simulate Attack" }).click();
  await expect(last).toContainText("Controlled attack simulation");
  await expect(last).toContainText("Denied requests: 2");
  await snap(page, "01-overview");

  // Scenario C — investigation.
  await page.getByRole("button", { name: "Investigate incident" }).click();
  await expect(page.getByRole("heading", { name: /Blocked attempt to access secret.txt/ })).toBeVisible();
  await expect(page.getByText("POL-DENY-SECRET-FILE").first()).toBeVisible();
  await expect(page.getByText("AI-BOUNDARY-001").first()).toBeVisible();
  await expect(page.getByText(/controlled simulated attack/i)).toBeVisible();
  const graph = page.getByRole("group", { name: "Evidence graph of recorded events" });
  await expect(graph.getByRole("button")).toHaveCount(12);
  await graph.getByRole("button", { name: /Incident recorded/ }).click();
  await expect(page.getByText("Incident recorded:").first()).toBeVisible();
  await snap(page, "02-investigation");

  // Scenario D — remediation.
  await page.getByRole("button", { name: "Review policy change" }).click();
  await expect(page.getByRole("checkbox", { name: /Restrict read access/ })).toBeChecked();
  await expect(page.getByRole("checkbox", { name: /Deny the whole class/ })).toBeChecked();
  await page.getByRole("button", { name: "Preview change" }).click();
  await expect(page.getByText("Proposed policy (v2)")).toBeVisible();
  await snap(page, "03-policy-preview");
  await page.getByRole("button", { name: "Apply as v2…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Apply policy" }).click();
  await expect(page.getByText(/Policy v2 is now active and enforced/)).toBeVisible();

  // Scenario E — replay & verify.
  await page.getByRole("button", { name: "Replay to verify" }).click();
  await expect(page.getByText("Active policy v2")).toBeVisible();
  await page.getByRole("button", { name: "Run replay" }).click();
  const status = page.getByTestId("replay-status");
  await expect(status).toContainText("Verified");
  await expect(page.getByText("POL-DENY-SECRET-CLASS").first()).toBeVisible();
  await snap(page, "04-replay");

  // Persisted after refresh.
  await page.reload();
  await expect(page.getByTestId("replay-status")).toContainText("Verified");

  // Regression path: disabling write_file blocks the attack but breaks the task -> not verified.
  await page.goto("/policies");
  await page.getByRole("checkbox", { name: /Disable write_file/ }).check();
  await page.getByRole("button", { name: "Preview change" }).click();
  await expect(page.getByText(/Legitimate operation would be denied/).first()).toBeVisible();
  await page.getByRole("button", { name: "Apply as v3…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Apply policy" }).click();
  await page.getByRole("button", { name: "Replay to verify" }).click();
  await page.getByRole("button", { name: "Run replay" }).click();
  await expect(page.getByTestId("replay-status")).toContainText("regression");

  // Scenario F — recovery.
  await page.goto("/recovery");
  await page.getByRole("button", { name: "Simulate unauthorized edit" }).click();
  await expect(page.getByRole("heading", { name: "Snapshot v1" })).toBeVisible();
  await page.getByRole("button", { name: "Restore this version…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Restore file" }).click();
  await expect(page.getByTestId("restore-result")).toContainText("Restored and hash-verified");
  await snap(page, "05-recovery");

  // Event explorer & settings show real data.
  await page.goto("/events?outcome=denied");
  await expect(page.getByText(/Hash chain intact/)).toBeVisible();
  await snap(page, "06-events");
  await page.goto("/settings");
  await expect(page.getByText("Synthetic only (fictional project, fake secret)")).toBeVisible();
  await snap(page, "07-settings");
});

test("secret content never reaches the browser", async ({ page }) => {
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/api/")) bodies.push(await r.text().catch(() => ""));
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Simulate Attack" }).click();
  await page.getByRole("button", { name: "Investigate incident" }).click();
  await expect(page.getByText("Evidence graph")).toBeVisible();
  await page.goto("/events");
  await expect(page.getByText(/Hash chain intact/)).toBeVisible();
  const all = bodies.join("\n") + (await page.content());
  expect(all).not.toContain("AFTERIMAGE-CANARY-");
  expect(all).not.toContain("SYNTHETIC DEMO SECRET");
});

test("injection lab: baseline vs protected with the simulated agent (no API key)", async ({ page }) => {
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/api/")) bodies.push(await r.text().catch(() => ""));
  });
  await page.goto("/experiment");
  await expect(page.getByRole("heading", { name: "Prompt-injection experiment" })).toBeVisible();
  await page.getByRole("button", { name: /Simulated agent \(no LLM\)/ }).click();
  await page.getByRole("button", { name: "Run experiment" }).click();
  const verdict = page.getByTestId("experiment-verdict");
  await expect(verdict).toContainText("Protected");
  const leakRows = page.getByText("Fake secret leaked");
  await expect(leakRows.nth(0).locator("..")).toContainText("1 / 1"); // baseline leaked
  await expect(leakRows.nth(1).locator("..")).toContainText("0 / 1"); // protected did not
  await expect(page.getByText("A simulated (non-LLM) agent was used")).toBeVisible();

  // Tool-call history with real policy outcomes.
  await page.getByRole("button", { name: /Show model tool-call history/ }).click();
  await expect(page.getByText("BASELINE-ALLOW-ALL").first()).toBeVisible();

  // Runs are labelled distinctly on the overview.
  await page.goto("/");
  await expect(page.getByText("Recent runs")).toBeVisible();
  await expect(page.getByText(/simulated · simulated-agent/).first()).toBeVisible();
  await expect(page.getByText("baseline", { exact: true }).first()).toBeVisible();

  // The fake secret never reached the browser.
  const all = bodies.join("\n") + (await page.content());
  expect(all).not.toContain("AFTERIMAGE-CANARY-");
  expect(all).not.toContain("SYNTHETIC DEMO SECRET");
});

test("replay lab: LLM run replayed with model trials plus a deterministic control", async ({ page, request }) => {
  // Self-contained setup: reset policy to baseline (earlier tests changed it), then create an LLM run.
  expect((await request.post("/api/settings/reset", { data: { mode: "demo", confirm_text: "RESET DEMO" } })).ok()).toBeTruthy();
  const run = await (await request.post("/api/runs/llm", { data: { provider: "simulated", enforcement: "protected" } })).json();

  await page.goto("/replay");
  await page.getByRole("combobox", { name: "Baseline run" }).selectOption(run.run_id);
  await page.getByRole("spinbutton", { name: "Model trials" }).fill("2");
  await page.getByRole("button", { name: "Run replay" }).click();
  await expect(page.getByTestId("replay-status")).toContainText("Verified");
  await expect(page.getByTestId("replay-status")).toContainText("deterministic");
  await expect(page.getByText("Model trials (probabilistic)")).toBeVisible();
  await expect(page.getByText(/attempted the injected request in 2 of 2/).first()).toBeVisible();
  await expect(page.getByText("Deterministic control: Every unauthorized request was denied before execution")).toBeVisible();
});

test("responsive: no horizontal page overflow at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/", "/incidents", "/investigation", "/replay", "/experiment", "/policies", "/recovery", "/events", "/settings"]) {
    await page.goto(path);
    await expect(page.getByText("Backend connected")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const width = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(width, `horizontal overflow on ${path}`).toBeLessThanOrEqual(390);
  }
});

test("providers: Gemini and Ollama (mocked APIs) — status, checks, runs, quota errors", async ({ page }) => {
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/api/")) bodies.push(await r.text().catch(() => ""));
  });

  // Settings: configured status and live checks, without revealing the key.
  await page.goto("/settings");
  const gemini = page.locator("li", { hasText: "Google Gemini" });
  await expect(gemini).toContainText("configured");
  await expect(gemini).toContainText("cloud · free tier or paid");
  await gemini.getByRole("button", { name: "Check" }).click();
  await expect(gemini.getByTestId("provider-check")).toContainText("model gemini-3.8-flash available");
  const ollama = page.locator("li", { hasText: "Ollama (local)" });
  await expect(ollama).toContainText("local inference");
  await ollama.getByRole("button", { name: "Check" }).click();
  await expect(ollama.getByTestId("provider-check")).toContainText("tool calling: supported");

  // Injection Lab with Gemini: the real google-genai SDK against the mock API.
  await page.goto("/experiment");
  await page.getByRole("button", { name: /Google Gemini/ }).click();
  await page.getByRole("button", { name: "Run experiment" }).click();
  await expect(page.getByTestId("experiment-verdict")).toContainText("Protected", { timeout: 20_000 });
  const leaks = page.getByText("Fake secret leaked");
  await expect(leaks.nth(0).locator("..")).toContainText("1 / 1");
  await expect(leaks.nth(1).locator("..")).toContainText("0 / 1");

  // A model on an exhausted free-tier quota: an honest "inconclusive" with guidance.
  await page.getByRole("textbox", { name: "Model", exact: true }).fill("gemini-quota-test");
  await page.getByRole("button", { name: "Run experiment" }).click();
  await expect(page.getByTestId("experiment-verdict")).toContainText("Inconclusive", { timeout: 20_000 });
  await expect(page.getByTestId("provider-error").first()).toContainText("Gemini quota exhausted");
  await expect(page.getByTestId("provider-error").first()).toContainText("never switches to a different provider");

  // Ollama: a pulled model without tool calling is reported, not used.
  await page.getByRole("button", { name: /Ollama \(local\)/ }).click();
  await page.getByRole("textbox", { name: "Model", exact: true }).fill("gemma:2b");
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByTestId("provider-check")).toContainText("tool calling: unsupported");

  // Runs are labelled by provider on the overview.
  await page.goto("/");
  await expect(page.getByText("Gemini · gemini-3.8-flash").first()).toBeVisible();

  const all = bodies.join("\n") + (await page.content());
  expect(all).not.toContain("AIzaFAKE-e2e-key");
  expect(all).not.toContain("AFTERIMAGE-CANARY-");
});
