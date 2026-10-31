"""Private server/SD recording jobs and authenticated RTSP replay orchestration."""

import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from .recordings import RecordingStore, Recorder
from .sd_archive import SDArchive


class Replay:
    def __init__(self, ffmpeg, path, url):
        self.path = path
        self.url = url
        self.process = None
        env = dict(os.environ)
        env.pop("FFREPORT", None)
        self.process = subprocess.Popen(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-re",
                "-i",
                path,
                "-an",
                "-c:v",
                "copy",
                "-f",
                "rtsp",
                "-rtsp_transport",
                "tcp",
                url,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(2)


class ArchiveManager:
    def __init__(self, registry, root=None):
        self.registry = registry
        self.root = root or os.environ.get(
            "BRIDGE_RECORDINGS_DIR", str(Path(".runtime/recordings").resolve())
        )
        self.lock = threading.RLock()
        self._store = None
        self.recorders = {}
        self.jobs = {}
        self.sd_indexes = {}
        self.replays = {}

    @property
    def store(self):
        with self.lock:
            if self._store is None:
                self._store = RecordingStore(self.root, self.registry.ffmpeg)
            return self._store

    def owner(self, workspace):
        owner = workspace.account_id
        if workspace.closed or not owner:
            raise ValueError("session_expired")
        return owner

    def _entry(self, workspace, camera_id):
        entry = self.registry._find(workspace, camera_id)
        if not entry or entry.stop.is_set():
            raise ValueError("export_not_enabled")
        return entry

    def status(self, workspace, camera_id):
        owner = self.owner(workspace)
        with workspace.lock:
            if camera_id not in workspace.records:
                raise KeyError(camera_id)
        entry = self.registry._find(workspace, camera_id)
        with self.lock:
            workers = self.recorders.get(entry.export_id, []) if entry else []
            jobs = [
                {
                    k: v
                    for k, v in job.items()
                    if k in ("id", "state", "error", "records", "date", "source_id")
                }
                for job in self.jobs.values()
                if job["workspace"] is workspace and job["camera_id"] == camera_id
            ]
        return {
            "recording_enabled": bool(workers),
            "workers": [w.status() for w in workers],
            "records": self.store.list(owner, camera_id),
            "storage": {
                **self.store.stats(owner, camera_id),
                **self.store.policy(owner, camera_id),
            },
            "jobs": jobs[-20:],
        }

    def set_recording(self, workspace, camera_id, data):
        if type(data.get("enabled")) is not bool:
            raise ValueError("invalid_recording_settings")
        entry = self._entry(workspace, camera_id)
        segment = data.get("segment_seconds", 60)
        retention = data.get("retention_days", 7)
        quota = data.get("max_bytes", 10 * 1024**3)
        if data["enabled"] and (
            type(segment) is not int
            or not 5 <= segment <= 3600
            or type(retention) is not int
            or not 1 <= retention <= 365
            or type(quota) is not int
            or not 1024**2 <= quota <= 1024**4
        ):
            raise ValueError("invalid_recording_settings")
        with self.lock:
            old = self.recorders.pop(entry.export_id, [])
            for worker in old:
                worker.stop()
            for worker in old:
                worker.join()
            if data["enabled"]:
                self.store.set_policy(
                    self.owner(workspace),
                    camera_id,
                    retention_days=retention,
                    max_bytes=quota,
                )
                camera = self.registry._camera(entry)
                if not camera:
                    raise ValueError("camera_not_streaming")
                workers = [
                    Recorder(
                        camera,
                        lens,
                        self.store,
                        self.owner(workspace),
                        camera_id,
                        segment_seconds=segment,
                        retention_days=retention,
                        max_bytes=quota,
                    )
                    for lens in camera.status()["lenses"]
                ]
                with self.lock:
                    if entry.stop.is_set():
                        raise ValueError("export_not_enabled")
                    self.recorders[entry.export_id] = workers
                    for worker in workers:
                        worker.start()
        with workspace.lock:
            if data["enabled"]:
                workspace.saved_recordings[camera_id] = dict(
                    enabled=True,
                    segment_seconds=segment,
                    retention_days=retention,
                    max_bytes=quota,
                )
            else:
                workspace.saved_recordings.pop(camera_id, None)
        return self.status(workspace, camera_id)

    def _sd(self, workspace, camera_id):
        entry = self._entry(workspace, camera_id)
        camera = self.registry._camera(entry)
        if camera is None:
            raise ValueError("camera_not_streaming")
        return SDArchive(dict(camera.config), self.registry.ffmpeg)

    def sd_dates(self, workspace, camera_id):
        return self._sd(workspace, camera_id).list_dates()

    def sd_records(self, workspace, camera_id, date):
        rows = self._sd(workspace, camera_id).list_records(date)
        with self.lock:
            key = (workspace, camera_id)
            self.sd_indexes[key] = {row["id"]: row for row in rows[:4096]}
        return rows

    def import_sd(self, workspace, camera_id, data):
        entry = self._entry(workspace, camera_id)
        source_id = data.get("source_id")
        seconds = data.get("duration", 60)
        if type(seconds) is not int or not 1 <= seconds <= 300:
            raise ValueError("invalid_import_duration")
        with self.lock:
            source = self.sd_indexes.get((workspace, camera_id), {}).get(source_id)
            if source is None:
                raise ValueError("sd_record_not_listed")
            if any(
                job["workspace"] is workspace
                and job["camera_id"] == camera_id
                and job["state"] in ("pending", "downloading")
                for job in self.jobs.values()
            ):
                raise ValueError("archive_job_busy")
            for token in list(self.jobs):
                if self.jobs[token]["state"] not in ("pending", "downloading"):
                    self.jobs.pop(token, None)
            if len(self.jobs) >= 32:
                raise ValueError("archive_job_limit")
            token = secrets.token_urlsafe(16)
            job = {
                "id": token,
                "workspace": workspace,
                "camera_id": camera_id,
                "state": "pending",
                "error": None,
                "records": [],
                "source_id": source_id,
                "cancel": threading.Event(),
            }
            self.jobs[token] = job
        import shutil

        if shutil.disk_usage(self.store.root).free < 2 * 1024**3:
            with self.lock:
                self.jobs.pop(token, None)
            raise ValueError("insufficient_archive_disk_space")
        with self.lock:
            if (
                sum(
                    j["state"] in ("pending", "downloading") for j in self.jobs.values()
                )
                > 2
            ):
                self.jobs.pop(token, None)
                raise ValueError("archive_job_limit")
        sd = self._sd(workspace, camera_id)
        owner = self.owner(workspace)

        def run():
            paths = []
            try:
                job["state"] = "downloading"
                directory = self.store.directory(owner, camera_id)
                rows = sd.fetch(
                    source, directory, max_seconds=seconds, cancel=job["cancel"]
                )
                paths = [Path(row["path"]) for row in rows]
                if entry.stop.is_set() or job["cancel"].is_set():
                    raise ValueError("archive_job_cancelled")
                records = [
                    self.store.add_recording(
                        owner,
                        camera_id,
                        row["path"],
                        source="sd",
                        lens=row["lens"],
                        start=row["start"],
                        end=row["end"],
                    )
                    for row in rows
                ]
                self.store.enforce_limits(
                    owner, camera_id, **self.store.policy(owner, camera_id)
                )
                job["records"] = records
                job["state"] = "completed"
                paths = []
            except Exception:
                job["state"] = "cancelled" if job["cancel"].is_set() else "error"
                job["error"] = (
                    "sd_import_failed"
                    if job["state"] == "error"
                    else "archive_job_cancelled"
                )
            finally:
                for path in paths:
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass

        thread = threading.Thread(target=run, daemon=True)
        job["thread"] = thread
        thread.start()
        return {"id": token, "state": job["state"]}

    def records(self, export_id):
        with self.registry.lock:
            entry = self.registry.entries.get(export_id)
        if not entry or entry.stop.is_set():
            raise ValueError("export_not_enabled")
        return self.store.list(self.owner(entry.workspace), entry.camera_id)

    def file(self, workspace, camera_id, token):
        with workspace.lock:
            if camera_id not in workspace.records:
                raise KeyError(camera_id)
        record = self.store.get(self.owner(workspace), camera_id, token)
        if not record:
            raise KeyError(token)
        return record

    def replay(self, export_id, token):
        with self.registry.lock:
            entry = self.registry.entries.get(export_id)
        if not entry or entry.stop.is_set():
            raise ValueError("export_not_enabled")
        record = self.file(entry.workspace, entry.camera_id, token)
        key = (export_id, token)
        with self.lock:
            # Finished processes do not retain per-clip replay resources.
            for old in list(self.replays):
                worker = self.replays[old]
                if worker is not None and worker.process.poll() is not None:
                    self.replays.pop(old, None)
            old = self.replays.get(key)
            if old:
                old.stop()
            if len(self.replays) >= 16:
                raise ValueError("replay_limit")
            path = export_id + "/replay/" + token
            internal = (
                self.registry.internal_url.replace(
                    "rtsp://",
                    "rtsp://publish:" + self.registry.publisher_password + "@",
                    1,
                )
                + "/"
                + path
            )
            # Register path before MediaMTX challenges the publisher.
            self.replays[key] = None
            worker = Replay(self.registry.ffmpeg, record["path"], internal)
            self.replays[key] = worker
        return f"rtsp://{entry.host}:{self.registry.rtsp_port}/{path}"

    def replay_allowed(self, export_id, token):
        with self.lock:
            exists = (export_id, token) in self.replays
        return exists and any(row["token"] == token for row in self.records(export_id))

    def drop(self, entry):
        with self.lock:
            workers = self.recorders.pop(entry.export_id, [])
            jobs = [
                j
                for j in self.jobs.values()
                if j["workspace"] is entry.workspace
                and j["camera_id"] == entry.camera_id
            ]
            replays = [
                self.replays.pop(k)
                for k in list(self.replays)
                if k[0] == entry.export_id
            ]
            self.sd_indexes.pop((entry.workspace, entry.camera_id), None)
            for job in jobs:
                job["cancel"].set()
        for worker in workers:
            worker.stop()
        for worker in workers:
            worker.join()
        for worker in replays:
            if worker:
                worker.stop()

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job["cancel"].set()
            jobs = list(self.jobs.values())
        for job in jobs:
            if job.get("thread"):
                job["thread"].join(60)
        if self._store:
            self._store.close()
