import { Aperture } from "lucide-react";
import { cn } from "@/lib/utils";
export function Brand({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-[0_0_24px_#baf26a12]">
        <Aperture className="size-6" strokeWidth={1.7} />
      </span>
      {!compact && (
        <span>
          <span className="block font-display text-lg font-bold tracking-tight">
            O-Kam{" "}
            <span className="font-normal text-muted-foreground">Bridge</span>
          </span>
          <span className="block text-[9px] font-medium tracking-[0.23em] text-muted-foreground">
            ВАШИ КАМЕРЫ. ВАШ СЕРВЕР.
          </span>
        </span>
      )}
    </div>
  );
}
