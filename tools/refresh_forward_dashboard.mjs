#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";


function parseArgs(argv) {
  const values = {
    artifact: "user_data/dashboard/forward_dashboard_artifact.json",
    output: "user_data/dashboard/forward_dashboard.html",
    status: "user_data/dashboard/forward_dashboard_build_status.json",
    builder: null,
    watchSeconds: 0,
  };
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (!flag?.startsWith("--") || value === undefined) {
      throw new Error(`Invalid argument near ${flag ?? "end of command"}`);
    }
    const key = flag.slice(2).replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
    if (!(key in values)) throw new Error(`Unknown argument ${flag}`);
    values[key] = key === "watchSeconds" ? Number(value) : value;
  }
  if (!values.builder) throw new Error("--builder is required");
  if (!Number.isInteger(values.watchSeconds) || values.watchSeconds < 0) {
    throw new Error("--watch-seconds must be a non-negative integer");
  }
  return values;
}


function readJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}


function atomicWriteJson(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  renameSync(temporary, path);
}


function parseReceipt(stdout) {
  const lines = String(stdout || "").split(/\r?\n/u).filter((line) => line.trim());
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    try {
      return JSON.parse(lines[index]);
    } catch {
      // Keep looking for the final JSON receipt.
    }
  }
  return null;
}


export function buildIfChanged(options) {
  const artifactPath = resolve(options.artifact);
  const outputPath = resolve(options.output);
  const statusPath = resolve(options.status);
  const builderPath = resolve(options.builder);
  if (!existsSync(artifactPath)) {
    const status = {
      status: "WAITING_FOR_ARTIFACT",
      artifact: options.artifact,
      output: options.output,
    };
    atomicWriteJson(statusPath, status);
    return { ok: true, skipped: true, status };
  }
  const artifact = readJson(artifactPath);
  const generatedAt = artifact?.snapshot?.generatedAt;
  if (typeof generatedAt !== "string" || !generatedAt) {
    throw new Error("Artifact snapshot.generatedAt is missing");
  }
  if (existsSync(statusPath) && existsSync(outputPath)) {
    const previous = readJson(statusPath);
    if (previous.status === "READY" && previous.generated_at === generatedAt) {
      return { ok: true, skipped: true, status: previous };
    }
  }

  mkdirSync(dirname(outputPath), { recursive: true });
  const stableInputPath = `${outputPath}.artifact-${process.pid}-${Date.now()}.json`;
  writeFileSync(stableInputPath, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
  let result;
  try {
    result = spawnSync(
      process.execPath,
      [builderPath, "--input", stableInputPath, "--output", outputPath],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          CHROMIUM_EXECUTABLE_PATH: "",
          PLAYWRIGHT_EXECUTABLE_PATH: "",
        },
        timeout: 120_000,
      },
    );
  } finally {
    rmSync(stableInputPath, { force: true });
  }
  const receipt = parseReceipt(result.stdout);
  if (result.status !== 0 || !receipt?.ok) {
    const status = {
      status: "ERROR",
      generated_at: generatedAt,
      artifact: options.artifact,
      output: options.output,
      exit_code: result.status,
      error: String(result.stderr || result.stdout || "dashboard builder failed").slice(0, 2000),
    };
    atomicWriteJson(statusPath, status);
    return { ok: false, skipped: false, status };
  }
  const status = {
    status: "READY",
    generated_at: generatedAt,
    artifact: options.artifact,
    output: options.output,
    verification: receipt.stages?.verification ?? "unknown",
    counts: receipt.counts ?? {},
  };
  atomicWriteJson(statusPath, status);
  return { ok: true, skipped: false, status };
}


async function main() {
  const options = parseArgs(process.argv.slice(2));
  while (true) {
    try {
      const result = buildIfChanged(options);
      console.log(JSON.stringify(result));
    } catch (error) {
      const status = {
        status: "ERROR",
        error: `${error?.name ?? "Error"}: ${error?.message ?? String(error)}`,
      };
      atomicWriteJson(resolve(options.status), status);
      console.error(JSON.stringify({ ok: false, status }));
      if (options.watchSeconds === 0) process.exitCode = 2;
    }
    if (options.watchSeconds === 0) return;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, options.watchSeconds * 1000));
  }
}


const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (fileURLToPath(import.meta.url) === invokedPath) {
  await main();
}
