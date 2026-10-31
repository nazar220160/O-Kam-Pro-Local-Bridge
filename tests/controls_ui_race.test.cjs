const fs = require("fs"),
  vm = require("vm"),
  assert = require("assert");
function environment() {
  const elements = new Map(),
    pending = [];
  function element() {
    return {
      value: "",
      textContent: "",
      disabled: false,
      children: [],
      options: [],
      append(...v) {
        this.children.push(...v);
        this.options.push(...v);
      },
      replaceChildren() {
        this.children = [];
        this.options = [];
      },
      remove() {},
      close() {},
      setAttribute() {},
    };
  }
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const ctx = vm.createContext({
    S: { selected: "A", epoch: 1, cameras: [] },
    $: get,
    document: {
      getElementById: get,
      querySelectorAll: () => [],
      createElement: () => element(),
    },
    api: (...args) => new Promise((resolve) => pending.push({ args, resolve })),
    toast() {},
    friendly: (x) => x,
    console,
    setTimeout: () => {},
    Blob,
    URL,
  });
  vm.runInContext(fs.readFileSync("web/controls.js", "utf8"), ctx);
  vm.runInContext("C.id='A';C.epoch=1", ctx);
  return { ctx, pending, get, run: (s) => vm.runInContext(s, ctx) };
}
(async () => {
  let e = environment(),
    promise = e.run("loadControlDetails('A')");
  e.run(
    "resetControlUI();S.selected='B';C.id='B';resetControlUI();S.selected='A';C.id='A'",
  );
  e.pending.shift().resolve({ account: { model: "OLD" } });
  await promise;
  assert.equal(e.run("C.data"), null);
  e = environment();
  promise = e.run("runControl('query',{section:'status'})");
  e.run(
    "resetControlUI();S.selected='B';resetControlUI();S.selected='A';C.id='A';C.busy=true",
  );
  e.pending.shift().resolve({ state: "confirmed", parameters: { old: 1 } });
  await promise;
  assert.equal(e.run("C.busy"), true);
  assert.equal(e.get("control-response").textContent, "");
  e = environment();
  promise = e.run("refreshAllDetails()");
  e.run(
    "resetControlUI();S.selected='B';resetControlUI();S.selected='A';C.id='A'",
  );
  e.pending.shift().resolve({ state: "confirmed" });
  await promise;
  assert.equal(e.pending.length, 0);
  assert.equal(e.get("refresh-metadata").disabled, false);
  assert.equal(e.get("metadata-progress").textContent, "");
  console.log("3 controls UI camera-selection race tests passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
