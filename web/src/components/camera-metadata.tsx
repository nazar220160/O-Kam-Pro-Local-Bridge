"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Database,
  Download,
  Info,
  Loader2,
  RefreshCw,
  Search,
  Square,
  X,
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
  featureLabels,
  querySections,
  selectClass,
  valueText,
} from "./camera-panel-utils";

export function CameraMetadata({ camera }: { camera: Camera }) {
  return <CameraMetadataPanel key={camera.id} camera={camera} />;
}

function CameraMetadataPanel({ camera }: { camera: Camera }) {
  const details = useCameraDetails(camera.id);
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const [group, setGroup] = useState("all");
  const [page, setPage] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [progress, setProgress] = useState<string | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const cancelled = useRef(false);
  const mounted = useRef(false);
  const mutation = useMutation({
    mutationFn: (section: string) =>
      api.control(camera.id, "query", { section }),
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      cancelled.current = true;
    };
  }, []);

  const groups = useMemo<Record<string, Record<string, unknown>>>(
    () => ({
      account: details.data?.account || {},
      ...(details.data?.groups || {}),
    }),
    [details.data],
  );
  const rows = useMemo(
    () =>
      Object.entries(groups).flatMap(([name, values]) =>
        Object.entries(values).map(([key, value]) => ({
          group: name,
          key,
          value: valueText(value),
        })),
      ),
    [groups],
  );
  const filtered = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return rows.filter(
      (row) =>
        (group === "all" || group === row.group) &&
        (!needle ||
          `${row.group} ${row.key} ${row.value}`
            .toLocaleLowerCase()
            .includes(needle)),
    );
  }, [rows, search, group]);
  const capabilities = Object.entries(details.data?.capabilities || {});
  const pageCount = Math.max(1, Math.ceil(filtered.length / 100));
  const activePage = Math.min(page, pageCount - 1);
  const visibleRows = filtered.slice(activePage * 100, (activePage + 1) * 100);

  async function refreshAll() {
    if (refreshing || !camera.viewable) return;
    cancelled.current = false;
    setRefreshing(true);
    setReadError(null);
    let count = 0;
    try {
      for (const [section, title] of Object.entries(querySections)) {
        if (cancelled.current || !mounted.current) break;
        setProgress(title);
        const result: ControlResult = await mutation.mutateAsync(section);
        if (!mounted.current) return;
        count++;
        await queryClient.invalidateQueries({
          queryKey: queryKeys.details(camera.id),
        });
        if (result.state === "interrupted") break;
      }
      if (mounted.current)
        toast.success(
          cancelled.current
            ? "Чтение остановлено. Полученные параметры сохранены."
            : `Разделов прочитано: ${count}`,
        );
    } catch (error) {
      if (mounted.current) {
        setReadError(errorMessage(error));
        toast.error(errorMessage(error));
      }
    } finally {
      if (mounted.current) {
        setRefreshing(false);
        setProgress(null);
      }
    }
  }

  function download() {
    if (!details.data) return;
    const blob = new Blob(
      [
        JSON.stringify(
          {
            camera: {
              id: camera.id,
              name: camera.name,
              connection_mode: camera.connection_mode,
              lens_metadata: camera.lens_metadata,
            },
            ...details.data,
          },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `camera-${camera.id}-metadata.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Данные камеры
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Наблюдаемые параметры, возможности и ответы прошивки.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={!details.data}
            onClick={download}
          >
            <Download className="size-4" />
            Скачать JSON
          </Button>
          {refreshing ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                cancelled.current = true;
              }}
            >
              <Square className="size-3.5" />
              Остановить чтение
            </Button>
          ) : (
            <Button
              size="sm"
              disabled={!camera.viewable || details.isFetching}
              onClick={() => void refreshAll()}
            >
              <RefreshCw className="size-4" />
              Обновить параметры
            </Button>
          )}
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { label: "Поля параметров", value: rows.length, icon: Database },
          {
            label: "Разделы данных",
            value: Object.keys(groups).filter(
              (key) => Object.keys(groups[key]).length,
            ).length,
            icon: Info,
          },
          {
            label: "Возможности камеры",
            value: capabilities.filter(([, value]) => value.available === true)
              .length,
            icon: CheckCircle2,
          },
        ].map(({ label, value, icon: Icon }) => (
          <Card key={label} className="gap-0 py-4">
            <CardContent className="flex items-center justify-between gap-3 px-4">
              <div>
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">
                  {value}
                </p>
              </div>
              <Icon className="size-5 text-muted-foreground/60" />
            </CardContent>
          </Card>
        ))}
      </div>
      {refreshing && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3 text-sm"
        >
          <Loader2 className="size-4 animate-spin text-primary" />
          <div>
            Читаем: {progress || "подготовка"}
            <p className="mt-0.5 text-xs text-muted-foreground">
              Камера отвечает на разделы по очереди. Остановка прервёт чтение
              после текущего ответа.
            </p>
          </div>
        </div>
      )}
      {(readError || details.error) && (
        <div
          role="alert"
          className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
        >
          {readError || errorMessage(details.error)}
          <Button
            size="sm"
            variant="ghost"
            className="ml-2"
            onClick={() => void details.refetch()}
          >
            Повторить
          </Button>
        </div>
      )}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Возможности</CardTitle>
          <CardDescription>
            «Неизвестно» означает, что прошивка ещё не сообщила соответствующий
            флаг.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {capabilities.length ? (
            <div className="flex flex-wrap gap-2">
              {capabilities.map(([name, capability]) => (
                <details key={name} className="group">
                  <summary className="cursor-pointer list-none">
                    <CapabilityBadge
                      name={name}
                      available={capability.available}
                    />
                  </summary>
                  <div className="mt-2 max-w-md rounded-lg border bg-muted/20 p-3">
                    <p className="mb-2 text-xs font-medium">
                      {featureLabels[name] || name} · признаки из прошивки
                    </p>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all text-xs text-muted-foreground">
                      {JSON.stringify(capability.evidence, null, 2)}
                    </pre>
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {details.isPending
                ? "Загружаем данные…"
                : "Подключите камеру и прочитайте параметры, чтобы получить признаки возможностей."}
            </p>
          )}
        </CardContent>
      </Card>
      <Card className="overflow-hidden">
        <CardHeader className="gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <CardTitle className="text-base">Параметры и метаданные</CardTitle>
            <Badge variant="secondary" className="tabular-nums">
              {filtered.length} из {rows.length}
            </Badge>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="Поиск по метаданным"
                placeholder="Поиск по названию, значению или разделу…"
                className="pl-9 pr-9"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(0);
                }}
              />
              {search && (
                <button
                  type="button"
                  aria-label="Очистить поиск"
                  className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    setSearch("");
                    setPage(0);
                  }}
                >
                  <X className="size-4" />
                </button>
              )}
            </div>
            <select
              aria-label="Раздел метаданных"
              className={`${selectClass} sm:w-52`}
              value={group}
              onChange={(e) => {
                setGroup(e.target.value);
                setPage(0);
              }}
            >
              <option value="all">Все разделы</option>
              {Object.keys(groups).map((key) => (
                <option key={key} value={key}>
                  {key === "account"
                    ? "Данные аккаунта"
                    : querySections[key as keyof typeof querySections] || key}
                </option>
              ))}
            </select>
          </div>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <div className="max-h-[560px] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 z-10 border-y bg-card text-xs text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-medium">Раздел</th>
                  <th className="px-5 py-3 font-medium">Параметр</th>
                  <th className="px-5 py-3 font-medium">Значение</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((row) => (
                  <tr
                    key={`${row.group}:${row.key}`}
                    className="border-b border-border/50 align-top last:border-0 hover:bg-muted/20"
                  >
                    <td className="whitespace-nowrap px-5 py-3 text-xs text-muted-foreground">
                      {row.group === "account"
                        ? "Аккаунт"
                        : querySections[
                            row.group as keyof typeof querySections
                          ] || row.group}
                    </td>
                    <td className="max-w-[260px] break-words px-5 py-3 font-mono text-xs">
                      {row.key}
                    </td>
                    <td className="min-w-[180px] max-w-[600px] select-text break-all px-5 py-3 font-mono text-xs leading-relaxed text-muted-foreground">
                      {row.value}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!filtered.length && (
              <div className="flex min-h-40 flex-col items-center justify-center gap-2 px-6 py-10 text-center">
                <Database className="mb-1 size-6 text-muted-foreground/50" />
                <p className="text-sm font-medium">
                  {rows.length ? "Ничего не найдено" : "Параметров пока нет"}
                </p>
                <p className="max-w-sm text-xs leading-relaxed text-muted-foreground">
                  {rows.length
                    ? "Попробуйте другой запрос или выберите все разделы."
                    : "Откройте видео и нажмите «Обновить параметры». Часть данных зависит от поддержки прошивки."}
                </p>
              </div>
            )}
          </div>
          {filtered.length > 100 && (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-3 text-xs text-muted-foreground">
              <span>
                {activePage * 100 + 1}–
                {Math.min((activePage + 1) * 100, filtered.length)} из{" "}
                {filtered.length} полей
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={activePage === 0}
                  onClick={() => setPage(activePage - 1)}
                >
                  <ChevronLeft className="size-3.5" />
                  Назад
                </Button>
                <span className="tabular-nums">
                  {activePage + 1} / {pageCount}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={activePage === pageCount - 1}
                  onClick={() => setPage(activePage + 1)}
                >
                  Вперёд
                  <ChevronRight className="size-3.5" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      {!!Object.keys(details.data?.queries || {}).length && (
        <details className="rounded-xl border p-4">
          <summary className="cursor-pointer text-sm font-medium">
            Результаты чтения разделов
          </summary>
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(details.data?.queries || {}).map(
              ([name, query]) => (
                <Badge key={name} variant="outline">
                  {querySections[name as keyof typeof querySections] || name}
                  <span className="ml-1 text-muted-foreground">
                    ·{" "}
                    {query.state === "confirmed"
                      ? "подтверждено"
                      : query.state === "rejected"
                        ? `отказ ${query.result ?? ""}`
                        : query.state || "нет ответа"}
                  </span>
                </Badge>
              ),
            )}
          </div>
        </details>
      )}
    </div>
  );
}
