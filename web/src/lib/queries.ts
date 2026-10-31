import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./api";

export const queryKeys = {
  account: ["account"] as const,
  cameras: ["cameras"] as const,
  health: ["health"] as const,
  details: (id: string) => ["details", id] as const,
  services: (id: string) => ["services", id] as const,
  export: (id: string) => ["export", id] as const,
  archive: (id: string) => ["archive", id] as const,
};
export function retryRead(attempt: number, error: Error) {
  return !(error instanceof ApiError && error.status === 401) && attempt < 2;
}
export function useAccount() {
  return useQuery({
    queryKey: queryKeys.account,
    queryFn: ({ signal }) => api.account(signal),
    retry: retryRead,
    refetchInterval: 30_000,
  });
}
export function useCameras(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.cameras,
    queryFn: ({ signal }) => api.cameras(signal),
    enabled,
    retry: retryRead,
    refetchInterval: 2500,
  });
}
export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: ({ signal }) => api.health(signal),
    refetchInterval: 30_000,
    retry: 1,
  });
}
export function useCameraDetails(id: string) {
  return useQuery({
    queryKey: queryKeys.details(id),
    queryFn: ({ signal }) => api.details(id, signal),
    enabled: !!id,
    staleTime: 10_000,
    retry: retryRead,
  });
}
export function useCameraExport(id: string) {
  return useQuery({
    queryKey: queryKeys.export(id),
    queryFn: ({ signal }) => api.exportStatus(id, signal),
    enabled: !!id,
    refetchInterval: 5000,
    retry: retryRead,
  });
}
export function useCameraArchive(id: string) {
  return useQuery({
    queryKey: queryKeys.archive(id),
    queryFn: ({ signal }) => api.archiveStatus(id, signal),
    enabled: !!id,
    refetchInterval: 5000,
    retry: retryRead,
  });
}
