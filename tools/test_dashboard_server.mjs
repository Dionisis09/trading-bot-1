import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { startDashboardServer } from "./serve_dashboard.mjs";


test("serves only the dashboard and a secret-free health endpoint", async () => {
  const temporary = await mkdtemp(join(tmpdir(), "trading-dashboard-test-"));
  const dashboard = join(temporary, "dashboard.html");
  const dailyReport = join(temporary, "daily.html");
  await writeFile(dashboard, "<!doctype html><title>Trading UI</title>", "utf8");
  await writeFile(dailyReport, "<!doctype html><title>Daily Report</title>", "utf8");
  const server = startDashboardServer({
    dashboard,
    dailyReport,
    host: "127.0.0.1",
    port: 0,
  });
  await new Promise((resolvePromise) => server.once("listening", resolvePromise));
  const address = server.address();
  assert.equal(typeof address, "object");
  const base = `http://127.0.0.1:${address.port}`;
  try {
    const page = await fetch(`${base}/`);
    assert.equal(page.status, 200);
    assert.match(page.headers.get("content-type"), /^text\/html/u);
    assert.equal(page.headers.get("x-frame-options"), "DENY");
    assert.match(await page.text(), /Trading UI/u);

    const health = await fetch(`${base}/health`);
    assert.equal(health.status, 200);
    const payload = await health.json();
    assert.equal(payload.status, "ready");
    assert.equal(typeof payload.dashboard_bytes, "number");
    assert.deepEqual(Object.keys(payload).sort(), [
      "daily_report_bytes",
      "daily_report_status",
      "daily_report_updated_utc",
      "dashboard_bytes",
      "dashboard_updated_utc",
      "status",
    ]);
    assert.equal(payload.daily_report_status, "ready");

    const daily = await fetch(`${base}/daily`);
    assert.equal(daily.status, 200);
    assert.match(await daily.text(), /Daily Report/u);

    const missing = await fetch(`${base}/artifact.json`);
    assert.equal(missing.status, 404);
  } finally {
    await new Promise((resolvePromise, rejectPromise) => {
      server.close((error) => error ? rejectPromise(error) : resolvePromise());
    });
    await rm(temporary, { recursive: true, force: true });
  }
});
