import { afterEach, describe, expect, it, vi } from "vitest";
import { AxiosError, CanceledError } from "axios";
import { api, ApiError, http } from "./api";
afterEach(() => vi.restoreAllMocks());
describe("typed account API", () => {
  it("serializes logout and login so an old Set-Cookie cannot erase the new session", async () => {
    let finish!: (value: unknown) => void;
    const request = vi
      .spyOn(http, "request")
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      )
      .mockResolvedValueOnce({ data: { username: "new", camera_count: 1 } });
    const logout = api.logout();
    await vi.waitFor(() => expect(request).toHaveBeenCalledOnce());
    const login = api.login("new", "fixture-password");
    await Promise.resolve();
    expect(request).toHaveBeenCalledOnce();
    finish({ data: { ok: true } });
    await logout;
    await expect(login).resolves.toEqual({ username: "new", camera_count: 1 });
    expect(request.mock.calls.map(([config]) => config.url)).toEqual([
      "/api/account/logout",
      "/api/account/login",
    ]);
  });
  it("keeps the account bearer token out of the client query result", async () => {
    vi.spyOn(http, "request").mockResolvedValue({
      data: {
        username: "fixture",
        camera_count: 2,
        session_token: "private-bearer",
      },
    });
    expect(await api.login("fixture", "fixture-password")).toEqual({
      username: "fixture",
      camera_count: 2,
    });
    expect(http.defaults.withCredentials).toBe(true);
  });
  it("normalizes server errors without retaining raw response headers", async () => {
    vi.spyOn(http, "request").mockRejectedValue(
      new AxiosError(
        "raw vendor detail",
        "ERR_BAD_REQUEST",
        undefined,
        undefined,
        { status: 401, data: { error: "account_login_required" } } as never,
      ),
    );
    await expect(api.account()).rejects.toEqual(
      new ApiError("account_login_required", 401),
    );
  });
  it("preserves query cancellation instead of treating it as an outage", async () => {
    const cancelled = new CanceledError();
    vi.spyOn(http, "request").mockRejectedValue(cancelled);
    await expect(api.cameras(new AbortController().signal)).rejects.toBe(
      cancelled,
    );
  });
  it("allows enough time for cloud SD rendezvous and encodes opaque camera IDs", async () => {
    const request = vi.spyOn(http, "request").mockResolvedValue({ data: [] });
    await api.sdRecords("camera/id", "20261101");
    expect(request).toHaveBeenCalledWith(
      expect.objectContaining({
        url: "/api/cameras/camera%2Fid/archive/sd_records?date=20261101",
        timeout: 120_000,
      }),
    );
  });
});
