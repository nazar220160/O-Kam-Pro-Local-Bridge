// Camera controls share the authenticated account workspace and live session.
const C = {
  id: null,
  epoch: 0,
  data: null,
  busy: false,
  refreshing: false,
  wasViewable: false,
};
const queryNames = {
  status: "Статус",
  video: "Изображение и звук",
  parameters: "Сеть и параметры",
  light: "Свет / сирена",
  tracking: "Слежение",
  zoom_tracking: "Слежение с зумом",
  indicator: "Индикатор",
  presets: "Позиции PTZ",
  archive_dates: "Даты SD",
  recording: "Запись SD",
  sleep: "Энергосбережение",
  power: "Питание",
};
const nativeExamples = {
  Статус: "get_status.cgi?",
  "Все параметры": "get_params.cgi?",
  "Видео и звук": "get_camera_params.cgi?",
  "Позиции PTZ": "trans_cmd_string.cgi?cmd=2161&command=0&",
  "Даты на SD": "get_record_file.cgi?GetType=date&",
  "Режим записи SD": "get_record.cgi?",
  "План записи": "trans_cmd_string.cgi?cmd=2017&command=11&mark=212&type=3&",
  "План записи по движению":
    "trans_cmd_string.cgi?cmd=2017&command=11&mark=212&type=1&",
  "План тревог": "trans_cmd_string.cgi?cmd=2017&command=11&mark=212&type=2&",
  "Зоны движения сенсора0": "trans_cmd_string.cgi?cmd=2123&command=3&sensor=0&",
  "Облачная запись": "trans_cmd_string.cgi?cmd=2106&command=8&",
  "Режим тревожного света": "trans_cmd_string.cgi?cmd=2108&command=0&",
  Слежение: "trans_cmd_string.cgi?cmd=2127&command=1&",
  "Слежение с зумом": "trans_cmd_string.cgi?cmd=2126&command=1&",
  Индикатор: "trans_cmd_string.cgi?cmd=2125&command=1&",
  Энергосбережение: "trans_cmd_string.cgi?cmd=2106&command=17&",
  Питание: "trans_cmd_string.cgi?cmd=2106&command=14&",
};
const featureNames = {
  ptz: "Мотор PTZ",
  microphone: "Микрофон",
  speaker: "Динамик",
  zoom: "Оптический зум",
  tracking: "Слежение",
  sd_card: "Карта памяти",
  white_light: "Белая подсветка",
  night_vision: "Ночное видение",
  presets: "Позиции PTZ",
  ai: "AI",
  onvif: "ONVIF",
};
function closeCredentialDialog() {
  const d = $("credentials-dialog");
  if (d) {
    d.close();
    d.remove();
  }
}
function resetControlUI() {
  C.id = null;
  C.epoch++;
  C.data = null;
  C.busy = false;
  C.refreshing = false;
  $("refresh-metadata").disabled = false;
  $("metadata-progress").textContent = "";
  C.wasViewable = false;
  closeCredentialDialog();
  $("control-response").textContent = "";
  $("metadata-body").replaceChildren();
  $("capability-list").replaceChildren();
}
function controlNotice(result) {
  return result.state === "interrupted"
    ? "Подключение закрыто. Последующие команды не отправлены."
    : result.state === "rejected"
      ? "Камера отказала: result=" + result.result
      : result.state === "confirmed"
        ? "Камера подтвердила команду"
        : result.state === "response"
          ? "Получен ответ камеры"
          : "Команда передана. Отдельное подтверждение камеры не получено.";
}
async function loadControlDetails(id = S.selected) {
  const epoch = S.epoch,
    generation = C.epoch;
  try {
    const d = await api("/api/cameras/" + encodeURIComponent(id) + "/details");
    if (S.selected !== id || S.epoch !== epoch || C.epoch !== generation)
      return;
    C.data = d;
    renderMetadata();
    renderCapabilities();
  } catch (e) {
    if (S.selected === id && S.epoch === epoch && C.epoch === generation)
      toast(friendly(e.code));
  }
}
function renderCapabilities() {
  const box = $("capability-list");
  box.replaceChildren();
  for (const [key, value] of Object.entries(C.data?.capabilities || {})) {
    const chip = document.createElement("span");
    chip.className = "cap-chip";
    chip.textContent =
      (featureNames[key] || key) +
      " · " +
      (value.available === true
        ? "есть"
        : value.available === false
          ? "нет"
          : "неизвестно");
    chip.title = JSON.stringify(value.evidence);
    box.append(chip);
  }
}
function renderMetadata() {
  const body = $("metadata-body"),
    query = $("metadata-search").value.toLowerCase();
  body.replaceChildren();
  let count = 0;
  const groups = { account: C.data?.account || {}, ...(C.data?.groups || {}) };
  for (const [group, values] of Object.entries(groups)) {
    for (const [key, value] of Object.entries(values)) {
      const text =
        typeof value === "object" ? JSON.stringify(value) : String(value);
      if (
        query &&
        !(group + " " + key + " " + text).toLowerCase().includes(query)
      )
        continue;
      const tr = document.createElement("tr");
      for (const v of [queryNames[group] || group, key, text]) {
        const td = document.createElement("td");
        td.textContent = v;
        tr.append(td);
      }
      body.append(tr);
      count++;
    }
  }
  $("metadata-count").textContent = count + " полей";
}
function renderCameraControls(c) {
  if (C.id !== c.id) {
    resetControlUI();
    C.id = c.id;
    C.wasViewable = !!c.viewable;
    $("native-path").value = "get_status.cgi?";
    loadControlDetails(c.id);
  }
  const ready = c.viewable;
  $("configure-local-password").disabled = !ready || N.configBusy;
  if (ready && !C.wasViewable) loadControlDetails(c.id);
  C.wasViewable = ready;
  for (const button of document.querySelectorAll("[data-control]"))
    button.disabled = !ready || C.busy || C.refreshing;
  $("control-readiness").textContent = ready
    ? "Команды выполняются в текущей сессии камеры."
    : "Откройте видео для управления камерой.";
  const pulse = $("ptz-mode").value === "pulse";
  for (const id of ["ptz-speed", "ptz-duration", "ptz-lens"])
    $(id).disabled = !pulse || !ready;
  const ptz = C.data?.capabilities?.ptz?.available;
  if (ptz === false)
    for (const b of document.querySelectorAll("[data-move]")) b.disabled = true;
  const select = $("ptz-lens");
  const previous = select.value;
  const ids = c.lenses.length ? c.lenses : [0];
  if (
    Array.from(select.options)
      .map((o) => o.value)
      .join(",") !== ids.map(String).join(",")
  ) {
    select.replaceChildren();
    for (const n of ids) {
      const o = document.createElement("option");
      o.value = n;
      o.textContent = "Сенсор " + n + " · линза " + (n + 1);
      select.append(o);
    }
    if (ids.includes(Number(previous))) select.value = previous;
  }
}
async function runControl(action, args = {}, quiet = false) {
  const id = S.selected,
    epoch = S.epoch,
    generation = C.epoch;
  if (!id) throw { code: "camera_not_streaming" };
  C.busy = true;
  const current = S.cameras.find((c) => c.id === id);
  if (current) renderCameraControls(current);
  try {
    const result = await api(
      "/api/cameras/" + encodeURIComponent(id) + "/control",
      "POST",
      { action, args },
    );
    if (S.selected === id && S.epoch === epoch && C.epoch === generation) {
      $("control-response").textContent = JSON.stringify(result, null, 2);
      if (!quiet) toast(controlNotice(result));
      await loadControlDetails(id);
    }
    return result;
  } catch (e) {
    if (S.selected === id && S.epoch === epoch && C.epoch === generation)
      toast(friendly(e.code));
    throw e;
  } finally {
    if (S.selected === id && S.epoch === epoch && C.epoch === generation) {
      C.busy = false;
      const c = S.cameras.find((c) => c.id === id);
      if (c) renderCameraControls(c);
    }
  }
}
async function refreshAllDetails() {
  const id = S.selected,
    epoch = S.epoch,
    generation = C.epoch;
  C.refreshing = true;
  $("refresh-metadata").disabled = true;
  try {
    for (const section of Object.keys(queryNames)) {
      if (S.selected !== id || S.epoch !== epoch || C.epoch !== generation)
        return;
      $("metadata-progress").textContent = "Читаем: " + queryNames[section];
      await runControl("query", { section }, true);
    }
    if (S.selected !== id || S.epoch !== epoch || C.epoch !== generation)
      return;
    $("metadata-progress").textContent =
      "Параметры обновлены. Ответы «не поддерживается» видны в результате.";
  } catch {
  } finally {
    if (S.selected === id && S.epoch === epoch && C.epoch === generation) {
      C.refreshing = false;
      $("refresh-metadata").disabled = false;
      const c = S.cameras.find((c) => c.id === id);
      if (c) renderCameraControls(c);
    }
  }
}
async function revealCameraPassword() {
  const id = S.selected,
    epoch = S.epoch,
    generation = C.epoch;
  try {
    const value = await api(
      "/api/cameras/" + encodeURIComponent(id) + "/credentials",
      "POST",
      {},
    );
    if (S.selected !== id || S.epoch !== epoch || C.epoch !== generation)
      return;
    closeCredentialDialog();
    const dialog = document.createElement("dialog");
    dialog.id = "credentials-dialog";
    dialog.className = "control-dialog";
    const title = document.createElement("h3");
    title.textContent = "Локальные данные камеры";
    const note = document.createElement("p");
    note.textContent =
      "Нативный пароль, выданный вашему аккаунту. Это не пароль входа в O-Kam Pro. Окно закроется через 30 секунд.";
    dialog.append(title, note);
    for (const [key, label] of [
      ["username", "Пользователь камеры"],
      ["password", "Пароль камеры"],
    ]) {
      const l = document.createElement("label");
      l.textContent = label;
      const input = document.createElement("input");
      input.readOnly = true;
      input.value = value[key];
      input.setAttribute("aria-label", label);
      const b = document.createElement("button");
      b.textContent = "Копировать " + label.toLowerCase();
      b.onclick = async () => {
        try {
          await navigator.clipboard.writeText(input.value);
          b.textContent = "Скопировано";
        } catch {
          input.select();
        }
      };
      dialog.append(l, input, b);
    }
    const close = document.createElement("button");
    close.textContent = "Закрыть";
    close.onclick = closeCredentialDialog;
    dialog.append(close);
    dialog.oncancel = () => dialog.remove();
    document.body.append(dialog);
    dialog.showModal();
    setTimeout(() => {
      if (dialog.isConnected) {
        dialog.close();
        dialog.remove();
      }
    }, 30000);
  } catch (e) {
    if (S.selected === id && S.epoch === epoch && C.epoch === generation)
      toast(friendly(e.code));
  }
}
for (const b of document.querySelectorAll("[data-move]"))
  b.onclick = () =>
    runControl($("ptz-mode").value === "firmware" ? "ptz_step" : "ptz", {
      direction: b.dataset.move,
      speed: Number($("ptz-speed").value),
      duration_ms: Number($("ptz-duration").value),
      lens: Number($("ptz-lens").value),
    }).catch(() => {});
