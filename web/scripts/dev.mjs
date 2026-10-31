import http from "node:http";
import https from "node:https";
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HOP_HEADERS = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade",
]);

function targetURL(value) {
  const target = new URL(value);
  if (
    !["http:", "https:"].includes(target.protocol) || target.username || target.password ||
    target.pathname !== "/" || target.search || target.hash
  ) throw new Error("Development upstream must be an HTTP(S) origin without credentials or a path");
  return target;
}

function requestPath(value) {
  if (!value?.startsWith("/") || value.startsWith("//")) return null;
  try {
    const parsed = new URL(value, "http://dev.invalid");
    return { pathname: parsed.pathname, path: parsed.pathname + parsed.search };
  } catch {
    return null;
  }
}

function isBridgePath(pathname) {
  return pathname.startsWith("/api/") || pathname === "/health" ||
    pathname === "/docs" || pathname.startsWith("/docs/") || pathname === "/openapi.json";
}

function cleanHeaders(headers) {
  const connectionHeaders = String(headers.connection || "").split(",").map((name) => name.trim().toLowerCase());
  return Object.fromEntries(Object.entries(headers).filter(([name]) =>
    !HOP_HEADERS.has(name.toLowerCase()) && !connectionHeaders.includes(name.toLowerCase()),
  ));
}

function upstreamHeaders(request, target, upgrade = false) {
  const headers = cleanHeaders(request.headers);
  headers.host = target.host;
  // The browser Origin was checked before this server-to-server adaptation.
  if (headers.origin) headers.origin = target.origin;
  if (upgrade) {
    headers.connection = "Upgrade";
    headers.upgrade = request.headers.upgrade;
  }
  return headers;
}

function allowedRequest(request, loopbackOnly) {
  try {
    const authority = request.headers.host;
    if (!authority || /[\s/@\\]/.test(authority)) return false;
    const url = new URL("http://" + authority);
    if (loopbackOnly && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) return false;
    if (request.headers.origin) {
      const origin = new URL(request.headers.origin);
      if (!["http:", "https:"].includes(origin.protocol) || origin.host !== authority) return false;
    }
    return true;
  } catch {
    return false;
  }
}

function transport(target) {
  return target.protocol === "https:" ? https : http;
}

