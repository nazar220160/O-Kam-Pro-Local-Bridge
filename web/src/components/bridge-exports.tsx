"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  Copy,
  KeyRound,
  Loader2,
  Network,
  Radio,
  RefreshCw,
  ShieldCheck,
  Unplug,
  Video,
} from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import type { Camera } from "@/lib/types";
import { useCameraExport } from "@/lib/queries";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";

function safeAddress(value: string | undefined | null, protocols: string[]) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return protocols.includes(url.protocol) &&
      !url.username &&
      !url.password &&
      !url.hash
      ? url.href
      : "";
  } catch {
    return "";
  }
}

function CopyField({
  label,
  value,
  mono = true,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1800);
    } catch {
      input.current?.focus();
      input.current?.select();
      toast.info("Значение выделено — скопируйте его сочетанием клавиш.");
    }
  }
  return (
    <div className="space-y-2">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="flex gap-2">
        <Input
          ref={input}
          type="text"
          value={value}
          readOnly
          autoComplete="off"
          spellCheck={false}
          aria-label={label}
          className={mono ? "font-mono text-xs" : ""}
          onFocus={(event) => event.currentTarget.select()}
        />
        <Button
          variant="outline"
          size="icon"
          onClick={copy}
          disabled={!value}
          aria-label={`Скопировать ${label.toLowerCase()}`}
          title="Скопировать"
        >
          {copied ? (
            <Check className="size-4 text-emerald-400" />
          ) : (
            <Copy className="size-4" />
          )}
        </Button>
      </div>
    </div>
  );
}

export function BridgeExports({ camera }: { camera: Camera }) {
  return <ExportPanel key={camera.id} camera={camera} />;
}

