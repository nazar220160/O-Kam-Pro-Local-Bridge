"use client";
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowRight,
  Cloud,
  Eye,
  EyeOff,
  Loader2,
  Network,
  Radio,
  ShieldCheck,
  Video,
} from "lucide-react";
import { api, errorMessage } from "@/lib/api";
import type { AccountInfo } from "@/lib/types";
import { Brand } from "./brand";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

export function Login({
  onLogin,
  beforeLogin,
}: {
  onLogin: (account: AccountInfo) => void;
  beforeLogin?: () => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const login = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      await beforeLogin?.();
      return api.login(username.trim(), password);
    },
    onSuccess: (account) => {
      setPassword("");
      onLogin(account);
    },
  });
  return (
    <main className="login-shell grid min-h-dvh lg:grid-cols-[1.15fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-border/70 bg-[#0d1419] p-12 lg:flex lg:flex-col xl:p-16">
        <div className="login-grid absolute inset-0 opacity-40" />
        <div className="pointer-events-none absolute -left-40 top-44 size-[580px] rounded-full bg-primary/[0.045] blur-[120px]" />
        <Brand className="relative" />
        <div className="relative my-auto max-w-lg py-16">
          <div className="mb-6 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.22em] text-primary">
            <span className="size-1.5 rounded-full bg-primary" /> СВОЁ
            ПРОСТРАНСТВО НАБЛЮДЕНИЯ
          </div>
          <h1 className="font-display text-5xl font-semibold leading-[1.12] tracking-[-0.045em] xl:text-6xl">
            Все ракурсы.
            <br />
            <span className="text-muted-foreground">Одно пространство.</span>
          </h1>
          <p className="mt-6 max-w-sm text-sm leading-7 text-muted-foreground">
            Прямой эфир, управление и архив камер O-Kam Pro — на вашем сервере.
          </p>
          <div
            className="camera-illustration relative mt-12 h-52"
            aria-hidden="true"
          >
            <div className="absolute left-0 top-7 w-[72%] rounded-2xl border border-[#37443a] bg-[#141e20] p-3 shadow-2xl">
              <div className="mb-2 flex items-center justify-between text-[9px] tracking-wider text-muted-foreground">
                <span>ОБЪЕКТИВ 01</span>
                <span className="flex items-center gap-1.5 text-primary">
                  <span className="size-1 rounded-full bg-primary" /> LIVE
                </span>
              </div>
              <div className="illustration-view flex h-32 items-center justify-center rounded-lg border border-primary/10">
                <div className="flex size-16 items-center justify-center rounded-full border border-primary/20">
                  <Video className="size-7 text-primary/70" strokeWidth={1} />
                </div>
              </div>
            </div>
            <div className="absolute right-0 top-0 w-[46%] rounded-xl border border-border bg-[#172027] p-3 shadow-2xl">
              <div className="mb-2 text-[9px] tracking-wider text-muted-foreground">
                ОБЪЕКТИВ 02
              </div>
              <div className="illustration-view flex h-24 items-center justify-center rounded-md">
                <div className="size-10 rounded-full border border-primary/20 ring-[12px] ring-primary/[0.025]" />
              </div>
            </div>
            <div className="absolute bottom-0 right-5 flex items-center gap-3 rounded-xl border border-primary/20 bg-[#1b2920] px-4 py-3 shadow-xl">
              <ShieldCheck className="size-5 text-primary" />
              <div className="text-xs">
                <div className="font-medium">Под вашим контролем</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  Прямое подключение к камере
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="relative flex flex-wrap gap-6 text-xs text-muted-foreground">
          <span className="flex items-center gap-2">
            <Network className="size-3.5" /> Локальная сеть
          </span>
          <span className="flex items-center gap-2">
            <Cloud className="size-3.5" /> O-Kam Pro
          </span>
          <span className="flex items-center gap-2">
            <Radio className="size-3.5" /> ONVIF / RTSP
          </span>
        </div>
      </section>
      <section className="flex flex-col px-6 py-8 sm:px-12">
        <Brand className="lg:hidden" />
        <div className="m-auto w-full max-w-[360px] py-16">
          <div className="mb-9">
            <div className="mb-4 flex size-11 items-center justify-center rounded-xl border border-border bg-card">
              <ShieldCheck className="size-5 text-primary" />
            </div>
            <h2 className="font-display text-3xl font-semibold tracking-tight">
              Добро пожаловать
            </h2>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Войдите в аккаунт O-Kam Pro.
              <br />
              Ваши камеры появятся автоматически.
            </p>
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!login.isPending) login.mutate();
            }}
            className="space-y-5"
          >
            <div className="space-y-2.5">
              <Label htmlFor="username">Логин или электронная почта</Label>
              <Input
                id="username"
                name="username"
                autoComplete="username"
                placeholder="you@example.com"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                disabled={login.isPending}
                required
                className="h-12 bg-background/60"
              />
            </div>
            <div className="space-y-2.5">
              <Label htmlFor="password">Пароль</Label>
              <div className="relative">
                <Input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  placeholder="Пароль аккаунта"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={login.isPending}
                  required
                  className="h-12 bg-background/60 pr-12"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute right-1.5 top-1.5 size-9 text-muted-foreground"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={
                    showPassword ? "Скрыть пароль" : "Показать пароль"
                  }
                >
                  {showPassword ? <EyeOff /> : <Eye />}
                </Button>
              </div>
            </div>
            {login.isError && (
              <p
                role="alert"
                className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive"
              >
                {errorMessage(login.error)}
              </p>
            )}
            <Button
              type="submit"
              size="lg"
              className="h-12 w-full justify-between px-5 font-semibold"
              disabled={login.isPending || !username.trim() || !password}
            >
              {login.isPending ? "Входим в аккаунт…" : "Войти в пространство"}
              {login.isPending ? (
                <Loader2 className="animate-spin" />
              ) : (
                <ArrowRight />
              )}
            </Button>
          </form>
          <p className="mt-6 flex items-start gap-2 text-xs leading-5 text-muted-foreground">
            <ShieldCheck className="mt-0.5 size-3.5 shrink-0" /> Сессия
            сохраняется автоматически. После перезапуска сервера повторный вход
            не потребуется.
          </p>
        </div>
        <footer className="text-center text-[11px] text-muted-foreground/60">
          Независимый проект · O-Kam Pro Local Bridge
        </footer>
      </section>
    </main>
  );
}
