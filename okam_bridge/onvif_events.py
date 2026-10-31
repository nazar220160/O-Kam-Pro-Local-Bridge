"""Bounded ONVIF pull-point subscriptions for actual bridge alarm observations."""

from collections import deque
from datetime import datetime, timedelta, timezone
import math
import re
import secrets
import threading
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET

NAMESPACES = {
    "tev": "http://www.onvif.org/ver10/events/wsdl",
    "wsnt": "http://docs.oasis-open.org/wsn/b-2",
    "wstop": "http://docs.oasis-open.org/wsn/t-1",
    "tns1": "http://www.onvif.org/ver10/topics",
    "wsa": "http://www.w3.org/2005/08/addressing",
    "tt": "http://www.onvif.org/ver10/schema",
}
for _prefix, _uri in NAMESPACES.items():
    ET.register_namespace(_prefix, _uri)
DIALECT = "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet"
TOPICS = ("tns1:VideoSource/MotionAlarm", "tns1:Device/Trigger/Alarm")


def _node(parent, name, text=None, **attrs):
    prefix, local = name.split(":")
    result = ET.SubElement(
        parent,
        "{" + NAMESPACES[prefix] + "}" + local,
        {k: str(v) for k, v in attrs.items()},
    )
    if text is not None:
        result.text = str(text)
    return result


def _utc(value=None):
    return (
        (value or datetime.now(timezone.utc))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _seconds(value, default, maximum):
    if value is None:
        return default
    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value.strip()
    )
    if not match or not any(match.groups()):
        raise ValueError("Only positive ISO 8601 durations are supported")
    hours, minutes, seconds = match.groups()
    duration = int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)
    if duration < 0:
        raise ValueError("Invalid duration")
    return min(duration, maximum)


