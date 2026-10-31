"""OpenAPI contract and self-contained API reference; no external CDN scripts."""

import html
import json
from . import __version__

ACTIONS = {
    "query": {
        "section": [
            "status",
            "parameters",
            "video",
            "tracking",
            "zoom_tracking",
            "light",
            "indicator",
            "presets",
            "archive_dates",
            "recording",
            "sleep",
            "power",
        ]
    },
    "ptz": {
        "direction": ["up", "down", "left", "right"],
        "duration_ms": [80, 600],
        "speed": [1, 10],
        "lens": [0, 15],
    },
    "ptz_step": {"direction": ["up", "down", "left", "right"]},
    "ptz_stop": {},
    "calibrate": {},
    "cruise": {
        "mode": [
            "horizontal",
            "vertical",
            "presets",
            "stop_horizontal",
            "stop_vertical",
            "stop_presets",
        ]
    },
    "preset": {"operation": ["save", "goto", "delete"], "slot": [1, 5]},
    "guard": {"slot": [0, 5]},
    "volume": {"channel": ["microphone", "speaker"], "value": [0, 31]},
    "quality": {"quality": ["high", "medium", "low"]},
    "image": {
        "field": ["brightness", "contrast", "orientation", "night"],
        "value": [0, 255],
    },
    "zoom": {"scale": [1, 30]},
    "light": {"value": [0, 1]},
    "siren": {"value": [0, 1]},
    "tracking": {"value": [0, 1]},
    "zoom_tracking": {"value": [0, 1]},
    "indicator": {"value": [0, 1]},
    "osd": {"value": [0, 1]},
    "record_audio": {"value": [0, 1]},
    "camera_parameter": {"param": [0, 255], "value": [-10000, 10000]},
    "archive_files": {"date": "YYYYMMDD or firmware date directory"},
    "plaintext_password": {
        "enabled": "boolean",
        "password": "8–63 printable non-space ASCII characters; required when enabled",
    },
    "native": {
        "path": "Relative name.cgi?parameters; credentials and userId are inserted by bridge, cannot be overridden"
    },
}


