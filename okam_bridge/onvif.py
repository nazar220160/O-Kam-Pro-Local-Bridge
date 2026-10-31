"""Small, read-only bridge ONVIF facade; not an ONVIF certified device.

Only bridge exports are addressed here. No native camera configuration is read or
changed. PTZ, events and completed recording search/replay are bridged through
explicit native controls and private server storage. Unsupported configuration
writes, absolute positioning and multicast RTP are not advertised. HTTP Basic is intended for a trusted LAN only.
"""

import base64
import hashlib
import hmac
import re
import secrets
import socket
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "tds": "http://www.onvif.org/ver10/device/wsdl",
    "trt": "http://www.onvif.org/ver10/media/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
    "a": "http://schemas.xmlsoap.org/ws/2004/08/addressing",
    "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    "dn": "http://www.onvif.org/ver10/network/wsdl",
    "wsse": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
    "tptz": "http://www.onvif.org/ver20/ptz/wsdl",
    "trc": "http://www.onvif.org/ver10/recording/wsdl",
    "tse": "http://www.onvif.org/ver10/search/wsdl",
    "trp": "http://www.onvif.org/ver10/replay/wsdl",
    "tev": "http://www.onvif.org/ver10/events/wsdl",
    "wsnt": "http://docs.oasis-open.org/wsn/b-2",
    "wsu": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd",
}
for _prefix, _uri in NS.items():
    ET.register_namespace(_prefix, _uri)
MAX_XML = 65536


def node(parent, name, text=None, **attrs):
    prefix, local = name.split(":")
    value = ET.SubElement(
        parent, "{" + NS[prefix] + "}" + local, {k: str(v) for k, v in attrs.items()}
    )
    if text is not None:
        value.text = str(text)
    return value


def parse_xml(data):
    # XML declarations with UTF-16 encodings cannot bypass this ASCII check.
    if len(data) > MAX_XML or b"<!" in data or b"\x00" in data:
        raise ValueError("Unsafe XML")
    return ET.fromstring(data)


def envelope():
    root = ET.Element("{" + NS["s"] + "}Envelope")
    return root, node(root, "s:Body")


def url(item, service):
    host = str(item["advertise_host"])
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return f"http://{host}:{item['onvif_port']}/onvif/{quote(item['export_id'],safe='')}/{service}_service"


def scopes(item):
    return [
        "onvif://www.onvif.org/type/video_encoder",
        "onvif://www.onvif.org/name/" + quote(str(item.get("name", "Bridge")), safe=""),
    ]


class ONVIFServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, registry):
        self.registry = registry
        self._secret = secrets.token_bytes(32)
        self._auth_lock = threading.Lock()
        self._replays = {}
        super().__init__(address, _Handler)

    def nonce(self):
        stamp = str(int(time.time()))
        return (
            stamp
            + ":"
            + hmac.new(self._secret, stamp.encode(), hashlib.sha256).hexdigest()
        )

    def valid_nonce(self, value):
        try:
            stamp, signature = value.split(":", 1)
            return 0 <= time.time() - int(stamp) <= 300 and hmac.compare_digest(
                signature,
                hmac.new(self._secret, stamp.encode(), hashlib.sha256).hexdigest(),
            )
        except (ValueError, TypeError):
            return False

    def remember(self, key, number=1):
        with self._auth_lock:
            now = time.time()
            self._replays = {k: v for k, v in self._replays.items() if v[1] > now}
            if key in self._replays and self._replays[key][0] >= number:
                return False
            if len(self._replays) >= 10000:
                return False
            self._replays[key] = (number, now + 300)
            return True