class EventBroker:
    """Subscriptions are scoped to exports and expire using a monotonic clock."""

    def __init__(self):
        self._condition = threading.Condition()
        self._exports = {}
        self._subscriptions = {}
        self._sequence = 0

    def _prune(self):
        now = time.monotonic()
        for key in list(self._subscriptions):
            if self._subscriptions[key]["deadline"] <= now:
                del self._subscriptions[key]

    def _subscription(self, export_id, subscription_id):
        self._prune()
        sub = self._subscriptions.get(subscription_id)
        if sub is None or sub["export_id"] != export_id:
            raise ValueError("Unknown or expired subscription")
        return sub

    def publish(self, export_id, topic, source, data):
        if topic not in TOPICS:
            raise ValueError("Unsupported event topic")
        # Copy observations: callers cannot mutate queued alarm state later.
        source, data = dict(source), dict(data)
        if (
            len(source) > 32
            or len(data) > 32
            or any(
                len(str(k)) > 256 or len(str(v)) > 4096
                for mapping in (source, data)
                for k, v in mapping.items()
            )
        ):
            raise ValueError("Event observation exceeds limits")
        with self._condition:
            self._prune()
            state = self._exports.setdefault(
                export_id, {"events": deque(maxlen=256), "last": {}}
            )
            self._sequence += 1
            event = dict(
                sequence=self._sequence,
                utc=_utc(),
                topic=topic,
                source=source,
                data=data,
                operation="Changed",
            )
            state["events"].append(event)
            key = (topic, tuple(sorted((str(k), str(v)) for k, v in source.items())))
            if key not in state["last"] and len(state["last"]) >= 256:
                del state["last"][next(iter(state["last"]))]
            state["last"][key] = event
            self._condition.notify_all()
            return dict(event, source=dict(source), data=dict(data))

    def subscribe(self, export_id, ttl=60, topics=None):
        ttl = float(ttl)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("TTL must be positive and finite")
        ttl = min(ttl, 3600)
        if topics is not None:
            topics = frozenset(topics)
            if not topics or not topics.issubset(TOPICS):
                raise ValueError("Unsupported topic filter")
        with self._condition:
            self._prune()
            if (
                len(self._subscriptions) >= 512
                or sum(
                    s["export_id"] == export_id for s in self._subscriptions.values()
                )
                >= 32
            ):
                raise ValueError("Subscription limit reached")
            key = secrets.token_urlsafe(24)
            self._subscriptions[key] = dict(
                export_id=export_id,
                deadline=time.monotonic() + ttl,
                expiration=datetime.now(timezone.utc) + timedelta(seconds=ttl),
                cursor=self._sequence,
                topics=topics,
                pending=deque(maxlen=256),
            )
            self._synchronize(self._subscriptions[key])
            return key

    def _synchronize(self, sub):
        sub["pending"].clear()
        for event in self._exports.get(sub["export_id"], {}).get("last", {}).values():
            if sub["topics"] is None or event["topic"] in sub["topics"]:
                sub["pending"].append(dict(event, operation="Initialized", utc=_utc()))
        sub["cursor"] = self._sequence

    def synchronize(self, export_id, subscription_id):
        with self._condition:
            self._synchronize(self._subscription(export_id, subscription_id))
            self._condition.notify_all()

    def termination(self, export_id, subscription_id):
        with self._condition:
            return self._subscription(export_id, subscription_id)["expiration"]

    def renew(self, export_id, subscription_id, ttl=60):
        ttl = float(ttl)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("TTL must be positive and finite")
        ttl = min(ttl, 3600)
        with self._condition:
            sub = self._subscription(export_id, subscription_id)
            sub.update(
                deadline=time.monotonic() + ttl,
                expiration=datetime.now(timezone.utc) + timedelta(seconds=ttl),
            )
            self._condition.notify_all()
            return sub["expiration"]

    def unsubscribe(self, export_id, subscription_id):
        with self._condition:
            self._subscription(export_id, subscription_id)
            del self._subscriptions[subscription_id]
            self._condition.notify_all()

    def drop(self, export_id):
        with self._condition:
            self._exports.pop(export_id, None)
            for key in list(self._subscriptions):
                if self._subscriptions[key]["export_id"] == export_id:
                    del self._subscriptions[key]
            self._condition.notify_all()

    def pull(self, export_id, subscription_id, timeout=0, limit=100):
        timeout = max(0, min(float(timeout), 30))
        limit = max(1, min(int(limit), 100))
        end = time.monotonic() + timeout
        with self._condition:
            while True:
                sub = self._subscription(export_id, subscription_id)
                events = []
                while sub["pending"] and len(events) < limit:
                    events.append(sub["pending"].popleft())
                for event in self._exports.get(export_id, {}).get("events", ()):
                    if len(events) >= limit:
                        break
                    if event["sequence"] > sub["cursor"]:
                        sub["cursor"] = event["sequence"]
                        if sub["topics"] is None or event["topic"] in sub["topics"]:
                            events.append(event)
                if events:
                    return [
                        dict(e, source=dict(e["source"]), data=dict(e["data"]))
                        for e in events
                    ]
                remaining = min(end, sub["deadline"]) - time.monotonic()
                if remaining <= 0:
                    return []
                self._condition.wait(remaining)


def _find(request, local):
    return next(
        (element for element in request.iter() if element.tag.split("}")[-1] == local),
        None,
    )


def _text(request, local):
    element = _find(request, local)
    return element.text if element is not None else None


def _filters(request):
    filt = _find(request, "Filter")
    if filt is None:
        return None
    if (
        len(filt) != 1
        or filt[0].tag != "{" + NAMESPACES["wsnt"] + "}TopicExpression"
        or filt[0].get("Dialect") != DIALECT
    ):
        raise ValueError("Unsupported event filter")
    topics = {part.strip() for part in (filt[0].text or "").split("|")}
    if not topics or not topics.issubset(TOPICS):
        raise ValueError("Unsupported topic expression")
    return topics


