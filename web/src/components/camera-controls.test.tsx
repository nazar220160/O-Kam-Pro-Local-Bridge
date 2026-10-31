import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Camera, CameraDetails, ControlResult } from "@/lib/types";
import { CameraControls } from "./camera-controls";
import { CameraMetadata } from "./camera-metadata";
import { NativeServices } from "./native-services";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn() },
}));
const camera: Camera = {
  id: "camera-a",
  name: "Camera A",
  device_id: "fixture-a",
  state: "streaming",
  error: null,
  ip: "192.168.20.10",
  substream: 1,
  quality: "high",
  connection_mode: "lan",
  transport: { mode: "lan", path: "LAN" },
  viewable: true,
  capability: "native",
  protocol: "CS2/PPPP",
  lenses: [0, 1, 2],
  lens_metadata: [],
  metadata: {},
  account_metadata: {},
  viewers: 1,
  last_frame: null,
  connections: 1,
};
const details: CameraDetails = {
  account: { model: "Fixture" },
  groups: { status: { firmware: "fixture-1" } },
  queries: {},
  capabilities: {},
};
const clients: QueryClient[] = [];
function wrapper(client: QueryClient, children: React.ReactNode) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
function client() {
  const result = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  clients.push(result);
  return result;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.spyOn(api, "details").mockResolvedValue(details);
  vi.spyOn(api, "control").mockResolvedValue({ state: "confirmed" });
  vi.spyOn(api, "credentials").mockResolvedValue({
    username: "admin",
    password: "native-secret",
  });
  vi.spyOn(api, "services").mockResolvedValue({
    camera_id: camera.id,
    ip: camera.ip!,
    ports: [],
    capabilities: {},
    configuration: {},
    protocol_verified: false,
  });
  vi.stubGlobal("PointerEvent", MouseEvent);
});
afterEach(() => {
  for (const value of clients.splice(0)) value.clear();
  vi.unstubAllGlobals();
});

describe("camera controls", () => {
  it("loads cached details without sending commands and honors an explicit unsupported PTZ flag", async () => {
    vi.mocked(api.details).mockResolvedValue({
      ...details,
      capabilities: { ptz: { available: false, evidence: { haveMotor: 0 } } },
    });
    render(wrapper(client(), <CameraControls camera={camera} />));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Повернуть вверх" }),
      ).toBeDisabled(),
    );
    expect(api.control).not.toHaveBeenCalled();
    expect(
      screen.getByRole("button", { name: "Остановить поворот" }),
    ).toBeEnabled();
  });

  it("releases a bounded PTZ impulse with Stop even while the move request is pending", async () => {
    const move = deferred<ControlResult>();
    vi.mocked(api.control).mockImplementation((_id, action) =>
      action === "ptz" ? move.promise : Promise.resolve({ state: "confirmed" }),
    );
    render(wrapper(client(), <CameraControls camera={camera} />));
    fireEvent.change(screen.getByLabelText("Режим поворота"), {
      target: { value: "pulse" },
    });
    const up = screen.getByRole("button", { name: "Повернуть вверх" });
    fireEvent.pointerDown(up, { button: 0, pointerId: 1 });
    await waitFor(() =>
      expect(api.control).toHaveBeenCalledWith(camera.id, "ptz", {
        direction: "up",
        speed: 1,
        duration_ms: 200,
        lens: 0,
      }),
    );
    fireEvent.pointerUp(up, { button: 0, pointerId: 1 });
    await waitFor(() =>
      expect(api.control).toHaveBeenCalledWith(camera.id, "ptz_stop", {}),
    );
    await act(async () => move.resolve({ state: "confirmed" }));
  });

  it("ignores a late command result after camera selection changes", async () => {
    const old = deferred<ControlResult>();
    vi.mocked(api.control).mockReturnValueOnce(old.promise);
    const cache = client();
    const view = render(wrapper(cache, <CameraControls camera={camera} />));
    fireEvent.click(screen.getByRole("button", { name: "Применить функцию" }));
    await waitFor(() =>
      expect(api.control).toHaveBeenCalledWith(camera.id, "light", {
        value: 0,
      }),
    );
    view.rerender(
      wrapper(
        cache,
        <CameraControls
          camera={{ ...camera, id: "camera-b", name: "Camera B" }}
        />,
      ),
    );
    await act(async () =>
      old.resolve({ state: "confirmed", payload: "old-camera-response" }),
    );
    expect(screen.queryByText(/old-camera-response/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Применить функцию" }),
    ).toBeEnabled();
    expect(toast.success).not.toHaveBeenCalled();
  });
});