$("preset-apply").onclick = () =>
  runControl("preset", {
    slot: Number($("preset-slot").value),
    operation: $("preset-operation").value,
  }).catch(() => {});
$("volume-apply").onclick = () =>
  runControl("volume", {
    channel: $("volume-channel").value,
    value: Number($("volume-value").value),
  }).catch(() => {});
$("image-apply").onclick = () =>
  runControl("image", {
    field: $("image-field").value,
    value: Number($("image-value").value),
  }).catch(() => {});
$("image-field").onchange = () => {
  const field = $("image-field").value;
  const max = ["brightness", "contrast"].includes(field)
    ? 255
    : field === "night"
      ? 2
      : 3;
  $("image-value").max = max;
  $("image-value").value =
    field === "orientation" ? 0 : field === "night" ? 0 : 126;
};
$("ptz-stop").onclick = () => runControl("ptz_stop").catch(() => {});
$("ptz-calibrate").onclick = () => runControl("calibrate").catch(() => {});
$("cruise-apply").onclick = () =>
  runControl("cruise", { mode: $("cruise-mode").value }).catch(() => {});
$("zoom-apply").onclick = () =>
  runControl("zoom", { scale: Number($("zoom-scale").value) }).catch(() => {});
$("toggle-apply").onclick = () =>
  runControl($("toggle-action").value, {
    value: Number($("toggle-value").value),
  }).catch(() => {});
