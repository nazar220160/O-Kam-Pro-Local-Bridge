const $ = (id) => document.getElementById(id);
const S = {
  username: null,
  cameras: [],
  selected: null,
  lensNodes: new Map(),
  paused: new Set(),
  polling: false,
  ipDirty: false,
  connected: false,
  epoch: 0,
  pendingConnect: null,
};
function uiPreference(update) {
  if (!S.username) return {};
  try {
    const key = "okam-ui:" + S.username.toLowerCase();
    const value = JSON.parse(localStorage.getItem(key) || "{}");
    if (!update) return value;
    const next = { ...value, ...update };
    localStorage.setItem(key, JSON.stringify(next));
    return next;
  } catch { return {}; }
}
const labels = {
  disconnected: "Не подключена",
  preparing: "Готовим локальное подключение…",
  resolving: "Определяем протокол…",
  discovering: "Ищем камеру в локальной сети…",
  starting: "Запускаем видео и ждём первый кадр…",
  connecting: "Подключаемся к камере…",
  streaming: "Идёт локальное видео",
  reconnecting: "Восстанавливаем соединение…",
  idle: "Готова к просмотру",
  error: "Не удалось подключиться",
  stopped: "Остановлена",
};
const errors = {
  state_save_failed: "Не удалось сохранить настройки на диске сервера. Проверьте место и права хранилища состояния.",
  camera_not_streaming: "Сначала откройте видео выбранной камеры.",
  control_busy: "Очередь команд занята.",
  control_timeout: "Камера не выполнила команду вовремя.",
  control_expired: "Команда устарела и не была выполнена. Повторите её.",
  camera_control_failed: "Не удалось передать команду камере.",
  camera_stopped: "Подключение к камере закрыто.",
  invalid_control_value: "Проверьте значение параметра.",
  invalid_native_command: "Нужна CGI-команда без IP и данных авторизации.",
  unknown_control: "Неизвестная команда управления.",
  invalid_quality: "Выберите доступное качество видео.",
  invalid_connection_mode: "Выберите локальное подключение или O-Kam Pro.",
  cloud_connection_failed:
    "Не удалось связаться с камерой через O-Kam Pro. Проверьте интернет на сервере и у камеры; облачный маршрут может быть временно недоступен.",
  cloud_unavailable_or_video_interrupted:
    "Связь через O-Kam Pro недоступна или видео прервалось. Проверьте интернет на сервере и у камеры; можно повторить попытку или открыть локальное видео.",
  password_decoder_required:
    "Обновите мост: расшифровка пароля камеры встроена в актуальную версию.",
  crypto_dependency_required:
    "Для зашифрованного пароля установите зависимости: python3 -m pip install -r requirements.txt",
  encrypted_credentials_invalid:
    "Зашифрованные данные камеры не удалось прочитать. Обновите список аккаунта.",
  credential_client_invalid:
    "Файл официального PC-клиента недоступен или некорректен.",
  credential_key_not_found:
    "В указанном PC-клиенте не найден подходящий ключ пароля.",
  credential_key_ambiguous: "Ключ пароля не удалось определить однозначно.",
  account_login_failed:
    "Не удалось войти. Проверьте логин, пароль и доступность сервиса O-Kam Pro.",
  account_service_unavailable:
    "Сервис аккаунта сейчас недоступен. Попробуйте ещё раз.",
  account_login_required: "Войдите в аккаунт заново.",
  session_expired: "Сессия завершена. Войдите заново.",
  no_lan_reply:
    "Камера не ответила в локальной сети. Проверьте Wi-Fi или укажите её IP вручную.",
  native_credentials_unavailable:
    "Этот аккаунт не выдаёт нативные учётные данные камеры. Текущий драйвер не может открыть её видео. PlainText password не всегда заменяет эти данные.",
  unsupported_protocol:
    "Для этой камеры требуется другой протокол. Она остаётся доступна в каталоге, но текущий драйвер не поддерживает её видео.",
  video_start_rejected:
    "Камера отклонила запуск видео. Проверьте предоставленные аккаунту права и попробуйте другой поток.",
  camera_password_rejected:
    "Камера отклонила выданные аккаунту учётные данные. Обновите список или войдите заново.",
  camera_unavailable: "Камера недоступна по локальной сети.",
  connection_failed:
    "Не удалось подключиться. Проверьте сеть камеры, её доступность и совместимость протокола.",
  camera_unavailable_or_video_interrupted:
    "Передача видео прервалась. Мост пытается восстановить соединение.",
  invalid_lan_ip: "Введите корректный локальный IPv4-адрес.",
  invalid_stream: "Выберите один из доступных потоков.",
  connection_in_progress: "Подключение уже выполняется.",
  video_unavailable: "Камера не прислала видеокадр за отведённое время.",
  too_many_sessions: "Достигнут предел сессий моста.",
};
const friendly = (code) =>
  errors[code] || "Не удалось выполнить действие. Повторите попытку.";
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").hidden = true), 3500);
}
async function api(path, method = "GET", data) {
  const epoch = S.epoch;
  const options = { method, credentials: "same-origin", cache: "no-store" };
  if (data !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(data);
  }
  const r = await fetch(path, options);
  let value;
  try {
    value = await r.json();
  } catch {
    throw { code: "connection_failed" };
  }
  if (!r.ok) {
    if (value.error === "bridge_auth_required" && epoch === S.epoch) {
      location.reload();
    }
    if (
      r.status === 401 &&
      path !== "/api/account/login" &&
      epoch === S.epoch
    ) {
      showLogin();
    }
    throw { code: value.error || "connection_failed" };
  }
  return value;
}
function stopFeeds() {
  for (const item of S.lensNodes.values()) {
    item.img.removeAttribute("src");
    clearTimeout(item.retry);
  }
  S.lensNodes.clear();
  $("lens-grid").replaceChildren();
}
function showLogin() {
  S.epoch++;
  if (typeof resetControlUI === "function") resetControlUI();
  $("refresh").disabled = false;
  closePlayer();
  S.paused.clear();
  stopFeeds();
  S.username = null;
  S.cameras = [];
  S.selected = null;
  S.pendingConnect = null;
  $("workspace").hidden = true;
  $("login-screen").hidden = false;
  $("password").value = "";
}
function showWorkspace(info) {
  S.epoch++;
  $("refresh").disabled = false;
  S.username = info.username;
  $("account-name").textContent = info.username;
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  $("login-error").hidden = true;
  const tab = uiPreference().tab;
  if (["video", "controls", "services", "metadata"].includes(tab)) activateTab(tab);
}
function connectionMode(c) {
  return c.connection_mode || c.transport?.mode || "lan";
}
function statusText(c) {
  if (connectionMode(c) === "cloud") {
    if (["preparing", "resolving", "discovering"].includes(c.state))
      return "Готовим подключение через O-Kam Pro…";
    if (["starting", "connecting"].includes(c.state))
      return "Ждём связь через O-Kam Pro…";
    if (c.state === "streaming")
      return c.transport?.path === "relay"
        ? "Идёт видео через сервер O-Kam Pro"
        : "Идёт видео · O-Kam Pro";
  }
  return labels[c.state] || c.state || "Не подключена";
}
function dotClass(c) {
  return c.error || c.state === "error"
    ? "bad"
    : c.state === "streaming"
      ? "good"
      : [
            "preparing",
            "starting",
            "connecting",
            "reconnecting",
            "discovering",
            "resolving",
          ].includes(c.state)
        ? "busy"
        : "";
}
function renderList() {
  const query = $("search").value.toLocaleLowerCase();
  $("camera-count").textContent = S.cameras.length;
  const list = $("camera-list");
  list.replaceChildren();
  for (const c of S.cameras.filter((c) =>
    c.name.toLocaleLowerCase().includes(query),
  )) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "camera-row" + (S.selected === c.id ? " selected" : "");
    b.setAttribute("aria-pressed", String(S.selected === c.id));
    const title = document.createElement("span");
    title.className = "row-title";
    title.textContent = c.name;
    const state = document.createElement("span");
    state.className = "row-state";
    const dot = document.createElement("i");
    dot.className = "dot " + dotClass(c);
    state.append(dot, document.createTextNode(statusText(c)));
    b.append(title, state);
    b.onclick = () => selectCamera(c.id);
    list.append(b);
  }
  if (!list.children.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = S.cameras.length
      ? "Камера не найдена"
      : "В этом аккаунте пока нет камер.";
    list.append(p);
  }
}
function selectCamera(id) {
  if (S.selected !== id) {
    stopFeeds();
    S.ipDirty = false;
    const c = S.cameras.find((c) => c.id === id);
    $("camera-ip").value = c?.ip || "";
    $("substream").value = String(c?.substream ?? 1);
    $("quality").value = c?.quality || "";
  }
  S.selected = id;
  uiPreference({camera: id});
  renderList();
  renderDetails();
}
function valueText(v, fallback = "Не сообщается") {
  return v === undefined ||
    v === null ||
    v === "" ||
    ["null", "undefined", "none"].includes(String(v).toLowerCase())
    ? fallback
    : typeof v === "boolean"
      ? v
        ? "Да"
        : "Нет"
      : String(v);
}
function info(container, label, value, wide = false) {
  const div = document.createElement("div");
  if (wide) div.className = "wide";
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.textContent = valueText(value);
  div.append(dt, dd);
  container.append(div);
}
function age(value) {
  if (!value) return "Ещё нет кадров";
  const n = Math.max(0, Math.round(Date.now() / 1000 - value));
  return n < 3
    ? "Сейчас"
    : n < 60
      ? n + " с назад"
      : Math.floor(n / 60) + " мин назад";
}
function renderDetails() {
  const c = S.cameras.find((c) => c.id === S.selected);
  if (c && typeof renderCameraControls === "function") renderCameraControls(c);
  $("empty").hidden = !!c;
  $("details").hidden = !c;
  if (!c) {
    stopFeeds();
    return;
  }
  $("camera-title").textContent = c.name;
  $("camera-state").textContent = statusText(c);
  $("state-dot").className = "dot " + dotClass(c);
  const pending = S.pendingConnect?.id === c.id && S.pendingConnect.epoch === S.epoch;
  const busy = pending || ["preparing", "resolving", "discovering", "starting"].includes(c.state);
  const cloud = connectionMode(c) === "cloud";
  const connectingCloud = pending ? S.pendingConnect.mode === "cloud" : cloud;
  $("connect").disabled = busy;
  $("connect-cloud").disabled = busy;
  $("apply-stream").disabled = busy;
  $("substream").disabled = busy;
  $("quality").disabled = busy;
  $("connect").textContent = busy && !connectingCloud
    ? "Подключение…"
    : c.viewable && !cloud
      ? "Переподключить"
      : "Открыть видео";
  $("connect-cloud").textContent = busy && connectingCloud
    ? "Подключение к O-Kam…"
    : c.viewable && cloud
      ? "Переподключить O-Kam Pro"
      : "Через O-Kam Pro";
  $("connection-info").textContent = connectingCloud
    ? "Источник: O-Kam Pro. Локальный IP не используется. Ожидание первого кадра может занимать до 100 секунд."
    : "Источник: локальная сеть. «Через O-Kam Pro» использует интернет и серверы производителя вместо локального IP.";
  $("disconnect").disabled = c.state === "disconnected";
  $("camera-error").hidden = !c.error;
  $("camera-error").textContent = c.error ? friendly(c.error) : "";
  const actual = [
    ...new Set(
      (c.lens_metadata || [])
        .filter((m) => m.width && m.height)
        .map((m) => m.width + " × " + m.height),
    ),
  ];
  $("stream-info").textContent =
    (c.viewable
      ? "Выбрано: " +
        ({ low: "низкое", medium: "среднее", high: "высокое" }[c.quality] ||
          "как есть") +
        ". Фактически: " +
        (actual.length ? actual.join(", ") : "ожидаем параметры видео") +
        ". "
      : "") +
    "Качество запрашивается у самой камеры и действует на все линзы. Низкое качество уменьшает трафик камера → мост; доступное разрешение зависит от прошивки.";
  const m = c.metadata || {},
    a = c.account_metadata || {},
    grid = $("camera-metadata");
  grid.replaceChildren();
  info(grid, "Протокол", c.protocol || "Определяется при подключении");
  info(grid, "Источник подключения", cloud ? "O-Kam Pro" : "Локальная сеть");
  if (c.transport?.path)
    info(grid, "Маршрут видео", ({ relay: "Ретранслятор O-Kam Pro", direct: "Прямое P2P-соединение", lan: "Локальная сеть", LAN: "Локальная сеть" })[c.transport.path] || c.transport.path);
  info(grid, "Локальный IP", c.ip || a.lan_ip || "Не передан аккаунтом");
  info(grid, "Модель / тип", a.model || m.camera_type || a.device_type);
  info(grid, "Прошивка", m.firmware || a.firmware);
  info(grid, "Линз обнаружено", c.lenses.length || "После подключения");
  info(grid, "Последний кадр", age(c.last_frame));
  info(grid, "Микрофон", m.microphone);
  info(grid, "Динамик", m.speaker);
  info(grid, "Мотор / PTZ", m.motor);
  info(
    grid,
    "Состояние в аккаунте",
    a.account_online === undefined
      ? null
      : a.account_online
        ? "В сети по данным аккаунта"
        : "Не в сети по данным аккаунта",
  );
  info(
    grid,
    "Доступ к нативным данным",
    c.capability === "native"
      ? "Выданы этому аккаунту"
      : c.capability === "encrypted"
        ? "Выданы в зашифрованном виде"
        : "Не выданы",
  );
  info(grid, "Активных зрителей", c.viewers);
  info(grid, "ID устройства", c.device_id, true);
  if (m.application_version)
    info(grid, "Версия приложения камеры", m.application_version, true);
  $("lens-summary").textContent = c.viewable
    ? "Одна сессия камеры · отдельные декодеры"
    : "";
  $("lenses-title").textContent = c.viewable
    ? "Линзы · " + c.lenses.length
    : "Линзы";
  $("view-hint").hidden = !!c.viewable;
  if (!c.viewable || pending) {
    stopFeeds();
    return;
  }
  renderLenses(c);
}
function renderLenses(c) {
  const expected = new Set(c.lenses.map(String));
  for (const [key, item] of S.lensNodes) {
    if (!expected.has(key)) {
      item.img.removeAttribute("src");
      clearTimeout(item.retry);
      item.card.remove();
      S.lensNodes.delete(key);
    }
  }
  for (const n of c.lenses) {
    const key = String(n),
      url = "/api/cameras/" + encodeURIComponent(c.id) + "/",
      jpeg = url + "mjpeg?lens=" + n;
    let item = S.lensNodes.get(key);
    if (!item) {
      const card = document.createElement("article");
      card.className = "lens-card";
      card.dataset.lens = n;
      const head = document.createElement("div");
      head.className = "lens-head";
      const title = document.createElement("strong");
      title.textContent = "Линза " + (n + 1);
      const label = document.createElement("span");
      label.className = "lens-label";
      head.append(title, label);
      const picture = document.createElement("div");
      picture.className = "picture";
      const waiting = document.createElement("span");
      waiting.className = "waiting";
      waiting.textContent = "Ожидание кадра…";
      const img = document.createElement("img");
      img.alt = c.name + " · линза " + (n + 1);
      picture.append(waiting, img);
      const stats = document.createElement("dl");
      stats.className = "lens-stats";
      const foot = document.createElement("div");
      foot.className = "lens-foot";
      const shot = document.createElement("a");
      shot.textContent = "Снимок";
      shot.href = url + "snapshot.jpg?lens=" + n;
      shot.target = "_blank";
      shot.rel = "noopener";
      const vlc = document.createElement("button");
      vlc.className = "text-button";
      vlc.textContent = "Ссылка VLC";
      vlc.onclick = async () => {
        const epoch = S.epoch;
        try {
          const p = await api("/api/account/player");
          if (epoch !== S.epoch) return;
          const stream = location.origin + url + "stream.h264?lens=" + n;
          showPlayer(stream, p);
        } catch (e) {
          if (epoch === S.epoch) toast(friendly(e.code));
        }
      };
      const pause = document.createElement("button");
      pause.className = "text-button";
      pause.textContent = "Пауза";
      foot.append(shot, vlc, pause);
      card.append(head, picture, stats, foot);
      $("lens-grid").append(card);
      item = {
        card,
        img,
        label,
        waiting,
        stats,
        pause,
        retry: null,
        source: jpeg,
      };
      S.lensNodes.set(key, item);
      img.onload = () => {
        waiting.hidden = true;
      };
      img.onerror = () => {
        if (S.paused.has(c.id + ":" + n)) return;
        waiting.hidden = false;
        waiting.textContent = "Восстанавливаем изображение…";
        clearTimeout(item.retry);
        item.retry = setTimeout(() => {
          if (S.selected === c.id && !S.paused.has(c.id + ":" + n))
            img.src = jpeg + "&retry=" + Date.now();
        }, 3000);
      };
      pause.onclick = () => {
        const k = c.id + ":" + n;
        if (S.paused.has(k)) {
          S.paused.delete(k);
          img.hidden = false;
          img.src = jpeg + "&resume=" + Date.now();
          pause.textContent = "Пауза";
        } else {
          S.paused.add(k);
          img.removeAttribute("src");
          img.hidden = true;
          waiting.hidden = false;
          waiting.textContent = "Просмотр приостановлен";
          pause.textContent = "Продолжить";
        }
      };
      if (!S.paused.has(c.id + ":" + n)) img.src = jpeg;
      else {
        img.hidden = true;
        waiting.textContent = "Просмотр приостановлен";
        pause.textContent = "Продолжить";
      }
    }
    item.label.textContent = S.paused.has(c.id + ":" + n)
      ? "Пауза"
      : statusText(c);
    const meta = (c.lens_metadata || []).find((m) => m.id === n) || {};
    item.stats.replaceChildren();
    info(
      item.stats,
      "Исходное видео",
      meta.width && meta.height ? meta.width + " × " + meta.height : null,
    );
    info(item.stats, "Кодек", meta.codec ? meta.codec.toUpperCase() : null);
    info(
      item.stats,
      "Частота",
      meta.reported_fps
        ? meta.reported_fps + " кадр/с"
        : meta.measured_fps
          ? meta.measured_fps + " кадр/с"
          : null,
    );
    info(
      item.stats,
      "Битрейт",
      meta.bitrate_kbps ? meta.bitrate_kbps + " кбит/с" : null,
    );
    info(item.stats, "Кадров получено", meta.frames_received);
    info(item.stats, "Последний кадр", age(meta.last_frame));
    if (
      c.state === "idle" &&
      !S.paused.has(c.id + ":" + n) &&
      Date.now() - (item.lastRestart || 0) > 6000
    ) {
      item.lastRestart = Date.now();
      item.img.src = item.source + "&restart=" + Date.now();
    }
  }
}
function closePlayer() {
  const d = $("player-dialog");
  if (d) {
    d.close();
    d.remove();
  }
}
function showPlayer(url, credentials) {
  closePlayer();
  const d = document.createElement("dialog");
  d.id = "player-dialog";
  d.style.cssText =
    "color:var(--text);background:#141c28;border:1px solid #354258;border-radius:18px;padding:28px;max-width:560px;width:85vw";
  const h = document.createElement("h3");
  h.textContent = "Эта линза в VLC";
  d.append(h);
  for (const [label, value] of [
    ["Сетевой адрес", url],
    ["Логин", credentials.username],
    ["Временный пароль плеера", credentials.password],
  ]) {
    const l = document.createElement("label");
    l.textContent = label;
    const input = document.createElement("input");
    input.readOnly = true;
    input.value = value;
    input.setAttribute("aria-label", label);
    input.style.marginBottom = "12px";
    const copy = document.createElement("button");
    copy.textContent = "Копировать " + label.toLowerCase();
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(value);
        copy.textContent = "Скопировано";
      } catch {
        input.select();
      }
    };
    d.append(l, input, copy);
  }
  const note = document.createElement("p");
  note.className = "muted";
  note.textContent =
    "Откройте сетевой адрес в VLC и введите эти данные при запросе авторизации. При необходимости выберите демультиплексор H264. Пароль плеера действует до выхода из аккаунта.";
  const close = document.createElement("button");
  close.textContent = "Закрыть";
  close.onclick = closePlayer;
  d.append(note, close);
  d.oncancel = () => d.remove();
  document.body.append(d);
  d.showModal();
}
async function fetchCatalog() {
  const epoch = S.epoch;
  const cameras = await api("/api/cameras");
  if (epoch !== S.epoch) return;
  S.cameras = cameras;
  if (!S.selected) {
    const saved = uiPreference().camera;
    if (S.cameras.some(c => c.id === saved)) selectCamera(saved);
  }
  if (S.selected && !S.cameras.some((c) => c.id === S.selected))
    S.selected = null;
  renderList();
  renderDetails();
}
$("account-form").onsubmit = async (e) => {
  e.preventDefault();
  $("login-error").hidden = true;
  $("sign-in").disabled = true;
  $("sign-in").textContent = "Входим…";
  try {
    const info = await api("/api/account/login", "POST", {
      username: $("username").value.trim(),
      password: $("password").value,
    });
    showWorkspace(info);
    await fetchCatalog();
  } catch (error) {
    $("login-error").hidden = false;
    $("login-error").textContent = friendly(error.code);
  } finally {
    $("password").value = "";
    $("sign-in").disabled = false;
    $("sign-in").textContent = "Войти в O-Kam Pro";
  }
};
$("search").oninput = renderList;
$("camera-ip").oninput = () => (S.ipDirty = true);
async function openCamera(connection_mode) {
  if (!S.selected) return;
  const id = S.selected, epoch = S.epoch;
  stopFeeds();
  const pending = { id, epoch, mode: connection_mode };
  S.pendingConnect = pending;
  renderDetails();
  try {
    await api("/api/cameras/" + encodeURIComponent(id) + "/connect", "POST", {
      connection_mode,
      ip: connection_mode === "lan" ? $("camera-ip").value.trim() || null : null,
      substream: Number($("substream").value),
      quality: $("quality").value || null,
    });
    if (epoch !== S.epoch) return;
    await fetchCatalog();
  } catch (e) {
    if (epoch === S.epoch && S.selected === id) toast(friendly(e.code));
  } finally {
    if (S.pendingConnect === pending) S.pendingConnect = null;
    if (epoch === S.epoch && S.selected === id) renderDetails();
  }
}
$("connect").onclick = () => openCamera("lan");
$("connect-cloud").onclick = () => openCamera("cloud");
$("apply-stream").onclick = async () => {
  if (!S.selected) return;
  const id = S.selected, epoch = S.epoch;
  const mode = connectionMode(S.cameras.find(c => c.id === id) || {});
  $("apply-stream").disabled = $("connect").disabled = $("connect-cloud").disabled = true;
  try {
    const result = await api("/api/cameras/" + encodeURIComponent(id) + "/stream", "POST", {
      connection_mode: mode,
      ip: mode === "lan" ? $("camera-ip").value.trim() || null : null,
      substream: Number($("substream").value),
      quality: $("quality").value || null,
    });
    if (S.epoch !== epoch || S.selected !== id) return;
    await fetchCatalog();
    toast(result.mode === "live" ? "Качество применено без переподключения." : "Подключаемся с новыми параметрами потока…");
  } catch (error) {
    if (S.epoch === epoch && S.selected === id) toast(friendly(error.code));
  } finally {
    if (S.epoch === epoch && S.selected === id) renderDetails();
  }
};
$("disconnect").onclick = async () => {
  if (!S.selected) return;
  stopFeeds();
  $("disconnect").disabled = true;
  try {
    await api("/api/cameras/" + S.selected + "/disconnect", "POST", {});
    await fetchCatalog();
  } catch (e) {
    toast(friendly(e.code));
  } finally {
    renderDetails();
  }
};
$("refresh").onclick = async () => {
  const epoch = S.epoch;
  $("refresh").disabled = true;
  try {
    const cameras = await api("/api/account/refresh", "POST", {});
    if (epoch !== S.epoch) return;
    S.cameras = cameras;
    renderList();
    renderDetails();
    toast("Список камер обновлён");
  } catch (e) {
    if (epoch === S.epoch) toast(friendly(e.code));
  } finally {
    if (epoch === S.epoch) $("refresh").disabled = false;
  }
};
$("logout").onclick = async () => {
  $("logout").disabled = true;
  stopFeeds();
  try {
    await api("/api/account/logout", "POST", {});
    showLogin();
  } catch (e) {
    toast(friendly(e.code));
  } finally {
    $("logout").disabled = false;
  }
};
async function poll() {
  if (!S.username || S.polling) return;
  S.polling = true;
  try {
    await fetchCatalog();
  } catch (e) {
    if (e.code !== "account_login_required") toast(friendly(e.code));
  } finally {
    S.polling = false;
  }
}
async function resumeWorkspace() {
  try {
    const account = await api("/api/account");
    if (S.username) return;
    showWorkspace(account);
    await fetchCatalog();
  } catch (error) {
    if (error.code === "account_login_required") {
      showLogin();
    } else {
      $("login-error").hidden = false;
      $("login-error").textContent = "Мост запускается или временно недоступен. Подключение восстановится автоматически…";
      setTimeout(() => { if (!S.username) void resumeWorkspace(); }, 2000);
    }
  }
}
void resumeWorkspace();
setInterval(poll, 2500);

// Tab state is local UI state; changing tabs never starts a network probe.
function activateTab(name, focus = false) {
  uiPreference({tab: name});
  const tabs = Array.from(document.querySelectorAll("[data-tab]"));
  for (const tab of tabs) {
    const active = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  }
  for (const panel of document.querySelectorAll("[data-panel]"))
    panel.hidden = panel.dataset.panel !== name;
}
for (const tab of document.querySelectorAll("[data-tab]")) {
  tab.onclick = () => activateTab(tab.dataset.tab);
  tab.onkeydown = (event) => {
    const tabs = Array.from(document.querySelectorAll("[data-tab]")),
      index = tabs.indexOf(tab);
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft")
      next = (index + tabs.length - 1) % tabs.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = tabs.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      activateTab(tabs[next].dataset.tab, true);
    }
  };
}