def openapi():
    obj = {"type": "object", "additionalProperties": True}
    error = {
        "description": "Request failed; JSON error is a stable machine-readable code.",
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/Error"}}
        },
    }
    paths = {}

    def operation(
        path,
        method,
        summary,
        body=None,
        response=None,
        status="200",
        public=False,
        description="",
    ):
        params = []
        if "{camera_id}" in path:
            params.append(
                {
                    "name": "camera_id",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                    "description": "Opaque ID returned by the current account catalog.",
                }
            )
        if path.endswith(("mjpeg", "snapshot.jpg", "stream.h264")):
            params.append(
                {
                    "name": "lens",
                    "in": "query",
                    "schema": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 15,
                        "default": 0,
                    },
                }
            )
        op = {
            "summary": summary,
            "operationId": method
            + "_"
            + path.strip("/")
            .replace("/", "_")
            .replace("{", "")
            .replace("}", "")
            .replace(".", "_"),
            "tags": [
                (
                    "Media"
                    if params
                    and path.endswith(("mjpeg", "snapshot.jpg", "stream.h264"))
                    else (
                        "Cameras"
                        if "cameras" in path
                        else "Account" if "account" in path else "System"
                    )
                )
            ],
            "description": description,
            "parameters": params,
            "responses": {
                status: {
                    "description": "Success",
                    "content": {"application/json": {"schema": response or obj}},
                },
                **{str(c): error for c in (400, 401, 403, 404, 409, 415, 502)},
            },
            "security": (
                [] if public else [{"sessionBearer": []}, {"accountCookie": []}]
            ),
        }
        if body:
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": body}},
            }
        paths.setdefault(path, {})[method] = op
        return op

    def body(props, required=()):
        return {
            "type": "object",
            "properties": props,
            "required": list(required),
            "additionalProperties": False,
        }

    string = {"type": "string"}
    operation("/", "get", "API service information", public=True)
    operation(
        "/health",
        "get",
        "Liveness; does not test a camera or vendor cloud",
        public=True,
    )
    operation("/openapi.json", "get", "Download this OpenAPI 3.1 contract", public=True)
    operation("/docs/", "get", "Self-contained API reference", public=True)[
        "responses"
    ]["200"]["content"] = {"text/html": {"schema": string}}
    login = operation(
        "/api/account/login",
        "post",
        "Create or resume a persistent account session",
        body(
            {
                "username": {"type": "string", "maxLength": 320},
                "password": {"type": "string", "format": "password", "maxLength": 1024},
            },
            ["username", "password"],
        ),
        body(
            {
                "username": string,
                "camera_count": {"type": "integer"},
                "session_token": {"type": "string", "writeOnly": False},
                "expires_in": {"type": "integer"},
            }
        ),
        public=True,
        description="O-Kam account credentials are sent to vendor HTTPS services. The original password is not stored; the vendor protocol password digest and authorized session/transport credentials are saved in encrypted state for unattended recovery. Returns HttpOnly SameSite=Strict cookie and a Bearer session token for API clients. Protect both as secrets. If a bridge access token is configured, authenticate this request with Authorization: Bearer <bridge-access-token> (or Basic bridge:<token>); Compose web gateway supplies its private gateway header automatically. Sessions normally last one year; enabled publications retain their session. API restart restores sessions/cameras/publications. Explicit logout removes saved state.",
    )
    login["responses"]["200"]["headers"] = {
        "Set-Cookie": {
            "description": "HttpOnly account session cookie",
            "schema": string,
        }
    }
    operation(
        "/api/account",
        "get",
        "Current session account",
        response=body({"username": string, "camera_count": {"type": "integer"}}),
    )
    operation(
        "/api/account/logout",
        "post",
        "Revoke session, media credentials and close camera sessions",
        body({}),
    )
    operation(
        "/api/account/refresh",
        "post",
        "Refresh vendor account camera catalog",
        body({}),
        {"type": "array", "items": {"$ref": "#/components/schemas/Camera"}},
    )
    operation(
        "/api/account/player",
        "get",
        "Issue current temporary media-only Basic credentials",
        response=body({"username": {"const": "player"}, "password": string}),
        description="Only snapshot/MJPEG/H264 routes accept these credentials. Revoked on session logout/expiry; not the camera or account password.",
    )
    operation(
        "/api/cameras",
        "get",
        "List own and shared cameras; no automatic video connection",
        response={"type": "array", "items": {"$ref": "#/components/schemas/Camera"}},
    )
    operation(
        "/api/cameras/{camera_id}",
        "get",
        "Camera state and observed lenses",
        response={"$ref": "#/components/schemas/Camera"},
    )
    operation(
        "/api/cameras/{camera_id}/connect",
        "post",
        "Start or reconnect camera over LAN or O-Kam cloud relay",
        body(
            {
                "ip": {
                    "type": ["string", "null"],
                    "description": "Optional private IPv4 address; if omitted retain the saved LAN hint, then use account LAN IP or UID discovery. Not used for cloud routing.",
                },
                "connection_mode": {
                    "type": "string",
                    "enum": ["lan", "cloud"],
                    "default": "lan",
                    "description": "LAN uses private IP/discovery; cloud requires vendor relay rendezvous by camera UID and ignores the LAN address for routing. No automatic fallback.",
                },
                "substream": {"type": "integer", "enum": [0, 1, 2], "default": 1},
                "quality": {
                    "type": ["string", "null"],
                    "enum": [None, "high", "medium", "low"],
                    "description": "Native quality command: high=1, medium=2, low=4. Null leaves existing quality untouched.",
                },
            }
        ),
        status="202",
        description="Asynchronous. Poll camera state until viewable=true or error. Multiple lenses share one physical connection. LAN requires private network reachability; cloud uses vendor relay services and can require up to 100 seconds for the first frame. The chosen mode is persisted; existing publication URLs/passwords are retained across a source change. Cloud availability depends on vendor services, camera firmware and UDP reachability.",
    )
    operation(
        "/api/cameras/{camera_id}/stream",
        "post",
        "Apply native stream preferences; change quality without reconnecting",
        body(
            {
                "ip": {"type": ["string", "null"]},
                "connection_mode": {
                    "type": "string",
                    "enum": ["lan", "cloud"],
                    "description": "Omit to retain the current camera mode. Changing mode starts a new connection.",
                },
                "substream": {"type": "integer", "enum": [0, 1, 2], "default": 1},
                "quality": {
                    "type": ["string", "null"],
                    "enum": [None, "high", "medium", "low"],
                },
            }
        ),
        description="On an already connected camera with unchanged transport/IP/substream, applies native quality over the serialized existing session and persists it without replacing the camera or publication. A changed mode, LAN IP, substream or disconnected camera starts asynchronous connection instead. Cloud does not use IP for routing. Response mode is live or reconnect. Null clears the saved override without changing the current native quality. Native quality is shared by all lenses; a brief keyframe/encoder transition is possible.",
    )
    operation(
        "/api/cameras/{camera_id}/disconnect",
        "post",
        "Close selected camera session",
        body({}),
    )
    operation(
        "/api/cameras/{camera_id}/details",
        "get",
        "Redacted metadata groups and evidence for feature support",
        description="Query groups through control action query. Secret-looking fields and known native secrets are removed; missing flags mean unknown, not unsupported.",
    )
    operation(
        "/api/cameras/{camera_id}/services",
        "get",
        "Probe selected private camera native service ports",
        description="Fixed TCP ports 554,10554,10555,10556,10080; bounded parallel connection checks, no subnet scan. Requires known IP from connect or account. Open TCP port is not a verified RTSP/ONVIF login. Does not change camera settings.",
    )
    operation(
        "/api/cameras/{camera_id}/credentials",
        "post",
        "Explicitly reveal current account-issued native camera password",
        body({}),
        body({"username": string, "password": string}),
        description="Sensitive endpoint. Credentials are not included in metadata, exports or player URLs. Plaintext external-user credentials and account-issued native credentials can differ.",
    )
    operation(
        "/api/cameras/{camera_id}/control",
        "post",
        "Send a validated native camera action",
        {"$ref": "#/components/schemas/ControlRequest"},
        description="Requires a connected viewable camera. Commands execute serially in its existing native session. state=confirmed means result=0; sent means transport delivery only; rejected carries firmware result. Queue timeouts never execute later. Commands can change persistent settings; call only intentionally. Action definitions and parameter ranges are in x-actions. Image ranges: brightness/contrast 0..255, orientation 0..3, night 0..2. plaintext_password configures documented ExUserSwitch external access; it does not prove ONVIF/RTSP services exist. Verify get_params + independent service probe afterwards.",
    )
    operation(
        "/api/cameras/{camera_id}/export",
        "get",
        "Get bridge-owned RTSP/ONVIF publication status",
        description="Independent of native camera service settings. Status and URLs never include publication credentials. Requires a live MediaMTX service for availability.",
    )
    operation(
        "/api/cameras/{camera_id}/export",
        "post",
        "Enable or disable bridge-owned publication",
        body(
            {
                "enabled": {"type": "boolean"},
                "rtsp": {"type": "boolean", "default": True},
                "onvif": {"type": "boolean", "default": True},
                "advertise_host": {
                    "type": "string",
                    "description": "Optional server LAN IP or DNS name for NVR access; inferred from camera route when omitted.",
                },
            },
            ["enabled"],
        ),
        description="Requires connected camera. Publishes original H264 for observed lenses over RTSP/TCP; ONVIF exposes Device/Media, bounded PTZ when a motor is reported, PullPoint events from actual native observations, and Recording/Search/Replay for completed server/SD-cache clips. No native camera settings are changed. Active publication keeps the camera and owning account session alive; closing a browser tab does not stop it. Logout, explicit disconnect or disabling publication stops it. Server restart restores desired publication with the same paths and credentials. Enabling extends the account cookie lifetime while publication is active. No ONVIF certification, absolute positioning, reverse playback or events inferred from video are claimed.",
    )
    operation(
        "/api/cameras/{camera_id}/export/credentials",
        "post",
        "Reveal separate publication credentials",
        body({}),
        body({"username": {"const": "bridge"}, "password": string}),
        description="Explicit sensitive operation. These credentials only access the selected publication and differ from account, native-camera and temporary HTTP player credentials. URLs never embed passwords.",
    )
    operation(
        "/api/exports/auth",
        "post",
        "MediaMTX authorization callback",
        body(
            {
                "user": string,
                "password": string,
                "path": string,
                "protocol": {"const": "rtsp"},
                "action": {"enum": ["read", "publish"]},
            }
        ),
        public=True,
        description="Server-to-server callback. No account cookie is used; the submitted per-publication or publisher credentials are verified against the exact enabled path and action. Returns 200 on authorization, 401 otherwise. Does not create or change publications.",
    )
    operation(
        "/api/cameras/{camera_id}/archive",
        "get",
        "List completed server/SD-cache recordings, jobs and storage policy",
        description="Private persistent files are scoped to the current vendor account and camera. No file path or credentials are returned. Recording is off by default. A completed SD import appears as source=sd; cached files remain after logout but access requires the owning account.",
    )
    operation(
        "/api/cameras/{camera_id}/archive",
        "post",
        "Control server recording, import SD clip or start forward replay",
        body(
            {
                "action": {"type": "string", "enum": ["record", "sd_import", "replay"]},
                "enabled": {"type": "boolean"},
                "segment_seconds": {
                    "type": "integer",
                    "minimum": 5,
                    "maximum": 3600,
                    "default": 60,
                },
                "retention_days": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 365,
                    "default": 7,
                },
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1048576,
                    "maximum": 1099511627776,
                    "default": 10737418240,
                },
                "source_id": string,
                "duration": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 300,
                    "default": 60,
                },
                "token": string,
            },
            ["action"],
        ),
        description="Requires an enabled bridge publication. record explicitly starts/stops H264-copy server recording. sd_import uses only an identifier from sd_records, returns an asynchronous job, downloads at most 300 seconds and 500 MiB in a separate authenticated camera session; no SD files are deleted. replay returns RTSP URI for a completed private recording. Credentials are the current publication credentials. Server retention/quota policy is persisted per account/camera; SD cache shares quota but is not aged out using its original camera date. At most two SD download jobs run globally; 2 GiB free space required before import. File playback is forward at normal speed, not arbitrary reverse or clock-range seeking.",
    )
    operation(
        "/api/cameras/{camera_id}/archive/sd_dates",
        "get",
        "Read available SD recording dates",
        description="Read-only separate camera session; requires enabled publication and connected camera.",
    )
    op = operation(
        "/api/cameras/{camera_id}/archive/sd_records",
        "get",
        "Read SD timeline entries for a date",
        description="Returns actual timeline metadata and opaque source IDs; call sd_import explicitly to make a clip playable/searchable through the bridge. Does not download video automatically.",
    )
    op["parameters"].append(
        {
            "name": "date",
            "in": "query",
            "required": True,
            "schema": {"type": "string", "pattern": "^[0-9]{8}$"},
        }
    )
    op = operation(
        "/api/cameras/{camera_id}/archive/file/{recording_token}",
        "get",
        "Download authenticated Matroska recording with HTTP byte ranges",
        description="Completed private recording only; cookie/Bearer account authorization required. Optional Range: bytes=start-end returns 206. Not every browser supports Matroska inline; VLC or download can be used.",
    )
    op["parameters"].append(
        {
            "name": "recording_token",
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
    )
    op["responses"]["200"]["content"] = {
        "video/x-matroska": {"schema": {"type": "string", "format": "binary"}}
    }
    op["responses"]["206"] = {
        "description": "Requested byte range",
        "content": op["responses"]["200"]["content"],
    }
    for endpoint, mime in [
        ("snapshot.jpg", "image/jpeg"),
        ("mjpeg", "multipart/x-mixed-replace"),
        ("stream.h264", "video/h264"),
    ]:
        op = operation(
            "/api/cameras/{camera_id}/" + endpoint,
            "get",
            "Read " + endpoint,
            description="Requires connected camera. Basic player credentials also accepted. Original H264 is not transcoded; browser MJPEG is capped at 960px wide and 5fps. Streaming response stays open until disconnect. First frame unavailable returns 503.",
        )
        op["security"].append({"playerBasic": []})
        op["responses"]["200"]["content"] = {
            mime: {"schema": {"type": "string", "format": "binary"}}
        }
        op["responses"]["503"] = {
            "description": "Camera unavailable before the first frame",
            "content": {"text/plain": {"schema": {"type": "string"}}},
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "O-Kam Pro Local Bridge API",
            "version": __version__,
            "license": {"name": "MIT"},
            "description": "Independent camera bridge with LAN and optional O-Kam CS2 relay video. Camera/firmware support varies; account login, bootstrap and cloud mode use vendor services.",
        },
        "servers": [{"url": "/"}],
        "tags": [{"name": t} for t in ("System", "Account", "Cameras", "Media")],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "sessionBearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "session_token returned by account login",
                },
                "accountCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": "okam_account",
                },
                "playerBasic": {
                    "type": "http",
                    "scheme": "basic",
                    "description": "Media-only temporary player credentials",
                },
            },
            "schemas": {
                "Error": body({"error": string}, ["error"]),
                "Camera": {
                    "type": "object",
                    "properties": {
                        "id": string,
                        "name": string,
                        "state": string,
                        "viewable": {"type": "boolean"},
                        "ip": {"type": ["string", "null"]},
                        "connection_mode": {"type": "string", "enum": ["lan", "cloud"]},
                        "transport": {
                            "type": "object",
                            "properties": {
                                "mode": {"type": "string", "enum": ["lan", "cloud"]},
                                "path": {"type": ["string", "null"]},
                            },
                            "description": "Observed session path, e.g. relay, once negotiated. Empty before a camera instance exists.",
                        },
                        "lenses": {"type": "array", "items": {"type": "integer"}},
                        "lens_metadata": {"type": "array", "items": obj},
                        "metadata": obj,
                        "error": {"type": ["string", "null"]},
                    },
                    "additionalProperties": True,
                },
                "ControlRequest": body(
                    {"action": {"type": "string", "enum": list(ACTIONS)}, "args": obj},
                    ["action"],
                ),
            },
        },
        "x-actions": ACTIONS,
    }


