import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import { once } from "node:events";
import test from "node:test";
import { createDevProxy } from "./dev.mjs";

async function listen(server) {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return `http://127.0.0.1:${server.address().port}`;
}

async function fixture(t) {
  const gatewayRequests = [], nextRequests = [], sockets = new Set();
  const gateway = http.createServer((request, response) => {
    let body = "";
    request.on("data", (data) => { body += data; });
    request.on("end", () => {
      gatewayRequests.push({ url: request.url, headers: request.headers, body });
      response.writeHead(200, {
        "Content-Type": "application/json", "Cache-Control": "no-store",
        "Set-Cookie": ["okam_account=fixture; Path=/; HttpOnly; SameSite=Strict", "second=fixture; Path=/; HttpOnly"],
      });
      response.end(JSON.stringify({ source: "gateway" }));
    });
  });
  const next = http.createServer((request, response) => {
    nextRequests.push({ url: request.url, headers: request.headers });
    response.end("next");
  });
  next.on("upgrade", (request, socket) => {
    nextRequests.push({ url: request.url, headers: request.headers, upgrade: true });
    socket.write("HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\nready");
    socket.on("data", (bytes) => { if (bytes.toString() === "PING") socket.write("PONG"); });
  });
  for (const server of [gateway, next]) server.on("connection", (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  const gatewayURL = await listen(gateway), nextURL = await listen(next);
  const proxy = createDevProxy({ bridgeURL: gatewayURL, nextURL });
  proxy.on("connection", (socket) => {
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
  });
  const proxyURL = await listen(proxy);
  t.after(async () => {
    for (const socket of sockets) socket.destroy();
    await Promise.all([proxy, gateway, next].map((server) => new Promise((resolve) => {
      if (!server.listening) return resolve();
      server.close(resolve);
      server.closeAllConnections();
    })));
  });
  return { gateway, next, proxy, gatewayURL, nextURL, proxyURL, gatewayRequests, nextRequests };
}

function request(base, path, { method = "GET", headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(base);
    const outgoing = http.request({ hostname: url.hostname, port: url.port, path, method, headers }, (incoming) => {
      let data = "";
      incoming.on("data", (chunk) => { data += chunk; });
      incoming.on("end", () => resolve({ status: incoming.statusCode, headers: incoming.headers, body: data }));
    });
    outgoing.on("error", reject);
    outgoing.end(body);
  });
}

test("API calls retain body, cookies and multiple HttpOnly cookies while adapting upstream origin", async (t) => {
  const f = await fixture(t), origin = f.proxyURL;
  const result = await request(origin, "/api/account/login", {
    method: "POST", headers: { Origin: origin, Cookie: "okam_account=fixture", "Content-Type": "application/json" },
    body: '{"username":"fixture"}',
  });
  assert.equal(result.status, 200);
  assert.equal(f.gatewayRequests[0].headers.origin, f.gatewayURL);
  assert.equal(f.gatewayRequests[0].headers.host, new URL(f.gatewayURL).host);
  assert.equal(f.gatewayRequests[0].headers.cookie, "okam_account=fixture");
  assert.equal(f.gatewayRequests[0].body, '{"username":"fixture"}');
  assert.equal(result.headers["set-cookie"].length, 2);
  assert.match(result.headers["set-cookie"][0], /HttpOnly; SameSite=Strict/);
  assert.equal(f.nextRequests.length, 0);
});

test("only the fixed bridge paths reach the gateway", async (t) => {
  const f = await fixture(t);
  for (const path of ["/api/cameras?lens=1", "/health", "/docs", "/docs/", "/openapi.json"])
    assert.equal((await request(f.proxyURL, path)).body, '{"source":"gateway"}');
  for (const path of ["/", "/_next/static/chunk.js", "/api-other", "/healthz", "/docs-other"])
    assert.equal((await request(f.proxyURL, path)).body, "next");
});

test("foreign origins, rebinding hosts and absolute-form request targets cannot bypass the proxy boundary", async (t) => {
  const f = await fixture(t);
  assert.equal((await request(f.proxyURL, "/api/account/login", { method: "POST", headers: { Origin: "https://foreign.example" } })).status, 403);
  assert.equal((await request(f.proxyURL, "/api/cameras", { headers: { Host: "foreign.example" } })).status, 403);
  assert.equal((await request(f.proxyURL, "http://foreign.example/api/cameras")).status, 400);
  assert.equal(f.gatewayRequests.length, 0);
  assert.equal(f.nextRequests.length, 0);
});

test("an unavailable gateway returns a bounded friendly error without disclosing request credentials", async (t) => {
  const f = await fixture(t);
  await new Promise((resolve) => f.gateway.close(resolve));
  const response = await request(f.proxyURL, "/health", { headers: { Cookie: "secret-fixture-cookie" } });
  assert.equal(response.status, 502);
  assert.match(response.body, /BRIDGE_DEV_URL/);
  assert.doesNotMatch(response.body, /secret-fixture-cookie/);
});

test("streaming responses arrive before the upstream finishes", { timeout: 5_000 }, async (t) => {
  const f = await fixture(t);
  f.gateway.removeAllListeners("request");
  let finish;
  f.gateway.on("request", (_request, response) => {
    response.writeHead(200, { "Content-Type": "multipart/x-mixed-replace; boundary=frame" });
    response.write("first-frame");
    finish = () => response.end("last-frame");
  });
  const outgoing = http.get(f.proxyURL + "/api/cameras/fixture/mjpeg");
  const [incoming] = await once(outgoing, "response");
  const [first] = await once(incoming, "data");
  assert.equal(first.toString(), "first-frame");
  const ended = once(incoming, "end");
  incoming.resume();
  finish();
  await ended;
});

test("Next.js HMR upgrades are tunneled bidirectionally", { timeout: 5_000 }, async (t) => {
  const f = await fixture(t), url = new URL(f.proxyURL);
  const socket = net.connect({ host: url.hostname, port: Number(url.port) });
  t.after(() => socket.destroy());
  await once(socket, "connect");
  let received = "";
  const ready = new Promise((resolve) => socket.on("data", (bytes) => {
    received += bytes.toString();
    if (received.includes("ready")) resolve();
  }));
  socket.write(`GET /_next/webpack-hmr HTTP/1.1\r\nHost: ${url.host}\r\nOrigin: ${url.origin}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n`);
  await ready;
  assert.match(received, /101 Switching Protocols/);
  assert.equal(f.nextRequests.at(-1).headers.origin, f.nextURL);
  const pong = new Promise((resolve) => socket.on("data", (bytes) => {
    if (bytes.toString().includes("PONG")) resolve();
  }));
  socket.write("PING");
  await pong;
  socket.destroy();
});

test("upgrades cannot tunnel into the camera API", async (t) => {
  const f = await fixture(t);
  const response = await request(f.proxyURL, "/api/cameras", {
    headers: { Connection: "Upgrade", Upgrade: "websocket", Origin: f.proxyURL },
  });
  assert.equal(response.status, 403);
  assert.equal(f.gatewayRequests.length, 0);
  assert.equal(f.nextRequests.length, 0);
});

test("upstream configuration rejects credential-bearing URLs and non-HTTP destinations", () => {
  for (const value of ["file:///private", "http://user:password@host", "http://host/path", "http://host/?secret=value"])
    assert.throws(() => createDevProxy({ bridgeURL: value, nextURL: "http://127.0.0.1:3001" }));
});
