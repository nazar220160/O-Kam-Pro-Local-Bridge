import axios from "axios";
import type {
  AccountInfo,
  ArchiveStatus,
  Camera,
  CameraDetails,
  ControlResult,
  Credentials,
  ExportStatus,
  Health,
  NativeServices,
  SDRecord,
  StreamPreferences,
} from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    public status = 0,
  ) {
    super(code);
    this.name = "ApiError";
  }
}
export const http = axios.create({
  baseURL: "/",
  withCredentials: true,
  timeout: 25_000,
  headers: { "Content-Type": "application/json" },
});
async function request<T>(
  method: "get" | "post",
  url: string,
  data?: unknown,
  signal?: AbortSignal,
  timeout = 25_000,
): Promise<T> {
  try {
    return (await http.request<T>({ method, url, data, signal, timeout })).data;
  } catch (error) {
    if (axios.isCancel(error)) throw error;
    if (axios.isAxiosError(error))
      throw new ApiError(
        typeof error.response?.data?.error === "string"
          ? error.response.data.error
          : error.code === "ECONNABORTED"
            ? "request_timeout"
            : "network_unavailable",
        error.response?.status || 0,
      );
    throw error;
  }
}
const cameraPath = (id: string) => `/api/cameras/${encodeURIComponent(id)}`;
// A late logout response must not clear the HttpOnly cookie of a newer login.
let authWrite: Promise<unknown> = Promise.resolve();
function authMutation<T>(write: () => Promise<T>): Promise<T> {
  const next = authWrite.catch(() => undefined).then(write);
  authWrite = next.then(
    () => undefined,
    () => undefined,
  );
  return next;
}
export const api = {
  account: async (signal?: AbortSignal) => {
    await authWrite;
    return request<AccountInfo>("get", "/api/account", undefined, signal);
  },
  health: (signal?: AbortSignal) =>
    request<Health>("get", "/health", undefined, signal),
  login: (username: string, password: string) =>
    authMutation(async () => {
      const value = await request<AccountInfo>("post", "/api/account/login", {
        username,
        password,
      });
      // Account tokens stay in the HttpOnly cookie; never cache the login response's bearer token.
      return { username: value.username, camera_count: value.camera_count };
    }),
  logout: () =>
    authMutation(() =>
      request<{ ok: boolean }>("post", "/api/account/logout", {}),
    ),
  cameras: (signal?: AbortSignal) =>
    request<Camera[]>("get", "/api/cameras", undefined, signal),
  refreshCatalog: () => request<Camera[]>("post", "/api/account/refresh", {}),
  connect: (id: string, preferences: StreamPreferences) =>
    request<{ ok: boolean; state: string }>(
      "post",
      cameraPath(id) + "/connect",
      preferences,
    ),
  disconnect: (id: string) =>
    request<{ ok: boolean }>("post", cameraPath(id) + "/disconnect", {}),
  stream: (id: string, preferences: StreamPreferences) =>
    request<{ ok: boolean; mode: "live" | "reconnect" }>(
      "post",
      cameraPath(id) + "/stream",
      preferences,
    ),
  details: (id: string, signal?: AbortSignal) =>
    request<CameraDetails>(
      "get",
      cameraPath(id) + "/details",
      undefined,
      signal,
    ),
  services: (id: string) =>
    request<NativeServices>("get", cameraPath(id) + "/services"),
  control: (id: string, action: string, args: Record<string, unknown> = {}) =>
    request<ControlResult>("post", cameraPath(id) + "/control", {
      action,
      args,
    }),
  credentials: (id: string) =>
    request<Credentials>("post", cameraPath(id) + "/credentials", {}),
  player: () => request<Credentials>("get", "/api/account/player"),
  exportStatus: (id: string, signal?: AbortSignal) =>
    request<ExportStatus>("get", cameraPath(id) + "/export", undefined, signal),
  configureExport: (id: string, data: Record<string, unknown>) =>
    request<ExportStatus>("post", cameraPath(id) + "/export", data),
  exportCredentials: (id: string) =>
    request<Credentials>("post", cameraPath(id) + "/export/credentials", {}),
  archiveStatus: (id: string, signal?: AbortSignal) =>
    request<ArchiveStatus>(
      "get",
      cameraPath(id) + "/archive",
      undefined,
      signal,
    ),
  configureArchive: (id: string, data: Record<string, unknown>) =>
    request<Record<string, unknown>>("post", cameraPath(id) + "/archive", data),
  sdDates: (id: string) =>
    request<string[] | { dates: string[] }>(
      "get",
      cameraPath(id) + "/archive/sd_dates",
      undefined,
      undefined,
      120_000,
    ),
  sdRecords: (id: string, date: string) =>
    request<SDRecord[] | { records: SDRecord[] }>(
      "get",
      cameraPath(id) + "/archive/sd_records?date=" + encodeURIComponent(date),
      undefined,
      undefined,
      120_000,
    ),
};

