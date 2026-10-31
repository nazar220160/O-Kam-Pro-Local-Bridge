import { createHash } from "node:crypto";
import { readdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

export function inlineScriptHashes(html) {
  const hashes = new Set();
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script\s*>/gi)) {
    if (/(?:^|\s)src\s*=/i.test(match[1]) || !match[2]) continue;
    const digest = createHash("sha256").update(match[2], "utf8").digest("base64");
    hashes.add(`'sha256-${digest}'`);
  }
  return [...hashes].sort();
}

export async function buildScriptHashes(directory) {
  const hashes = new Set();
  let htmlFiles = 0;
  async function visit(path) {
    for (const item of await readdir(path, { withFileTypes: true })) {
      const file = resolve(path, item.name);
      if (item.isDirectory()) await visit(file);
      else if (item.isFile() && item.name.endsWith(".html")) {
        htmlFiles++;
        for (const hash of inlineScriptHashes(await readFile(file, "utf8"))) hashes.add(hash);
      }
    }
  }
  await visit(directory);
  if (!htmlFiles) throw new Error("No exported HTML found; run next build first");
  const result = [...hashes].sort();
  await writeFile(resolve(directory, "csp-script-hashes.txt"), result.join(" ") + "\n");
  return { htmlFiles, hashes: result.length };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const result = await buildScriptHashes(resolve(process.argv[2] || "out"));
  process.stdout.write(`CSP: ${result.hashes} inline script hashes from ${result.htmlFiles} HTML files\n`);
}
