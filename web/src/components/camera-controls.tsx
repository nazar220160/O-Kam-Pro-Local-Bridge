"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  ChevronDown,
  CircleStop,
  Code2,
  Loader2,
  Move,
  RotateCcw,
  Send,
  SlidersHorizontal,
  Volume2,
  ZoomIn,
} from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { queryKeys, useCameraDetails } from "@/lib/queries";
import type { Camera, ControlResult } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  CapabilityBadge,
  controlFeedback,
  FormField,
  querySections,
  selectClass,
} from "./camera-panel-utils";

const nativeExamples: Record<string, string> = {
  Статус: "get_status.cgi?",
  "Все параметры": "get_params.cgi?",
  "Изображение и звук": "get_camera_params.cgi?",
  "Позиции PTZ": "trans_cmd_string.cgi?cmd=2161&command=0&",
  "Даты на SD": "get_record_file.cgi?GetType=date&",
  "Режим записи SD": "get_record.cgi?",
  "План записи SD": "trans_cmd_string.cgi?cmd=2017&command=11&mark=212&type=3&",
  "План записи по движению":
    "trans_cmd_string.cgi?cmd=2017&command=11&mark=212&type=1&",
  "План тревог": "trans_cmd_string.cgi?cmd=2017&command=11&mark=212&type=2&",
  "Зоны движения сенсора 0":
    "trans_cmd_string.cgi?cmd=2123&command=3&sensor=0&",
  "Облачная запись": "trans_cmd_string.cgi?cmd=2106&command=8&",
  "Режим тревожного света": "trans_cmd_string.cgi?cmd=2108&command=0&",
  Слежение: "trans_cmd_string.cgi?cmd=2127&command=1&",
  "Слежение с зумом": "trans_cmd_string.cgi?cmd=2126&command=1&",
  Индикатор: "trans_cmd_string.cgi?cmd=2125&command=1&",
  Энергосбережение: "trans_cmd_string.cgi?cmd=2106&command=17&",
  Питание: "trans_cmd_string.cgi?cmd=2106&command=14&",
};
const modes = {
  light: "Белая подсветка",
  tracking: "Слежение за человеком",
  zoom_tracking: "Слежение с зумом",
  indicator: "Скрытие индикатора",
  siren: "Сирена",
  osd: "Дата и время на видео",
  record_audio: "Звук в записях SD",
};
const actionCapabilities: Record<string, string> = {
  preset: "ptz",
  cruise: "ptz",
  light: "white_light",
  tracking: "tracking",
  zoom_tracking: "tracking",
  record_audio: "microphone",
};
function validInteger(value: string, min: number, max: number) {
  const number = Number(value);
  return (
    value.trim() !== "" &&
    Number.isInteger(number) &&
    number >= min &&
    number <= max
  );
}
const directions = [
  {
    value: "up",
    label: "Повернуть вверх",
    icon: ArrowUp,
    position: "col-start-2",
  },
  {
    value: "left",
    label: "Повернуть влево",
    icon: ArrowLeft,
    position: "col-start-1 row-start-2",
  },
  {
    value: "right",
    label: "Повернуть вправо",
    icon: ArrowRight,
    position: "col-start-3 row-start-2",
  },
  {
    value: "down",
    label: "Повернуть вниз",
    icon: ArrowDown,
    position: "col-start-2 row-start-3",
  },
] as const;

export function CameraControls({ camera }: { camera: Camera }) {
  return <CameraControlsPanel key={camera.id} camera={camera} />;
}

