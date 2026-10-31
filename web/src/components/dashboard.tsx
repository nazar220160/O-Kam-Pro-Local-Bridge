"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  QueryClientProvider,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Activity,
  Archive,
  ArrowUpRight,
  BookOpen,
  Cable,
  Camera as CameraIcon,
  ChevronDown,
  Cloud,
  Info,
  LayoutGrid,
  Loader2,
  LogOut,
  Menu,
  Network,
  Power,
  Radio,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Video,
} from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, errorMessage } from "@/lib/api";
import type { AccountInfo, Camera } from "@/lib/types";
import {
  queryKeys,
  useAccount,
  useCameraExport,
  useCameras,
  useHealth,
} from "@/lib/queries";
import {
  cameraStatus,
  connectingStates,
  transportLabel,
} from "@/lib/presentation";
import { cn } from "@/lib/utils";
import dynamic from "next/dynamic";
import { Brand } from "./brand";
import { Login } from "./login";
import { createQueryClient } from "./providers";
import { CameraVideo, ConnectionToolbar } from "./camera-video";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Badge } from "./ui/badge";
import { Skeleton } from "./ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/tabs";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "./ui/sheet";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "./ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

const panelLoading = () => <Skeleton className="h-72 rounded-xl" />;
const CameraControls = dynamic(
  () => import("./camera-controls").then((module) => module.CameraControls),
  { loading: panelLoading },
);
const CameraMetadata = dynamic(
  () => import("./camera-metadata").then((module) => module.CameraMetadata),
  { loading: panelLoading },
);
const NativeServices = dynamic(
  () => import("./native-services").then((module) => module.NativeServices),
  { loading: panelLoading },
);
const BridgeExports = dynamic(
  () => import("./bridge-exports").then((module) => module.BridgeExports),
  { loading: panelLoading },
);
const CameraArchive = dynamic(
  () => import("./camera-archive").then((module) => module.CameraArchive),
  { loading: panelLoading },
);

type Panel =
  | "video"
  | "controls"
  | "exports"
  | "archive"
  | "metadata"
  | "native";
const panels: { value: Panel; label: string; icon: typeof Video }[] = [
  { value: "video", label: "Прямой эфир", icon: Video },
  { value: "controls", label: "Управление", icon: SlidersHorizontal },
  { value: "exports", label: "ONVIF / RTSP", icon: Radio },
  { value: "archive", label: "Архив", icon: Archive },
  { value: "metadata", label: "Данные", icon: Info },
  { value: "native", label: "Диагностика", icon: Settings2 },
];
function preferences(username: string): { camera?: string; tab?: string } {
  try {
    const value = JSON.parse(
      localStorage.getItem("okam-ui:" + username.toLowerCase()) || "{}",
    );
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    return {
      camera: typeof value.camera === "string" ? value.camera : undefined,
      tab: typeof value.tab === "string" ? value.tab : undefined,
    };
  } catch {
    return {};
  }
}
function savePreferences(
  username: string,
  value: { camera?: string; tab?: string },
) {
  try {
    localStorage.setItem(
      "okam-ui:" + username.toLowerCase(),
      JSON.stringify({ ...preferences(username), ...value }),
    );
  } catch {
    /* Browser storage is optional. */
  }
}

