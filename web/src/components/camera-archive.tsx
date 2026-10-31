"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Circle,
  Clock3,
  Copy,
  Database,
  Download,
  FileVideo,
  HardDrive,
  History,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Square,
} from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import type { ArchiveRecord, Camera, SDRecord } from "@/lib/types";
import { useCameraArchive, useCameraExport } from "@/lib/queries";
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

type PolicyDraft = { segment: string; retention: string; quota: string };
const MIB = 1048576;
const PAGE_SIZE = 20;
const jobLabels: Record<string, string> = {
  pending: "В очереди",
  downloading: "Загружается",
  completed: "Готово",
  error: "Ошибка",
  cancelled: "Отменено",
};

function sizeLabel(value = 0) {
  if (!Number.isFinite(value) || value <= 0) return "0 МиБ";
  return value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ГиБ`
    : `${(value / MIB).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} МиБ`;
}
function dateLabel(value?: string | number) {
  if (value === undefined || value === "") return "Дата неизвестна";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime())
    ? "Дата неизвестна"
    : new Intl.DateTimeFormat("ru-RU", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}
function durationLabel(value?: number) {
  if (!value || !Number.isFinite(value)) return "—";
  return value >= 60
    ? `${Math.floor(value / 60)} мин ${Math.round(value % 60)} с`
    : `${Math.round(value)} с`;
}
function localDay(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function safeReplay(value: unknown) {
  if (typeof value !== "string") return "";
  try {
    const uri = new URL(value);
    return ["rtsp:", "rtsps:"].includes(uri.protocol) &&
      !uri.username &&
      !uri.password &&
      !uri.search &&
      !uri.hash
      ? uri.href
      : "";
  } catch {
    return "";
  }
}

export function CameraArchive({ camera }: { camera: Camera }) {
  return <ArchivePanel key={camera.id} camera={camera} />;
}

function ArchivePanel({ camera }: { camera: Camera }) {
  const queryClient = useQueryClient();
  const archive = useCameraArchive(camera.id);
  const publication = useCameraExport(camera.id);
  const [draft, setDraft] = useState<PolicyDraft | null>(null);
  const [source, setSource] = useState("all");
  const [lens, setLens] = useState("all");
  const [date, setDate] = useState("");
  const [page, setPage] = useState(0);
  const [sdDays, setSDDays] = useState<string[]>([]);
  const [sdDay, setSDDay] = useState("");
  const [importDuration, setImportDuration] = useState("30");
  const [replayURI, setReplayURI] = useState("");
  const replayInput = useRef<HTMLInputElement>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const data = archive.data;
  const exported = !!publication.data?.enabled;
  const policy: PolicyDraft = draft ?? {
    segment: String(data?.workers?.[0]?.segment_seconds ?? 60),
    retention: String(data?.storage.retention_days ?? 7),
    quota: String(Math.ceil((data?.storage.max_bytes ?? 10 * 1024 ** 3) / MIB)),
  };
  function changePolicy(key: keyof PolicyDraft, value: string) {
    setDraft({ ...policy, [key]: value });
  }
  const storageBytes = data?.storage.bytes ?? 0;
  const storageLimit = data?.storage.max_bytes ?? 10 * 1024 ** 3;
  const used = Math.min(
    100,
    Math.max(0, storageLimit > 0 ? (storageBytes / storageLimit) * 100 : 0),
  );
  const activeJob = !!data?.jobs.some((job) =>
    ["pending", "downloading"].includes(job.state),
  );

  const recording = useMutation({
    mutationFn: (settings: Record<string, unknown>) =>
      api.configureArchive(camera.id, { action: "record", ...settings }),
    onSuccess: (_result, settings) => {
      if (!alive.current) return;
      setDraft(null);
      void queryClient.invalidateQueries({ queryKey: ["archive", camera.id] });
      toast.success(
        settings.enabled
          ? "Запись на сервер включена"
          : "Запись остановлена. Текущий сегмент сохранён.",
      );
    },
    onError: (error) => {
      if (alive.current) toast.error(errorMessage(error));
    },
  });
  const replay = useMutation({
    mutationFn: (token: string) =>
      api.configureArchive(camera.id, { action: "replay", token }),
    onSuccess: (result) => {
      if (!alive.current) return;
      const uri = safeReplay(result.uri);
      if (!uri) {
        toast.error("Сервер не вернул адрес воспроизведения.");
        return;
      }
      setReplayURI(uri);
      toast.success("Адрес повтора готов. Откройте его в VLC или NVR.");
    },
    onError: (error) => {
      if (alive.current) toast.error(errorMessage(error));
    },
  });
  const sdDates = useMutation({
    mutationFn: () => api.sdDates(camera.id),
    onSuccess: (result) => {
      if (!alive.current) return;
      const values = (Array.isArray(result) ? result : result.dates)
        .filter((value) => /^\d{8}$/.test(value))
        .sort()
        .reverse();
      setSDDays(values);
      setSDDay(values[0] ?? "");
      void queryClient.invalidateQueries({
        queryKey: ["sd-records", camera.id],
      });
      if (!values.length) toast.info("Камера не вернула даты архива SD.");
    },
    onError: (error) => {
      if (alive.current) toast.error(errorMessage(error));
    },
  });
  const sdRecords = useQuery({
    queryKey: ["sd-records", camera.id, sdDay],
    queryFn: () => api.sdRecords(camera.id, sdDay),
    enabled: !!sdDay && camera.viewable && exported,
    staleTime: 0,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const sdImport = useMutation({
    mutationFn: ({
      sourceId,
      duration,
    }: {
      sourceId: string;
      duration: number;
    }) =>
      api.configureArchive(camera.id, {
        action: "sd_import",
        source_id: sourceId,
        duration,
      }),
    onSuccess: () => {
      if (!alive.current) return;
      void queryClient.invalidateQueries({ queryKey: ["archive", camera.id] });
      toast.success("Фрагмент добавлен в очередь загрузки");
    },
    onError: (error) => {
      if (alive.current) toast.error(errorMessage(error));
    },
  });
  const sdRows = sdRecords.data
    ? Array.isArray(sdRecords.data)
      ? sdRecords.data
      : sdRecords.data.records
    : [];
  const rows = useMemo(
    () =>
      (data?.records ?? []).filter(
        (record) =>
          (source === "all" || record.source === source) &&
          (lens === "all" || record.lens === Number(lens)) &&
          (!date || localDay(record.start) === date),
      ),
    [data?.records, source, lens, date],
  );
  const lenses = useMemo(
    () =>
      Array.from(
        new Set((data?.records ?? []).map((record) => record.lens)),
      ).sort((a, b) => a - b),
    [data?.records],
  );
  const maxPage = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, maxPage);
  const visibleRows = rows.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );

  function submitRecording(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const segment = Number(policy.segment),
      retention = Number(policy.retention),
      quota = Number(policy.quota);
    if (
      !Number.isInteger(segment) ||
      segment < 5 ||
      segment > 3600 ||
      !Number.isInteger(retention) ||
      retention < 1 ||
      retention > 365 ||
      !Number.isInteger(quota) ||
      quota < 1 ||
      quota > 1048576
    ) {
      toast.error(
        "Укажите сегмент 5–3600 с, хранение 1–365 дней и квоту 1–1048576 МиБ.",
      );
      return;
    }
    recording.mutate({
      enabled: true,
      segment_seconds: segment,
      retention_days: retention,
      max_bytes: quota * MIB,
    });
  }
  function importClip(record: SDRecord) {
    const duration = Number(importDuration);
    if (!Number.isInteger(duration) || duration < 1 || duration > 300) {
      toast.error("Длительность фрагмента — от 1 до 300 секунд.");
      return;
    }
    sdImport.mutate({ sourceId: record.id, duration });
  }
  async function copyReplay() {
    try {
      await navigator.clipboard.writeText(replayURI);
      toast.success("Адрес повтора скопирован");
    } catch {
      replayInput.current?.focus();
      replayInput.current?.select();
      toast.info("Адрес выделен — скопируйте его сочетанием клавиш.");
    }
  }
  function recordSize(record: ArchiveRecord) {
    return typeof record.size === "number" ? record.size : (record.bytes ?? 0);
  }
  const selectClass =
    "h-9 w-full rounded-md border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h2 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <History className="size-5 text-primary" /> Архив камеры
          </h2>
          <p className="text-sm text-muted-foreground">
            Записи на сервере и фрагменты с SD-карты в одном месте.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            void archive.refetch();
            void publication.refetch();
          }}
          disabled={archive.isFetching}
        >
          <RefreshCw
            className={`size-4 ${archive.isFetching ? "animate-spin" : ""}`}
          />{" "}
          Обновить
        </Button>
      </div>
      {archive.error && (
        <Alert variant="destructive">
          <AlertCircle className="size-4" />
          <AlertDescription>{errorMessage(archive.error)}</AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="border-border/70">
          <CardContent className="flex items-start justify-between gap-3 pt-6">
            <div>
              <p className="text-xs text-muted-foreground">Запись на сервер</p>
              <p
                className={`mt-2 text-xl font-semibold ${data?.recording_enabled ? "text-emerald-400" : ""}`}
              >
                {data?.recording_enabled ? "Включена" : "Выключена"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {data?.recording_enabled
                  ? `${data.workers.length} ${data.workers.length === 1 ? "линия записи" : "линии записи"}`
                  : "Запускается вручную"}
              </p>
            </div>
            <Circle
              className={`mt-1 size-4 ${data?.recording_enabled ? "fill-red-400 text-red-400" : "text-muted-foreground"}`}
            />
          </CardContent>
        </Card>
        <Card className="border-border/70">
          <CardContent className="flex items-start justify-between gap-3 pt-6">
            <div>
              <p className="text-xs text-muted-foreground">Готовые фрагменты</p>
              <p className="mt-2 text-xl font-semibold tabular-nums">
                {data?.storage.count ?? 0}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Сервер и импортированные SD
              </p>
            </div>
            <FileVideo className="mt-1 size-4 text-muted-foreground" />
          </CardContent>
        </Card>
        <Card className="border-border/70">
          <CardContent className="space-y-3 pt-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs text-muted-foreground">Занято в архиве</p>
                <p className="mt-2 text-xl font-semibold tabular-nums">
                  {sizeLabel(storageBytes)}
                </p>
              </div>
              <HardDrive className="mt-1 size-4 text-muted-foreground" />
            </div>
            <div
              className="h-1.5 overflow-hidden rounded-full bg-muted"
              role="progressbar"
              aria-label="Использование квоты архива"
              aria-valuenow={Math.round(used)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={`h-full rounded-full ${used > 90 ? "bg-amber-400" : "bg-primary"}`}
                style={{ width: `${used}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              из {sizeLabel(storageLimit)} · квота этой камеры
            </p>
          </CardContent>
        </Card>
      </div>

      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Database className="size-4 text-primary" /> Запись на сервер
            </CardTitle>
            {data?.recording_enabled && (
              <Badge
                variant="outline"
                className="border-red-500/30 text-red-400"
              >
                <span className="mr-1.5 size-1.5 animate-pulse rounded-full bg-red-400" />{" "}
                REC
              </Badge>
            )}
          </div>
          <CardDescription>
            Отдельный файл для каждой линзы. Исходный H.264 сохраняется без
            перекодирования.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={submitRecording} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="recording-segment">Длина сегмента, с</Label>
                <Input
                  id="recording-segment"
                  type="number"
                  min={5}
                  max={3600}
                  step={1}
                  value={policy.segment}
                  onChange={(event) =>
                    changePolicy("segment", event.target.value)
                  }
                  disabled={recording.isPending}
                />
                <p className="text-[11px] text-muted-foreground">
                  От 5 секунд до часа
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="recording-retention">Хранить, дней</Label>
                <Input
                  id="recording-retention"
                  type="number"
                  min={1}
                  max={365}
                  step={1}
                  value={policy.retention}
                  onChange={(event) =>
                    changePolicy("retention", event.target.value)
                  }
                  disabled={recording.isPending}
                />
                <p className="text-[11px] text-muted-foreground">
                  Срок для записей сервера
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="recording-quota">Квота камеры, МиБ</Label>
                <Input
                  id="recording-quota"
                  type="number"
                  min={1}
                  max={1048576}
                  step={1}
                  value={policy.quota}
                  onChange={(event) =>
                    changePolicy("quota", event.target.value)
                  }
                  disabled={recording.isPending}
                />
                <p className="text-[11px] text-muted-foreground">
                  Общая для записи и импорта SD
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="submit"
                disabled={
                  recording.isPending ||
                  archive.isPending ||
                  !camera.viewable ||
                  !exported
                }
              >
                {recording.isPending && recording.variables?.enabled ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Circle className="size-3 fill-current" />
                )}
                {data?.recording_enabled
                  ? "Применить настройки записи"
                  : "Начать запись"}
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={recording.isPending || !data?.recording_enabled}
                onClick={() => recording.mutate({ enabled: false })}
              >
                <Square className="size-3 fill-current" /> Остановить
              </Button>
            </div>
          </form>
          {!exported && (
            <p className="flex items-center gap-2 text-xs text-amber-400">
              <AlertCircle className="size-3.5 shrink-0" /> Для записи и доступа
              к SD включите RTSP-публикацию моста.
            </p>
          )}
          {data?.recording_enabled && (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Применение настроек завершит текущий сегмент и начнёт новый.
              Закрытие панели не останавливает запись.
            </p>
          )}
          {!!data?.workers.length && (
            <div className="flex flex-wrap gap-2">
              {data.workers.map((worker) => (
                <Badge
                  key={worker.lens}
                  variant="outline"
                  className={
                    worker.error
                      ? "border-destructive/30 text-destructive"
                      : "text-muted-foreground"
                  }
                >
                  Линза {worker.lens + 1} ·{" "}
                  {worker.error
                    ? errorMessage(worker.error)
                    : worker.running
                      ? "записывается"
                      : "остановлена"}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/70">
        <CardHeader>
          <CardTitle className="text-base">Готовые записи</CardTitle>
          <CardDescription>
            Скачайте MKV или получите адрес RTSP-повтора для VLC и NVR.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex rounded-lg border border-border/70 bg-muted/20 p-1">
              {[
                { value: "all", label: "Все" },
                { value: "server", label: "Сервер" },
                { value: "sd", label: "Импорт SD" },
              ].map((item) => (
                <button
                  key={item.value}
                  onClick={() => {
                    setSource(item.value);
                    setPage(0);
                  }}
                  className={`rounded-md px-3 py-1.5 text-xs transition-colors ${source === item.value ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                  aria-pressed={source === item.value}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <select
                className={`${selectClass} w-auto min-w-32`}
                value={lens}
                onChange={(event) => {
                  setLens(event.target.value);
                  setPage(0);
                }}
                aria-label="Фильтр записей по линзе"
              >
                <option value="all">Все линзы</option>
                {lenses.map((value) => (
                  <option key={value} value={value}>
                    Линза {value + 1}
                  </option>
                ))}
              </select>
              <Input
                type="date"
                value={date}
                onChange={(event) => {
                  setDate(event.target.value);
                  setPage(0);
                }}
                className="w-auto text-xs"
                aria-label="Дата записей"
              />
            </div>
          </div>
          {archive.isPending ? (
            <div className="flex h-36 items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Загружаем архив…
            </div>
          ) : visibleRows.length ? (
            <div className="overflow-x-auto rounded-lg border border-border/70">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="bg-muted/30 text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 font-medium">Начало</th>
                    <th className="px-3 py-3 font-medium">Линза / источник</th>
                    <th className="px-3 py-3 font-medium">Длительность</th>
                    <th className="px-3 py-3 font-medium">Размер</th>
                    <th className="px-4 py-3 text-right font-medium">
                      Действия
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {visibleRows.map((record) => (
                    <tr
                      key={record.token}
                      className="transition-colors hover:bg-muted/15"
                    >
                      <td className="whitespace-nowrap px-4 py-3.5 text-xs">
                        {dateLabel(record.start)}
                      </td>
                      <td className="px-3 py-3.5">
                        <span className="text-xs">Линза {record.lens + 1}</span>
                        <span className="mt-1 block text-[10px] text-muted-foreground">
                          {record.source === "sd" ? "Импорт SD" : "Сервер"}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-3 py-3.5 text-xs tabular-nums text-muted-foreground">
                        {durationLabel(record.duration)}
                      </td>
                      <td className="whitespace-nowrap px-3 py-3.5 text-xs tabular-nums text-muted-foreground">
                        {sizeLabel(recordSize(record))}
                      </td>
                      <td className="px-4 py-3.5">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" asChild>
                            <a
                              href={`/api/cameras/${encodeURIComponent(camera.id)}/archive/file/${encodeURIComponent(record.token)}`}
                              download="recording.mkv"
                              aria-label={`Скачать запись линзы ${record.lens + 1}`}
                              title="Скачать MKV"
                            >
                              <Download className="size-4" />
                            </a>
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            disabled={replay.isPending || !exported}
                            onClick={() => replay.mutate(record.token)}
                            aria-label={`Повтор записи линзы ${record.lens + 1}`}
                            title="Получить RTSP-повтор"
                          >
                            {replay.isPending &&
                            replay.variables === record.token ? (
                              <Loader2 className="size-4 animate-spin" />
                            ) : (
                              <Play className="size-4" />
                            )}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border px-6 py-12 text-center">
              <FileVideo className="mb-3 size-7 text-muted-foreground/60" />
              <p className="text-sm font-medium">
                {data?.records.length
                  ? "По этим фильтрам записей нет"
                  : "Здесь появятся готовые записи"}
              </p>
              <p className="mt-2 max-w-sm text-xs leading-relaxed text-muted-foreground">
                {data?.records.length
                  ? "Измените дату, линзу или источник."
                  : "Включите запись на сервер или импортируйте фрагмент с SD-карты."}
              </p>
            </div>
          )}
          {rows.length > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <p>
                {currentPage * PAGE_SIZE + 1}–
                {Math.min((currentPage + 1) * PAGE_SIZE, rows.length)} из{" "}
                {rows.length}
              </p>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}
                  aria-label="Предыдущая страница"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                <span className="tabular-nums">
                  {currentPage + 1} / {maxPage + 1}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  disabled={currentPage === maxPage}
                  onClick={() => setPage(currentPage + 1)}
                  aria-label="Следующая страница"
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          )}
          {replayURI && (
            <div className="space-y-2 rounded-lg border border-primary/20 bg-primary/5 p-4">
              <Label
                htmlFor="archive-replay"
                className="flex items-center gap-2 text-xs"
              >
                <Play className="size-3.5" /> RTSP-повтор готов
              </Label>
              <div className="flex gap-2">
                <Input
                  id="archive-replay"
                  ref={replayInput}
                  value={replayURI}
                  readOnly
                  className="font-mono text-xs"
                  onFocus={(event) => event.currentTarget.select()}
                />
                <Button
                  variant="outline"
                  size="icon"
                  onClick={copyReplay}
                  aria-label="Скопировать адрес повтора"
                >
                  <Copy className="size-4" />
                </Button>
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Откройте в VLC. Используются логин и пароль публикации моста;
                воспроизведение идёт вперёд с обычной скоростью.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-border/70">
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <HardDrive className="size-4 text-primary" /> SD-карта камеры
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              disabled={
                !camera.viewable ||
                !exported ||
                sdDates.isPending ||
                sdRecords.isFetching
              }
              onClick={() => sdDates.mutate()}
            >
              {sdDates.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Search className="size-4" />
              )}{" "}
              Проверить SD
            </Button>
          </div>
          <CardDescription>
            Запросите даты на карте и выберите фрагмент для загрузки в архив
            моста.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label
                htmlFor="sd-recording-date"
                className="flex items-center gap-2"
              >
                <CalendarDays className="size-3.5 text-muted-foreground" /> Дата
                на SD-карте
              </Label>
              <select
                id="sd-recording-date"
                value={sdDay}
                onChange={(event) => setSDDay(event.target.value)}
                className={selectClass}
                disabled={
                  !sdDays.length ||
                  sdDates.isPending ||
                  sdRecords.isFetching ||
                  !camera.viewable ||
                  !exported
                }
              >
                <option value="" disabled>
                  Сначала проверьте SD-карту
                </option>
                {sdDays.map((value) => (
                  <option
                    key={value}
                    value={value}
                  >{`${value.slice(6)}.${value.slice(4, 6)}.${value.slice(0, 4)}`}</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label
                htmlFor="sd-import-duration"
                className="flex items-center gap-2"
              >
                <Clock3 className="size-3.5 text-muted-foreground" />{" "}
                Длительность импорта, с
              </Label>
              <Input
                id="sd-import-duration"
                type="number"
                min={1}
                max={300}
                step={1}
                value={importDuration}
                onChange={(event) => setImportDuration(event.target.value)}
                disabled={sdImport.isPending}
              />
            </div>
          </div>
          {(sdDates.error || sdRecords.error) && (
            <Alert variant="destructive">
              <AlertCircle className="size-4" />
              <AlertDescription>
                {errorMessage(sdDates.error ?? sdRecords.error)}
              </AlertDescription>
            </Alert>
          )}
          {sdRecords.isFetching || sdDates.isPending ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Читаем индекс
              SD-карты…
            </div>
          ) : sdRows.length ? (
            <div className="max-h-96 space-y-2 overflow-y-auto pr-1">
              {sdRows.map((record) => (
                <div
                  key={record.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/70 bg-muted/10 p-3.5"
                >
                  <div className="min-w-0 space-y-1">
                    <p className="text-sm font-medium">
                      {dateLabel(record.start ?? record.timestamp)}
                    </p>
                    <p className="max-w-lg truncate font-mono text-[10px] text-muted-foreground">
                      {record.filename ?? record.id} ·{" "}
                      {durationLabel(record.duration)}
                    </p>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={
                      !camera.viewable ||
                      !exported ||
                      sdImport.isPending ||
                      activeJob
                    }
                    onClick={() => importClip(record)}
                  >
                    {sdImport.isPending &&
                    sdImport.variables?.sourceId === record.id ? (
                      <Loader2 className="size-4 animate-spin" />
                    ) : (
                      <Download className="size-4" />
                    )}{" "}
                    В архив моста
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <p className="rounded-lg border border-dashed border-border p-6 text-center text-sm leading-relaxed text-muted-foreground">
              {sdDay
                ? "За эту дату записей нет."
                : "Нажмите «Проверить SD», чтобы прочитать даты с камеры. Видео загружается только по кнопке выбранного фрагмента."}
            </p>
          )}
          {!!data?.jobs.length && (
            <div className="space-y-3 border-t border-border/70 pt-5">
              <h3 className="text-sm font-medium">Задания импорта</h3>
              {data.jobs.map((job) => (
                <div
                  key={job.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-muted/20 p-3"
                >
                  <div className="flex min-w-0 items-center gap-2.5">
                    {["pending", "downloading"].includes(job.state) ? (
                      <Loader2 className="size-4 shrink-0 animate-spin text-primary" />
                    ) : job.state === "completed" ? (
                      <Check className="size-4 shrink-0 text-emerald-400" />
                    ) : (
                      <AlertCircle className="size-4 shrink-0 text-muted-foreground" />
                    )}
                    <span className="truncate font-mono text-xs text-muted-foreground">
                      {job.id}
                    </span>
                  </div>
                  <span
                    className={`text-xs ${job.state === "error" ? "text-destructive" : "text-muted-foreground"}`}
                  >
                    {jobLabels[job.state] ?? job.state}
                    {job.error && job.state !== "cancelled"
                      ? ` · ${job.error === "sd_import_failed" ? "Повторите загрузку фрагмента." : errorMessage(job.error)}`
                      : ""}
                  </span>
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Импорт копирует до 300 секунд в архив сервера и не удаляет файлы с
            карты камеры. Готовые фрагменты доступны в списке записей выше.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
