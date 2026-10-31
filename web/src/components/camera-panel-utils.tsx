"use client";

import type { ReactNode } from "react";
import type { ControlResult } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";

export const querySections = {
  status: "Статус",
  video: "Изображение и звук",
  parameters: "Сеть и параметры",
  light: "Подсветка и сирена",
  tracking: "Слежение",
  zoom_tracking: "Слежение с зумом",
  indicator: "Индикатор",
  presets: "Позиции PTZ",
  archive_dates: "Даты SD-карты",
  recording: "Запись SD",
  sleep: "Энергосбережение",
  power: "Питание",
} as const;

export const featureLabels: Record<string, string> = {
  ptz: "Поворот PTZ",
  microphone: "Микрофон",
  speaker: "Динамик",
  zoom: "Зум",
  tracking: "Слежение",
  sd_card: "SD-карта",
  white_light: "Подсветка",
  night_vision: "Ночное видение",
  presets: "Позиции PTZ",
  ai: "AI",
  onvif: "ONVIF",
};

export function controlFeedback(result: ControlResult) {
  if (result.state === "rejected")
    return (
      "Камера отклонила команду" +
      (result.result == null ? "" : ` · код ${result.result}`)
    );
  if (result.state === "interrupted")
    return "Подключение прервалось. Следующие команды не отправлены.";
  if (result.state === "confirmed") return "Камера подтвердила команду";
  if (result.state === "response") return "Ответ камеры получен";
  return "Команда отправлена. Отдельное подтверждение не получено.";
}

export function valueText(value: unknown) {
  if (value == null) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function CapabilityBadge({
  name,
  available,
}: {
  name: string;
  available?: boolean | null;
}) {
  return (
    <Badge
      variant="outline"
      className={
        available === true
          ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
          : "text-muted-foreground"
      }
    >
      {featureLabels[name] || name}
      <span className="ml-1 opacity-70">
        ·{" "}
        {available === true
          ? "есть"
          : available === false
            ? "нет"
            : "неизвестно"}
      </span>
    </Badge>
  );
}

export function FormField({
  label,
  htmlFor,
  children,
  hint,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint && (
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

export const selectClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-xs dark:bg-input/30 md:text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50";