export function Dashboard() {
  const client = useQueryClient();
  const account = useAccount();
  const [sessionRevision, setSessionRevision] = useState(0);
  const authRevision = useRef(0);
  const expired = useCallback(() => {
    if (authRevision.current !== sessionRevision) return;
    authRevision.current += 1;
    setSessionRevision(authRevision.current);
    void client.cancelQueries({ queryKey: queryKeys.account });
    client.setQueryData(queryKeys.account, null);
  }, [client, sessionRevision]);
  async function loggedIn(info: AccountInfo) {
    const revision = ++authRevision.current;
    await client.cancelQueries({ queryKey: queryKeys.account });
    if (authRevision.current !== revision) return;
    setSessionRevision(revision);
    client.setQueryData(queryKeys.account, info);
  }
  if (account.isPending)
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-5">
        <Brand />
        <Loader2 className="size-5 animate-spin text-primary" />
        <span className="text-xs text-muted-foreground">
          Восстанавливаем рабочее пространство…
        </span>
      </main>
    );
  if (
    (account.error instanceof ApiError && account.error.status === 401) ||
    (!account.data && !account.isError)
  )
    return (
      <Login
        onLogin={loggedIn}
        beforeLogin={() =>
          client.cancelQueries({ queryKey: queryKeys.account })
        }
      />
    );
  if (!account.data)
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-5 px-6 text-center">
        <Brand />
        <h1 className="mt-5 font-display text-2xl font-semibold">
          Нет связи с сервером
        </h1>
        <p className="max-w-md text-sm text-muted-foreground">
          {errorMessage(account.error)} Сохранённая сессия останется на месте.
        </p>
        <Button variant="outline" onClick={() => account.refetch()}>
          <RefreshCw className="size-4" /> Повторить подключение
        </Button>
      </main>
    );
  return (
    <AccountWorkspace
      key={`${account.data.username}:${sessionRevision}`}
      account={account.data}
      onExpired={expired}
    />
  );
}

function AccountWorkspace({
  account,
  onExpired,
}: {
  account: AccountInfo;
  onExpired: () => void;
}) {
  const [client] = useState(createQueryClient);
  useEffect(
    () => () => {
      void client.cancelQueries();
      client.clear();
    },
    [client],
  );
  return (
    <QueryClientProvider client={client}>
      <Workspace account={account} onExpired={onExpired} />
    </QueryClientProvider>
  );
}