class _Handler(BaseHTTPRequestHandler):
    server_version = "BridgeONVIF/1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass

    def send(
        self,
        status,
        data=b"",
        kind="application/soap+xml; charset=utf-8",
        challenge=False,
    ):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.send_header("Cache-Control", "no-store")
        if challenge:
            self.send_header(
                "WWW-Authenticate",
                f'Digest realm="Bridge ONVIF", nonce="{self.server.nonce()}", algorithm=MD5, qop="auth"',
            )
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def fault(self, message, status=400, challenge=False):
        root, body = envelope()
        fault = node(body, "s:Fault")
        code = node(fault, "s:Code")
        node(code, "s:Value", "s:Sender")
        reason = node(fault, "s:Reason")
        text = node(reason, "s:Text", message)
        text.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
        self.send(
            status,
            ET.tostring(root, encoding="utf-8", xml_declaration=True),
            challenge=challenge,
        )

    def target(self):
        parts = urlsplit(self.path)
        match = re.fullmatch(
            r"/onvif/([A-Za-z0-9_-]+)/((?:device|media|ptz|events|recording|search|replay)_service|subscriptions/[A-Za-z0-9_-]+|snapshot\.jpg)",
            parts.path,
        )
        if not match:
            return None, None, parts
        return self.server.registry.get_export(match[1]), match[2], parts

    def authorized(self, item, root=None):
        username = str(item.get("username", ""))
        password = str(item.get("password", ""))
        if not username or not password:
            return False
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                return hmac.compare_digest(
                    base64.b64decode(header[6:], validate=True),
                    f"{username}:{password}".encode(),
                )
            except (ValueError, TypeError):
                return False
        if header.startswith("Digest "):
            fields = {
                m[0]: (m[1] if m[1] else m[2])
                for m in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))', header[7:])
            }
            try:
                if (
                    fields["username"] != username
                    or fields["realm"] != "Bridge ONVIF"
                    or fields["uri"] != self.path
                    or fields.get("qop") != "auth"
                    or fields.get("algorithm", "MD5").upper() != "MD5"
                    or not self.server.valid_nonce(fields["nonce"])
                ):
                    return False
                nc = int(fields["nc"], 16)
                if nc < 1 or len(fields["nc"]) != 8 or not fields["cnonce"]:
                    return False
                md5 = lambda v: hashlib.md5(v.encode()).hexdigest()
                expected = md5(
                    ":".join(
                        [
                            md5(f"{username}:Bridge ONVIF:{password}"),
                            fields["nonce"],
                            fields["nc"],
                            fields["cnonce"],
                            "auth",
                            md5(f"{self.command}:{self.path}"),
                        ]
                    )
                )
                return hmac.compare_digest(
                    expected, fields["response"]
                ) and self.server.remember(
                    (
                        "digest",
                        item["export_id"],
                        username,
                        fields["nonce"],
                        fields["cnonce"],
                    ),
                    nc,
                )
            except (KeyError, ValueError):
                return False
        if root is not None:
            token = root.find("./s:Header/wsse:Security/wsse:UsernameToken", NS)
            if token is None:
                return False
            try:
                if token.findtext("wsse:Username", namespaces=NS) != username:
                    return False
                pwd = token.find("wsse:Password", NS)
                if pwd is None or not pwd.get("Type", "").endswith("#PasswordDigest"):
                    return False
                created = token.findtext("wsu:Created", namespaces=NS)
                timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if (
                    timestamp.tzinfo is None
                    or abs((datetime.now(timezone.utc) - timestamp).total_seconds())
                    > 300
                ):
                    return False
                nonce = base64.b64decode(
                    token.findtext("wsse:Nonce", namespaces=NS), validate=True
                )
                expected = base64.b64encode(
                    hashlib.sha1(nonce + created.encode() + password.encode()).digest()
                ).decode()
                return hmac.compare_digest(
                    expected, pwd.text or ""
                ) and self.server.remember(
                    ("wsse", item["export_id"], username, nonce, created)
                )
            except (ValueError, TypeError, AttributeError):
                return False
        return False

    def do_GET(self):
        item, service, parts = self.target()
        if item is None:
            self.fault("Unknown export", 404)
            return
        if not self.authorized(item):
            self.fault("Authentication required", 401, True)
            return
        if service != "snapshot.jpg":
            self.fault("Unsupported resource", 404)
            return
        try:
            query = parse_qs(parts.query, strict_parsing=True)
            lens = int(query.get("lens", ["0"])[0])
            if not any(p["lens"] == lens for p in item["profiles"]):
                raise ValueError()
            data = self.server.registry.snapshot(item["export_id"], lens)
            if not isinstance(data, bytes) or not data:
                raise ValueError()
        except (ValueError, KeyError):
            self.fault("Invalid lens", 400)
            return
        except Exception:
            self.fault("Snapshot unavailable", 503)
            return
        self.send(200, data, "image/jpeg")

    def do_POST(self):
        item, service, parts = self.target()
        standard_entrypoint = parts.path == "/onvif/device_service"
        if standard_entrypoint:
            service = "device_service"
        if item is None and not standard_entrypoint:
            self.fault("Unknown export", 404)
            return
        if self.headers.get("Transfer-Encoding"):
            self.fault("Unsupported encoding")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.fault("Invalid length")
            return
        if size > MAX_XML:
            self.fault("Request too large", 413)
            return
        if size <= 0:
            self.fault("Empty request")
            return
        try:
            data = self.rfile.read(size)
            root = parse_xml(data)
            body = root.find("s:Body", NS)
            if (
                root.tag != "{" + NS["s"] + "}Envelope"
                or body is None
                or len(body) != 1
            ):
                raise ValueError()
            request = body[0]
            action = request.tag.split("}")[-1]
            prefix_map = {
                "device_service": "tds",
                "media_service": "trt",
                "ptz_service": "tptz",
                "events_service": "tev",
                "recording_service": "trc",
                "search_service": "tse",
                "replay_service": "trp",
            }
            subscription = service.startswith("subscriptions/")
            prefix = (
                "wsnt"
                if subscription and action in ("Renew", "Unsubscribe")
                else "tev" if subscription else prefix_map.get(service)
            )
            if not prefix:
                raise ValueError()
            expected = NS[prefix]
            if request.tag != "{" + expected + "}" + action:
                raise ValueError()
        except (ET.ParseError, ValueError):
            self.fault("Invalid XML")
            return
        clock_request = service == "device_service" and action == "GetSystemDateAndTime"
        if standard_entrypoint:
            # Host/port-only clients bootstrap at this standard path. The
            # publication password selects the camera; never pick the first
            # account's camera or expose its metadata without authentication.
            item = (
                {}
                if clock_request
                else next(
                    (
                        candidate
                        for candidate in self.server.registry.list_exports()
                        if self.authorized(candidate, root)
                    ),
                    None,
                )
            )
            if item is None:
                self.fault("Authentication required", 401, True)
                return
        elif not clock_request and not self.authorized(item, root):
            self.fault("Authentication required", 401, True)
            return
        try:
            root, body = envelope()
            prefix = prefix
            response = node(body, prefix + ":" + action + "Response")
            if service == "device_service":
                self.device(response, action, item)
            elif service == "media_service":
                self.media(response, action, item, request)
            elif service == "ptz_service":
                from .onvif_ptz import handle_ptz

                handle_ptz(response, action, item, request, self.server.registry)
            elif service in ("recording_service", "search_service", "replay_service"):
                from .onvif_archive import handle_archive

                handle_archive(
                    response, service, action, item, request, self.server.registry
                )
            elif service == "events_service" or subscription:
                from .onvif_events import handle_events

                handle_events(
                    response,
                    action,
                    item,
                    request,
                    self.server.registry,
                    service.split("/", 1)[1] if subscription else None,
                )
            else:
                raise ValueError("Unsupported service")
            self.send(200, ET.tostring(root, encoding="utf-8", xml_declaration=True))
        except (ValueError, KeyError, TypeError):
            self.fault("Unsupported action or invalid profile")

    def device(self, r, action, item):
        if action == "GetSystemDateAndTime":
            now = datetime.now(timezone.utc)
            date = node(r, "tds:SystemDateAndTime")
            node(date, "tt:DateTimeType", "NTP")
            node(date, "tt:DaylightSavings", "false")
            zone = node(date, "tt:TimeZone")
            node(zone, "tt:TZ", "UTC0")
            utc = node(date, "tt:UTCDateTime")
            t = node(utc, "tt:Time")
            d = node(utc, "tt:Date")
            for key, value in [
                ("Hour", now.hour),
                ("Minute", now.minute),
                ("Second", now.second),
            ]:
                node(t, "tt:" + key, value)
            for key, value in [
                ("Year", now.year),
                ("Month", now.month),
                ("Day", now.day),
            ]:
                node(d, "tt:" + key, value)
        elif action == "GetDeviceInformation":
            for key, value in [
                ("Manufacturer", "O-Kam Local Bridge"),
                ("Model", "Bridge export"),
                ("FirmwareVersion", "1"),
                ("SerialNumber", item["export_id"]),
                ("HardwareId", "bridge"),
            ]:
                node(r, "tds:" + key, value)
        elif action == "GetServices":
            services = [("device", "tds"), ("media", "trt")]
            if item.get("ptz"):
                services.append(("ptz", "tptz"))
            if item.get("events"):
                services.append(("events", "tev"))
            if item.get("recording"):
                services.extend(
                    [("recording", "trc"), ("search", "tse"), ("replay", "trp")]
                )
            for name, prefix in services:
                s = node(r, "tds:Service")
                node(s, "tds:Namespace", NS[prefix])
                node(s, "tds:XAddr", url(item, name))
                version = node(s, "tds:Version")
                node(version, "tt:Major", 2)
                node(version, "tt:Minor", 0)
        elif action == "GetCapabilities":
            caps = node(r, "tds:Capabilities")
            device = node(caps, "tt:Device")
            node(device, "tt:XAddr", url(item, "device"))
            media = node(caps, "tt:Media")
            node(media, "tt:XAddr", url(item, "media"))
            if item.get("ptz"):
                ptz = node(caps, "tt:PTZ")
                node(ptz, "tt:XAddr", url(item, "ptz"))
            if item.get("events"):
                events = node(caps, "tt:Events")
                node(events, "tt:XAddr", url(item, "events"))
                node(events, "tt:WSSubscriptionPolicySupport", "false")
                node(events, "tt:WSPullPointSupport", "true")
                node(
                    events, "tt:WSPausableSubscriptionManagerInterfaceSupport", "false"
                )
            if item.get("recording"):
                extension = node(caps, "tt:Extension")
                recording = node(extension, "tt:Recording")
                node(recording, "tt:XAddr", url(item, "recording"))
                node(recording, "tt:ReceiverSource", "false")
                node(recording, "tt:MediaProfileSource", "true")
                node(recording, "tt:DynamicRecordings", "false")
                node(recording, "tt:DynamicTracks", "false")
                node(recording, "tt:MaxStringLength", 256)
                search = node(extension, "tt:Search")
                node(search, "tt:XAddr", url(item, "search"))
                node(search, "tt:MetadataSearch", "false")
                replay = node(extension, "tt:Replay")
                node(replay, "tt:XAddr", url(item, "replay"))
            stream = node(media, "tt:StreamingCapabilities")
            node(stream, "tt:RTPMulticast", "false")
            node(stream, "tt:RTP_TCP", "true")
            node(stream, "tt:RTP_RTSP_TCP", "true")
            order = [
                "Analytics",
                "Device",
                "Events",
                "Imaging",
                "Media",
                "PTZ",
                "Extension",
            ]
            caps[:] = sorted(caps, key=lambda e: order.index(e.tag.rsplit("}", 1)[-1]))
            if item.get("recording"):
                extorder = [
                    "DeviceIO",
                    "Display",
                    "Recording",
                    "Search",
                    "Replay",
                    "Receiver",
                    "AnalyticsDevice",
                    "Extensions",
                ]
                extension[:] = sorted(
                    extension, key=lambda e: extorder.index(e.tag.rsplit("}", 1)[-1])
                )
        elif action == "GetScopes":
            for scope in scopes(item):
                s = node(r, "tds:Scopes")
                node(s, "tt:ScopeDef", "Fixed")
                node(s, "tt:ScopeItem", scope)
        elif action == "GetHostname":
            info = node(r, "tds:HostnameInformation")
            node(info, "tt:FromDHCP", "false")
            node(info, "tt:Name", item["advertise_host"])
        else:
            raise ValueError()

    def encoder(self, parent, name, p):
        c = node(parent, name, token=p["token"])
        node(c, "tt:Name", p["token"])
        node(c, "tt:UseCount", 1)
        node(c, "tt:Encoding", "H264")
        resolution = node(c, "tt:Resolution")
        node(resolution, "tt:Width", p["width"])
        node(resolution, "tt:Height", p["height"])
        node(c, "tt:Quality", 5)
        rate = node(c, "tt:RateControl")
        node(rate, "tt:FrameRateLimit", p["fps"])
        node(rate, "tt:EncodingInterval", 1)
        node(rate, "tt:BitrateLimit", 2048)
        h264 = node(c, "tt:H264")
        node(h264, "tt:GovLength", p["fps"])
        node(h264, "tt:H264Profile", "Main")
        multicast = node(c, "tt:Multicast")
        address = node(multicast, "tt:Address")
        node(address, "tt:Type", "IPv4")
        node(address, "tt:IPv4Address", "0.0.0.0")
        node(multicast, "tt:Port", 0)
        node(multicast, "tt:TTL", 1)
        node(multicast, "tt:AutoStart", "false")
        node(c, "tt:SessionTimeout", "PT60S")

    def profile(self, r, name, p, ptz=False):
        profile = node(r, name, token=p["token"], fixed="true")
        node(profile, "tt:Name", p["token"])
        source = node(profile, "tt:VideoSourceConfiguration", token=p["token"])
        node(source, "tt:Name", p["token"])
        node(source, "tt:UseCount", 1)
        node(source, "tt:SourceToken", p["token"])
        node(source, "tt:Bounds", x=0, y=0, width=p["width"], height=p["height"])
        self.encoder(profile, "tt:VideoEncoderConfiguration", p)
        if ptz:
            from .onvif_ptz import configuration

            configuration(profile, "tt:PTZConfiguration", p)

    def media(self, r, action, item, request):
        profiles = item["profiles"]
        if action == "GetProfiles":
            for p in profiles:
                self.profile(r, "trt:Profiles", p, item.get("ptz", False))
        elif action in ("GetProfile", "GetStreamUri", "GetSnapshotUri"):
            token = request.findtext("trt:ProfileToken", namespaces=NS)
            p = next((p for p in profiles if p["token"] == token), None)
            if p is None:
                raise ValueError()
            if action == "GetProfile":
                self.profile(r, "trt:Profile", p, item.get("ptz", False))
            else:
                uri = node(r, "trt:MediaUri")
                node(
                    uri,
                    "tt:Uri",
                    p["rtsp_uri" if action == "GetStreamUri" else "snapshot_uri"],
                )
                node(uri, "tt:InvalidAfterConnect", "false")
                node(uri, "tt:InvalidAfterReboot", "false")
                node(uri, "tt:Timeout", "PT60S")
        elif action == "GetVideoSources":
            for p in profiles:
                v = node(r, "trt:VideoSources", token=p["token"])
                node(v, "tt:Framerate", p["fps"])
                res = node(v, "tt:Resolution")
                node(res, "tt:Width", p["width"])
                node(res, "tt:Height", p["height"])
        elif action == "GetVideoEncoderConfigurations":
            for p in profiles:
                self.encoder(r, "trt:Configurations", p)
        elif action == "GetServiceCapabilities":
            c = node(
                r,
                "trt:Capabilities",
                SnapshotUri="true",
                Rotation="false",
                VideoSourceMode="false",
                OSD="false",
            )
            node(c, "trt:ProfileCapabilities", MaximumNumberOfProfiles=len(profiles))
            node(
                c,
                "trt:StreamingCapabilities",
                RTPMulticast="false",
                RTP_TCP="true",
                RTP_RTSP_TCP="true",
            )
        else:
            raise ValueError()


