import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import type { ArchiveStatus, Camera, ExportStatus } from "@/lib/types";
import { BridgeExports } from "./bridge-exports";
import { CameraArchive } from "./camera-archive";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const camera: Camera = {
  id: "camera-a",
  name: "Test camera",
  device_id: "redacted",
  state: "streaming",
  error: null,
  ip: null,
  substream: 1,
  quality: "high",
  connection_mode: "cloud",
  transport: { mode: "cloud", path: "relay" },
  viewable: true,
  capability: "native",
  protocol: "CS2",
  lenses: [0, 1],
  lens_metadata: [],
  metadata: {},
  account_metadata: {},
  viewers: 1,
  last_frame: null,
  connections: 1,
};
const published: ExportStatus = {
  enabled: true,
  available: true,
  state: "streaming",
  export_id: "publication-a",
  advertise_host: "bridge.example.test",
  rtsp: true,
  onvif: true,
  rtsp_port: 8557,
  onvif_port: 8899,
  onvif_uri:
    "http://bridge.example.test:8899/onvif/publication-a/device_service",
  profiles: [
    {
      lens: 0,
      token: "lens0",
      width: 1920,
      height: 1080,
      fps: 10,
      rtsp_uri: "rtsp://bridge.example.test:8557/publication-a/lens0",
      snapshot_uri:
        "http://bridge.example.test:8899/onvif/publication-a/snapshot.jpg?lens=0",
    },
  ],
};
const archiveStatus: ArchiveStatus = {
  recording_enabled: false,
  workers: [],
  records: [
    {
      token: "recording/token",
      source: "server",
      lens: 0,
      start: "2026-11-01T12:00:00Z",
      duration: 60,
      size: 4096,
    },
  ],
  storage: {
    count: 1,
    bytes: 4096,
    retention_days: 7,
    max_bytes: 10 * 1024 ** 3,
  },
  jobs: [],
};

const clients: QueryClient[] = [];
function client() {
  const value = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(value);
  return value;
}
function withClient(queryClient: QueryClient, component: React.ReactNode) {
  return (
    <QueryClientProvider client={queryClient}>{component}</QueryClientProvider>
  );
}

beforeEach(() => {
  vi.spyOn(api, "exportStatus").mockResolvedValue(published);
  vi.spyOn(api, "exportCredentials").mockResolvedValue({
    username: "bridge",
    password: "publication-password",
  });
  vi.spyOn(api, "configureExport").mockResolvedValue(published);
  vi.spyOn(api, "archiveStatus").mockResolvedValue(archiveStatus);
  vi.spyOn(api, "configureArchive").mockResolvedValue({
    id: "job-a",
    state: "pending",
  });
  vi.spyOn(api, "sdDates").mockResolvedValue(["20261031", "20261101"]);
  vi.spyOn(api, "sdRecords").mockResolvedValue([
    {
      id: "sd-source-a",
      filename: "fragment.mp4",
      start: "2026-11-01T10:00:00Z",
      duration: 120,
    },
  ]);
});
afterEach(() => {
  for (const value of clients.splice(0)) value.clear();
});

describe("bridge publication", () => {
  it("shows selectable credentials automatically and drops their query on unmount", async () => {
    const queryClient = client();
    const view = render(
      withClient(queryClient, <BridgeExports camera={camera} />),
    );
    const password = await screen.findByDisplayValue("publication-password");
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveAttribute("readonly");
    expect(screen.getByDisplayValue("bridge")).toBeInTheDocument();
    expect(api.configureExport).not.toHaveBeenCalled();
    expect(api.exportCredentials).toHaveBeenCalledWith(camera.id);
    view.unmount();
    await waitFor(() =>
      expect(
        queryClient.getQueryData([
          "export-credentials",
          camera.id,
          "publication-a",
        ]),
      ).toBeUndefined(),
    );
  });

  it("lets the API select a cloud publication host and preserves edited fields during polling", async () => {
    vi.mocked(api.exportStatus).mockResolvedValue({
      enabled: false,
      available: true,
    });
    vi.mocked(api.configureExport).mockImplementation(async () => {
      vi.mocked(api.exportStatus).mockResolvedValue(published);
      return published;
    });
    const queryClient = client();
    render(withClient(queryClient, <BridgeExports camera={camera} />));
    const enable = screen.getByRole("button", { name: "Включить публикацию" });
    await waitFor(() => expect(enable).toBeEnabled());
    fireEvent.click(enable);
    await waitFor(() =>
      expect(api.configureExport).toHaveBeenCalledWith(camera.id, {
        enabled: true,
        rtsp: true,
        onvif: true,
      }),
    );
    const host = await screen.findByDisplayValue("bridge.example.test");
    expect(host).toHaveValue("bridge.example.test");
    fireEvent.change(host, { target: { value: "custom-nvr.example.test" } });
    await act(async () => {
      queryClient.setQueryData(["export", camera.id], {
        ...published,
        advertise_host: "another.example.test",
      });
    });
    expect(host).toHaveValue("custom-nvr.example.test");
  });

  it("does not expose a late credential reply after selecting another camera", async () => {
    let resolve!: (value: { username: string; password: string }) => void;
    vi.mocked(api.exportCredentials).mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    vi.mocked(api.exportStatus).mockImplementation(async (id) =>
      id === camera.id ? published : { enabled: false, available: true },
    );
    const queryClient = client();
    const view = render(
      withClient(queryClient, <BridgeExports camera={camera} />),
    );
    await waitFor(() => expect(api.exportCredentials).toHaveBeenCalled());
    view.rerender(
      withClient(
        queryClient,
        <BridgeExports camera={{ ...camera, id: "camera-b" }} />,
      ),
    );
    await act(async () => {
      resolve({ username: "old-user", password: "old-secret" });
    });
    expect(screen.queryByDisplayValue("old-secret")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(
        queryClient.getQueryData([
          "export-credentials",
          camera.id,
          "publication-a",
        ]),
      ).toBeUndefined(),
    );
  });
});

