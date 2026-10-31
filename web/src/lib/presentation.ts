import type { Camera } from "./types";
export const connectingStates = new Set([
  "preparing",
  "resolving",
  "discovering",
  "starting",
  "connecting",
  "reconnecting",
]);
export function cameraStatus(camera: Camera) {
  if (camera.error || camera.state === "error") return "Нет связи";
  if (camera.state === "streaming") return "В эфире";
  if (connectingStates.has(camera.state))
    return camera.state === "reconnecting" ? "Восстановление" : "Подключение";
  if (camera.viewable) return "Готова к просмотру";
  return "Не подключена";
}
export function transportLabel(camera: Camera) {
  return camera.connection_mode === "cloud" ? "O-Kam Pro" : "Локальная сеть";
}
export function frameAge(stamp?: number | null) {
  if (!stamp) return "Нет кадров";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - stamp));
  return seconds < 3
    ? "Только что"
    : seconds < 60
      ? `${seconds} с назад`
      : `${Math.floor(seconds / 60)} мин назад`;
}
export function formatBytes(bytes = 0) {
  return bytes >= 1024 ** 3
    ? `${(bytes / 1024 ** 3).toFixed(1)} ГиБ`
    : `${Math.round(bytes / 1024 ** 2)} МиБ`;
}
export function cameraMediaURL(
  id: string,
  kind: "mjpeg" | "snapshot.jpg" | "stream.h264",
  lens: number,
) {
  return `/api/cameras/${encodeURIComponent(id)}/${kind}?lens=${lens}`;
}
