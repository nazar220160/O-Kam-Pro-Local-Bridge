const fs = require("fs"),
  vm = require("vm"),
  assert = require("node:assert/strict");
function environment() {
  const elements = new Map(),
    pending = [];
  function element() {
    return {
      value: "",
      checked: false,
      textContent: "",
      disabled: false,
      hidden: false,
      children: [],
      options: [],
      append(...values) {
        this.children.push(...values);
        this.options.push(...values);
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
  const context = vm.createContext({
    S: { selected: "A", epoch: 1, cameras: [] },
    $: get,
    document: {
      getElementById: get,
      querySelectorAll: () => [],
      createElement: () => element(),
    },
    api: (...args) =>
      new Promise((resolve, reject) => pending.push({ args, resolve, reject })),
    toast() {},
    friendly: (x) => x,
    console,
    setTimeout: () => {},
    Blob,
    URL,
  });
  vm.runInContext(fs.readFileSync("web/controls.js", "utf8"), context);
  return { pending, get, run: (source) => vm.runInContext(source, context) };
}
(async () => {
  let e = environment();
  assert.equal(e.pending.length, 0, "loading controls must never probe");
  let promise = e.run("checkNativeServices()");
  assert.deepEqual(Array.from(e.pending[0].args), ["/api/cameras/A/services"]);
  e.pending
    .shift()
    .resolve({
      ip: "camera-address",
      capabilities: {
        onvif: { available: true, evidence: "<script>unsafe</script>" },
        rtsp: { available: null },
      },
      ports: [{ port: 554, service: "rtsp", open: true }],
      configuration: {
        onvif: { writable: false, reason: "No verified switch" },
      },
      instructions: ["Check camera application"],
    });
  await promise;
  assert.equal(e.get("services-results").hidden, false);
  assert.equal(
    e.get("service-cards").children[0].children[2].textContent,
    "<script>unsafe</script>",
  );
  assert.equal(e.get("service-cards").children[0].children[3].disabled, true);
  e = environment();
  promise = e.run("checkNativeServices()");
  e.run("resetControlUI();S.selected='B';resetControlUI();S.selected='A'");
  e.pending.shift().resolve({ capabilities: { onvif: { available: true } } });
  await promise;
  assert.equal(
    e.get("services-results").hidden,
    true,
    "late A reply cannot overwrite a newly selected A",
  );
  e = environment();
  e.get("local-password-enabled").checked = true;
  e.get("local-password").value = "short";
  await e.get("local-password-form").onsubmit({ preventDefault() {} });
  assert.equal(e.pending.length, 0, "invalid password cannot be sent");
  e.get("local-password").value = "Valid local password";
  promise = e.get("local-password-form").onsubmit({ preventDefault() {} });
  assert.equal(e.pending[0].args[2].action, "plaintext_password");
  assert.equal(e.pending[0].args[2].args.enabled, true);
  e.pending
    .shift()
    .resolve({ state: "confirmed", parameters: { password: "NEVER DISPLAY" } });
  await promise;
  assert.equal(e.get("local-password").value, "");
  assert.equal(
    e.get("local-password-status").textContent.includes("NEVER DISPLAY"),
    false,
  );
  assert.equal(e.pending.length, 0, "configuration never auto-probes");
  console.log(
    "Frontend native service checks passed: explicit probe, safe text, disabled switches, selection race, password validation and clearing",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