function ExportPanel({ camera }: { camera: Camera }) {
  const queryClient = useQueryClient();
  const query = useCameraExport(camera.id);
  const status = query.data;
  const [host, setHost] = useState<string | null>(null);
  const [protocols, setProtocols] = useState<{
    rtsp: boolean;
    onvif: boolean;
  } | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const rtsp = protocols?.rtsp ?? status?.rtsp ?? true;
  const onvif = protocols?.onvif ?? status?.onvif ?? true;
  const credentials = useQuery({
    queryKey: ["export-credentials", camera.id, status?.export_id],
    queryFn: () => api.exportCredentials(camera.id),
    enabled: !!status?.enabled && !!status.export_id,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: (enabled: boolean) =>
      api.configureExport(
        camera.id,
        enabled
          ? {
              enabled: true,
              rtsp,
              onvif,
              ...((host ?? status?.advertise_host ?? "").trim()
                ? {
                    advertise_host: (
                      host ??
                      status?.advertise_host ??
                      ""
                    ).trim(),
                  }
                : {}),
            }
          : { enabled: false },
      ),
    onSuccess: (result, enabled) => {
      if (!alive.current) return;
      queryClient.setQueryData(["export", camera.id], result);
      setHost(null);
      setProtocols(null);
      if (!enabled)
        queryClient.removeQueries({
          queryKey: ["export-credentials", camera.id],
        });
      void queryClient.invalidateQueries({ queryKey: ["export", camera.id] });
      void queryClient.invalidateQueries({ queryKey: ["archive", camera.id] });
      toast.success(
        enabled ? "Настройки публикации сохранены" : "Публикация выключена",
      );
    },
    onError: (error) => {
      if (alive.current) toast.error(errorMessage(error));
    },
  });
  const stateLabels: Record<string, string> = {
    starting: "Запускается",
    streaming: "Передаётся видео",
    waiting: "Ожидание камеры",
    error: "Ошибка публикации",
  };
  const disabled = mutation.isPending;
  const available = status?.available !== false;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Network className="size-5 text-primary" /> Подключение к NVR
          </h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            RTSP и ONVIF от моста для Frigate, Home Assistant и внешних плееров.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className={
              status?.enabled
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
                : "text-muted-foreground"
            }
          >
            <span
              className={`mr-1.5 size-1.5 rounded-full ${status?.enabled ? "bg-emerald-400" : "bg-muted-foreground"}`}
            />
            {status?.enabled
              ? (stateLabels[status.state ?? ""] ?? "Включено")
              : "Выключено"}
          </Badge>
          <Button
            size="icon"
            variant="ghost"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
            aria-label="Обновить публикацию"
            title="Обновить статус"
          >
            <RefreshCw
              className={`size-4 ${query.isFetching ? "animate-spin" : ""}`}
            />
          </Button>
        </div>
      </div>

      {(query.error || status?.error || !available) && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertDescription>
            {query.error
              ? errorMessage(query.error)
              : status?.error
                ? errorMessage(status.error)
                : "Служба RTSP моста недоступна. Проверьте, запущен ли MediaMTX."}
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="text-base">Публикация моста</CardTitle>
            <CardDescription>
              Одна камера, отдельный поток для каждой линзы.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="space-y-4 rounded-xl border border-border/70 bg-muted/20 p-4">
              <div className="flex items-center justify-between gap-4">
                <Label
                  htmlFor="export-rtsp"
                  className="flex cursor-pointer items-center gap-3"
                >
                  <Radio className="size-4 text-muted-foreground" />
                  <span>
                    RTSP
                    <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                      Оригинальное видео и доступный звук
                    </span>
                  </span>
                </Label>
                <Switch
                  id="export-rtsp"
                  checked={rtsp}
                  disabled={disabled}
                  onCheckedChange={(value) =>
                    setProtocols({ rtsp: value, onvif: value && onvif })
                  }
                />
              </div>
              <div className="border-t border-border/60" />
              <div className="flex items-center justify-between gap-4">
                <Label
                  htmlFor="export-onvif"
                  className="flex cursor-pointer items-center gap-3"
                >
                  <Network className="size-4 text-muted-foreground" />
                  <span>
                    ONVIF
                    <span className="mt-0.5 block text-xs font-normal text-muted-foreground">
                      Профили, PTZ, события и архив
                    </span>
                  </span>
                </Label>
                <Switch
                  id="export-onvif"
                  checked={onvif}
                  disabled={disabled}
                  onCheckedChange={(value) =>
                    setProtocols({ rtsp: value || rtsp, onvif: value })
                  }
                />
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <Label htmlFor="publication-host">Адрес сервера для NVR</Label>
                <Badge
                  variant="outline"
                  className="text-[10px] font-normal text-muted-foreground"
                >
                  Необязательно
                </Badge>
              </div>
              <Input
                id="publication-host"
                placeholder="Определить автоматически"
                value={host ?? status?.advertise_host ?? ""}
                disabled={disabled}
                onChange={(event) => setHost(event.target.value)}
                autoComplete="off"
                spellCheck={false}
              />
              <div className="flex items-start justify-between gap-3 text-xs text-muted-foreground">
                <p className="max-w-sm leading-relaxed">
                  IP или имя моста, доступное плееру. Для облачной камеры
                  используется адрес панели.
                </p>
                <button
                  className="shrink-0 text-primary hover:underline disabled:opacity-50"
                  disabled={disabled}
                  onClick={() => setHost(window.location.hostname)}
                >
                  Адрес панели
                </button>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                onClick={() => mutation.mutate(true)}
                disabled={
                  disabled ||
                  query.isPending ||
                  !camera.viewable ||
                  !available ||
                  !rtsp
                }
              >
                {disabled && mutation.variables ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <ArrowUpRight className="size-4" />
                )}
                {status?.enabled
                  ? "Применить настройки"
                  : "Включить публикацию"}
              </Button>
              {status?.enabled && (
                <Button
                  variant="outline"
                  onClick={() => mutation.mutate(false)}
                  disabled={disabled}
                >
                  <Unplug className="size-4" /> Выключить
                </Button>
              )}
            </div>
            {!camera.viewable && (
              <p className="text-xs text-amber-400">
                Сначала подключите камеру на вкладке просмотра.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="size-4 text-muted-foreground" /> Данные
              подключения
            </CardTitle>
            <CardDescription>
              Отдельные логин и пароль для этой публикации.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {status?.enabled ? (
              <>
                {credentials.isPending ? (
                  <div className="flex h-36 items-center justify-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" /> Получаем данные
                    подключения…
                  </div>
                ) : credentials.error ? (
                  <Alert variant="destructive">
                    <AlertCircle className="size-4" />
                    <AlertDescription>
                      {errorMessage(credentials.error)}
                      <Button
                        variant="link"
                        className="h-auto px-0 py-1"
                        onClick={() => void credentials.refetch()}
                      >
                        Повторить
                      </Button>
                    </AlertDescription>
                  </Alert>
                ) : credentials.data ? (
                  <div className="space-y-4">
                    <CopyField
                      label="Логин моста"
                      value={credentials.data.username}
                    />
                    <CopyField
                      label="Пароль моста"
                      value={credentials.data.password}
                    />
                  </div>
                ) : null}
                <div className="flex gap-2.5 rounded-lg bg-primary/5 p-3 text-xs leading-relaxed text-muted-foreground">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-primary" />
                  <p>
                    Выделите или скопируйте данные в NVR. Адреса и пароль
                    сохраняются после перезапуска моста.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <Badge variant="outline">
                    RTSP · {status.rtsp_port ?? 8554}
                  </Badge>
                  {status.onvif && (
                    <Badge variant="outline">
                      ONVIF · {status.onvif_port ?? 8899}
                    </Badge>
                  )}
                  <Badge variant="outline">
                    {status.audio?.available ? "Видео + звук" : "Видео"}
                  </Badge>
                </div>
              </>
            ) : (
              <div className="flex min-h-56 flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 text-center">
                <div className="mb-4 rounded-full bg-muted p-3">
                  <KeyRound className="size-5 text-muted-foreground" />
                </div>
                <p className="text-sm font-medium">
                  Подключение ещё не опубликовано
                </p>
                <p className="mt-2 max-w-xs text-xs leading-relaxed text-muted-foreground">
                  Включите публикацию — здесь появятся данные для подключения
                  плеера или NVR.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {status?.enabled && (
        <Card className="border-border/70">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Video className="size-4 text-primary" /> Адреса потоков
            </CardTitle>
            <CardDescription>
              В Frigate укажите адрес моста и порт ONVIF, либо добавьте RTSP
              каждой линзы.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {status.onvif &&
              safeAddress(status.onvif_uri, ["http:", "https:"]) && (
                <CopyField
                  label="ONVIF · адрес устройства"
                  value={safeAddress(status.onvif_uri, ["http:", "https:"])}
                />
              )}
            <div className="grid gap-4 lg:grid-cols-3">
              {status.profiles?.map((profile) => (
                <div
                  key={profile.token}
                  className="space-y-4 rounded-xl border border-border/70 bg-muted/15 p-4"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      Линза {profile.lens + 1}
                    </span>
                    <Badge
                      variant="outline"
                      className="font-mono text-[10px] text-muted-foreground"
                    >
                      {profile.width && profile.height
                        ? `${profile.width} × ${profile.height}`
                        : "H.264"}
                    </Badge>
                  </div>
                  <CopyField
                    label="RTSP-поток"
                    value={safeAddress(profile.rtsp_uri, ["rtsp:", "rtsps:"])}
                  />
                  {safeAddress(profile.snapshot_uri, ["http:", "https:"]) && (
                    <CopyField
                      label="Снимок JPEG"
                      value={safeAddress(profile.snapshot_uri, [
                        "http:",
                        "https:",
                      ])}
                    />
                  )}
                  {profile.fps ? (
                    <p className="text-[11px] text-muted-foreground">
                      Заявленная частота · {profile.fps} кадр/с
                    </p>
                  ) : null}
                </div>
              ))}
            </div>
            {status.discovery_error && (
              <p className="flex items-start gap-2 text-xs leading-relaxed text-amber-400">
                <AlertCircle className="mt-0.5 size-3.5 shrink-0" />{" "}
                Автообнаружение ONVIF недоступно. Добавьте устройство вручную по
                указанному адресу.
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
