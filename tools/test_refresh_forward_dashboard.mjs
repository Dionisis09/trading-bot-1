import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { buildIfChanged } from "./refresh_forward_dashboard.mjs";


test("builds from an immutable artifact copy while the live artifact changes", async () => {
  const temporary = await mkdtemp(join(tmpdir(), "dashboard-refresh-test-"));
  const artifactPath = join(temporary, "artifact.json");
  const outputPath = join(temporary, "dashboard.html");
  const statusPath = join(temporary, "status.json");
  const builderPath = join(temporary, "fake-builder.mjs");
  const first = { surface: "dashboard", snapshot: { generatedAt: "2026-01-01T00:00:00Z" } };
  const second = { surface: "dashboard", snapshot: { generatedAt: "2026-01-01T04:00:00Z" } };
  await writeFile(artifactPath, JSON.stringify(first), "utf8");
  await writeFile(
    builderPath,
    `import { readFileSync, writeFileSync } from "node:fs";\n`
      + `const args = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, all) => index % 2 === 0 ? [...rows, [value, all[index + 1]]] : rows, []));\n`
      + `if (args["--input"] === ${JSON.stringify(artifactPath)}) throw new Error("live artifact was not isolated");\n`
      + `const payload = JSON.parse(readFileSync(args["--input"], "utf8"));\n`
      + `writeFileSync(${JSON.stringify(artifactPath)}, ${JSON.stringify(JSON.stringify(second))}, "utf8");\n`
      + `writeFileSync(args["--output"], JSON.stringify(payload), "utf8");\n`
      + `console.log(JSON.stringify({ok:true,stages:{verification:"passed"},counts:{metrics:1}}));\n`,
    "utf8",
  );
  try {
    const result = buildIfChanged({
      artifact: artifactPath,
      output: outputPath,
      status: statusPath,
      builder: builderPath,
      watchSeconds: 0,
    });
    assert.equal(result.ok, true);
    assert.equal(result.status.generated_at, first.snapshot.generatedAt);
    assert.deepEqual(JSON.parse(await readFile(outputPath, "utf8")), first);
    assert.deepEqual(JSON.parse(await readFile(artifactPath, "utf8")), second);
    const leftovers = (await readdir(temporary)).filter((name) => name.includes(".artifact-"));
    assert.deepEqual(leftovers, []);
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