function CameraControlsPanel({ camera }: { camera: Camera }) {
  const queryClient = useQueryClient();
  const details = useCameraDetails(camera.id);
  const [pending, setPending] = useState<string | null>(null);
  const busy = useRef(false);
  const generation = useRef(0);
  const hold = useRef<{ id: string; pulse: boolean } | null>(null);
  const [lastResult, setLastResult] = useState<ControlResult | null>(null);
  const [ptzMode, setPtzMode] = useState("step");
  const [speed, setSpeed] = useState("1");
  const [duration, setDuration] = useState("200");
  const [lens, setLens] = useState("0");
  const [preset, setPreset] = useState("1");
  const [presetOperation, setPresetOperation] = useState("goto");
  const [cruise, setCruise] = useState("stop_horizontal");
  const [zoom, setZoom] = useState("1");
  const [imageField, setImageField] = useState("brightness");
  const [imageValue, setImageValue] = useState("126");
  const [volumeChannel, setVolumeChannel] = useState("microphone");
  const [volume, setVolume] = useState("31");
  const [toggle, setToggle] = useState("light");
  const [toggleValue, setToggleValue] = useState("0");
  const [parameter, setParameter] = useState("33");
  const [parameterValue, setParameterValue] = useState("0");
  const [section, setSection] = useState("status");
  const [sdDate, setSdDate] = useState("");
  const [nativePath, setNativePath] = useState("get_status.cgi?");
  const mutation = useMutation({
    mutationFn: ({
      id,
      action,
      args,
    }: {
      id: string;
      action: string;
      args: Record<string, unknown>;
    }) => api.control(id, action, args),
  });
  const stopMutation = useMutation({
    mutationFn: (id: string) => api.control(id, "ptz_stop", {}),
  });
  const ready = camera.viewable;
  const ptzAvailable = details.data?.capabilities?.ptz?.available !== false;
  const disabled = !ready || !!pending;
  const imageMax = ["brightness", "contrast"].includes(imageField)
    ? 255
    : imageField === "night"
      ? 2
      : 3;
  const sensorIds = camera.lenses.length ? camera.lenses : [0];
  const activeLens = sensorIds.includes(Number(lens))
    ? Number(lens)
    : sensorIds[0];
  const validPulse =
    validInteger(speed, 1, 10) && validInteger(duration, 80, 600);

  useEffect(() => {
    const current = ++generation.current;
    return () => {
      generation.current = current + 1;
      const active = hold.current;
      hold.current = null;
      if (active?.pulse)
        void api.control(active.id, "ptz_stop", {}).catch(() => {});
    };
  }, [camera.id]);

  useEffect(() => {
    const blur = () => {
      const active = hold.current;
      hold.current = null;
      if (active?.pulse)
        void api.control(active.id, "ptz_stop", {}).catch(() => {});
    };
    window.addEventListener("blur", blur);
    return () => window.removeEventListener("blur", blur);
  }, []);

  async function run(
    action: string,
    args: Record<string, unknown> = {},
    quiet = false,
  ) {
    if (!ready || busy.current) return;
    const current = generation.current,
      id = camera.id;
    busy.current = true;
    setPending(action);
    try {
      const result = await mutation.mutateAsync({ id, action, args });
      if (generation.current !== current) return;
      setLastResult(result);
      if (result.state === "rejected" || result.state === "interrupted")
        toast.error(controlFeedback(result));
      else if (!quiet) toast.success(controlFeedback(result));
      await queryClient.invalidateQueries({ queryKey: queryKeys.details(id) });
    } catch (error) {
      if (generation.current === current) toast.error(errorMessage(error));
    } finally {
      if (generation.current === current) {
        busy.current = false;
        setPending(null);
      }
    }
  }

  async function stop() {
    if (!ready || stopMutation.isPending) return;
    const current = generation.current;
    try {
      const result = await stopMutation.mutateAsync(camera.id);
      if (generation.current === current) {
        setLastResult(result);
        if (result.state === "rejected") toast.error(controlFeedback(result));
      }
    } catch (error) {
      if (generation.current === current) toast.error(errorMessage(error));
    }
  }

  function move(direction: string) {
    if (ptzMode === "pulse" && !validPulse) return;
    const args =
      ptzMode === "step"
        ? { direction }
        : {
            direction,
            speed: Number(speed),
            duration_ms: Number(duration),
            lens: activeLens,
          };
    void run(ptzMode === "step" ? "ptz_step" : "ptz", args, true);
  }
  function releaseMotion() {
    const active = hold.current;
    hold.current = null;
    if (active?.pulse) void stop();
  }
  const actionButton = (
    label: string,
    action: string,
    args: Record<string, unknown>,
    icon = false,
  ) => (
    <Button
      type="button"
      variant="secondary"
      className="w-full"
      disabled={
        disabled ||
        details.data?.capabilities?.[actionCapabilities[action]]?.available ===
          false ||
        (action === "preset" && !validInteger(preset, 1, 5))
      }
      onClick={() => void run(action, args)}
    >
      {pending === action ? (
        <Loader2 className="size-4 animate-spin" />
      ) : icon ? (
        <Check className="size-4" />
      ) : null}
      {label}
    </Button>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Управление камерой
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {ready
              ? "Команды выполняются через текущее подключение камеры."
              : "Подключите видео, чтобы управлять камерой."}
          </p>
        </div>
        {pending && (
          <Badge variant="secondary" className="gap-2">
            <Loader2 className="size-3 animate-spin" />
            Выполняем команду
          </Badge>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(details.data?.capabilities || {}).map(
          ([name, capability]) => (
            <CapabilityBadge
              key={name}
              name={name}
              available={capability.available}
            />
          ),
        )}
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(300px,.95fr)_minmax(0,1.25fr)]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Move className="size-4 text-primary" />
              Поворот и позиции
            </CardTitle>
            <CardDescription>
              Точный шаг или короткий импульс движения.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {!ptzAvailable && (
              <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-200">
                Камера сообщает об отсутствии мотора PTZ.
              </p>
            )}
            <FormField label="Режим поворота" htmlFor="ptz-mode">
              <select
                id="ptz-mode"
                className={selectClass}
                value={ptzMode}
                disabled={disabled}
                onChange={(e) => setPtzMode(e.target.value)}
              >
                <option value="step">Шаг прошивки · основной мотор</option>
                <option value="pulse">Короткий импульс · выбор сенсора</option>
              </select>
            </FormField>
            <div className="mx-auto grid w-fit grid-cols-3 gap-2 rounded-2xl border border-border/60 bg-muted/25 p-3">
              {directions.map(({ value, label, icon: Icon, position }) => (
                <Button
                  key={value}
                  type="button"
                  variant="outline"
                  size="icon"
                  aria-label={label}
                  className={`size-14 touch-none rounded-xl ${position}`}
                  disabled={
                    disabled ||
                    !ptzAvailable ||
                    (ptzMode === "pulse" && !validPulse)
                  }
                  onPointerDown={(e) => {
                    if (e.button !== 0) return;
                    e.preventDefault();
                    e.currentTarget.setPointerCapture(e.pointerId);
                    hold.current = {
                      id: camera.id,
                      pulse: ptzMode === "pulse",
                    };
                    move(value);
                  }}
                  onPointerUp={releaseMotion}
                  onPointerCancel={releaseMotion}
                  onLostPointerCapture={releaseMotion}
                  onClick={(e) => {
                    if (e.detail === 0) move(value);
                  }}
                >
                  <Icon className="size-5" />
                </Button>
              ))}
              <Button
                type="button"
                variant="secondary"
                size="icon"
                className="col-start-2 row-start-2 size-14 rounded-xl border border-border"
                aria-label="Остановить поворот"
                disabled={!ready || stopMutation.isPending}
                onClick={() => void stop()}
              >
                <CircleStop className="size-5 text-rose-300" />
              </Button>
            </div>
            <p className="text-center text-xs leading-relaxed text-muted-foreground">
              Каждое нажатие ограничено по времени. Для импульса стоп
              отправляется и при отпускании кнопки.
            </p>
            {ptzMode === "pulse" && (
              <div className="grid grid-cols-3 gap-3">
                <FormField label="Скорость" htmlFor="ptz-speed">
                  <Input
                    id="ptz-speed"
                    type="number"
                    min={1}
                    max={10}
                    value={speed}
                    onChange={(e) => setSpeed(e.target.value)}
                    disabled={disabled}
                  />
                </FormField>
                <FormField label="Импульс, мс" htmlFor="ptz-duration">
                  <Input
                    id="ptz-duration"
                    type="number"
                    min={80}
                    max={600}
                    step={20}
                    value={duration}
                    onChange={(e) => setDuration(e.target.value)}
                    disabled={disabled}
                  />
                </FormField>
                <FormField label="Сенсор" htmlFor="ptz-lens">
                  <select
                    id="ptz-lens"
                    className={selectClass}
                    value={String(activeLens)}
                    onChange={(e) => setLens(e.target.value)}
                    disabled={disabled}
                  >
                    {sensorIds.map((id) => (
                      <option key={id} value={id}>
                        Линза {id + 1}
                      </option>
                    ))}
                  </select>
                </FormField>
              </div>
            )}
            <div className="space-y-3 border-t pt-5">
              <h3 className="text-sm font-medium">Сохранённая позиция</h3>
              <div className="grid grid-cols-[80px_1fr] gap-3">
                <Input
                  aria-label="Номер позиции"
                  type="number"
                  min={1}
                  max={5}
                  value={preset}
                  onChange={(e) => setPreset(e.target.value)}
                  disabled={disabled}
                />
                <select
                  aria-label="Действие с позицией"
                  className={selectClass}
                  value={presetOperation}
                  onChange={(e) => setPresetOperation(e.target.value)}
                  disabled={disabled}
                >
                  <option value="goto">Перейти</option>
                  <option value="save">Сохранить текущую</option>
                  <option value="delete">Удалить</option>
                </select>
              </div>
              {actionButton("Применить позицию", "preset", {
                slot: Number(preset),
                operation: presetOperation,
              })}
            </div>
            <details className="group border-t pt-4">
              <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">
                Круиз, калибровка и зум
                <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
              </summary>
              <div className="mt-4 space-y-4">
                <FormField label="Режим круиза" htmlFor="cruise-mode">
                  <select
                    id="cruise-mode"
                    className={selectClass}
                    value={cruise}
                    onChange={(e) => setCruise(e.target.value)}
                    disabled={disabled}
                  >
                    <option value="stop_horizontal">
                      Остановить горизонтальный
                    </option>
                    <option value="stop_vertical">
                      Остановить вертикальный
                    </option>
                    <option value="stop_presets">Остановить по позициям</option>
                    <option value="horizontal">Горизонтальный</option>
                    <option value="vertical">Вертикальный</option>
                    <option value="presets">По позициям</option>
                  </select>
                </FormField>
                {actionButton("Применить круиз", "cruise", { mode: cruise })}
                <Button
                  variant="outline"
                  className="w-full"
                  disabled={disabled || !ptzAvailable}
                  onClick={() => void run("calibrate")}
                >
                  <RotateCcw className="size-4" />
                  Калибровка PTZ
                </Button>
                <FormField label="Оптический зум · 1–30" htmlFor="zoom-scale">
                  <Input
                    id="zoom-scale"
                    type="number"
                    min={1}
                    max={30}
                    value={zoom}
                    onChange={(e) => setZoom(e.target.value)}
                    disabled={
                      disabled ||
                      details.data?.capabilities?.zoom?.available === false
                    }
                  />
                </FormField>
                <Button
                  variant="outline"
                  className="w-full"
                  disabled={
                    disabled ||
                    details.data?.capabilities?.zoom?.available === false ||
                    !validInteger(zoom, 1, 30)
                  }
                  onClick={() => void run("zoom", { scale: Number(zoom) })}
                >
                  <ZoomIn className="size-4" />
                  Установить зум
                </Button>
              </div>
            </details>
          </CardContent>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <SlidersHorizontal className="size-4 text-primary" />
                Изображение и звук
              </CardTitle>
              <CardDescription>
                Настройки применяются к камере и могут влиять на все линзы.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run("image", {
                    field: imageField,
                    value: Number(imageValue),
                  });
                }}
              >
                <div className="grid gap-3 sm:grid-cols-[1fr_100px]">
                  <FormField label="Параметр изображения" htmlFor="image-field">
                    <select
                      id="image-field"
                      className={selectClass}
                      value={imageField}
                      disabled={disabled}
                      onChange={(e) => {
                        setImageField(e.target.value);
                        setImageValue(
                          ["brightness", "contrast"].includes(e.target.value)
                            ? "126"
                            : "0",
                        );
                      }}
                    >
                      <option value="brightness">Яркость</option>
                      <option value="contrast">Контраст</option>
                      <option value="orientation">Зеркало / переворот</option>
                      <option value="night">Ночное видение</option>
                    </select>
                  </FormField>
                  <FormField label={`0–${imageMax}`} htmlFor="image-value">
                    <Input
                      id="image-value"
                      required
                      type="number"
                      min={0}
                      max={imageMax}
                      value={imageValue}
                      onChange={(e) => setImageValue(e.target.value)}
                      disabled={disabled}
                    />
                  </FormField>
                </div>
                {imageField === "orientation" && (
                  <p className="text-xs text-muted-foreground">
                    0 — обычное · 1 — зеркало · 2 — переворот · 3 — оба
                  </p>
                )}
                {imageField === "night" && (
                  <p className="text-xs text-muted-foreground">
                    0 — чёрно-белая · 1 — цветная · 2 — умная
                  </p>
                )}
                <Button
                  type="submit"
                  variant="secondary"
                  className="w-full"
                  disabled={disabled}
                >
                  Применить изображение
                </Button>
              </form>
              <form
                className="space-y-3 border-t pt-5"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run("volume", {
                    channel: volumeChannel,
                    value: Number(volume),
                  });
                }}
              >
                <div className="grid gap-3 sm:grid-cols-[1fr_100px]">
                  <FormField label="Громкость" htmlFor="volume-channel">
                    <select
                      id="volume-channel"
                      className={selectClass}
                      value={volumeChannel}
                      onChange={(e) => setVolumeChannel(e.target.value)}
                      disabled={disabled}
                    >
                      <option value="microphone">Микрофон камеры</option>
                      <option value="speaker">Динамик камеры</option>
                    </select>
                  </FormField>
                  <FormField label="0–31" htmlFor="volume-value">
                    <Input
                      id="volume-value"
                      type="number"
                      required
                      min={0}
                      max={31}
                      value={volume}
                      onChange={(e) => setVolume(e.target.value)}
                      disabled={disabled}
                    />
                  </FormField>
                </div>
                <Button
                  type="submit"
                  variant="outline"
                  className="w-full"
                  disabled={disabled}
                >
                  <Volume2 className="size-4" />
                  Установить громкость
                </Button>
              </form>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Функции камеры</CardTitle>
              <CardDescription>
                Доступность и значения зависят от модели и прошивки.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-[1fr_130px]">
                <select
                  aria-label="Функция камеры"
                  className={selectClass}
                  value={toggle}
                  onChange={(e) => setToggle(e.target.value)}
                  disabled={disabled}
                >
                  {Object.entries(modes).map(([value, title]) => (
                    <option key={value} value={value}>
                      {title}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Новое состояние функции"
                  className={selectClass}
                  value={toggleValue}
                  onChange={(e) => setToggleValue(e.target.value)}
                  disabled={disabled}
                >
                  <option value="0">Выключить</option>
                  <option value="1">Включить</option>
                </select>
              </div>
              {actionButton(
                "Применить функцию",
                toggle,
                { value: Number(toggleValue) },
                true,
              )}
            </CardContent>
          </Card>
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Code2 className="size-4 text-primary" />
            Расширенные инструменты
          </CardTitle>
          <CardDescription>
            Чтение параметров и прямые команды прошивки.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">
              Прочитать параметры или индекс SD
              <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
            </summary>
            <div className="mt-4 grid gap-5 md:grid-cols-2">
              <div className="space-y-3">
                <FormField label="Раздел параметров" htmlFor="query-section">
                  <select
                    id="query-section"
                    className={selectClass}
                    value={section}
                    onChange={(e) => setSection(e.target.value)}
                    disabled={disabled}
                  >
                    {Object.entries(querySections).map(([key, title]) => (
                      <option key={key} value={key}>
                        {title}
                      </option>
                    ))}
                  </select>
                </FormField>
                {actionButton("Прочитать", "query", { section })}
              </div>
              <form
                className="space-y-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void run("archive_files", { date: sdDate.trim() });
                }}
              >
                <FormField
                  label="Дата / каталог SD"
                  htmlFor="sd-index-date"
                  hint="Индекс записей выводится в ответе камеры."
                >
                  <Input
                    id="sd-index-date"
                    required
                    pattern="[0-9_-]{8,16}"
                    maxLength={16}
                    placeholder="20261101"
                    value={sdDate}
                    onChange={(e) => setSdDate(e.target.value)}
                    disabled={disabled}
                  />
                </FormField>
                <Button
                  type="submit"
                  variant="outline"
                  className="w-full"
                  disabled={disabled}
                >
                  Получить индекс SD
                </Button>
              </form>
            </div>
          </details>
          <details className="group border-t pt-4">
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">
              Числовой параметр изображения
              <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
            </summary>
            <form
              className="mt-4 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void run("camera_parameter", {
                  param: Number(parameter),
                  value: Number(parameterValue),
                });
              }}
            >
              <select
                aria-label="Шаблон числового параметра"
                className={selectClass}
                defaultValue=""
                disabled={disabled}
                onChange={(e) => {
                  if (e.target.value) setParameter(e.target.value);
                }}
              >
                <option value="">Выберите параметр или укажите номер</option>
                <option value="33">Ночное видение · 33</option>
                <option value="14">Звёздное / чёрно-белое · 14</option>
                <option value="5">Переворот / зеркало · 5</option>
                <option value="3">Антимерцание · 3</option>
                <option value="16">Качество потока · 16</option>
              </select>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Номер · 0–255" htmlFor="camera-param">
                  <Input
                    id="camera-param"
                    type="number"
                    required
                    min={0}
                    max={255}
                    value={parameter}
                    onChange={(e) => setParameter(e.target.value)}
                    disabled={disabled}
                  />
                </FormField>
                <FormField label="Значение" htmlFor="camera-param-value">
                  <Input
                    id="camera-param-value"
                    type="number"
                    required
                    min={-10000}
                    max={10000}
                    value={parameterValue}
                    onChange={(e) => setParameterValue(e.target.value)}
                    disabled={disabled}
                  />
                </FormField>
              </div>
              <Button type="submit" variant="outline" disabled={disabled}>
                <Send className="size-4" />
                Отправить параметр
              </Button>
            </form>
          </details>
          <details className="group border-t pt-4">
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">
              Консоль CGI
              <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
            </summary>
            <form
              className="mt-4 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void run("native", { path: nativePath.trim() });
              }}
            >
              <p className="text-xs leading-relaxed text-muted-foreground">
                Команда выполняется на выбранной камере. Данные авторизации
                добавляет мост. Шаблон только заполняет поле; отправка —
                отдельным действием.
              </p>
              <select
                aria-label="Шаблон CGI-команды"
                className={selectClass}
                defaultValue=""
                disabled={disabled}
                onChange={(e) => {
                  if (e.target.value) setNativePath(e.target.value);
                }}
              >
                <option value="">Выбрать шаблон</option>
                {Object.entries(nativeExamples).map(([title, path]) => (
                  <option key={path} value={path}>
                    {title}
                  </option>
                ))}
              </select>
              <textarea
                aria-label="CGI-команда без IP и пароля"
                className="min-h-24 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
                required
                spellCheck={false}
                value={nativePath}
                onChange={(e) => setNativePath(e.target.value)}
                disabled={disabled}
              />
              <Button type="submit" disabled={disabled}>
                <Send className="size-4" />
                Выполнить на камере
              </Button>
            </form>
          </details>
          <details className="group border-t pt-4" open={!!lastResult}>
            <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium">
              Последний ответ камеры
              <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
            </summary>
            <pre className="mt-3 max-h-96 overflow-auto rounded-lg border border-border/70 bg-muted/20 p-4 font-mono text-xs leading-relaxed text-muted-foreground">
              {lastResult
                ? JSON.stringify(lastResult, null, 2)
                : "Отправьте команду, чтобы увидеть ответ."}
            </pre>
          </details>
        </CardContent>
      </Card>
    </div>
  );
}
