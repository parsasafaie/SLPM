"""Subprocess helpers. Never raise on non-zero exit - return (rc, out, err)."""
import contextvars
import os
import shutil
import subprocess

from . import i18n

TIMEOUT = 300
PKEXEC_TIMEOUT = 45   # how long to wait for a person to answer the polkit dialog

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

def _can_root_without_password(user):
    rc, _, _ = run(["sudo", "-n", "-u", "root", "true"], timeout=10)
    return rc == 0


def privilege_helper():
    """What we would use to escalate, or None if we already are root."""
    if os.geteuid() == 0:
        return None
    if which("pkexec"):
        return "pkexec"
    if which("sudo"):
        try:
            import getpass

            if _can_root_without_password(getpass.getuser()):
                return "sudo"
        except Exception:
            pass
        return "sudo"
    return None


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

    rc = helper.client(helper_socket(), argv, timeout=timeout)
    if rc is not None:
        return rc

    auth_err = ""
    if which("pkexec"):
        # pkexec shows a desktop dialog. Give the user time to answer, but far less
        # than a package operation needs: if nobody answers we must report that
        # instead of holding the request open.
        rc, out, err = run(["pkexec", *argv], timeout=PKEXEC_TIMEOUT)
        if rc == 0:
            return rc, out, err
        if rc == -1:
            auth_err = t("The permission dialog was not answered. Approve the request "
                         "when it appears, or start the helper once from the Install "
                         "page.")
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
