"""Read-only archive discovery and forward replay for completed playable clips.

Field order follows ONVIF recording/search/replay WSDL and ver10/schema XSD.
No recording jobs, camera SD controls, reverse playback or RTSP seeking are implied.
"""

from datetime import datetime, timezone
import math
import re
import secrets
import threading
import time
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

NAMESPACES = {
    "trc": "http://www.onvif.org/ver10/recording/wsdl",
    "tse": "http://www.onvif.org/ver10/search/wsdl",
    "trp": "http://www.onvif.org/ver10/replay/wsdl",
    "tt": "http://www.onvif.org/ver10/schema",
}
for _prefix, _namespace in NAMESPACES.items():
    ET.register_namespace(_prefix, _namespace)


def _node(parent, name, text=None, **attrs):
    prefix, local = name.split(":")
    child = ET.SubElement(parent, "{" + NAMESPACES[prefix] + "}" + local, attrs)
    if text is not None:
        child.text = str(text)
    return child


def _text(parent, local, default=None):
    for element in parent.iter():
        if element.tag.split("}")[-1] == local:
            return element.text if element.text is not None else default
    return default


def _utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _ttl(text):
    if text is None:
        raise ValueError("KeepAliveTime is required")
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", text)
    if not match or not any(match.groups()):
        raise ValueError("Invalid KeepAliveTime")
    h, m, s = match.groups()
    value = int(h or 0) * 3600 + int(m or 0) * 60 + float(s or 0)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Invalid KeepAliveTime")
    return min(value, 300)


