"""Subprocess helpers. Never raise on non-zero exit - return (rc, out, err)."""
import contextvars
import os
import re
import shutil
import subprocess

from . import i18n

TIMEOUT = 300

# ------------------------------------------------------------------- name shapes
#
# A string that is about to become a non-flag operand of a package tool (a package
# name, an app id, a snap name) must match one of these before it is handed to any
# command - privileged or not. The helper's allowlist is the second gate, but it only
# runs when the helper answers; the pkexec and sudo fallbacks in privileged() have no
# allowlist at all, so this is the check that covers every path. The shapes also keep
# a leading dash (which a package tool would read as an option) and any whitespace
# out of the operands.

APT_PKG = re.compile(r"^[a-z0-9][a-z0-9+._:-]*$")          # vlc, libfoo1.2-3
FLATPAK_APP_ID = re.compile(r"^[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)+$")  # org.gimp.GIMP
SNAP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")            # code, gimp


def is_apt_pkg(name):
    return bool(APT_PKG.match(name or ""))


def is_flatpak_app_id(name):
    return bool(FLATPAK_APP_ID.match(name or ""))


def is_snap_name(name):
    return bool(SNAP_NAME.match(name or ""))


# ---------------------------------------------------------------- live processes

def exe_to_pids():
    """{resolved executable path: [pids]} for every process readable from /proc.

    One pass over /proc so a caller asking about several apps does not pay for a
    pass per app. A pid that exits mid-scan, or one the caller may not inspect,
    simply does not appear - for our uses (this user's own apps) that is exact.
    """
    mapping = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return mapping  # not a Linux /proc view
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            target = os.readlink(f"/proc/{entry}/exe")
        except OSError:
            continue
        mapping.setdefault(target, []).append(int(entry))
    return mapping


def pids_with_exe_prefix(prefix):
    """The pids of every process whose executable path starts with prefix."""
    return [pid for exe, pids in exe_to_pids().items() if exe.startswith(prefix)
            for pid in pids]


# How long to wait for a person to answer the polkit dialog. This is the time to *answer*,
# not a cap on the operation: pkexec runs its child to completion, and a package operation
# (a kernel install, a big upgrade) routinely takes longer than a minute. Bounding the whole
# pkexec call by the dialog deadline killed long operations mid-transaction and left apt
# holding the dpkg lock, so the dialog and the work now get separate budgets.
PKEXEC_TIMEOUT = 900

# The language this request is being served in. A module-level global would be shared
# by every thread Flask runs, so two people with the page open in different languages
# would overwrite each other's choice; a ContextVar is per-request.
_lang = contextvars.ContextVar("slpm_lang", default=i18n.DEFAULT)


def set_lang(lang):
    """Set the current request's language. Called by the web layer."""
    return _lang.set(i18n.normalize(lang))


def lang():
    return _lang.get()


def t(english, **values):
    """Translate one message into the current request's language."""
    return i18n.tr(_lang.get(), english, **values)


def which(cmd):
    return shutil.which(cmd)


def run(argv, timeout=TIMEOUT, env=None, cwd=None, stdin_text=None):
    """Returns (returncode, stdout, stderr). returncode is -1 on timeout, 127 if not found."""
    if isinstance(argv, str):
        argv = [argv]
    if not which(argv[0]):
        return 127, "", f"command not found: {argv[0]}"
    e = dict(os.environ)
    e.setdefault("LANG", "C.UTF-8")
    e["DEBIAN_FRONTEND"] = "noninteractive"
    if env:
        e.update(env)
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=e,
            cwd=cwd,
            input=stdin_text,
        )
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except OSError as exc:
        return 126, "", str(exc)


def ok(argv, **kw):
    rc, out, _ = run(argv, **kw)
    return rc == 0, out


def lines(text):
    return [ln for ln in (text or "").splitlines() if ln.strip()]


def have_graphical_session():
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# ---------------------------------------------------------------- privileges

def privileged(argv, timeout=TIMEOUT):
    """
    Run argv as root without ever waiting on a password prompt.

    Order of attempts: a live helper socket (already authenticated for this session),
    then pkexec for a polkit dialog, then passwordless sudo. Returns
    (returncode, stdout, stderr); returncode -2 means privileges were refused and
    nothing was changed.
    """
    if os.geteuid() == 0:
        return run(argv, timeout=timeout)

    from . import helper  # late import: helper imports this module

    # A live helper answers with a real result; a refusal (rc 126) is not a final
    # answer, because the allowlist may simply not cover this operation. Fall through
    # to pkexec for it, so an unsupported-but-legitimate command still has a path.
    # The client timeout must cover the helper's own execution budget: an operation
    # the helper is allowed to run for 900s must not be declared dead at 300s, or the
    # same work would be reissued through pkexec while the first copy still runs.
    rc = helper.client(helper_socket(), argv, timeout=max(timeout, helper.RUN_TIMEOUT))
    if rc is not None and rc[0] != 126:
        return rc

    auth_err = ""
    if which("pkexec"):
        # pkexec runs the whole command, not just the dialog, so the timeout has to be
        # one a package operation can finish inside. A short "dialog" timeout used to
        # kill installs and removals mid-flight and report them as an unanswered
        # dialog, leaving apt holding the dpkg lock.
        rc, out, err = run(["pkexec", *argv], timeout=PKEXEC_TIMEOUT)
        if rc == 0:
            return rc, out, err
        if rc == -1:
            auth_err = t("The command did not finish in time. It may still be running; "
                         "close any package tool and try again.")
        else:
            auth_err = err
        if rc != -1 and not _is_auth_failure(err):
            return rc, out, err

    if which("sudo"):
        rc, out, err = run(["sudo", "-n", *argv], timeout=timeout)
        if rc == 0:
            return rc, out, err
        auth_err = auth_err or err

    return -2, "", _auth_message(auth_err)


def helper_socket():
    """Path of the current user's helper socket, or None."""
    try:
        from .helper import default_socket

        return default_socket()
    except Exception:
        return None


def _is_auth_failure(err):
    e = (err or "").lower()
    return any(
        s in e
        for s in ("no authentication agent", "not autorized", "not authorized",
                  "a password is required", "no tty present", "password is required",
                  "dismissed", "cancelled", "canceled", "incorrect password",
                  "sudo: a terminal is required")
    )


def _auth_message(detail):
    return t(
        "Root permission was not granted. SLPM asked for it with pkexec/sudo and the "
        "request was declined or no authentication dialog could be shown.\n"
        "Details: {detail}",
        detail=detail.strip()[:400],
    )