const messages: Record<string, string> = {
  account_login_failed:
    "Не удалось войти. Проверьте логин, пароль и доступность O-Kam Pro.",
  account_login_required: "Войдите в аккаунт, чтобы продолжить.",
  session_expired: "Сессия завершена. Войдите снова.",
  account_service_unavailable: "Сервис O-Kam Pro временно недоступен.",
  network_unavailable: "Нет связи с мостом. Проверьте подключение к серверу.",
  request_timeout: "Сервер не ответил вовремя. Попробуйте ещё раз.",
  state_save_failed:
    "Не удалось сохранить настройки. Проверьте место и права на диске сервера.",
  bridge_auth_required: "Шлюз не подключён к API. Проверьте настройки сервера.",
  camera_not_streaming: "Сначала подключите камеру.",
  camera_stopped: "Подключение к камере закрыто.",
  no_lan_reply:
    "Камера не ответила в локальной сети. Проверьте адрес и подключение.",
  camera_unavailable: "Камера недоступна в локальной сети.",
  connection_failed:
    "Не удалось подключиться. Проверьте доступность камеры и совместимость протокола.",
  cloud_connection_failed:
    "Не удалось связаться с камерой через O-Kam Pro. Проверьте интернет у камеры и сервера.",
  cloud_unavailable_or_video_interrupted:
    "Облачный поток прервался. Мост пытается восстановить связь.",
  camera_unavailable_or_video_interrupted:
    "Видео прервалось. Мост восстанавливает подключение.",
  camera_password_rejected:
    "Камера отклонила данные входа. Обновите список камер.",
  unsupported_protocol: "Транспорт этой камеры пока не поддерживается.",
  native_credentials_unavailable:
    "Аккаунт не предоставил данные для подключения к камере.",
  encrypted_credentials_invalid:
    "Не удалось прочитать данные камеры. Обновите список аккаунта.",
  connection_in_progress: "Камера уже подключается.",
  video_unavailable: "Камера не прислала первый кадр.",
  video_start_rejected: "Камера отклонила запуск видео.",
  invalid_lan_ip: "Введите корректный локальный IPv4-адрес.",
  invalid_quality: "Выберите доступное качество видео.",
  invalid_stream: "Выберите доступный поток.",
  control_busy: "Очередь команд занята. Подождите немного.",
  control_timeout: "Камера не выполнила команду вовремя.",
  control_expired: "Команда устарела. Повторите её.",
  camera_control_failed: "Не удалось передать команду камере.",
  invalid_control_value: "Проверьте значение параметра.",
  advertise_host_required:
    "Укажите адрес сервера моста, доступный вашему плееру или NVR.",
  camera_ip_required: "Для этой операции нужен локальный адрес камеры.",
  invalid_advertise_host:
    "Укажите только IP или имя сервера, без протокола, порта и пароля.",
  rtsp_service_unavailable:
    "Сервис RTSP ещё не готов. Проверьте MediaMTX и повторите попытку.",
  onvif_port_unavailable: "Порт ONVIF занят другим сервисом.",
  export_not_enabled: "Сначала включите RTSP-публикацию моста.",
  archive_operation_failed:
    "Операция с архивом не выполнена. Проверьте публикацию, камеру и место на диске.",
};
export function errorMessage(error: unknown): string {
  const code =
    typeof error === "string"
      ? error
      : error instanceof ApiError
        ? error.code
        : "";
  return messages[code] || "Не удалось выполнить действие. Повторите попытку.";
}
export const friendlyError = errorMessage;
