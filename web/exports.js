// Bridge exports are independent of the camera's native service controls.
(() => {
  const E = {
    id: null,
    account: null,
    epoch: -1,
    generation: 0,
    request: 0,
    data: null,
    busy: false,
    loading: false,
    viewable: false,
    credentialId: undefined,
  };
  const el = (name) => $("bridge-export-" + name);
  const camera = () => S.cameras.find((c) => c.id === S.selected);
  const context = () => ({
    id: E.id,
    epoch: S.epoch,
    generation: E.generation,
  });
  const current = (c) =>
    !!S.username &&
    S.selected === c.id &&
    S.epoch === c.epoch &&
    E.generation === c.generation;
  const path = (c) => "/api/cameras/" + encodeURIComponent(c.id) + "/export";
  function clearSecret() {
    E.credentialId = undefined;
    el("username").value = el("password").value = "";
    el("secret").hidden = true;
  }
  function reset() {
    E.generation++;
    E.request++;
    E.data = null;
    E.busy = E.loading = false;
    clearSecret();
    el("host").value = "";
    el("rtsp").checked = el("onvif").checked = true;
    el("profiles").replaceChildren();
  }
  function render() {
    const c = camera(),
      ready = !!S.username && !!c?.viewable;
    const enabled = !!E.data?.enabled,
      unavailable = E.data?.available === false;
    el("enable").disabled =
      !ready || E.busy || E.loading || unavailable || !el("rtsp").checked;
    el("disable").disabled = !enabled || E.busy || E.loading;
    el("refresh").disabled = !S.username || !c || E.busy || E.loading;
    el("host").disabled = el("rtsp").disabled = el("onvif").disabled = E.busy;
    el("use-host").disabled = E.busy;
  }
  function safeURI(value, protocols) {
    try {
      const url = new URL(value);
      if (
        !protocols.includes(url.protocol) ||
        url.username ||
        url.password ||
        url.search ||
        url.hash
      )
        return "";
      return url.href;
    } catch {
      return "";
    }
  }
  function addAddress(label, uri) {
    if (!uri) return;
    const group = document.createElement("div"),
      title = document.createElement("label");
    title.textContent = label;
    const input = document.createElement("input");
    input.value = uri;
    input.readOnly = true;
    input.setAttribute("aria-label", label);
    const copy = document.createElement("button");
    copy.type = "button";
    copy.className = "text-button";
    copy.textContent = "Копировать адрес";
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(input.value);
      } catch {
        input.select();
      }
    };
    group.append(title, input, copy);
    el("profiles").append(group);
  }
  function showStatus(data) {
    // Credentials stay in the selected publication fields, outside catalog state.
    E.data = { enabled: !!data.enabled, available: data.available !== false, export_id: data.export_id };
    const states = {
      starting: "Запускается",
      streaming: "Передаётся видео",
      waiting: "Ожидание кадров",
      error: "Ошибка экспорта",
    };
    el("status").textContent =
      data.available === false
        ? "Экспорт недоступен. " +
          (data.reason ? String(data.reason) + ". " : "") +
          "Включите экспорт в настройках сервера и настройте RTSP / ONVIF службы моста. Откройте порты RTSP 8554 и ONVIF 8899 для вашей локальной сети."
        : !data.enabled
          ? "Экспорт выключен. " +
            (!camera()?.viewable
              ? "Сначала откройте видео камеры."
              : "Можно включить для этой камеры.")
          : (states[data.state] || "Экспорт включён") +
            (data.error ? ". " + String(data.error) : "") +
            (data.discovery_error
              ? ". Автообнаружение недоступно: используйте адрес ONVIF вручную."
              : "");
    el("profiles").replaceChildren();
    if (data.enabled) {
      addAddress(
        "ONVIF · адрес устройства",
        safeURI(data.onvif_uri, ["http:", "https:"]),
      );
      for (const p of data.profiles || []) {
        const label =
          "Линза " +
          (Number(p.lens) + 1) +
          (p.width && p.height ? " · " + p.width + " × " + p.height : "") +
          (p.fps ? " · " + p.fps + " кадр/с" : "");
        addAddress(label + " · RTSP", safeURI(p.rtsp_uri, ["rtsp:", "rtsps:"]));
        addAddress(
          label + " · снимок",
          safeURI(p.snapshot_uri, ["http:", "https:"]),
        );
      }
    } else clearSecret();
    render();
  }
  async function refresh() {
    if (document.hidden || !E.id || !S.username || E.busy || E.loading) return;
    const c = context(),
      request = ++E.request;
    E.loading = true;
    render();
    try {
      const data = await api(path(c));
      if (current(c) && request === E.request) {
        showStatus(data);
        await showCredentials(data, c);
      }
    } catch (error) {
      if (current(c) && request === E.request)
        el("status").textContent = friendly(error.code);
    } finally {
      if (current(c) && request === E.request) {
        E.loading = false;
        render();
      }
    }
  }
  function sync() {
    const c = camera();
    if (
      E.id !== S.selected ||
      E.epoch !== S.epoch ||
      E.account !== S.username
    ) {
      reset();
      E.id = S.selected;
      E.epoch = S.epoch;
      E.account = S.username;
      E.viewable = !!c?.viewable;
      el("status").textContent =
        S.username && c ? "Получаем статус экспорта…" : "Выберите камеру.";
      render();
      if (S.username && c) void refresh();
    } else {
      if (E.viewable && !c?.viewable) {
        clearSecret();
        E.generation++;
        E.request++;
        E.busy = E.loading = false;
        E.data = null;
        el("profiles").replaceChildren();
        el("status").textContent = "Камера отключена. Экспорт остановлен.";
      }
      E.viewable = !!c?.viewable;
      render();
    }
  }
  async function write(enabled) {
    sync();
    if (
      E.busy ||
      E.loading ||
      !E.id ||
      !S.username ||
      (enabled &&
        (!camera()?.viewable ||
          E.data?.available === false ||
          !el("rtsp").checked))
    )
      return;
    const c = context();
    const payload = enabled
      ? { enabled: true, rtsp: el("rtsp").checked, onvif: el("onvif").checked }
      : { enabled: false };
    if (enabled && el("host").value.trim())
      payload.advertise_host = el("host").value.trim();
    E.busy = true;
    E.request++;
    clearSecret();
    render();
    try {
      const data = await api(path(c), "POST", payload);
      if (current(c)) {
        showStatus(data);
        await showCredentials(data, c);
      }
    } catch (error) {
      if (current(c)) el("status").textContent = friendly(error.code);
    } finally {
      if (current(c)) {
        E.busy = false;
        render();
      }
    }
  }
  el("enable").onclick = () => write(true);
  el("disable").onclick = () => write(false);
  el("refresh").onclick = refresh;
  el("rtsp").onchange = () => {
    if (!el("rtsp").checked) el("onvif").checked = false;
    render();
  };
  el("onvif").onchange = () => {
    if (el("onvif").checked) el("rtsp").checked = true;
    render();
  };
  el("use-host").onclick = () => {
    el("host").value = location.hostname;
  };
  async function showCredentials(publication, c) {
    if (!publication.enabled) return;
    if (el("password").value && E.credentialId === publication.export_id) return;
    clearSecret();
    const data = await api(path(c) + "/credentials", "POST", {});
    if (!current(c) || !E.data?.enabled || E.data.export_id !== publication.export_id) return;
    el("username").value = data.username;
    el("password").value = data.password;
    E.credentialId = publication.export_id;
    el("secret").hidden = false;
  }
  for (const name of ["username", "password"])
    el("copy-" + name).onclick = async () => {
      const field = el(name);
      if (el("secret").hidden || !field.value) return;
      try {
        await navigator.clipboard.writeText(field.value);
      } catch {
        field.select();
      }
    };
  const baseRender = renderDetails;
  renderDetails = function (...args) {
    const result = baseRender.apply(this, args);
    sync();
    return result;
  };
  const baseLogin = showLogin;
  showLogin = function (...args) {
    reset();
    const result = baseLogin.apply(this, args);
    sync();
    return result;
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      sync();
      void refresh();
    }
  });
  setInterval(() => {
    sync();
    if (!document.hidden && S.username && E.id) void refresh();
  }, 5000);
  sync();
})();