describe("camera archive", () => {
  it("serializes SD index reads before another date can be selected", async () => {
    let resolve!: (value: []) => void;
    vi.mocked(api.sdRecords).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    render(withClient(client(), <CameraArchive camera={camera} />));
    await screen.findByRole("link", { name: "Скачать запись линзы 1" });
    fireEvent.click(screen.getByRole("button", { name: "Проверить SD" }));
    await waitFor(() => expect(api.sdRecords).toHaveBeenCalled());
    const date = screen.getByLabelText("Дата на SD-карте");
    expect(date).toBeDisabled();
    await act(async () => {
      resolve([]);
    });
    await waitFor(() => expect(date).toBeEnabled());
    fireEvent.change(date, { target: { value: "20261031" } });
    await waitFor(() =>
      expect(api.sdRecords).toHaveBeenCalledWith(camera.id, "20261031"),
    );
  });

  it("keeps recording and SD access explicit and imports only a listed source ID", async () => {
    render(withClient(client(), <CameraArchive camera={camera} />));
    await screen.findByRole("link", { name: "Скачать запись линзы 1" });
    expect(api.configureArchive).not.toHaveBeenCalled();
    expect(api.sdDates).not.toHaveBeenCalled();
    expect(api.sdRecords).not.toHaveBeenCalled();
    expect(
      screen.getByRole("link", { name: "Скачать запись линзы 1" }),
    ).toHaveAttribute(
      "href",
      "/api/cameras/camera-a/archive/file/recording%2Ftoken",
    );
    fireEvent.click(screen.getByRole("button", { name: "Проверить SD" }));
    const importButton = await screen.findByRole("button", {
      name: "В архив моста",
    });
    expect(api.sdRecords).toHaveBeenCalledWith(camera.id, "20261101");
    fireEvent.click(importButton);
    await waitFor(() =>
      expect(api.configureArchive).toHaveBeenCalledWith(camera.id, {
        action: "sd_import",
        source_id: "sd-source-a",
        duration: 30,
      }),
    );
  });

  it("preserves recording edits across status reads and submits the explicit policy", async () => {
    const queryClient = client();
    render(withClient(queryClient, <CameraArchive camera={camera} />));
    await screen.findByRole("link", { name: "Скачать запись линзы 1" });
    const quota = screen.getByLabelText("Квота камеры, МиБ");
    fireEvent.change(quota, { target: { value: "20480" } });
    await act(async () => {
      queryClient.setQueryData(["archive", camera.id], {
        ...archiveStatus,
        storage: { ...archiveStatus.storage, max_bytes: 30 * 1024 ** 3 },
      });
    });
    expect(quota).toHaveValue(20480);
    fireEvent.click(screen.getByRole("button", { name: "Начать запись" }));
    await waitFor(() =>
      expect(api.configureArchive).toHaveBeenCalledWith(camera.id, {
        action: "record",
        enabled: true,
        segment_seconds: 60,
        retention_days: 7,
        max_bytes: 20480 * 1048576,
      }),
    );
  });

  it("stops an active recording even if an edited future policy is invalid", async () => {
    vi.mocked(api.archiveStatus).mockResolvedValue({
      ...archiveStatus,
      recording_enabled: true,
      workers: [{ lens: 0, running: true, segment_seconds: 60 }],
    });
    render(withClient(client(), <CameraArchive camera={camera} />));
    await screen.findByText("REC");
    fireEvent.change(screen.getByLabelText("Длина сегмента, с"), {
      target: { value: "0" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Остановить" }));
    await waitFor(() =>
      expect(api.configureArchive).toHaveBeenCalledWith(camera.id, {
        action: "record",
        enabled: false,
      }),
    );
  });
});