export function Workspace({
  account,
  onExpired,
}: {
  account: AccountInfo;
  onExpired: () => void;
}) {
  const client = useQueryClient();
  const catalog = useCameras(true);
  const health = useHealth();
  const [selected, setSelected] = useState(
    () => preferences(account.username).camera || "",
  );
  const [panel, setPanel] = useState<Panel>(() => {
    const tab = preferences(account.username).tab;
    return panels.some((item) => item.value === tab)
      ? (tab as Panel)
      : tab === "services"
        ? "exports"
        : "video";
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const [logoutOpen, setLogoutOpen] = useState(false);
  const cameras = catalog.data || [];
  const camera = cameras.find((item) => item.id === selected) || cameras[0];
  useEffect(() => {
    if (catalog.error instanceof ApiError && catalog.error.status === 401)
      onExpired();
  }, [catalog.error, onExpired]);
  const refresh = useMutation({
    mutationFn: api.refreshCatalog,
    onSuccess: (value) => {
      client.setQueryData(queryKeys.cameras, value);
      toast.success("Список камер обновлён");
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: onExpired,
    onError: (error) => toast.error(errorMessage(error)),
  });
  function select(id: string) {
    setSelected(id);
    savePreferences(account.username, { camera: id });
    setMobileOpen(false);
  }
  function changePanel(value: string) {
    setPanel(value as Panel);
    savePreferences(account.username, { tab: value });
  }
  const online = cameras.filter((item) => item.state === "streaming").length;
  const sidebarProps = {
    cameras,
    selected: camera?.id,
    onSelect: select,
    pending: catalog.isPending,
    refreshing: refresh.isPending,
    onRefresh: () => refresh.mutate(),
  };
  return (
    <div className="min-h-dvh lg:pl-[272px]">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[272px] border-r border-border/70 bg-[#0e151b] lg:flex lg:flex-col">
        <Sidebar {...sidebarProps} />
        <div className="mx-5 mb-5 rounded-lg border border-border/60 bg-card/60 px-3 py-3">
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <ShieldCheck className="size-3.5 text-primary/80" />
            {health.data?.persistence.enabled
              ? "Сессия сохраняется автоматически"
              : "Рабочее пространство"}
          </div>
          <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground/50">
            <span>O-Kam Pro Local Bridge</span>
            <span>{health.data?.version ? "v" + health.data.version : ""}</span>
          </div>
        </div>
      </aside>
      <header className="sticky top-0 z-20 flex h-[76px] items-center justify-between gap-4 border-b border-border/70 bg-background/95 px-5 backdrop-blur-md md:px-8">
        <div className="flex items-center gap-4">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className="lg:hidden"
                aria-label="Открыть список камер"
              >
                <Menu className="size-5" />
              </Button>
            </SheetTrigger>
            <SheetContent
              side="left"
              className="w-[290px] gap-0 bg-[#0e151b] p-0"
            >
              <SheetHeader className="sr-only">
                <SheetTitle>Ваши камеры</SheetTitle>
                <SheetDescription>
                  Выберите камеру для просмотра и управления
                </SheetDescription>
              </SheetHeader>
              <Sidebar {...sidebarProps} />
            </SheetContent>
          </Sheet>
          <span className="text-xs text-muted-foreground">
            Рабочее пространство
          </span>
          <span className="hidden text-muted-foreground/30 sm:block">/</span>
          <span className="hidden text-xs font-medium sm:block">Камеры</span>
        </div>
        <div className="flex items-center gap-4">
          <div
            className={cn(
              "hidden items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] sm:flex",
              health.isError
                ? "border-amber-500/20 text-amber-400"
                : "border-border text-muted-foreground",
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                health.isError ? "bg-amber-400" : "bg-primary",
              )}
            />
            {health.isError ? "Нет связи с мостом" : "Мост на связи"}
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" className="h-auto gap-2.5 px-1.5 py-2">
                <span className="flex size-8 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-xs font-semibold text-primary">
                  {account.username.slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden max-w-[180px] truncate text-xs font-normal text-muted-foreground md:block">
                  {account.username}
                </span>
                <ChevronDown className="size-3.5 text-muted-foreground" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64">
              <div className="px-2 py-2 text-xs text-muted-foreground">
                {account.username}
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <a href="/docs/" target="_blank" rel="noreferrer">
                  <BookOpen className="size-4" /> Документация API
                </a>
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => setLogoutOpen(true)}
                className="text-destructive"
              >
                <LogOut className="size-4" /> Выйти из аккаунта
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <main className="mx-auto max-w-[1900px] px-5 py-7 md:px-8 md:py-8 xl:px-10">
        {catalog.isError && (
          <div
            role="alert"
            className="mb-5 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 text-sm text-amber-200"
          >
            {errorMessage(catalog.error)} Данные обновятся после восстановления
            связи.
          </div>
        )}
        {health.data?.persistence.error && (
          <div
            role="alert"
            className="mb-5 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            Настройки не сохраняются на диске сервера. Проверьте хранилище
            состояния.
          </div>
        )}
        <div className="mb-7 flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="mb-2 text-[10px] font-medium tracking-[0.18em] text-muted-foreground">
              ВАШИ КАМЕРЫ <span className="mx-2 text-border">/</span> {online}{" "}
              ИЗ {cameras.length} В ЭФИРЕ
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-display text-3xl font-semibold tracking-[-0.035em] md:text-[34px]">
                {camera?.name || "Камеры"}
              </h1>
              {camera && <StatusBadge camera={camera} />}
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {camera
                ? `${transportLabel(camera)} · ${camera.viewable ? `${camera.lenses.length} объектива доступны` : "Подключите камеру для просмотра"}`
                : "Все устройства вашего аккаунта в одном месте"}
            </p>
          </div>
          {camera && (
            <Disconnect
              key={camera.id}
              camera={camera}
              onDone={() => {
                void client.invalidateQueries({ queryKey: queryKeys.cameras });
                void client.invalidateQueries({
                  queryKey: queryKeys.export(camera.id),
                });
              }}
            />
          )}
        </div>
        {catalog.isPending ? (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
              {[0, 1, 2, 3].map((value) => (
                <Skeleton key={value} className="h-24 rounded-xl" />
              ))}
            </div>
            <Skeleton className="h-80 rounded-xl" />
          </div>
        ) : camera ? (
          <CameraWorkspace
            key={camera.id}
            camera={camera}
            panel={panel}
            onPanel={changePanel}
          />
        ) : (
          <div className="flex min-h-80 flex-col items-center justify-center rounded-xl border border-dashed border-border text-center">
            <CameraIcon className="mb-5 size-10 text-muted-foreground" />
            <h2 className="font-display text-lg font-medium">Камер пока нет</h2>
            <p className="mt-2 max-w-sm text-sm text-muted-foreground">
              Добавьте камеру в официальном O-Kam Pro, затем обновите список.
            </p>
            <Button
              variant="outline"
              className="mt-5"
              disabled={refresh.isPending}
              onClick={() => refresh.mutate()}
            >
              <RefreshCw className="size-4" /> Обновить список
            </Button>
          </div>
        )}
      </main>
      <Dialog open={logoutOpen} onOpenChange={setLogoutOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Выйти из аккаунта?</DialogTitle>
            <DialogDescription>
              Выход удалит сохранённую сессию и остановит подключения,
              публикации ONVIF/RTSP и запись этого аккаунта. Чтобы сохранить их
              работающими, достаточно закрыть страницу.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setLogoutOpen(false)}>
              Остаться
            </Button>
            <Button
              variant="destructive"
              disabled={logout.isPending}
              onClick={() => logout.mutate()}
            >
              {logout.isPending && <Loader2 className="size-4 animate-spin" />}{" "}
              Выйти и остановить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Sidebar({
  cameras,
  selected,
  onSelect,
  pending,
  refreshing,
  onRefresh,
}: {
  cameras: Camera[];
  selected?: string;
  onSelect: (id: string) => void;
  pending: boolean;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "online">("all");
  const filtered = cameras.filter(
    (camera) =>
      camera.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()) &&
      (filter !== "online" || camera.state === "streaming"),
  );
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="px-6 pb-8 pt-7">
        <Brand />
      </div>
      <div className="px-5">
        <div className="mb-5 flex items-center gap-2 rounded-lg border border-primary/15 bg-primary/[0.065] px-3 py-2.5 text-xs font-medium text-primary">
          <LayoutGrid className="size-4" /> Камеры
          <span className="ml-auto text-[10px] text-primary/60">
            {cameras.length}
          </span>
        </div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[9px] font-medium tracking-[0.18em] text-muted-foreground/70">
            УСТРОЙСТВА АККАУНТА
          </h2>
          <Button
            variant="ghost"
            size="icon"
            className="size-6 text-muted-foreground"
            disabled={refreshing}
            onClick={onRefresh}
            aria-label="Обновить список камер"
          >
            <RefreshCw className={cn("size-3", refreshing && "animate-spin")} />
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-3 top-3 size-3.5 text-muted-foreground" />
          <Input
            aria-label="Поиск камер"
            placeholder="Найти камеру…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-9 border-border/70 bg-background/70 pl-9 text-xs"
          />
        </div>
        <div className="my-3 flex gap-4 text-[10px]">
          <button
            onClick={() => setFilter("all")}
            className={
              filter === "all" ? "text-foreground" : "text-muted-foreground"
            }
          >
            Все камеры
          </button>
          <button
            onClick={() => setFilter("online")}
            className={
              filter === "online" ? "text-primary" : "text-muted-foreground"
            }
          >
            В эфире
          </button>
        </div>
      </div>
      <nav
        aria-label="Камеры аккаунта"
        className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-6"
      >
        {pending
          ? [0, 1, 2].map((value) => (
              <Skeleton key={value} className="m-2 h-20 rounded-lg" />
            ))
          : filtered.map((camera) => (
              <button
                key={camera.id}
                onClick={() => onSelect(camera.id)}
                aria-current={selected === camera.id ? "true" : undefined}
                className={cn(
                  "group flex w-full items-center gap-3 rounded-xl border px-3 py-3.5 text-left transition-colors",
                  selected === camera.id
                    ? "border-border bg-secondary/50"
                    : "border-transparent hover:bg-card",
                )}
              >
                <span
                  className={cn(
                    "flex size-10 shrink-0 items-center justify-center rounded-lg border",
                    selected === camera.id
                      ? "border-primary/15 bg-primary/[0.055] text-primary"
                      : "border-border/70 bg-background/60 text-muted-foreground",
                  )}
                >
                  <CameraIcon className="size-[18px]" strokeWidth={1.5} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">
                    {camera.name}
                  </span>
                  <span className="mt-1.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                    <span
                      className={cn(
                        "size-1 rounded-full",
                        camera.state === "streaming"
                          ? "bg-primary"
                          : camera.error
                            ? "bg-destructive"
                            : connectingStates.has(camera.state)
                              ? "animate-pulse bg-amber-400"
                              : "bg-muted-foreground/40",
                      )}
                    />
                    {cameraStatus(camera)}
                  </span>
                </span>
                {camera.connection_mode === "cloud" ? (
                  <Cloud className="size-3 text-muted-foreground/50" />
                ) : (
                  <Network className="size-3 text-muted-foreground/50" />
                )}
              </button>
            ))}
        {!pending && !filtered.length && (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            Ничего не найдено
          </p>
        )}
      </nav>
      <a
        href="/docs/"
        target="_blank"
        rel="noreferrer"
        className="mx-6 mb-6 flex items-center justify-between text-[11px] text-muted-foreground hover:text-foreground"
      >
        <span className="flex items-center gap-2">
          <BookOpen className="size-3.5" /> Документация API
        </span>
        <ArrowUpRight className="size-3" />
      </a>
    </div>
  );
}

function StatusBadge({ camera }: { camera: Camera }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        "gap-1.5 rounded-full py-1 text-[10px] font-normal",
        camera.state === "streaming"
          ? "border-primary/20 bg-primary/5 text-primary"
          : camera.error
            ? "border-destructive/30 text-destructive"
            : "text-muted-foreground",
      )}
    >
      <span className="size-1 rounded-full bg-current" />
      {cameraStatus(camera)}
    </Badge>
  );
}

function CameraWorkspace({
  camera,
  panel,
  onPanel,
}: {
  camera: Camera;
  panel: Panel;
  onPanel: (value: string) => void;
}) {
  const client = useQueryClient();
  const publication = useCameraExport(camera.id);
  const bitrate = camera.lens_metadata.reduce(
    (sum, lens) => sum + (lens.bitrate_kbps || 0),
    0,
  );
  const resolution = camera.lens_metadata.find(
    (lens) => lens.width && lens.height,
  );
  const cards = [
    {
      label: "Подключение",
      value: transportLabel(camera),
      note:
        camera.transport.path === "relay"
          ? "Через ретранслятор"
          : camera.ip || "IP определяется автоматически",
      icon: camera.connection_mode === "cloud" ? Cloud : Network,
    },
    {
      label: "Объективы",
      value: camera.viewable
        ? String(camera.lenses.length).padStart(2, "0")
        : "—",
      note: "Независимые изображения",
      icon: CameraIcon,
    },
    {
      label: "Исходное видео",
      value: resolution ? `${resolution.width} × ${resolution.height}` : "—",
      note: bitrate
        ? `${Math.round(bitrate)} кбит/с · все объективы`
        : "Параметры появятся в эфире",
      icon: Activity,
    },
    {
      label: "Публикация моста",
      value: publication.data?.enabled
        ? publication.data.onvif
          ? "ONVIF + RTSP"
          : "RTSP"
        : "Выключена",
      note: publication.data?.enabled
        ? "Доступна для вашего NVR"
        : "Подключите VLC или Frigate",
      icon: Cable,
    },
  ];
  return (
    <>
      <div className="mb-7 grid grid-cols-2 gap-3 xl:grid-cols-4">
        {cards.map((card) => (
          <div
            key={card.label}
            className="rounded-xl border border-border/80 bg-card px-4 py-4"
          >
            <div className="mb-3 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
              <span>{card.label}</span>
              <card.icon className="size-3.5 text-muted-foreground/65" />
            </div>
            <div className="truncate font-display text-base font-semibold tracking-tight sm:text-lg">
              {card.value}
            </div>
            <div className="mt-1.5 truncate text-[10px] text-muted-foreground/70">
              {card.note}
            </div>
          </div>
        ))}
      </div>
      {camera.error && (
        <p
          role="alert"
          className="mb-5 rounded-lg border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
          {errorMessage(camera.error)}
        </p>
      )}
      <Tabs value={panel} onValueChange={onPanel}>
        <div className="mb-5 overflow-x-auto border-b border-border/80">
          <TabsList className="h-12 min-w-max justify-start gap-5 rounded-none bg-transparent p-0">
            {panels.map((item) => (
              <TabsTrigger
                key={item.value}
                value={item.value}
                className="h-12 gap-2 rounded-none border-b-2 border-transparent px-0 text-xs text-muted-foreground shadow-none data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-primary data-[state=active]:shadow-none"
              >
                <item.icon className="size-3.5" />
                {item.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>
        <TabsContent
          forceMount
          value="video"
          className="data-[state=inactive]:hidden"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold">Прямой эфир</h2>
            <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <ShieldCheck className="size-3" />
              {camera.connection_mode === "cloud"
                ? "Через O-Kam Pro"
                : "Локальное подключение"}
            </span>
          </div>
          <ConnectionToolbar
            camera={camera}
            onChange={() =>
              client.invalidateQueries({ queryKey: queryKeys.cameras })
            }
          />
          <CameraVideo camera={camera} />
          <p className="mt-4 flex items-start gap-2 text-[10px] leading-5 text-muted-foreground/60">
            <Info className="mt-1 size-3 shrink-0" />
            Предпросмотр в браузере · до 960 px и 5 кадров/с. Полное качество и
            звук доступны в RTSP-потоке.
          </p>
        </TabsContent>
        <TabsContent value="controls">
          <CameraControls camera={camera} />
        </TabsContent>
        <TabsContent value="exports">
          <BridgeExports camera={camera} />
        </TabsContent>
        <TabsContent value="archive">
          <CameraArchive camera={camera} />
        </TabsContent>
        <TabsContent value="metadata">
          <CameraMetadata camera={camera} />
        </TabsContent>
        <TabsContent value="native">
          <NativeServices camera={camera} />
        </TabsContent>
      </Tabs>
    </>
  );
}

function Disconnect({
  camera,
  onDone,
}: {
  camera: Camera;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const disconnect = useMutation({
    mutationFn: () => api.disconnect(camera.id),
    onSuccess: () => {
      setOpen(false);
      onDone();
    },
    onError: (error) => toast.error(errorMessage(error)),
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Button
        variant="outline"
        size="sm"
        className="gap-2 border-border/80 text-xs text-muted-foreground"
        disabled={camera.state === "disconnected" || disconnect.isPending}
        onClick={() => setOpen(true)}
      >
        <Power className="size-3.5" /> Отключить
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Отключить «{camera.name}»?</DialogTitle>
          <DialogDescription>
            Подключение камеры и её публикации остановятся. Вы сможете
            подключить камеру снова в любой момент.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Отмена
          </Button>
          <Button
            variant="destructive"
            disabled={disconnect.isPending}
            onClick={() => disconnect.mutate()}
          >
            Отключить камеру
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
