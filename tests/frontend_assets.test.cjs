const fs = require("fs"),
  vm = require("vm"),
  assert = require("node:assert/strict");
const html = fs.readFileSync("web/index.html", "utf8");
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
assert.equal(new Set(ids).size, ids.length, "DOM IDs must be unique");
for (const asset of ["app.js", "controls.js", "exports.js", "archive.js", "styles.css"]) {
  assert(html.includes("/" + asset));
  assert(fs.statSync("web/" + asset).size > 0);
}
for (const filename of ["app.js", "controls.js", "exports.js", "archive.js"]) {
  const source = fs.readFileSync("web/" + filename, "utf8");
  new vm.Script(source, { filename });
  for (const match of source.matchAll(/\$\('([^']+)'\)/g)) {
    if (["player-dialog", "credentials-dialog"].includes(match[1])) continue;
    assert(
      ids.includes(match[1]),
      filename + " references missing element #" + match[1],
    );
  }
}
assert(
  !/<script>(?!\s*<\/script>)/.test(html),
  "scripts must be separate assets",
);
assert(html.includes('href="/docs/"'));
assert(
  !/https?:\/\/[^\s"<>]+\.(?:js|css)/.test(html),
  "no remote CDN dependency",
);
for (const name of ["video", "controls", "services", "metadata"])
  assert(html.includes('aria-controls="panel-' + name + '"'));
console.log(
  "Frontend assets passed: unique DOM IDs, valid JS, resolved controls, separate assets, accessible panels, no CDN",
);