def handle_events(response, action, item, request, registry, subscription_id=None):
    broker = registry.events
    export_id = item["export_id"]
    if action == "GetServiceCapabilities":
        _node(
            response,
            "tev:Capabilities",
            WSPullPointSupport="true",
            WSSubscriptionPolicySupport="false",
            WSPausableSubscriptionManagerInterfaceSupport="false",
            MaxNotificationProducers=512,
            MaxPullPoints=32,
            PersistentNotificationStorage="false",
        )
    elif action == "GetEventProperties":
        _node(
            response,
            "tev:TopicNamespaceLocation",
            "http://www.onvif.org/onvif/ver10/topics/topicns.xml",
        )
        _node(response, "wsnt:FixedTopicSet", "true")
        topicset = _node(response, "wstop:TopicSet")
        for branch, leaf, source_name, data_name in [
            ("VideoSource", "MotionAlarm", "VideoSourceConfigurationToken", "IsMotion"),
            ("Device", "Trigger", "rawAlarm", "State"),
        ]:
            parent = _node(topicset, "tns1:" + branch)
            target = _node(parent, "tns1:" + leaf)
            if branch == "Device":
                target = _node(target, "tns1:Alarm")
            target.set("{" + NAMESPACES["wstop"] + "}topic", "true")
            description = _node(target, "tt:MessageDescription", IsProperty="true")
            source = _node(description, "tt:Source")
            _node(
                source, "tt:SimpleItemDescription", Name=source_name, Type="xs:string"
            )
            data = _node(description, "tt:Data")
            _node(
                data,
                "tt:SimpleItemDescription",
                Name=data_name,
                Type="xs:boolean" if branch == "VideoSource" else "xs:string",
            )
        # QName values must have explicit declarations even without namespaced tags.
        response.set("xmlns:xs", "http://www.w3.org/2001/XMLSchema")
        _node(response, "wsnt:TopicExpressionDialect", DIALECT)
        # The required WSDL field is empty because message-content filters are
        # unsupported; only the advertised topic-expression dialect is accepted.
        _node(response, "tev:MessageContentFilterDialect", "")
        _node(
            response,
            "tev:MessageContentSchemaLocation",
            "http://www.onvif.org/onvif/ver10/schema/onvif.xsd",
        )
    elif action == "CreatePullPointSubscription":
        if _find(request, "SubscriptionPolicy") is not None:
            raise ValueError("Subscription policy is unsupported")
        key = broker.subscribe(
            export_id,
            _seconds(_text(request, "InitialTerminationTime"), 60, 3600),
            _filters(request),
        )
        host = str(item["advertise_host"])
        if ":" in host and not host.startswith("["):
            host = "[" + host + "]"
        reference = _node(response, "tev:SubscriptionReference")
        _node(
            reference,
            "wsa:Address",
            f"http://{host}:{item['onvif_port']}/onvif/{quote(export_id, safe='')}/subscriptions/{key}",
        )
        _node(response, "wsnt:CurrentTime", _utc())
        _node(
            response, "wsnt:TerminationTime", _utc(broker.termination(export_id, key))
        )
    elif action == "PullMessages":
        if not subscription_id:
            raise ValueError("Subscription endpoint required")
        limit = int(_text(request, "MessageLimit") or 100)
        if limit <= 0:
            raise ValueError("MessageLimit must be positive")
        events = broker.pull(
            export_id,
            subscription_id,
            _seconds(_text(request, "Timeout"), 0, 30),
            limit,
        )
        _node(response, "tev:CurrentTime", _utc())
        _node(
            response,
            "tev:TerminationTime",
            _utc(broker.termination(export_id, subscription_id)),
        )
        if events:
            response.set("xmlns:tns1", NAMESPACES["tns1"])
        for event in events:
            notification = _node(response, "wsnt:NotificationMessage")
            _node(notification, "wsnt:Topic", event["topic"], Dialect=DIALECT)
            message = _node(
                _node(notification, "wsnt:Message"),
                "tt:Message",
                UtcTime=event["utc"],
                PropertyOperation=event["operation"],
            )
            for section, values in [
                ("Source", event["source"]),
                ("Data", event["data"]),
            ]:
                target = _node(message, "tt:" + section)
                for name, value in values.items():
                    _node(
                        target,
                        "tt:SimpleItem",
                        Name=name,
                        Value=str(value).lower() if isinstance(value, bool) else value,
                    )
    elif action == "SetSynchronizationPoint":
        broker.synchronize(export_id, subscription_id)
    elif action == "Renew":
        termination = broker.renew(
            export_id,
            subscription_id,
            _seconds(_text(request, "TerminationTime"), 60, 3600),
        )
        _node(response, "wsnt:TerminationTime", _utc(termination))
        _node(response, "wsnt:CurrentTime", _utc())
    elif action == "Unsubscribe":
        broker.unsubscribe(export_id, subscription_id)
    else:
        raise ValueError("Unsupported events operation")
