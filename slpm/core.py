"""SLPM service layer: the part of the app no user interface can do without.

A front end - the Flask web layer today, a desktop window or a CLI later - owns
presentation: cookies, URLs, JSON enveloping, status codes. Everything that is
really domain behaviour sits here instead: the exclusive install/removal job, the
ownership gate that protects Simple Mode removals, the operations log and the
environment summary the pages show.

Nothing in this module imports Flask or builds a URL. Rows produced by the domain
modules carry an ``icon`` name and an ``id``; rendering them as ``/api/icon``
links (or anything else) is the web layer's business.
"""
import datetime
import os
import threading
from pathlib import Path

from . import apps as apps_mod
from . import desktop, helper, proc, selfupdate, state

_t = proc.t

# --------------------------------------------------------------- exclusive job
#
# One install, removal or update runs at a time. The flag and the work that
# guards it are decided under the same lock: two callers that both read the
# flag first would otherwise both start. A caller that loses gets None back and
# answers its own "busy" message, in whichever format its interface speaks.

_job_lock = threading.Lock()
_job = {"active": False, "label": ""}
# Set only under _job_lock, when run_exclusive() refuses a caller.
_lost_job_label = ""


def current_job():
    """A snapshot of the job state, safe to serve while a job runs."""
    with _job_lock:
        return {"active": _job["active"], "label": _job["label"]}


def lost_job_label():
    """The label of the job that was running when the caller was refused.

    Taken under the same lock acquisition that delivered the refusal, so the
    busy reply names the operation the caller actually raced against, even if
    that operation has since finished.
    """
    return _lost_job_label


def run_exclusive(label, fn):
    """Run ``fn`` as the one active package operation.

    Returns ``fn()``'s result, or ``None`` when another operation is already
    running (the caller can read its label from :func:`lost_job_label`).
    Whatever happens inside ``fn`` - including an exception - the job state is
    cleared and the packages/app caches are dropped afterwards, so a list read
    after the operation reflects the new facts on disk.
    """
    global _lost_job_label
    with _job_lock:
        if _job["active"]:
            _lost_job_label = _job["label"]
            return None
        _job["active"] = True
        _job["label"] = label
    try:
        return fn()
    finally:
        with _job_lock:
            _job["active"] = False
            _job["label"] = ""
        bust_caches()


def bust_caches():
    """Drop every cached fact a package operation makes stale."""
    apps_mod.bust_meta_cache()
    desktop.bust_collect_cache()


# ------------------------------------------------------- simple-mode ownership
#
# In Simple Mode a removal target has to be found in the Simple list itself -
# the server re-derives ownership from its own records instead of trusting the
# request, so the id of a pre-installed app cannot be driven through the removal
# path. Interfaces call this gate before run_exclusive(). In Advanced Mode the
# gate is skipped: the caller decides that, and this module only supplies the
# evidence.


def user_installed(target="", file_name=""):
    """Is this removal target one the user installed themselves?

    ``target`` is a package name, snap id or desktop entry id; ``file_name`` an
    optional .desktop path. True only when the app appears in the Simple list.
    """
    for rec in apps_mod.apps("simple"):
        if target and target in (rec.get("package"), rec.get("id")):
            return True
        if file_name and file_name == rec.get("file"):
            return True
    return False


def require_user_installed(target="", file_name=""):
    """The Simple Mode gate as a guard: raises PermissionError when it fails.

    A caller refuses the operation when this raises, whatever its format for
    saying "this is only available in Advanced Mode".
    """
    if not user_installed(target=target, file_name=file_name):
        raise PermissionError(
            _t("This is only available in Advanced Mode."))


# ----------------------------------------------------------------- operations
#
# One line per package operation, rotated at about one megabyte. The old file is
# renamed, never truncated in place: a reader holding the file open keeps
# reading the old contents while the new log starts fresh.

MAX_ACTIONS_LOG = 1024 * 1024


def log_action(kind, target, ok, message):
    try:
        state.CACHE.mkdir(parents=True, exist_ok=True)
        try:
            if state.ACTIONS_LOG.stat().st_size > MAX_ACTIONS_LOG:
                state.ACTIONS_LOG.replace(state.ACTIONS_LOG.with_name("actions.log.old"))
        except OSError:
            pass
        with open(state.ACTIONS_LOG, "a") as fh:
            lines = (message or "").splitlines()
            first_line = lines[0][:200] if lines else ""
            fh.write(f"{_now()}\t{kind}\t{target}\t{'ok' if ok else 'failed'}\t"
                     f"{first_line}\n")
    except OSError:
        pass


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- environment

def env():
    """What the computer offers: root, the managers, the helper, the distro."""
    return {
        "is_root": os.geteuid() == 0,
        "has_pkexec": bool(proc.which("pkexec")),
        "helper_up": not helper._stale(state.HELPER_SOCK),
        "version": selfupdate.current_version(),
        "distro": _distro(),
        "managers": {
            "apt": bool(proc.which("apt-get")),
            "flatpak": bool(proc.which("flatpak")),
            "snap": bool(proc.which("snap")),
        },
    }


def _distro():
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"
