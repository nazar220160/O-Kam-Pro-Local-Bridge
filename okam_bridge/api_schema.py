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
        "Create an in-memory account session",
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
        description="O-Kam account credentials are sent to vendor HTTPS services. Password is never persisted. Returns HttpOnly SameSite=Strict cookie and a Bearer session token for API clients. Protect both as secrets. If a bridge access token is configured, authenticate this request with Authorization: Bearer <bridge-access-token> (or Basic bridge:<token>); Compose web gateway supplies its private gateway header automatically. Sessions expire after 12 hours and are revoked on logout/restart.",
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
        "Start or reconnect selected LAN camera",
        body(
            {
                "ip": {
                    "type": ["string", "null"],
                    "description": "Optional private IPv4 address; if omitted use account LAN IP then UID discovery.",
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
        description="Asynchronous. Poll camera state until viewable=true or error. Multiple lenses share one physical connection. LAN/routed reachability is required; this API does not add cloud relay transport.",
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
            "description": "Independent local camera bridge. Camera/firmware support varies; account login and transport bootstrap use vendor services, video is LAN-only.",
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
        + """</pre><h2>Native ONVIF / RTSP</h2><p>plaintext_password configures the documented external-user credentials. Separate ONVIF/RTSP service switches are not verified. Refresh parameters and probe service ports; an open port is not protocol verification. Camera service passwords are different from bridge media credentials.</p><h2>Errors &amp; lifecycle</h2><p>400 invalid input or camera not streaming · 401 session required · 403 host/origin rejected · 404 unknown camera/route · 409 connection already in progress · 415 JSON required · 502 vendor service unavailable · 503 no video. POST JSON bodies are limited to 8192 bytes. Sessions expire after 12 hours; restart requires login again. Camera connections are demand-driven and reconnect after interruptions.</p></html>"""
    )
