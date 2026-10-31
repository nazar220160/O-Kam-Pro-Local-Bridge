"use client";
import { Button } from "@/components/ui/button";
export default function ErrorPage() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-5 px-6 text-center">
      <h1 className="font-display text-2xl font-semibold">
        Не удалось показать панель
      </h1>
      <p className="max-w-sm text-sm leading-6 text-muted-foreground">
        Попробуйте открыть её ещё раз. Подключения и настройки остаются на
        сервере.
      </p>
      <Button onClick={() => window.location.reload()}>Обновить панель</Button>
    </main>
  );
}