describe("metadata and native services", () => {
  it("bounds rendered metadata rows while searching across every field", async () => {
    vi.mocked(api.details).mockResolvedValue({
      ...details,
      groups: {
        status: Object.fromEntries(
          Array.from({ length: 500 }, (_, index) => [
            `field-${index}`,
            `value-${index}`,
          ]),
        ),
      },
    });
    render(wrapper(client(), <CameraMetadata camera={camera} />));
    await screen.findByText("value-0");
    expect(screen.queryByText("value-499")).not.toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(101);
    fireEvent.change(screen.getByLabelText("Поиск по метаданным"), {
      target: { value: "value-499" },
    });
    expect(await screen.findByText("value-499")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(2);
    expect(api.control).not.toHaveBeenCalled();
  });

  it("cancels the remaining read sequence when switching cameras", async () => {
    const first = deferred<ControlResult>();
    vi.mocked(api.control).mockReturnValueOnce(first.promise);
    const cache = client();
    const view = render(wrapper(cache, <CameraMetadata camera={camera} />));
    await screen.findByText("fixture-1");
    fireEvent.click(screen.getByRole("button", { name: "Обновить параметры" }));
    await waitFor(() => expect(api.control).toHaveBeenCalledTimes(1));
    view.rerender(
      wrapper(cache, <CameraMetadata camera={{ ...camera, id: "camera-b" }} />),
    );
    await act(async () => first.resolve({ state: "confirmed" }));
    expect(api.control).toHaveBeenCalledTimes(1);
    expect(api.control).toHaveBeenCalledWith(camera.id, "query", {
      section: "status",
    });
  });

  it("reveals credentials only on request and discards a reply for the previous camera", async () => {
    const secret = deferred<{ username: string; password: string }>();
    vi.mocked(api.credentials).mockReturnValueOnce(secret.promise);
    const cache = client();
    const view = render(wrapper(cache, <NativeServices camera={camera} />));
    expect(api.credentials).not.toHaveBeenCalled();
    expect(api.services).not.toHaveBeenCalled();
    expect(api.control).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Показать данные камеры" }),
    );
    await waitFor(() =>
      expect(api.credentials).toHaveBeenCalledWith(camera.id),
    );
    view.rerender(
      wrapper(cache, <NativeServices camera={{ ...camera, id: "camera-b" }} />),
    );
    await act(async () =>
      secret.resolve({ username: "admin", password: "old-native-secret" }),
    );
    expect(
      screen.queryByDisplayValue("old-native-secret"),
    ).not.toBeInTheDocument();
    expect(
      JSON.stringify(
        cache
          .getQueryCache()
          .getAll()
          .map((query) => query.state.data),
      ),
    ).not.toContain("old-native-secret");
  });

  it("does not change native access until explicitly selected and rejects a password with spaces", async () => {
    render(wrapper(client(), <NativeServices camera={camera} />));
    expect(
      screen.getByRole("button", { name: "Применить настройку" }),
    ).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Изменение настройки"), {
      target: { value: "enable" },
    });
    fireEvent.change(screen.getByLabelText("Новый локальный пароль"), {
      target: { value: "abcd efgh" },
    });
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Применить настройку" })
        .closest("form")!,
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        expect.stringContaining("без пробелов"),
      ),
    );
    expect(api.control).not.toHaveBeenCalled();
  });
});
