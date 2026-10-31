import type { Camera } from "@/lib/types";
export function cameraFixture(overrides: Partial<Camera> = {}): Camera {
  return {
    id: "camera-a",
    name: "Тестовая камера",
    device_id: "fixture-only",
    state: "streaming",
    error: null,
    ip: "192.168.20.10",
    substream: 1,
    quality: "high",
    connection_mode: "cloud",
    transport: { mode: "cloud", path: "relay" },
    viewable: true,
    capability: "native",
    protocol: "CS2/PPPP",
    lenses: [0, 1, 2],
    metadata: {},
    account_metadata: {},
    lens_metadata: [0, 1, 2].map((id) => ({
      id,
      width: 1920,
      height: 1080,
      measured_fps: 10,
      bitrate_kbps: 300,
      last_frame: Date.now() / 1000,
    })),
    viewers: 1,
    last_frame: Date.now() / 1000,
    connections: 1,
    ...overrides,
  };
}