class DiscoveryService:
    """Best-effort IPv4 WS-Discovery responder; errors are available in .error."""

    def __init__(self, registry, port=3702):
        self.registry = registry
        self.port = port
        self.error = None
        self._socket = None
        self._thread = None
        self._stop = threading.Event()

    def build_response(self, data):
        try:
            root = parse_xml(data)
            probe = root.find("s:Body/d:Probe", NS)
            message = root.findtext("s:Header/a:MessageID", namespaces=NS)
            if probe is None or not message:
                return None
            types = probe.findtext("d:Types", default="", namespaces=NS).split()
            # Resolve QNames rather than accepting a spoofed prefix/local name.
            namespaces = dict(re.findall(rb'xmlns:([\w.-]+)=[\'"]([^\'"]+)[\'"]', data))
            for kind in types:
                prefix, local = kind.split(":", 1)
                if (
                    local != "NetworkVideoTransmitter"
                    or namespaces.get(prefix.encode()) != NS["dn"].encode()
                ):
                    return None
            if probe.find("d:Scopes", NS) is not None:
                return None  # no scope matching advertised
            items = self.registry.list_exports()
            if not items:
                return None
            response = ET.Element("{" + NS["s"] + "}Envelope", {"xmlns:dn": NS["dn"]})
            header = node(response, "s:Header")
            node(header, "a:MessageID", "urn:uuid:" + str(uuid.uuid4()))
            node(header, "a:RelatesTo", message)
            node(
                header,
                "a:To",
                "http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous",
            )
            node(header, "a:Action", NS["d"] + "/ProbeMatches")
            body = node(response, "s:Body")
            matches = node(body, "d:ProbeMatches")
            for item in items:
                match = node(matches, "d:ProbeMatch")
                endpoint = node(match, "a:EndpointReference")
                node(
                    endpoint,
                    "a:Address",
                    "urn:uuid:"
                    + str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL, "okam-bridge:" + item["export_id"]
                        )
                    ),
                )
                node(match, "d:Types", "dn:NetworkVideoTransmitter")
                node(match, "d:Scopes", " ".join(scopes(item)))
                node(match, "d:XAddrs", url(item, "device"))
                node(match, "d:MetadataVersion", 1)
            result = ET.tostring(response, encoding="utf-8", xml_declaration=True)
            return result if len(result) < 60000 else None
        except (ET.ParseError, ValueError, KeyError, TypeError):
            return None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.error = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.bind(("", self.port))
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_ADD_MEMBERSHIP,
                socket.inet_aton("239.255.255.250") + socket.inet_aton("0.0.0.0"),
            )
            sock.settimeout(0.5)
        except OSError as exc:
            self.error = str(exc)
            sock.close()
            return
        self._socket = sock
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="bridge-onvif-discovery"
        )
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, peer = self._socket.recvfrom(MAX_XML + 1)
                reply = self.build_response(data)
                if reply:
                    self._socket.sendto(reply, peer)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self.error = str(exc)
                break
            except Exception:
                self.error = "Discovery response unavailable"

    def close(self):
        self._stop.set()
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=2)
