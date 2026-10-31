"use client";
import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { TooltipProvider } from "@/components/ui/tooltip";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 1500,
        refetchOnWindowFocus: true,
        refetchIntervalInBackground: false,
      },
      mutations: { retry: false },
    },
  });
}
export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(createQueryClient);
  return (
    <QueryClientProvider client={client}>
      <TooltipProvider>
        {children}
        <Toaster theme="dark" richColors position="bottom-right" closeButton />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