class ArchiveSearch:
    """Bounded, export-scoped snapshot search sessions with idle expiration."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = {}

    def _prune(self):
        now = time.monotonic()
        for token in list(self._sessions):
            if self._sessions[token]["expires"] <= now:
                del self._sessions[token]

    def _get(self, export_id, token):
        self._prune()
        session = self._sessions.get(token)
        if session is None or session["export_id"] != export_id:
            raise ValueError("Unknown or expired search token")
        session["expires"] = time.monotonic() + session["ttl"]
        return session

    def create(self, export_id, records, ttl=300, max_matches=None):
        ttl = float(ttl)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("Invalid search TTL")
        ttl = min(ttl, 300)
        limit = 4096 if max_matches is None else min(int(max_matches), 4096)
        if limit <= 0:
            raise ValueError("MaxMatches must be positive")
        with self._lock:
            self._prune()
            if (
                len(self._sessions) >= 512
                or sum(x["export_id"] == export_id for x in self._sessions.values())
                >= 32
            ):
                raise ValueError("Search session limit reached")
            token = secrets.token_urlsafe(24)
            snapshot = [dict(row) for row in records[:limit]]
            self._sessions[token] = dict(
                export_id=export_id,
                records=snapshot,
                cursor=0,
                ttl=ttl,
                expires=time.monotonic() + ttl,
                endpoint=max((r["end"] for r in snapshot), default=_utc()),
            )
            return token

    def results(self, export_id, token, limit=100, valid_tokens=None):
        limit = min(int(limit), 100)
        if limit <= 0:
            raise ValueError("MaxResults must be positive")
        with self._lock:
            session = self._get(export_id, token)
            result = []
            while session["cursor"] < len(session["records"]) and len(result) < limit:
                row = session["records"][session["cursor"]]
                session["cursor"] += 1
                if valid_tokens is None or row["token"] in valid_tokens:
                    result.append(dict(row))
            return result

    def state(self, export_id, token):
        with self._lock:
            self._get(export_id, token)
            return "Completed"

    def end(self, export_id, token):
        with self._lock:
            endpoint = self._get(export_id, token)["endpoint"]
            del self._sessions[token]
            return endpoint

    def drop(self, export_id):
        with self._lock:
            for token in list(self._sessions):
                if self._sessions[token]["export_id"] == export_id:
                    del self._sessions[token]


def _source(parent, row, item):
    source = _node(parent, "tt:Source")
    source_id = (
        "urn:okam-bridge:"
        + quote(str(item["export_id"]), safe="")
        + ":lens:"
        + str(row["lens"])
    )
    _node(source, "tt:SourceId", source_id)
    _node(source, "tt:Name", item.get("name", item["export_id"]))
    _node(source, "tt:Location", item.get("location", ""))
    _node(source, "tt:Description", f"{row['source']} recording, lens {row['lens']}")
    _node(source, "tt:Address", source_id)


def _configuration(parent, row, item):
    _source(parent, row, item)
    _node(parent, "tt:Content", f"Video clip, lens {row['lens']}")
    _node(parent, "tt:MaximumRetentionTime", "PT0S")


def _track(parent, row):
    _node(parent, "tt:TrackType", "Video")
    _node(parent, "tt:Description", f"Video lens {row['lens']}")


def _information(parent, row, item):
    _node(parent, "tt:RecordingToken", row["token"])
    _source(parent, row, item)
    _node(parent, "tt:EarliestRecording", row["start"])
    _node(parent, "tt:LatestRecording", row["end"])
    _node(parent, "tt:Content", f"Video clip, lens {row['lens']}")
    track = _node(parent, "tt:Track")
    _node(track, "tt:TrackToken", "video")
    _track(track, row)
    _node(track, "tt:DataFrom", row["start"])
    _node(track, "tt:DataTo", row["end"])
    _node(parent, "tt:RecordingStatus", "Stopped")


def _record(records, token):
    for row in records:
        if row["token"] == token:
            return row
    raise ValueError("Unknown recording token")


def handle_archive(response, service, action, item, request, registry):
    """Mutate an authenticated SOAP response; unsupported operations raise ValueError."""
    service = service.removesuffix("_service")
    prefix = {"recording": "trc", "search": "tse", "replay": "trp"}.get(service)
    if prefix is None:
        raise ValueError("Unknown archive service")
    export_id = item["export_id"]
    if action == "GetServiceCapabilities":
        if service == "recording":
            _node(
                response,
                "trc:Capabilities",
                DynamicRecordings="false",
                DynamicTracks="false",
                MetadataRecording="false",
                Options="false",
                MaxRecordingJobs="0",
            )
        elif service == "search":
            _node(
                response,
                "tse:Capabilities",
                MetadataSearch="false",
                GeneralStartEvents="false",
            )
        else:
            _node(
                response,
                "trp:Capabilities",
                ReversePlayback="false",
                RTP_RTSP_TCP="true",
            )
        return
    if service == "replay":
        if action != "GetReplayUri":
            raise ValueError("Replay configuration and seeking are unsupported")
        if (
            _text(request, "Stream") != "RTP-Unicast"
            or _text(request, "Protocol") != "RTSP"
        ):
            raise ValueError("Only RTP-Unicast over RTSP is supported")
        if any(element.tag.split("}")[-1] == "Tunnel" for element in request.iter()):
            raise ValueError("Tunneled replay is unsupported")
        token = _text(request, "RecordingToken")
        _record(registry.archive_records(export_id), token)
        uri = registry.archive_replay(export_id, token)
        parsed = urlsplit(uri or "")
        if (
            parsed.scheme != "rtsp"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Replay URI unavailable")
        _node(response, "trp:Uri", uri)
        return
    if service == "search" and action in ("GetSearchState", "EndSearch"):
        token = _text(request, "SearchToken")
        if action == "GetSearchState":
            _node(response, "tse:State", registry.searches.state(export_id, token))
        else:
            _node(response, "tse:Endpoint", registry.searches.end(export_id, token))
        return
    records = registry.archive_records(export_id)
    if action == "GetRecordingInformation" and service in ("recording", "search"):
        row = _record(records, _text(request, "RecordingToken"))
        _information(_node(response, prefix + ":RecordingInformation"), row, item)
    elif service == "recording" and action == "GetRecordings":
        for row in records:
            result = _node(response, "trc:RecordingItem")
            _node(result, "tt:RecordingToken", row["token"])
            _configuration(_node(result, "tt:Configuration"), row, item)
            track = _node(_node(result, "tt:Tracks"), "tt:Track")
            _node(track, "tt:TrackToken", "video")
            _track(_node(track, "tt:Configuration"), row)
    elif service == "recording" and action in (
        "GetRecordingConfiguration",
        "GetTrackConfiguration",
    ):
        row = _record(records, _text(request, "RecordingToken"))
        if action == "GetRecordingConfiguration":
            _configuration(_node(response, "trc:RecordingConfiguration"), row, item)
        else:
            if _text(request, "TrackToken") != "video":
                raise ValueError("Unknown track token")
            _track(_node(response, "trc:TrackConfiguration"), row)
    elif service == "search" and action == "GetRecordingSummary":
        summary = _node(response, "tse:Summary")
        # Empty archive uses the epoch as an empty interval, never a clip observation.
        _node(
            summary,
            "tt:DataFrom",
            min((r["start"] for r in records), default="1970-01-01T00:00:00Z"),
        )
        _node(
            summary,
            "tt:DataUntil",
            max((r["end"] for r in records), default="1970-01-01T00:00:00Z"),
        )
        _node(summary, "tt:NumberRecordings", len(records))
    elif service == "search" and action == "FindRecordings":
        scope = next((e for e in request if e.tag.split("}")[-1] == "Scope"), None)
        if scope is None:
            raise ValueError("Search Scope is required")
        allowed = {"IncludedRecordings", "RecordingTokenInclude"}
        if any(e.tag.split("}")[-1] not in allowed for e in scope):
            raise ValueError("Unsupported recording search scope")
        include = {e.text for e in scope}
        if include:
            records = [r for r in records if r["token"] in include]
        token = registry.searches.create(
            export_id,
            records,
            _ttl(_text(request, "KeepAliveTime")),
            _text(request, "MaxMatches"),
        )
        _node(response, "tse:SearchToken", token)
    elif service == "search" and action == "GetRecordingSearchResults":
        token = _text(request, "SearchToken")
        rows = registry.searches.results(
            export_id,
            token,
            int(_text(request, "MaxResults", "100")),
            {r["token"] for r in records},
        )
        results = _node(response, "tse:ResultList")
        _node(results, "tt:SearchState", "Completed")
        for row in rows:
            _information(_node(results, "tt:RecordingInformation"), row, item)
    else:
        raise ValueError("Unsupported read-only archive operation")
