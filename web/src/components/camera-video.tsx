"use client";
import { memo, useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Camera as CameraIcon,
  Check,
  Cloud,
  Copy,
  Expand,
  ExternalLink,
  Loader2,
  Network,
  Pause,
  Play,
  Settings2,
  Video,
} from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import {
  cameraMediaURL,
  connectingStates,
  frameAge,
  transportLabel,
} from "@/lib/presentation";
import type {
  Camera,
  ConnectionMode,
  Credentials,
  LensMetadata,
  Quality,
  StreamPreferences,
} from "@/lib/types";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import { cn } from "@/lib/utils";

export function ConnectionToolbar({
  camera,
  onChange,
}: {
  camera: Camera;
  onChange: () => void | Promise<unknown>;
}) {
  const [draft, setDraft] = useState<{
    quality?: Quality;
    ip?: string;
    substream?: string;
  }>({});
  const quality = draft.quality === undefined ? camera.quality : draft.quality;
  const ip =
    draft.ip ?? camera.ip ?? String(camera.account_metadata.lan_ip || "");
  const substream = draft.substream ?? String(camera.substream ?? 1);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const preferences = (mode: ConnectionMode): StreamPreferences => ({
    connection_mode: mode,
    ip: mode === "cloud" ? null : ip.trim() || null,
    substream: Number(substream),
    quality,
  });
  const connect = useMutation({
    mutationFn: (mode: ConnectionMode) =>
      api.connect(camera.id, preferences(mode)),
    onSuccess: async () => {
      setSettingsOpen(false);
      await onChange();
      setDraft({});
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const stream = useMutation({
    mutationFn: () =>
      api.stream(camera.id, preferences(camera.connection_mode)),
    onSuccess: async (result) => {
      toast.success(
        result.mode === "live"
          ? "Качество изменено без переподключения"
          : "Настройки применены, подключаем камеру",
      );
      await onChange();
      setDraft({});
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const busy =
    connect.isPending ||
    stream.isPending ||
    (!camera.viewable && connectingStates.has(camera.state));
  return (
    <div className="mb-5 flex flex-col gap-4 rounded-xl border border-border bg-card px-4 py-3.5 xl:flex-row xl:items-center xl:justify-between">
      <div className="flex flex-wrap items-center gap-3">
        <span className="mr-1 text-xs text-muted-foreground">Источник</span>
        <div className="flex rounded-lg bg-background p-1">
          <Button
            size="sm"
            variant="ghost"
            className={cn(
              "h-8 gap-2 text-xs text-muted-foreground",
              camera.connection_mode === "lan" &&
                "bg-secondary text-foreground shadow-sm",
            )}
            disabled={busy}
            onClick={() => connect.mutate("lan")}
          >
            <Network className="size-3.5" /> Локально
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className={cn(
              "h-8 gap-2 text-xs text-muted-foreground",
              camera.connection_mode === "cloud" &&
                "bg-secondary text-foreground shadow-sm",
            )}
            disabled={busy}
            onClick={() => connect.mutate("cloud")}
          >
            <Cloud className="size-3.5" /> O-Kam Pro
          </Button>
        </div>
        {busy && <Loader2 className="size-4 animate-spin text-primary" />}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={quality || "unchanged"}
          onValueChange={(value) =>
            setDraft((previous) => ({
              ...previous,
              quality: value === "unchanged" ? null : (value as Quality),
            }))
          }
          disabled={busy}
        >
          <SelectTrigger
            aria-label="Качество видео"
            className="h-9 w-[165px] bg-background text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="unchanged">Как на камере</SelectItem>
            <SelectItem value="high">Высокое качество</SelectItem>
            <SelectItem value="medium">Среднее качество</SelectItem>
            <SelectItem value="low">Низкое · слабая сеть</SelectItem>
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => stream.mutate()}
          className="h-9 text-xs"
        >
          Применить
        </Button>
        <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
          <DialogTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="size-9 text-muted-foreground"
              aria-label="Настройки подключения"
            >
              <Settings2 className="size-4" />
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Параметры подключения</DialogTitle>
              <DialogDescription>
                Качество меняется в текущей сессии. Смена адреса или потока
                потребует переподключения.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-5 py-3">
              <div className="space-y-2">
                <Label htmlFor="camera-ip">Локальный IP камеры</Label>
                <Input
                  id="camera-ip"
                  disabled={busy}
                  value={ip}
                  onChange={(event) =>
                    setDraft((previous) => ({
                      ...previous,
                      ip: event.target.value,
                    }))
                  }
                  placeholder="IP из аккаунта или поиск в LAN"
                />
                <p className="text-xs leading-5 text-muted-foreground">
                  Используется только для локального режима. Для O-Kam Pro адрес
                  камеры не нужен.
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="substream">Нативный поток</Label>
                <Select
                  value={substream}
                  disabled={busy}
                  onValueChange={(value) =>
                    setDraft((previous) => ({ ...previous, substream: value }))
                  }
                >
                  <SelectTrigger id="substream">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[0, 1, 2].map((value) => (
                      <SelectItem key={value} value={String(value)}>
                        Поток {value}
                        {value === 1 ? " · по умолчанию" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <p className="text-xs leading-5 text-muted-foreground">
                  Доступные потоки зависят от прошивки. Для слабого соединения
                  сначала выберите низкое качество.
                </p>
              </div>
              <Button
                className="w-full"
                disabled={busy}
                onClick={() => connect.mutate(camera.connection_mode)}
              >
                Переподключить · {transportLabel(camera)}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}

export function CameraVideo({ camera }: { camera: Camera }) {
  if (!camera.viewable) {
    const pending = connectingStates.has(camera.state);
    return (
      <div className="flex min-h-[340px] flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/40 p-8 text-center">
        <div className="mb-5 flex size-16 items-center justify-center rounded-2xl border border-border bg-secondary/40">
          {pending ? (
            <Loader2 className="size-7 animate-spin text-primary" />
          ) : (
            <Video className="size-7 text-muted-foreground" />
          )}
        </div>
        <h3 className="font-display text-xl font-semibold">
          {pending ? "Устанавливаем соединение" : "Откройте прямой эфир"}
        </h3>
        <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">
          {pending
            ? camera.connection_mode === "cloud"
              ? "Связываемся с камерой через серверы O-Kam Pro. Первый кадр может появиться в течение 100 секунд."
              : "Подключаемся к камере и ожидаем первый кадр."
            : "Выберите локальное подключение или O-Kam Pro выше. Каждая линза появится в отдельном окне."}
        </p>
      </div>
    );
  }
  return (
    <div
      className={cn(
        "grid gap-4",
        camera.lenses.length > 1 && "md:grid-cols-2",
        camera.lenses.length > 2 && "2xl:grid-cols-3",
      )}
    >
      {camera.lenses.map((lens) => (
        <LensCard
          key={`${camera.id}:${lens}`}
          cameraId={camera.id}
          cameraName={camera.name}
          lens={lens}
          metadata={camera.lens_metadata.find((item) => item.id === lens)}
        />
      ))}
    </div>
  );
}

export const LensCard = memo(function LensCard({
  cameraId,
  cameraName,
  lens,
  metadata,
}: {
  cameraId: string;
  cameraName: string;
  lens: number;
  metadata?: LensMetadata;
}) {
  const [paused, setPaused] = useState(false);
  const [revision, setRevision] = useState(0);
  const [failed, setFailed] = useState(false);
  const stage = useRef<HTMLDivElement>(null);
  const retry = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      clearTimeout(retry.current);
    };
  }, []);
  function retryFeed() {
    setFailed(true);
    clearTimeout(retry.current);
    retry.current = setTimeout(() => {
      if (alive.current) {
        setRevision((value) => value + 1);
        setFailed(false);
      }
    }, 3000);
  }
  function togglePause() {
    clearTimeout(retry.current);
    setPaused(!paused);
    setFailed(false);
    if (paused) setRevision((value) => value + 1);
  }
  async function fullscreen() {
    try {
      await stage.current?.requestFullscreen();
    } catch {
      toast.error("Полноэкранный режим недоступен в этом браузере");
    }
  }
  return (
    <article className="overflow-hidden rounded-xl border border-border bg-card">
      <header className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-6 items-center justify-center rounded-md bg-secondary text-[10px] font-medium text-muted-foreground">
            {String(lens + 1).padStart(2, "0")}
          </span>
          <span className="text-xs font-medium">Объектив {lens + 1}</span>
        </div>
        <span
          className={cn(
            "flex items-center gap-1.5 text-[9px] font-semibold tracking-wider",
            paused
              ? "text-muted-foreground"
              : failed
                ? "text-amber-400"
                : "text-primary",
          )}
        >
          <span className="size-1 rounded-full bg-current" />
          {paused ? "ПАУЗА" : failed ? "ПОВТОР" : "LIVE"}
        </span>
      </header>
      <div
        ref={stage}
        className="stream-stage group relative aspect-video overflow-hidden border-y border-border/60"
      >
        {paused ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-muted-foreground">
            <Pause className="size-7" />
            <span className="text-xs">Просмотр на паузе</span>
          </div>
        ) : (
          <img
            src={
              cameraMediaURL(cameraId, "mjpeg", lens) +
              (revision ? `&retry=${revision}` : "")
            }
            alt={`${cameraName} · объектив ${lens + 1}`}
            className="size-full object-contain"
            onError={retryFeed}
            onLoad={() => setFailed(false)}
          />
        )}
        {failed && !paused && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-background/90 text-xs text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Восстанавливаем
            изображение…
          </div>
        )}
        <div className="absolute bottom-0 inset-x-0 flex items-center justify-end gap-1 bg-gradient-to-t from-black/80 to-transparent p-2 pt-10 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 max-md:opacity-100">
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-white hover:bg-white/15 hover:text-white"
            onClick={togglePause}
            aria-label={
              paused
                ? `Продолжить объектив ${lens + 1}`
                : `Приостановить объектив ${lens + 1}`
            }
          >
            {paused ? (
              <Play className="size-4" />
            ) : (
              <Pause className="size-4" />
            )}
          </Button>
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="size-8 text-white hover:bg-white/15 hover:text-white"
          >
            <a
              href={cameraMediaURL(cameraId, "snapshot.jpg", lens)}
              target="_blank"
              rel="noreferrer"
              aria-label={`Снимок объектива ${lens + 1}`}
            >
              <CameraIcon className="size-4" />
            </a>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-8 text-white hover:bg-white/15 hover:text-white"
            onClick={fullscreen}
            aria-label={`Развернуть объектив ${lens + 1}`}
          >
            <Expand className="size-4" />
          </Button>
        </div>
      </div>
      <footer className="flex items-center justify-between gap-2 px-4 py-3 text-[10px] text-muted-foreground">
        <span>
          {metadata?.width && metadata.height
            ? `${metadata.width} × ${metadata.height}`
            : "Определяем разрешение"}
        </span>
        <span className="flex items-center gap-3">
          <span>
            {metadata?.measured_fps ? metadata.measured_fps.toFixed(1) : "—"}{" "}
            fps
          </span>
          <span>
            {metadata?.bitrate_kbps ? Math.round(metadata.bitrate_kbps) : "—"}{" "}
            кбит/с
          </span>
        </span>
      </footer>
      <div className="flex items-center justify-between border-t border-border/60 px-4 py-2 text-[10px] text-muted-foreground/70">
        <span>{frameAge(metadata?.last_frame)}</span>
        <PlayerLink cameraId={cameraId} lens={lens} />
      </div>
    </article>
  );
});

function PlayerLink({ cameraId, lens }: { cameraId: string; lens: number }) {
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  async function load() {
    setPending(true);
    try {
      const value = await api.player();
      if (alive.current) {
        setCredentials(value);
        setOpen(true);
      }
    } catch (error) {
      if (alive.current) toast.error(errorMessage(error));
    } finally {
      if (alive.current) setPending(false);
    }
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (!value) setCredentials(null);
      }}
    >
      <Button
        variant="ghost"
        size="sm"
        className="h-6 gap-1.5 px-0 text-[10px] text-muted-foreground hover:bg-transparent hover:text-primary"
        disabled={pending}
        onClick={load}
      >
        <ExternalLink className="size-3" /> Открыть в VLC
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Объектив {lens + 1} в плеере</DialogTitle>
          <DialogDescription>
            Откройте сетевой адрес в VLC и введите данные ниже. Исходный H.264
            передаётся без перекодирования.
          </DialogDescription>
        </DialogHeader>
        {credentials && (
          <div className="space-y-4 py-2">
            <CopyValue
              label="Сетевой адрес"
              value={
                typeof window === "undefined"
                  ? ""
                  : window.location.origin +
                    cameraMediaURL(cameraId, "stream.h264", lens)
              }
            />
            <CopyValue label="Логин" value={credentials.username} />
            <CopyValue label="Пароль плеера" value={credentials.password} />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
export function CopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      ref.current?.select();
      toast.info("Адрес выделен — скопируйте его вручную");
    }
  }
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input
          ref={ref}
          aria-label={label}
          readOnly
          value={value}
          className="font-mono text-xs"
          onClick={(event) => event.currentTarget.select()}
        />
        <Button
          variant="outline"
          size="icon"
          onClick={copy}
          aria-label={`Копировать: ${label}`}
        >
          {copied ? (
            <Check className="size-4 text-primary" />
          ) : (
            <Copy className="size-4" />
          )}
        </Button>
      </div>
    </div>
  );
}
