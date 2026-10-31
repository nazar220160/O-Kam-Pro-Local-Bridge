import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CameraVideo, ConnectionToolbar } from "./camera-video";
import { api } from "@/lib/api";
import { cameraFixture } from "@/test/fixtures";
afterEach(() => vi.restoreAllMocks());
function wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { mutations: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
describe("live transport and media lifecycle", () => {
  it("requests cloud explicitly without the camera LAN IP and blocks duplicate connections", async () => {
    let finish!: (value: { ok: boolean; state: string }) => void;
    const connect = vi.spyOn(api, "connect").mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const changed = vi.fn();
    render(<ConnectionToolbar camera={cameraFixture()} onChange={changed} />, {
      wrapper,
    });
    fireEvent.click(screen.getByRole("button", { name: "O-Kam Pro" }));
    await waitFor(() =>
      expect(connect).toHaveBeenCalledWith("camera-a", {
        connection_mode: "cloud",
        ip: null,
        substream: 1,
        quality: "high",
      }),
    );
    expect(screen.getByRole("button", { name: "O-Kam Pro" })).toBeDisabled();
    finish({ ok: true, state: "preparing" });
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
  });
  it("applies quality on the existing cloud session", async () => {
    const stream = vi
      .spyOn(api, "stream")
      .mockResolvedValue({ ok: true, mode: "live" });
    const connect = vi.spyOn(api, "connect");
    render(
      <ConnectionToolbar
        camera={cameraFixture({ quality: "low" })}
        onChange={vi.fn()}
      />,
      { wrapper },
    );
    fireEvent.click(screen.getByRole("button", { name: "Применить" }));
    await waitFor(() =>
      expect(stream).toHaveBeenCalledWith(
        "camera-a",
        expect.objectContaining({
          quality: "low",
          connection_mode: "cloud",
          ip: null,
        }),
      ),
    );
    expect(connect).not.toHaveBeenCalled();
  });
  it("retains the exact image nodes and URLs while metadata and quality update", () => {
    const camera = cameraFixture();
    const { rerender } = render(<CameraVideo camera={camera} />, { wrapper });
    const images = screen.getAllByRole("img");
    const sources = images.map((image) => image.getAttribute("src"));
    rerender(
      <CameraVideo
        camera={{
          ...camera,
          quality: "low",
          lens_metadata: camera.lens_metadata.map((lens) => ({
            ...lens,
            width: 448,
            height: 256,
          })),
        }}
      />,
    );
    expect(screen.getAllByRole("img")).toEqual(images);
    expect(
      screen.getAllByRole("img").map((image) => image.getAttribute("src")),
    ).toEqual(sources);
    expect(screen.getAllByText("448 × 256")).toHaveLength(3);
  });
  it("pauses only the chosen lens and resumes it without a camera reconnect", () => {
    render(<CameraVideo camera={cameraFixture()} />, { wrapper });
    fireEvent.click(
      screen.getByRole("button", { name: "Приостановить объектив 1" }),
    );
    expect(screen.getAllByRole("img")).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: "Продолжить объектив 1" }),
    );
    expect(screen.getAllByRole("img")).toHaveLength(3);
    expect(
      screen.getByAltText("Тестовая камера · объектив 1").getAttribute("src"),
    ).toContain("retry=1");
  });
});
