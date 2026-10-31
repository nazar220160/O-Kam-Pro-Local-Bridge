const fs = require("fs"), vm = require("vm"), assert = require("node:assert/strict");

function environment(mode = "lan") {
  const elements = new Map(), requests = [];
  function element() {
    return {
      value: "", textContent: "", disabled: false, hidden: false, children: [],
      append(...values) { this.children.push(...values); },
      replaceChildren() { this.children = []; },
      setAttribute() {}, removeAttribute() {}, close() {}, remove() {},
    };
  }
  const get = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const context = vm.createContext({
    document: {getElementById: get, querySelectorAll: () => [], createElement: element, createTextNode: text => text},
    fetch: (path, options) => new Promise(resolve => requests.push({path, options, resolve})),
    localStorage: {getItem: () => null, setItem() {}},
    location: {reload() {}}, console, setTimeout() {}, clearTimeout() {}, setInterval() {},
  });
  const run = source => vm.runInContext(source, context);
  vm.runInContext(fs.readFileSync("web/app.js", "utf8"), context);
  const camera = {
    id: "A", name: "Camera", state: "streaming", viewable: true,
    connection_mode: mode, transport: {mode, path: mode === "cloud" ? "relay" : "lan"},
    lenses: [], lens_metadata: [], metadata: {}, account_metadata: {}, quality: "high",
  };
  run(`S.username='account';S.selected='A';S.cameras=${JSON.stringify([camera])}`);
  get("camera-ip").value = "192.168.0.106";
  get("substream").value = "1";
  get("quality").value = "low";
  return {requests, get, run, camera};
}
async function respond(request, body) {
  request.resolve({ok: true, status: 200, json: async () => body});
  await new Promise(resolve => setImmediate(resolve));
}
async function finishConnect(e, promise, mode) {
  await respond(e.requests.at(-1), {ok: true});
  assert.equal(e.requests.at(-1).path, "/api/cameras");
  await respond(e.requests.at(-1), [{...e.camera, connection_mode: mode}]);
  await promise;
}

(async () => {
  let e = environment();
  let promise = e.get("connect-cloud").onclick();
  let request = e.requests.at(-1), body = JSON.parse(request.options.body);
  assert.equal(request.path, "/api/cameras/A/connect");
  assert.equal(body.connection_mode, "cloud");
  assert.equal(body.ip, null, "cloud connection must ignore a manually populated local IP");
  assert.equal(e.get("connect").disabled, true);
  assert.equal(e.get("connect-cloud").disabled, true);
  assert.match(e.get("connection-info").textContent, /до 100 секунд/);
  e.run("renderDetails()");
  assert.equal(e.get("connect-cloud").disabled, true, "polling must not re-enable a pending connection");
  await finishConnect(e, promise, "cloud");
  assert.equal(e.get("camera-ip").value, "192.168.0.106", "cloud mode preserves the LAN input");
  assert.match(e.get("connection-info").textContent, /Источник: O-Kam Pro/);
  assert.equal(e.get("connect-cloud").disabled, false);

  e = environment("cloud");
  promise = e.get("connect").onclick();
  body = JSON.parse(e.requests.at(-1).options.body);
  assert.equal(body.connection_mode, "lan");
  assert.equal(body.ip, "192.168.0.106", "local button uses the saved/manual LAN address");
  await finishConnect(e, promise, "lan");

  e = environment("cloud");
  promise = e.get("apply-stream").onclick();
  request = e.requests.at(-1);
  body = JSON.parse(request.options.body);
  assert.equal(request.path, "/api/cameras/A/stream");
  assert.equal(body.connection_mode, "cloud", "live quality changes must retain cloud transport");
  assert.equal(body.ip, null);
  assert.equal(body.quality, "low");
  await respond(request, {ok: true, mode: "live"});
  await respond(e.requests.at(-1), [e.camera]);
  await promise;
  assert.equal(e.get("connect-cloud").disabled, false);
  assert.match(e.get("camera-state").textContent, /сервер O-Kam Pro/);

  e = environment();
  promise = e.get("connect-cloud").onclick();
  const count = e.requests.length;
  e.run("S.epoch++;S.selected='B'");
  await respond(e.requests.at(-1), {ok: true});
  await promise;
  assert.equal(e.requests.length, count, "a response from an old account must not refresh the new catalog");
  console.log("Frontend cloud passed: explicit transport, IP isolation, pending controls, live quality, relay label and account race");
})().catch(error => { console.error(error); process.exit(1); });