function fail(response, status = 502) {
  if (response.destroyed) return;
  if (response.headersSent) return response.destroy();
  const messages = {
    400: "Invalid development proxy request.",
    403: "Development origin is not allowed.",
    502: "Development upstream is unavailable. Wait for Next.js or check BRIDGE_DEV_URL.",
  };
  response.writeHead(status, {
    "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(messages[status]);
}

export function createDevProxy({ bridgeURL, nextURL, loopbackOnly = true }) {
  const bridge = targetURL(bridgeURL);
  const next = targetURL(nextURL);
  const server = http.createServer((request, response) => {
    const path = requestPath(request.url);
    if (!path) return fail(response, 400);
    if (!allowedRequest(request, loopbackOnly)) return fail(response, 403);
    const target = isBridgePath(path.pathname) ? bridge : next;
    const upstream = transport(target).request({
      protocol: target.protocol, hostname: target.hostname, port: target.port,
      method: request.method, path: path.path, headers: upstreamHeaders(request, target),
    }, (incoming) => {
      if (response.destroyed) return incoming.destroy();
      response.writeHead(incoming.statusCode || 502, cleanHeaders(incoming.headers));
      incoming.on("error", () => response.destroy());
      incoming.pipe(response);
    });
    upstream.setTimeout(120_000, () => upstream.destroy());
    upstream.on("error", () => fail(response));
    request.on("aborted", () => upstream.destroy());
    response.on("close", () => {
      if (!response.writableEnded) upstream.destroy();
    });
    request.pipe(upstream);
  });

  server.on("upgrade", (request, socket, head) => {
    const path = requestPath(request.url);
    if (!path || !allowedRequest(request, loopbackOnly) || isBridgePath(path.pathname)) {
      socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
      return;
    }
    const upstream = transport(next).request({
      protocol: next.protocol, hostname: next.hostname, port: next.port,
      method: request.method, path: path.path, headers: upstreamHeaders(request, next, true),
    });
    let switched = false;
    upstream.on("upgrade", (incoming, tunnel, upstreamHead) => {
      switched = true;
      if (socket.destroyed) return tunnel.destroy();
      let headers = `HTTP/1.1 ${incoming.statusCode} ${incoming.statusMessage}\r\n`;
      for (let i = 0; i < incoming.rawHeaders.length; i += 2)
        headers += incoming.rawHeaders[i] + ": " + incoming.rawHeaders[i + 1] + "\r\n";
      socket.write(headers + "\r\n");
      if (upstreamHead.length) socket.write(upstreamHead);
      if (head.length) tunnel.write(head);
      socket.on("error", () => tunnel.destroy());
      tunnel.on("error", () => socket.destroy());
      socket.on("close", () => tunnel.destroy());
      tunnel.on("close", () => socket.destroy());
      socket.pipe(tunnel).pipe(socket);
    });
    upstream.on("response", (incoming) => {
      socket.write(`HTTP/1.1 ${incoming.statusCode} ${incoming.statusMessage}\r\nConnection: close\r\n\r\n`);
      incoming.pipe(socket);
    });
    upstream.on("error", () => {
      if (switched) socket.destroy();
      else if (!socket.destroyed) socket.end("HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n");
    });
    socket.on("error", () => upstream.destroy());
    socket.on("close", () => upstream.destroy());
    upstream.end();
  });
  return server;
}

function port(value, name) {
  if (!/^\d+$/.test(String(value)) || Number(value) < 1 || Number(value) > 65535)
    throw new Error(`${name} must be a port between 1 and 65535`);
  return Number(value);
}

export async function runDev(env = process.env) {
  const host = env.DEV_HOST || "127.0.0.1";
  const publicPort = port(env.DEV_PORT || env.PORT || "3000", "DEV_PORT");
  const nextPort = port(env.NEXT_DEV_PORT || "3001", "NEXT_DEV_PORT");
  if (publicPort === nextPort) throw new Error("DEV_PORT and NEXT_DEV_PORT must differ");
  const server = createDevProxy({
    bridgeURL: env.BRIDGE_DEV_URL || "http://127.0.0.1:8080",
    nextURL: `http://127.0.0.1:${nextPort}`,
    loopbackOnly: ["localhost", "127.0.0.1", "::1"].includes(host),
  });
  const clients = new Set();
  server.on("connection", (socket) => {
    clients.add(socket);
    socket.on("close", () => clients.delete(socket));
  });
  await new Promise((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(publicPort, host, resolveListen);
  });
  const directory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const child = spawn(process.execPath, [
    resolve(directory, "node_modules/next/dist/bin/next"), "dev",
    "--hostname", "127.0.0.1", "--port", String(nextPort),
  ], { cwd: directory, stdio: "inherit", env: { ...env, NEXT_TELEMETRY_DISABLED: "1" } });
  process.stdout.write(`Development dashboard: http://${host}:${publicPort}\n`);
  let closing = false;
  let forcedStop;
  const close = (signal = "SIGTERM") => {
    if (closing) return;
    closing = true;
    server.close();
    for (const socket of clients) socket.destroy();
    if (child.exitCode === null && child.signalCode === null) {
      child.kill(signal);
      forcedStop = setTimeout(() => child.kill("SIGKILL"), 5_000);
      forcedStop.unref();
    }
  };
  process.once("SIGINT", () => close("SIGINT"));
  process.once("SIGTERM", () => close());
  child.once("error", () => {
    process.stderr.write("Unable to start Next.js development server. Run npm ci first.\n");
    process.exitCode = 1;
    close();
  });
  child.once("exit", (code) => {
    clearTimeout(forcedStop);
    if (!closing) {
      process.exitCode = code || 1;
      close();
    }
  });
  return { server, child, close };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    await runDev();
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  }
}
