#!/usr/bin/env node

import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";


function parseArgs(argv) {
  const values = {
    dashboard: "user_data/dashboard/forward_dashboard.html",
    dailyReport: "user_data/dashboard/daily_report.html",
    host: "0.0.0.0",
    port: 8080,
  };
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument near ${flag ?? "end of command"}`);
    }
    const key = flag.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (!(key in values)) throw new Error(`Unknown argument ${flag}`);
    values[key] = key === "port" ? Number(value) : value;
  }
  if (!Number.isInteger(values.port) || values.port < 0 || values.port > 65535) {
    throw new Error("--port must be an integer from 0 through 65535");
  }
  if (typeof values.host !== "string" || !values.host.trim()) {
    throw new Error("--host must not be empty");
  }
  return values;
}


function applySecurityHeaders(response) {
  response.setHeader("Cache-Control", "no-store, max-age=0");
  response.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  response.setHeader("Referrer-Policy", "no-referrer");
  response.setHeader("X-Content-Type-Options", "nosniff");
  response.setHeader("X-Frame-Options", "DENY");
}


async function fileMetadata(path) {
  try {
    const metadata = await stat(path);
    return { ready: true, bytes: metadata.size, updatedUtc: metadata.mtime.toISOString() };
  } catch {
    return { ready: false, bytes: null, updatedUtc: null };
  }
}


async function requestHandler(request, response, dashboardPath, dailyReportPath) {
  applySecurityHeaders(response);
  if (!new Set(["GET", "HEAD"]).has(request.method ?? "")) {
    response.writeHead(405, { Allow: "GET, HEAD", "Content-Type": "text/plain; charset=utf-8" });
    response.end("Method not allowed\n");
    return;
  }
  const pathname = new URL(request.url ?? "/", "http://dashboard.local").pathname;
  if (pathname === "/favicon.ico") {
    response.writeHead(204);
    response.end();
    return;
  }
  if (pathname === "/health") {
    const dashboard = await fileMetadata(dashboardPath);
    const dailyReport = await fileMetadata(dailyReportPath);
    if (dashboard.ready) {
      const payload = JSON.stringify({
        status: "ready",
        dashboard_bytes: dashboard.bytes,
        dashboard_updated_utc: dashboard.updatedUtc,
        daily_report_status: dailyReport.ready ? "ready" : "waiting",
        daily_report_bytes: dailyReport.bytes,
        daily_report_updated_utc: dailyReport.updatedUtc,
      });
      response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
      response.end(request.method === "HEAD" ? undefined : `${payload}\n`);
    } else {
      response.writeHead(503, { "Content-Type": "application/json; charset=utf-8" });
      response.end(request.method === "HEAD" ? undefined : '{"status":"waiting_for_dashboard"}\n');
    }
    return;
  }
  const isDashboard = pathname === "/" || pathname === "/index.html";
  const isDailyReport = pathname === "/daily" || pathname === "/daily.html";
  if (!isDashboard && !isDailyReport) {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("Not found\n");
    return;
  }
  try {
    const html = await readFile(isDailyReport ? dailyReportPath : dashboardPath);
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    response.end(request.method === "HEAD" ? undefined : html);
  } catch {
    response.writeHead(503, { "Content-Type": "text/plain; charset=utf-8" });
    response.end(
      request.method === "HEAD"
        ? undefined
        : `${isDailyReport ? "Daily report" : "Dashboard"} is being prepared. Refresh shortly.\n`,
    );
  }
}


export function startDashboardServer(options) {
  const dashboardPath = resolve(options.dashboard);
  const dailyReportPath = resolve(options.dailyReport);
  const server = createServer((request, response) => {
    requestHandler(request, response, dashboardPath, dailyReportPath).catch((error) => {
      applySecurityHeaders(response);
      response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Internal server error\n");
      console.error(`${error?.name ?? "Error"}: ${error?.message ?? String(error)}`);
    });
  });
  server.listen(options.port, options.host);
  return server;
}


async function main() {
  const options = parseArgs(process.argv.slice(2));
  const server = startDashboardServer(options);
  await new Promise((resolvePromise) => server.once("listening", resolvePromise));
  const address = server.address();
  console.log(JSON.stringify({
    status: "LISTENING",
    host: options.host,
    port: typeof address === "object" && address ? address.port : options.port,
    dashboard: options.dashboard,
    dailyReport: options.dailyReport,
  }));
}


const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (fileURLToPath(import.meta.url) === invokedPath) {
  await main();
}
