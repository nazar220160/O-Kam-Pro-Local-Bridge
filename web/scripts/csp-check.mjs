import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { buildScriptHashes, inlineScriptHashes } from "./csp.mjs";

const hash = (value) => `'sha256-${createHash("sha256").update(value).digest("base64")}'`;

test("hashes exact inline script bytes without allowing external sources or duplicates", () => {
  const script = 'self.__next_f.push([1,"строка\\n"]);\n';
  const html = `<script src="/_next/static/chunk.js"></script><script>${script}</script><script>${script}</script>`;
  assert.deepEqual(inlineScriptHashes(html), [hash(script)]);
  assert.notEqual(hash(script), hash(script.trim()));
  assert.deepEqual(inlineScriptHashes('<script data-x="1" src = "/external.js">ignored()</script>'), []);
  assert.deepEqual(inlineScriptHashes('<script data-src="diagnostic">boot()</script>'), [hash("boot()")]);
});

test("includes nested exported pages and emits deterministic deduplicated policy tokens", async () => {
  const directory = await mkdtemp(join(tmpdir(), "okam-csp-"));
  try {
    await mkdir(join(directory, "nested"));
    await writeFile(join(directory, "index.html"), "<script>boot()</script>");
    await writeFile(join(directory, "nested", "404.html"), "<script>boot()</script><script>error()</script>");
    const result = await buildScriptHashes(directory);
    assert.deepEqual(result, { htmlFiles: 2, hashes: 2 });
    assert.equal(await readFile(join(directory, "csp-script-hashes.txt"), "utf8"), [hash("boot()"), hash("error()")].sort().join(" ") + "\n");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
