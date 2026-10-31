const fs = require("fs"),
  vm = require("vm"),
  assert = require("node:assert/strict");
function setup() {
  const nodes = new Map(),
    requests = [],
    timers = [],
    intervals = [];
  const node = () => ({
    value: "",
    textContent: "",
    hidden: false,
    disabled: false,
    checked: false,
    children: [],
    append(...x) {
      this.children.push(...x);
    },
    replaceChildren(...x) {
      this.children = x;
    },
    setAttribute() {},
    select() {},
  });
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, node());
    return nodes.get(id);
  };
  get("bridge-export-rtsp").checked = get("bridge-export-onvif").checked = true;
  const ctx = vm.createContext({
    S: {
      username: "account",
      epoch: 1,
      selected: "A",
      cameras: [
        { id: "A", viewable: true },
        { id: "B", viewable: true },
      ],
    },
    $: get,
    document: { hidden: false, createElement: node, addEventListener() {} },
    location: { hostname: "bridge.example" },
    URL,
    navigator: { clipboard: { writeText: async () => {} } },
    setTimeout: (f) => {
      timers.push(f);
      return timers.length;
    },
    clearTimeout() {},
    setInterval: (f) => intervals.push(f),
    renderDetails() {},
    showLogin() {
      this.S.epoch++;
      this.S.username = null;
      this.S.selected = null;
    },
    api: (...args) =>
      new Promise((resolve, reject) =>
        requests.push({ args, resolve, reject }),
      ),
    friendly: () => "Request failed",
  });
  vm.runInContext(fs.readFileSync("web/exports.js", "utf8"), ctx);
  return {
    get,
    requests,
    timers,
    intervals,
    run: (s) => vm.runInContext(s, ctx),
  };
}
const flush = async () => {
  for (let i=0; i<6; i++) await Promise.resolve();
};
(async () => {
  let e = setup();
  assert.equal(e.requests.length, 1);
  assert.equal(e.requests[0].args.length, 1, "initialization reads only");
  e.intervals[0]();
  assert(
    e.requests.every((r) => !r.args[1] || r.args[1] === "GET"),
    "polling never writes",
  );
  const old = e.requests.shift();
  e.run("S.selected='B';renderDetails();S.selected='A';renderDetails()");
  old.resolve({ enabled: true, state: "error", error: "STALE" });
  await flush();
  assert(
    !e.get("bridge-export-status").textContent.includes("STALE"),
    "A→B→A rejects old response",
  );
  e.requests
    .at(-1)
    .resolve({ enabled: false, available: true, password: "SECRET" });
  await flush();
  assert(
    !JSON.stringify([
      ...["bridge-export-status", "bridge-export-profiles"].map((x) =>
        e.get(x),
      ),
    ]).includes("SECRET"),
  );
  e.get("bridge-export-host").value = "bridge.example";
  const action = e.get("bridge-export-enable").onclick();
  const write = e.requests.at(-1);
  assert.equal(write.args[0], "/api/cameras/A/export");
  assert.equal(write.args[1], "POST");
  assert.deepEqual(JSON.parse(JSON.stringify(write.args[2])), {
    enabled: true,
    advertise_host: "bridge.example",
    rtsp: true,
    onvif: true,
  });
  e.run("S.selected='B';renderDetails()");
  write.resolve({ enabled: true, state: "streaming", profiles: [] });
  await action;
  assert(
    !e.get("bridge-export-status").textContent.includes("Передаётся"),
    "write reply bound to selected camera",
  );
  e = setup();
  e.requests
    .shift()
    .resolve({
      enabled: true,
      state: "streaming",
      profiles: [
        {
          lens: 0,
          rtsp_uri: "rtsp://bridge:SECRET@host:8554/a",
          snapshot_uri: "http://host/a?password=SECRET",
        },
      ],
      onvif_uri: "http://host/onvif/a",
    });
  await flush();
  assert(
    !JSON.stringify(e.get("bridge-export-profiles")).includes("SECRET"),
    "credential URLs excluded",
  );
  assert.equal(e.requests.at(-1).args[0], "/api/cameras/A/export/credentials");
  e.requests.at(-1).resolve({ username: "bridge", password: "TEMPORARY" });
  await flush();
  assert.equal(e.get("bridge-export-password").value, "TEMPORARY");
  assert.equal(e.get("bridge-export-secret").hidden, false);
  assert.equal(e.timers.length, 0, "credentials have no hiding timer");
  e.intervals[0]();
  e.requests.at(-1).resolve({enabled:true,state:"streaming",profiles:[]});
  await flush();
  assert.equal(e.get("bridge-export-password").value, "TEMPORARY", "polling keeps credentials visible");
  e.get("bridge-export-onvif").checked = true;
  e.get("bridge-export-rtsp").checked = false;
  e.get("bridge-export-onvif").onchange();
  assert(e.get("bridge-export-rtsp").checked);
  e.run("S.cameras[0].viewable=false;renderDetails()");
  assert(e.get("bridge-export-enable").disabled);
  assert.equal(e.get("bridge-export-password").value, "");
  assert(
    e.requests.every(
      (r) => r.args[1] !== "POST" || r.args[0].endsWith("/credentials"),
    ),
    "no automatic enable/disable",
  );
  e = setup();
  e.requests
    .shift()
    .resolve({ enabled: true, state: "streaming", profiles: [] });
  await flush();
  const secretReply = e.requests.shift();
  e.run("S.selected='B';renderDetails();S.selected='A';renderDetails()");
  secretReply.resolve({ username: "bridge", password: "STALE-SECRET" });
  await flush();
  assert.equal(
    e.get("bridge-export-password").value,
    "",
    "delayed credentials rejected across A→B→A",
  );
  const freshStatus = e.requests.at(-1);
  freshStatus.resolve({ enabled: true, state: "streaming", profiles: [] });
  await flush();
  const logoutReply = e.requests.at(-1);
  e.run("showLogin()");
  logoutReply.resolve({ username: "bridge", password: "LOGGED-OUT" });
  await flush();
  assert.equal(e.get("bridge-export-password").value, "");
  assert(e.get("bridge-export-secret").hidden);
  e = setup();
  e.requests.shift().resolve({ enabled: false, available: true });
  await flush();
  e.run("document.hidden=true");
  e.intervals[0]();
  assert.equal(e.requests.length, 0, "hidden page does not poll");
  e.run("document.hidden=false");
  e.intervals[0]();
  assert.equal(e.requests.length, 1);
  assert.equal(e.requests[0].args.length, 1, "visible poll reads only");
  e = setup();
  e.requests.shift().resolve({ enabled: false, available: true });
  await flush();
  const autoEnable = e.get("bridge-export-enable").onclick();
  const automaticWrite = e.requests.at(-1);
  assert.equal(automaticWrite.args[2].advertise_host, undefined,
    "empty address lets the API choose its trusted server address");
  automaticWrite.resolve({enabled:true,advertise_host:"bridge.example",profiles:[],export_id:"publication"});
  await flush();
  e.requests.at(-1).resolve({username:"bridge",password:"LOCAL"});
  await autoEnable;
  assert.equal(e.get("bridge-export-host").value, "bridge.example",
    "the resolved bridge address is visible after enabling");
  e.get("bridge-export-host").value = "edited.example";
  e.get("bridge-export-host").oninput();
  e.intervals[0]();
  e.requests.at(-1).resolve({enabled:true,advertise_host:"bridge.example",profiles:[],export_id:"publication"});
  await flush();
  assert.equal(e.get("bridge-export-host").value, "edited.example",
    "status polling does not overwrite an address being edited");
  e.run("S.selected='B';renderDetails()");
  assert.equal(e.get("bridge-export-host").value, "",
    "switching camera clears the previous address and edit state");
  console.log(
    "Frontend exports passed: explicit writes, selection races, automatic visible credentials and account isolation, readiness",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