$("parameter-apply").onclick = () =>
  runControl("camera_parameter", {
    param: Number($("camera-param").value),
    value: Number($("camera-value").value),
  }).catch(() => {});
$("parameter-preset").onchange = () => {
  if ($("parameter-preset").value !== "")
    $("camera-param").value = $("parameter-preset").value;
};
$("query-apply").onclick = () =>
  runControl("query", { section: $("query-section").value }).catch(() => {});
$("archive-files").onclick = () =>
  runControl("archive_files", { date: $("archive-date").value.trim() }).catch(
    () => {},
  );
$("native-send").onclick = () =>
  runControl("native", { path: $("native-path").value.trim() }).catch(() => {});
$("refresh-metadata").onclick = refreshAllDetails;
$("show-credentials").onclick = revealCameraPassword;
$("metadata-search").oninput = renderMetadata;
$("export-metadata").onclick = () => {
  if (!C.data) return;
  const blob = new Blob([JSON.stringify(C.data, null, 2)], {
      type: "application/json",
    }),
    url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = "camera-metadata.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
for (const [key, label] of Object.entries(queryNames)) {
  const o = document.createElement("option");
  o.value = key;
  o.textContent = label;
  $("query-section").append(o);
}

for (const [label, path] of Object.entries(nativeExamples)) {
  const o = document.createElement("option");
  o.value = path;
  o.textContent = label;
  $("native-example").append(o);
}
$("native-example").onchange = () => {
  $("native-path").value = $("native-example").value;
};

$("ptz-mode").onchange = () => {
  const c = S.cameras.find((c) => c.id === S.selected);
  if (c) renderCameraControls(c);
};

// A separate generation rejects late replies, including A → B → A selection.
const N = { generation: 0, busy: false, configBusy: false };
function resetNativeServices() {
  N.generation++;
  N.busy = false;
  N.configBusy = false;
  $("check-services").disabled = false;
  $("services-results").hidden = true;
  $("service-cards").replaceChildren();
  $("service-ports").replaceChildren();
  $("services-instructions").replaceChildren();
  $("services-status").textContent =
    "Сервисы ещё не проверены для этой камеры.";
  $("local-password").value = "";
  $("local-password-enabled").checked = false;
  $("local-password-status").textContent = "";
  $("configure-local-password").disabled = false;
}
const resetControlsWithoutServices = resetControlUI;
resetControlUI = function () {
  resetControlsWithoutServices();
  resetNativeServices();
};
function serviceText(value) {
  return typeof value === "object"
    ? JSON.stringify(value, null, 2)
    : String(value ?? "Нет данных");
}
function renderNativeServices(result) {
  $("services-results").hidden = false;
  $("service-cards").replaceChildren();
  for (const name of ["onvif", "rtsp"]) {
    const capability = result.capabilities?.[name] || {},
      config = result.configuration?.[name] || {};
    const card = document.createElement("article");
    card.className = "box service-card";
    const title = document.createElement("h3");
    title.textContent = name.toUpperCase();
    const state = document.createElement("p");
    state.className = "service-state";
    state.textContent =
      capability.available === true
        ? "Обнаружен"
        : capability.available === false
          ? "Не обнаружен"
          : "Неизвестно";
    const evidence = document.createElement("pre");
    evidence.className = "control-response";
    evidence.textContent = serviceText(capability.evidence);
    const button = document.createElement("button");
    button.disabled = true;
    button.textContent = "Переключение недоступно";
    const reason = document.createElement("p");
    reason.className = "muted";
    reason.textContent =
      config.reason ||
      "Отдельная команда включения этого сервиса не подтверждена для прошивки.";
    card.append(title, state, evidence, button, reason);
    $("service-cards").append(card);
  }
  $("services-address").textContent =
    "Проверенный адрес: " + (result.ip || "не определён");
  $("service-ports").replaceChildren();
  for (const port of result.ports || []) {
    const tr = document.createElement("tr");
    for (const value of [
      port.port,
      port.service,
      port.open === true
        ? "Открыт"
        : port.open === false
          ? "Закрыт / нет ответа"
          : "Неизвестно",
    ]) {
      const td = document.createElement("td");
      td.textContent = String(value ?? "—");
      tr.append(td);
    }
    $("service-ports").append(tr);
  }
  $("services-instructions").replaceChildren();
  for (const text of result.instructions || []) {
    const li = document.createElement("li");
    li.textContent = text;
    $("services-instructions").append(li);
  }
}
async function checkNativeServices() {
  const id = S.selected,
    epoch = S.epoch,
    generation = N.generation;
  if (!id || N.busy) return;
  N.busy = true;
  $("check-services").disabled = true;
  $("services-status").textContent = "Проверяем порты и признаки сервисов…";
  try {
    const result = await api(
      "/api/cameras/" + encodeURIComponent(id) + "/services",
    );
    if (S.selected !== id || S.epoch !== epoch || N.generation !== generation)
      return;
    renderNativeServices(result);
    $("services-status").textContent =
      "Проверка завершена. Результат отражает доступность сейчас.";
  } catch (error) {
    if (S.selected === id && S.epoch === epoch && N.generation === generation)
      $("services-status").textContent = friendly(error.code);
  } finally {
    if (S.selected === id && S.epoch === epoch && N.generation === generation) {
      N.busy = false;
      $("check-services").disabled = false;
    }
  }
}
$("check-services").onclick = checkNativeServices;
$("local-password-form").onsubmit = async (event) => {
  event.preventDefault();
  const id = S.selected,
    epoch = S.epoch,
    generation = N.generation;
  if (!id || N.configBusy) return;
  const enabled = $("local-password-enabled").checked,
    password = $("local-password").value;
  if (enabled && !/^[\x20-\x7e]{8,63}$/.test(password)) {
    $("local-password-status").textContent =
      "Введите от 8 до 63 печатных ASCII-символов.";
    return;
  }
  N.configBusy = true;
  $("configure-local-password").disabled = true;
  $("local-password-status").textContent = "Отправляем настройку камере…";
  $("local-password").value = "";
  try {
    const result = await api(
      "/api/cameras/" + encodeURIComponent(id) + "/control",
      "POST",
      {
        action: "plaintext_password",
        args: enabled ? { enabled: true, password } : { enabled: false },
      },
    );
    if (S.selected !== id || S.epoch !== epoch || N.generation !== generation)
      return;
    $("local-password-status").textContent =
      controlNotice(result) +
      ". Нажмите «Проверить сервисы», чтобы проверить доступность ONVIF / RTSP.";
  } catch (error) {
    if (S.selected === id && S.epoch === epoch && N.generation === generation)
      $("local-password-status").textContent = friendly(error.code);
  } finally {
    if (S.selected === id && S.epoch === epoch && N.generation === generation) {
      N.configBusy = false;
      $("local-password").value = "";
      $("configure-local-password").disabled = !S.cameras.some(
        (camera) => camera.id === id && camera.viewable,
      );
    }
  }
};
