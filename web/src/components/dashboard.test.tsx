import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import type { AccountInfo } from "@/lib/types";
import { cameraFixture } from "@/test/fixtures";
import { Dashboard, Workspace } from "./dashboard";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const clients: QueryClient[] = [];
function createClient(staleTime = Infinity) {
  const value = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime, gcTime: 0 },
      mutations: { retry: false, gcTime: 0 },
    },
  });
  clients.push(value);
  return value;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function display(client: QueryClient, children: React.ReactNode) {
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  );
}
function submitLogin(username = "new-account") {
  fireEvent.change(screen.getByLabelText("Логин или электронная почта"), {
    target: { value: username },
  });
  fireEvent.change(screen.getByLabelText("Пароль", { exact: true }), {
    target: { value: "fixture-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Войти в пространство" }));
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("PointerEvent", MouseEvent);
  vi.spyOn(api, "account").mockRejectedValue(
    new ApiError("account_login_required", 401),
  );
  vi.spyOn(api, "login").mockResolvedValue({
    username: "new-account",
    camera_count: 1,
  });
  vi.spyOn(api, "cameras").mockResolvedValue([cameraFixture()]);
  vi.spyOn(api, "health").mockResolvedValue({
    ok: true,
    version: "fixture",
    persistence: { enabled: true, error: null },
  });
  vi.spyOn(api, "exportStatus").mockResolvedValue({
    enabled: false,
    available: true,
  });
  vi.spyOn(api, "details").mockResolvedValue({
    groups: {},
    queries: {},
    capabilities: {},
  });
});
afterEach(() => {
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("dashboard session and camera demand lifecycle", () => {
  it("ignores a pre-login account read that returns 401 after a fresh login succeeds", async () => {
    const oldRead = deferred<AccountInfo>();
    vi.mocked(api.account).mockReturnValue(oldRead.promise);
    const client = createClient(0);
    client.setQueryData(queryKeys.account, null);
    display(client, <Dashboard />);
    await waitFor(() => expect(api.account).toHaveBeenCalledOnce());
    submitLogin();
    await screen.findByRole("heading", { name: "Тестовая камера" });
    await act(async () => {
      oldRead.reject(new ApiError("account_login_required", 401));
    });
    await waitFor(() =>
      expect(client.getQueryData(queryKeys.account)).toEqual({
        username: "new-account",
        camera_count: 1,
      }),
    );
    expect(
      screen.queryByRole("button", { name: "Войти в пространство" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Тестовая камера" }),
    ).toBeInTheDocument();
  });

  it("does not let a late logout callback from an old workspace clear a fresh session", async () => {
    const oldLogout = deferred<{ ok: boolean }>();
    vi.spyOn(api, "logout").mockReturnValue(oldLogout.promise);
    const client = createClient();
    client.setQueryData(queryKeys.account, {
      username: "old-account",
      camera_count: 1,
    });
    display(client, <Dashboard />);
    await screen.findByRole("heading", { name: "Тестовая камера" });
    fireEvent.pointerDown(screen.getByRole("button", { name: /old-account/ }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "Выйти из аккаунта" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Выйти и остановить" }));
    await waitFor(() => expect(api.logout).toHaveBeenCalledOnce());
    // Simulate a session-expiry read exposing sign-in before the old reply arrives.
    act(() => {
      client.setQueryData(queryKeys.account, null);
    });
    await screen.findByRole("button", { name: "Войти в пространство" });
    submitLogin();
    await screen.findByRole("heading", { name: "Тестовая камера" });
    await act(async () => {
      oldLogout.resolve({ ok: true });
    });
    expect(client.getQueryData(queryKeys.account)).toEqual({
      username: "new-account",
      camera_count: 1,
    });
    expect(
      screen.queryByRole("button", { name: "Войти в пространство" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the same video elements connected while opening camera controls", async () => {
    const client = createClient();
    display(
      client,
      <Workspace
        account={{ username: "fixture", camera_count: 1 }}
        onExpired={vi.fn()}
      />,
    );
    await screen.findByAltText("Тестовая камера · объектив 1");
    const images = screen.getAllByRole("img");
    const sourceURLs = images.map((image) => image.getAttribute("src"));
    const videoPanel = screen.getByRole("tabpanel", { name: "Прямой эфир" });
    fireEvent.keyDown(screen.getByRole("tab", { name: "Управление" }), {
      key: "Enter",
    });
    await waitFor(() =>
      expect(videoPanel).toHaveAttribute("data-state", "inactive"),
    );
    for (const image of images) expect(image).toBeInTheDocument();
    expect(images.map((image) => image.getAttribute("src"))).toEqual(
      sourceURLs,
    );
    expect(videoPanel).toHaveClass("data-[state=inactive]:hidden");
  });
});
