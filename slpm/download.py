"""HTTP downloads into the Downloads folder, with pause / stop / continue.

Each download runs on its own background thread so the page can stay responsive and
poll for progress. Progress is reported as bytes, and the browser turns it into a
percentage. A running job can be paused (the thread stops reading), continued (it
reopens the connection where it left off) or stopped (the partial file is removed).

Resume works through the HTTP Range header: the connection is reopened with
``Range: bytes=<downloaded>-`` so an interrupted download continues from the bytes
already on disk, instead of starting over.
"""
import contextvars
import ipaddress
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import proc
from .i18n import tr as _tr

CHUNK = 64 * 1024           # read this many bytes per loop
CONNECT_TIMEOUT = 15        # connect + read timeout for each connection
POLL = 0.2                  # how often the thread checks for pause/stop
MAX_REDIRECTS = 10          # a misbehaving server must not recurse forever
KEEP_FINISHED = 200         # jobs remembered so the status bar can still show them

_jobs = {}                  # id -> DownloadJob
_jobs_lock = threading.Lock()
_id_counter = [0]

# A download thread is not the Flask request thread, so it does not inherit the
# request's language contextvar. The language is captured when the job starts - on
# the request thread - and re-applied inside the thread, so a failure message about
# a download the user started in Persian comes back in Persian too.
_lang_ctx = contextvars.ContextVar("slpm_download_lang", default=None)


def _t(english, **values):
    lang = _lang_ctx.get() or proc.lang()
    return _tr(lang, english, **values)


def _downloads_dir():
    """Where downloads go. Uses the user's real Downloads folder when known.

    ``xdg-user-dir`` reports the localized folder name (e.g. a translated
    Downloads), and falls back to ~/Downloads when it is not available.
    """
    rc, out, _ = proc.run(["xdg-user-dir", "DOWNLOAD"], timeout=10)
    if rc == 0 and out.strip():
        path = out.strip().removeprefix("file://").strip()
        if path and Path(path).is_dir():
            return Path(path)
    return Path.home() / "Downloads"


def _filename_from_url(url):
    """Guess a file name from the end of the URL, or a generic default.

    The URL is decoded *before* the last path segment is taken, and the result is
    reduced to a bare file name: an encoded separator (%2F) is what re-introduced
    slashes after the split and turned "download the file at …/evil" into a write
    to an attacker-chosen path. What is left must be a plain name - no directory,
    no leading dot (a dotfile could hide a file, and "." and ".." are not names at
    all).
    """
    name = unquote(urlparse(url).path).rsplit("/", 1)[-1].strip()
    name = Path(name).name
    if not name or name in (".", "..") or name.startswith("."):
        return "download"
    return name if "." in name else "download"