def docs_html():
    spec = openapi()
    rows = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            schema = (
                op.get("requestBody", {})
                .get("content", {})
                .get("application/json", {})
                .get("schema")
            )
            details = (
                html.escape(json.dumps(schema, ensure_ascii=False, indent=2))
                if schema
                else "No JSON body."
            )
            rows.append(
                f'<details><summary><b>{method.upper()}</b> <code>{html.escape(path)}</code> — {html.escape(op["summary"])}</summary><p>{html.escape(op["description"])}</p><pre>{details}</pre></details>'
            )
    actions = html.escape(json.dumps(ACTIONS, ensure_ascii=False, indent=2))
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>O-Kam Bridge · API reference</title><style>body{max-width:1060px;margin:50px auto;padding:0 24px;background:#10151d;color:#e6edf5;font:15px/1.65 system-ui}a{color:#b4ef79}h1{font-size:40px;letter-spacing:-1px}p{color:#b1bfce}details{border:1px solid #303a46;border-radius:10px;margin:12px 0;padding:15px}summary{cursor:pointer}b{color:#b4ef79}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#19212c;padding:18px;border-radius:8px}code{color:#d9e6f4}nav{display:flex;gap:22px}</style><nav><a href="/">Home</a><a href="/openapi.json">OpenAPI JSON</a><a href="https://github.com/nazar220160/O-Kam-Pro-Local-Bridge">GitHub</a></nav><h1>Your cameras. Your API.</h1><p>O-Kam Pro Local Bridge · API v"""
        + __version__
        + """</p><h2>Authentication</h2><p>POST /api/account/login with your account username and password. The response sets an HttpOnly cookie and returns session_token. API clients send Authorization: Bearer &lt;session_token&gt;. Keep tokens private. Logout revokes the whole session. If accessing a protected bridge directly, supply its access token on login; the bundled web gateway handles this privately.</p><pre>curl -c session.cookies -H 'Content-Type: application/json' \\\n  -d '{"username":"YOUR_ACCOUNT","password":"YOUR_PASSWORD"}' \\\n  http://localhost:8080/api/account/login
curl -b session.cookies http://localhost:8080/api/cameras</pre><h2>Endpoints</h2>"""
        + "".join(rows)
        + """<h2>Native control actions</h2><p>Send {"action":"ptz_step","args":{"direction":"left"}} to /api/cameras/{camera_id}/control. Firmware may reject actions; transport delivery does not imply successful execution.</p><pre>"""
        + actions
        + """</pre><h2>Native ONVIF / RTSP</h2><p>plaintext_password configures the documented external-user credentials. Separate ONVIF/RTSP service switches are not verified. Refresh parameters and probe service ports; an open port is not protocol verification. Camera service passwords are different from bridge media credentials.</p><h2>Bridge-owned ONVIF / RTSP</h2><p>Enable /api/cameras/{camera_id}/export to publish the existing camera session independently of native ONVIF/RTSP support. Separate credentials are revealed only through POST export/credentials. RTSP/TCP is served by MediaMTX; the ONVIF Device/Media facade exposes observed lens profiles and authenticated snapshots. Native pan/tilt/presets, actual polled alarm events, completed recording search and forward replay are provided through the ONVIF facade. Full ONVIF certification, absolute positioning, reverse playback and arbitrary clock seeking are not claimed. Closing a tab keeps publication alive; logout or disconnect revokes it. Session and desired publication state persist across restart; explicit logout removes them.</p><h2>Errors &amp; lifecycle</h2><p>400 invalid input or camera not streaming · 401 session required · 403 host/origin rejected · 404 unknown camera/route · 409 connection already in progress · 415 JSON required · 502 vendor service unavailable · 503 no video. POST JSON bodies are limited to 8192 bytes. Sessions normally last one year unless held by a desired publication; restart restores login and connections. Camera connections are demand-driven and reconnect after interruptions.</p></html>"""
    )
