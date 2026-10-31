"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LockKeyhole,
  Network,
  Radio,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { api, errorMessage } from "@/lib/api";
import { queryKeys, useCameraDetails } from "@/lib/queries";
import type { Camera, ControlResult, Credentials } from "@/lib/types";
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
import { FormField, controlFeedback, selectClass } from "./camera-panel-utils";

export function NativeServices({ camera }: { camera: Camera }) {
  return <NativeServicesPanel key={camera.id} camera={camera} />;
}

function NativeServicesPanel({ camera }: { camera: Camera }) {
  const queryClient = useQueryClient();
  const details = useCameraDetails(camera.id);
  const services = useQuery({
    queryKey: queryKeys.services(camera.id),
    queryFn: () => api.services(camera.id),
    enabled: false,
    retry: false,
  });
  const [desired, setDesired] = useState("unchanged");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<ControlResult | null>(null);
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [revealing, setRevealing] = useState(false);
  const mounted = useRef(false);
  const requestBusy = useRef(false);
  const nativePassword = useRef<HTMLInputElement | null>(null);
  const usernameInput = useRef<HTMLInputElement | null>(null);
  const passwordInput = useRef<HTMLInputElement | null>(null);
  const values = useMemo(
    () =>
      Object.assign({}, ...Object.values(details.data?.groups || {})) as Record<
        string,
        unknown
      >,
    [details.data],
  );
  const localIP =
    camera.ip ||
    (typeof camera.account_metadata.lan_ip === "string"
      ? camera.account_metadata.lan_ip
      : "");
  const configuration = services.data?.configuration?.plaintext_password;
  const supported =
    configuration?.supported ??
    (values.support_Plaintext_Pwd == null
      ? null
      : String(values.support_Plaintext_Pwd) !== "0");
  const currentlyEnabled =
    configuration?.enabled ??
    (values.ExUserSwitch == null ? null : String(values.ExUserSwitch) === "1");

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!credentials) return;
    const timeout = setTimeout(() => setCredentials(null), 30_000);
    return () => clearTimeout(timeout);
  }, [credentials]);

  async function copy(text: string, input: HTMLInputElement | null) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Скопировано");
    } catch {
      input?.focus();
      input?.select();
      toast.message("Выделено — скопируйте текст вручную.");
    }
  }

  async function reveal() {
    if (requestBusy.current) return;
    requestBusy.current = true;
    setRevealing(true);
    try {
      // Native credentials are deliberately outside the query/mutation cache.
      const value = await api.credentials(camera.id);
      if (mounted.current) setCredentials(value);
    } catch (error) {
      if (mounted.current) toast.error(errorMessage(error));
    } finally {
      requestBusy.current = false;
      if (mounted.current) setRevealing(false);
    }
  }

  async function savePassword() {
    if (
      saving ||
      desired === "unchanged" ||
      !camera.viewable ||
      supported === false
    )
      return;
    const enabled = desired === "enable";
    if (enabled && !/^[\x21-\x7e]{8,63}$/.test(password)) {
      toast.error(
        "Нужен пароль из 8–63 латинских букв, цифр или ASCII-символов без пробелов.",
      );
      nativePassword.current?.focus();
      return;
    }
    const submittedPassword = password;
    setPassword("");
    setSaving(true);
    try {
      const reply = await api.control(
        camera.id,
        "plaintext_password",
        enabled
          ? { enabled: true, password: submittedPassword }
          : { enabled: false },
      );
      if (!mounted.current) return;
      setResult(reply);
      if (reply.state === "rejected" || reply.state === "interrupted")
        toast.error(controlFeedback(reply));
      else {
        toast.success(controlFeedback(reply));
        setDesired("unchanged");
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.details(camera.id),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.services(camera.id),
      });
    } catch (error) {
      if (mounted.current) toast.error(errorMessage(error));
    } finally {
      if (mounted.current) {
        setSaving(false);
        setPassword("");
      }
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">
          Сервисы самой камеры
        </h2>
        <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
          Проверка нативных ONVIF / RTSP и локальных данных доступа. Для
          подключения к NVR через мост используйте публикацию выше.
        </p>
      </div>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1.5">
              <CardTitle className="flex items-center gap-2 text-base">
                <Network className="size-4 text-primary" />
                Проверка локальных сервисов
              </CardTitle>
              <CardDescription>
                Только известные порты выбранной камеры. Проверка запускается
                вручную.
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={!localIP || services.isFetching}
              onClick={() => void services.refetch()}
            >
              {services.isFetching ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <RefreshCw className="size-4" />
              )}
              Проверить сервисы
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">
              {localIP || "Локальный IP не передан"}
            </Badge>
            <span>Нужен прямой сетевой маршрут от сервера к камере.</span>
          </div>
          {!localIP && (
            <p className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm leading-relaxed text-muted-foreground">
              Облачному подключению IP камеры не нужен. Вы по-прежнему можете
              использовать ONVIF / RTSP от моста.
            </p>
          )}
          {services.error && (
            <div
              role="alert"
              className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            >
              {errorMessage(services.error)}
            </div>
          )}
          {services.data ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                {["onvif", "rtsp"].map((name) => {
                  const capability = services.data.capabilities[name];
                  return (
                    <div
                      key={name}
                      className="rounded-xl border border-border/70 p-4"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-sm font-semibold">
                          <Radio className="size-4 text-muted-foreground" />
                          {name.toUpperCase()}
                        </span>
                        <Badge
                          variant="outline"
                          className={
                            capability?.available === true
                              ? "border-emerald-500/25 text-emerald-300"
                              : "text-muted-foreground"
                          }
                        >
                          {capability?.available === true
                            ? "Есть признак поддержки"
                            : capability?.available === false
                              ? "Нет признака поддержки"
                              : "Неизвестно"}
                        </Badge>
                      </div>
                      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                        Независимый переключатель сервиса для этой прошивки не
                        подтверждён. Публикация моста доступна отдельно.
                      </p>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="mt-3 w-full"
                        disabled
                      >
                        Переключение недоступно
                      </Button>
                      {capability?.evidence &&
                        Object.keys(capability.evidence).length > 0 && (
                          <details className="mt-3 text-xs">
                            <summary className="cursor-pointer text-muted-foreground">
                              Признаки из прошивки
                            </summary>
                            <pre className="mt-2 overflow-auto rounded-md bg-muted/30 p-2 text-muted-foreground">
                              {JSON.stringify(capability.evidence, null, 2)}
                            </pre>
                          </details>
                        )}
                    </div>
                  );
                })}
              </div>
              <div className="overflow-x-auto rounded-lg border">
                <table className="w-full text-left text-sm">
                  <thead className="border-b bg-muted/20 text-xs text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3 font-medium">Порт</th>
                      <th className="px-4 py-3 font-medium">Сервис</th>
                      <th className="px-4 py-3 font-medium">Состояние</th>
                    </tr>
                  </thead>
                  <tbody>
                    {services.data.ports.map((port) => (
                      <tr key={port.port} className="border-b last:border-0">
                        <td className="px-4 py-3 font-mono text-xs">
                          {port.port}
                        </td>
                        <td className="px-4 py-3 text-xs uppercase text-muted-foreground">
                          {String(port.service || "TCP")}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-2 text-xs ${port.open ? "text-emerald-300" : "text-muted-foreground"}`}
                          >
                            <span
                              className={`size-1.5 rounded-full ${port.open ? "bg-emerald-400" : "bg-muted-foreground/40"}`}
                            />
                            {port.open ? "Открыт" : "Закрыт / нет ответа"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground">
                <ShieldCheck className="mt-0.5 size-4 shrink-0" />
                Открытый TCP-порт не подтверждает работу протокола или вход по
                паролю.
              </p>
            </>
          ) : (
            !services.isFetching && (
              <p className="py-3 text-sm text-muted-foreground">
                Сервисы ещё не проверены. Проверка не изменяет настройки камеры.
              </p>
            )
          )}
        </CardContent>
      </Card>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <KeyRound className="size-4 text-primary" />
              PlainText password
            </CardTitle>
            <CardDescription>
              Отдельный пароль локального доступа, если его поддерживает
              прошивка.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">
                {supported === true
                  ? "Поддерживается"
                  : supported === false
                    ? "Не поддерживается"
                    : "Поддержка неизвестна"}
              </Badge>
              <Badge variant="secondary">
                {currentlyEnabled === true
                  ? "Сейчас включён"
                  : currentlyEnabled === false
                    ? "Сейчас выключен"
                    : "Состояние неизвестно"}
              </Badge>
            </div>
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault();
                void savePassword();
              }}
            >
              <FormField label="Изменение настройки" htmlFor="plaintext-mode">
                <select
                  id="plaintext-mode"
                  className={selectClass}
                  value={desired}
                  disabled={!camera.viewable || saving || supported === false}
                  onChange={(e) => {
                    setDesired(e.target.value);
                    setPassword("");
                  }}
                >
                  <option value="unchanged">Выберите действие</option>
                  <option value="enable">Включить / задать новый пароль</option>
                  <option value="disable">Выключить локальный пароль</option>
                </select>
              </FormField>
              {desired === "enable" && (
                <FormField
                  label="Новый локальный пароль"
                  htmlFor="plaintext-password"
                  hint="8–63 ASCII-символа без пробелов. Это не пароль аккаунта O-Kam Pro."
                >
                  <div className="relative">
                    <Input
                      ref={nativePassword}
                      id="plaintext-password"
                      type={passwordVisible ? "text" : "password"}
                      required
                      minLength={8}
                      maxLength={63}
                      autoComplete="new-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={saving}
                      className="pr-10"
                    />
                    <button
                      type="button"
                      aria-label={
                        passwordVisible
                          ? "Скрыть новый пароль"
                          : "Показать новый пароль"
                      }
                      className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground"
                      onClick={() => setPasswordVisible((value) => !value)}
                    >
                      {passwordVisible ? (
                        <EyeOff className="size-4" />
                      ) : (
                        <Eye className="size-4" />
                      )}
                    </button>
                  </div>
                </FormField>
              )}
              <Button
                type="submit"
                className="w-full"
                variant="secondary"
                disabled={
                  !camera.viewable ||
                  saving ||
                  desired === "unchanged" ||
                  supported === false
                }
              >
                {saving ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Check className="size-4" />
                )}
                Применить настройку
              </Button>
            </form>
            {!camera.viewable && (
              <p className="text-xs text-muted-foreground">
                Откройте видео камеры для изменения настройки.
              </p>
            )}
            {result && (
              <p
                role="status"
                className="rounded-lg border bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground"
              >
                {controlFeedback(result)} Проверка портов выполняется отдельно.
              </p>
            )}
            <p className="text-xs leading-relaxed text-muted-foreground">
              Этот пароль не заменяет нативную авторизацию моста и сам по себе
              не включает RTSP или ONVIF.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <LockKeyhole className="size-4 text-primary" />
              Нативные данные камеры
            </CardTitle>
            <CardDescription>
              Данные, выданные вашему аккаунту для прямого подключения драйвера.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm leading-relaxed text-muted-foreground">
              Они отличаются от пароля аккаунта, PlainText password и данных
              ONVIF / RTSP моста.
            </p>
            {credentials ? (
              <>
                <div className="space-y-3">
                  {[
                    {
                      id: "native-username",
                      label: "Пользователь камеры",
                      value: credentials.username,
                      ref: usernameInput,
                    },
                    {
                      id: "native-password",
                      label: "Пароль камеры",
                      value: credentials.password,
                      ref: passwordInput,
                    },
                  ].map((field) => (
                    <FormField
                      key={field.id}
                      label={field.label}
                      htmlFor={field.id}
                    >
                      <div className="flex gap-2">
                        <Input
                          id={field.id}
                          ref={field.ref}
                          readOnly
                          autoComplete="off"
                          value={field.value}
                          onFocus={(e) => e.target.select()}
                          className="font-mono text-xs"
                        />
                        <Button
                          type="button"
                          variant="outline"
                          size="icon"
                          aria-label={`Копировать: ${field.label}`}
                          onClick={() =>
                            void copy(field.value, field.ref.current)
                          }
                        >
                          <Copy className="size-4" />
                        </Button>
                      </div>
                    </FormField>
                  ))}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    Поле очистится через 30 секунд.
                  </p>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setCredentials(null)}
                  >
                    <EyeOff className="size-4" />
                    Скрыть
                  </Button>
                </div>
              </>
            ) : (
              <Button
                variant="outline"
                className="w-full"
                disabled={revealing}
                onClick={() => void reveal()}
              >
                {revealing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Eye className="size-4" />
                )}
                Показать данные камеры
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