class _CappingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib follows redirects without a count; a pair of servers that redirect
    at each other would loop the job until the per-read timeout. Cap the hops."""

    def __init__(self, limit):
        self.limit = limit
        self._count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._count += 1
        if self._count > self.limit:
            raise urllib.error.HTTPError(newurl, code, "Too many redirects", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener():
    return urllib.request.build_opener(_CappingRedirectHandler(MAX_REDIRECTS))


def _is_blocked_ip(ip):
    return (ip.is_loopback or ip.is_link_local or ip.is_private
            or ip.is_reserved or ip.is_unspecified)


def _blocked_host(hostname):
    """True when a URL points at this machine or the local network rather than the
    internet.

    The download endpoint runs with the user's rights and follows redirects, so a
    link to 127.0.0.1, the cloud metadata address or a router on the LAN would be a
    way to probe - and pull data from - services the user has no business talking to.
    Every address a name resolves to is checked; if one of them is private, the name
    is blocked.
    """
    if not hostname:
        return True
    host = hostname.strip("[]")  # bracketed IPv6 literal
    try:
        return _is_blocked_ip(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        addrs = socket.getaddrinfo(host, None)
    except OSError:
        return True  # a name that does not resolve is not a safe target either
    for entry in addrs:
        try:
            ip = ipaddress.ip_address(entry[4][0])
        except ValueError:
            return True
        if _is_blocked_ip(ip):
            return True
    return False


def _unique_path(dest):
    """A destination path that does not clobber a file already in Downloads."""
    dest = Path(dest)
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 1
    while True:
        cand = dest.parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


class DownloadJob:
    def __init__(self, url):
        _id_counter[0] += 1
        self.id = f"{_id_counter[0]}-{threading.get_ident()}"
        self.url = url
        self.state = "queued"          # queued, running, paused, done, failed, stopped
        self.downloaded = 0
        self.total = None
        self.error = ""
        self.finished_at = None       # set when the job leaves queued/running/paused
        self.filename = _filename_from_url(url)
        dest = _downloads_dir() / self.filename
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        self.path = str(_unique_path(dest))
        # If uniquifying changed the suffix, keep the name we actually wrote to.
        self.filename = Path(self.path).name
        self._thread = None
        self._lock = threading.Lock()

    def status(self):
        with self._lock:
            return {
                "id": self.id,
                "url": self.url,
                "state": self.state,
                "downloaded": self.downloaded,
                "total": self.total,
                "filename": self.filename,
                "path": self.path,
                "error": self.error,
                "percent": round(self.downloaded / self.total * 100, 1)
                if self.total else 0,
            }

    def start(self):
        """Spawn the background thread. Safe to call once per job."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            with self._lock:
                state = self.state
            if state in ("stopped", "failed", "done"):
                return
            if state == "paused":
                time.sleep(POLL)
                continue
            # queued or running: fetch until the stream ends or a control comes in.
            reason = self._download_once()
            if reason == "done":
                with self._lock:
                    self.state = "done"
                    self.finished_at = time.time()
                return
            if reason == "failed":
                # self.state is already "failed" (and self.error set) inside the
                # call; nothing else to do but leave the loop.
                return
            # 'paused' or 'stopped' -> the loop above rechecks the state each pass.

    def _download_once(self):
        """Download from the current byte offset until done, paused or stopped.

        Returns one of "done", "failed", "paused", "stopped". A fresh connection is
        opened each call so a resume simply starts the loop again from where the last
        one left off; the bytes already written stay put and the Range header continues
        them.
        """
        pos = self.downloaded
        try:
            req = urllib.request.Request(self.url)
            if pos > 0:
                req.add_header("Range", f"bytes={pos}-")
            resp = _opener().open(req, timeout=CONNECT_TIMEOUT)
        except urllib.error.HTTPError as exc:
            # A 416 means the server does not support range resumes; restart the
            # whole file fresh (truncating the partial) rather than append twice.
            if exc.code == 416 and pos > 0:
                os.truncate(self.path, 0)
                with self._lock:
                    self.downloaded = 0
                    self.total = None
                return self._download_once()
            with self._lock:
                self.state = "failed"
                self.finished_at = time.time()
                self.error = _t("Download failed.")
            return "failed"
        except (urllib.error.URLError, OSError) as exc:
            # Connection refused, DNS failure, timeout, etc. The download cannot
            # proceed at all; record it as failed instead of letting the thread die
            # and leaving the job stranded in "queued".
            with self._lock:
                self.state = "failed"
                self.finished_at = time.time()
                self.error = _t("Download failed.")
            return "failed"

        # Announce the total up front, then hand off to a writer loop that only ever
        # holds the lock for the fraction of a millisecond it takes to record a chunk,
        # so the progress bar can keep updating while the download runs.
        code = resp.getcode()
        if pos > 0 and code == 200:
            # A resume request was answered with the whole file instead of a partial
            # (206). Appending it to the partial already on disk would duplicate the
            # downloaded bytes, so drop the partial and start the whole thing over
            # without a Range header. Most servers return 206 here, which is the
            # normal continue path taken below.
            os.truncate(self.path, 0)
            with self._lock:
                self.downloaded = 0
                self.total = None
            resp.close()                    # drop the ignored-range connection first
            return self._download_once()
        if code == 206:                 # partial content: total = already + now
            remaining = int(resp.headers.get("Content-Length") or 0)
            with self._lock:
                self.total = pos + remaining
        elif self.total is None:
            with self._lock:
                self.total = int(resp.headers.get("Content-Length") or 0) or None

        try:
            with open(self.path, "ab") as f:
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        return "done"
                    with self._lock:
                        state = self.state
                        if state == "stopped":
                            return "stopped"
                        if state == "paused":
                            return "paused"
                    f.write(chunk)
                    with self._lock:
                        self.downloaded += len(chunk)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            with self._lock:
                self.state = "failed"
                self.finished_at = time.time()
                self.error = _t("Download failed.")
            return "failed"
        finally:
            # Always release the connection. This matters most on pause: a server that
            # serves one request at a time (e.g. a simple http.server) stays busy on the
            # half-closed socket otherwise, so a resume could never connect.
            resp.close()

    def pause(self):
        with self._lock:
            if self.state in ("queued", "running"):
                self.state = "paused"

    def resume(self):
        with self._lock:
            if self.state == "paused":
                self.state = "running"

    def stop(self):
        with self._lock:
            self.state = "stopped"
            self.finished_at = time.time()
        # Removing the partial file is safe: the thread checks the state under the
        # same lock before every write, so no chunk is written after this returns.
        try:
            Path(self.path).unlink(missing_ok=True)
        except OSError:
            pass


def start(url):
    """Validate a URL and begin downloading it. Returns (ok, job-or-error)."""
    url = str(url or "").strip()
    if not re.match(r"^https?://[^\s]+$", url):
        return {"ok": False, "error": _t("Enter a link starting with http:// or https://")}
    # The destination is checked before the job is created, so a blocked link never
    # even touches the filesystem.
    if _blocked_host(urlparse(url).hostname):
        return {"ok": False,
                "error": _t("This link points at a local or reserved address, so SLPM "
                            "will not download it.")}
    job = DownloadJob(url)
    with _jobs_lock:
        _jobs[job.id] = job
    job.start()
    return {"ok": True, "job": job.status()}


def control(job_id, action):
    """pause / resume / stop for one job."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return None
    if action == "pause":
        job.pause()
    elif action == "resume":
        job.resume()
    elif action == "stop":
        job.stop()
    else:
        return {"ok": False, "error": _t("Unknown action.")}
    return {"ok": True, "job": job.status()}


def list_status():
    """Every job, with the oldest finished ones pruned.

    The page polls this once a second, so a finished row has already been drawn
    before it is dropped; keeping only the newest KEEP_FINISHED finished jobs stops
    the table (and the memory it costs) growing for the life of the server.
    """
    with _jobs_lock:
        finished = [j for j in _jobs.values()
                    if j.state in ("done", "failed", "stopped")]
        if len(finished) > KEEP_FINISHED:
            finished.sort(key=lambda j: j.finished_at or 0)
            for j in finished[: len(finished) - KEEP_FINISHED]:
                _jobs.pop(j.id, None)
        return [job.status() for job in _jobs.values()]
