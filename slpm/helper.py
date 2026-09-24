"""
Unix-socket helper for privileged package operations.

Why this exists: a GUI dialog never has a terminal, so `sudo -S` cannot ask for a
password and `sudo -n` always fails. pkexec does the opposite - it shows a proper
polkit dialog through the desktop session, but pkexec drops most of the environment,
so the command it runs cannot talk back to the Flask process over a pipe.

The helper bridges the two: the Flask server starts it through pkexec (one polkit
dialog), and it then serves commands over a socket the unprivileged server can reach.
It holds no policy of its own - every command it accepts is one of the five package
manager calls below, and it exits on its own after IDLE_TIMEOUT.

Standalone by design: run it directly for testing with
    .venv/bin/python -m slpm.helper /tmp/slpm-test.sock
"""
import json
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

from . import proc

IDLE_TIMEOUT = 300
MAX_MSG = 1 << 20


def default_socket():
    from . import state

    return state.HELPER_SOCK


def _stale(path):
    """A socket is stale if its file exists but nothing is listening."""
    path = Path(path)
    if not path.exists():
        return True
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(str(path))
        return False
    except OSError:
        return True
    finally:
        s.close()


def client(sock_path, argv, timeout=600):
    """Send one command to a running helper.

    Returns (rc, out, err) on a real reply, or None when no helper is reachable so the
    caller can fall back to pkexec/sudo. A helper that answers with a refusal is a real
    answer, not a reason to give up: `rc` is 126 and the caller decides.
    """
    if not sock_path or not Path(sock_path).exists():
        return None
    if _stale(sock_path):
        return None
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(sock_path))
        s.sendall(json.dumps({"argv": argv}).encode())
        s.shutdown(socket.SHUT_WR)
        chunks = []
        total = 0
        while True:
            b = s.recv(65536)
            if not b:
                break
            total += len(b)
            if total > MAX_MSG:
                break
            chunks.append(b)
        data = json.loads(b"".join(chunks) or b"{}")
        return data.get("rc", -1), data.get("out", ""), data.get("err", "")
    except (OSError, ValueError):
        return None
    finally:
        s.close()


def spawn(sock_path, log_path):
    """Start the helper through pkexec. Returns (ok, message). The polkit dialog
    appears at this point; users without admin rights decline and we report that."""
    sock_path = Path(sock_path)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        sock_path.unlink()
    except OSError:
        pass

    argv = [sys.executable, "-m", "slpm.helper", str(sock_path)]
    env_note = ""
    if os.geteuid() != 0:
        if proc.which("pkexec"):
            argv = ["pkexec", *argv]
        elif proc.which("sudo"):
            argv = ["sudo", *argv]
            env_note = proc.t(
                " (password prompt may appear in the terminal that started SLPM)")
        else:
            return False, proc.t(
                "Neither pkexec nor sudo is available, so privileged actions cannot run.")

    kwargs = {"env": {**os.environ, "PYTHONPATH": _project_root(),
                      "SLPM_LANG": proc.lang()}}
    try:
        import subprocess

        with open(log_path, "ab") as log:
            subprocess.Popen(argv, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                             **kwargs)
    except OSError as exc:
        return False, proc.t("Could not start the privileged helper: {exc}", exc=exc)

    for _ in range(60):  # up to ~30s: the user may be typing a password
        time.sleep(0.5)
        if not _stale(sock_path):
            return True, proc.t("Privileged helper is running.")
    return False, proc.t(
        "Root permission was not granted. SLPM asked for it with pkexec and the request "
        "was dismissed or denied.") + env_note


def _project_root():
    return str(Path(__file__).resolve().parents[1])


# --------------------------------------------------------------- server side

def serve(sock_path):
    sock_path = Path(sock_path)
    helper_lang = os.environ.get("SLPM_LANG", "en")
    proc.set_lang(helper_lang)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        sock_path.unlink()
    except OSError:
        pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock_path))
    os.chmod(sock_path, 0o600)
    # The connecting process is the unprivileged launcher, not root, so the socket
    # has to be reachable across the uid boundary. pkexec sets PKEXEC_UID; sudo does
    # not, and in that case chowning to -1 would leave the socket owned by root with
    # mode 0600 - the caller could never connect, and every privileged action would
    # report an auth failure. SUDO_UID is the equivalent when sudo started us.
    owner = os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID")
    if owner:
        try:
            os.chown(sock_path, int(owner), -1)
        except (OSError, ValueError):
            pass
    srv.listen(8)
    srv.settimeout(IDLE_TIMEOUT)

    last = time.time()

    def handle(conn):
        nonlocal last
        proc.set_lang(helper_lang)
        last = time.time()
        try:
            # A single recv() can return a partial request; read until the client's
            # shutdown(SHUT_WR) closes its side, the same way client() reads the reply.
            conn.settimeout(30)
            chunks = []
            total = 0
            while True:
                b = conn.recv(65536)
                if not b:
                    break
                total += len(b)
                if total > MAX_MSG:
                    break
                chunks.append(b)
            req = json.loads(b"".join(chunks) or b"{}")
            argv = req.get("argv") or []
            if not _allowed(argv):
                payload = {"rc": 126, "out": "", "err": proc.t(
                    "Refused by helper: {argv}", argv=argv)}
            else:
                rc, out, err = proc.run(argv, timeout=900)
                payload = {"rc": rc, "out": out[-200_000:], "err": err[-200_000:]}
            conn.sendall(json.dumps(payload).encode())
        except Exception as exc:
            try:
                conn.sendall(json.dumps({"rc": -1, "out": "", "err": str(exc)}).encode())
            except OSError:
                pass
        finally:
            conn.close()

    try:
        while time.time() - last < IDLE_TIMEOUT:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                break
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    finally:
        srv.close()
        try:
            sock_path.unlink()
        except OSError:
            pass


# Allowlist: the helper refuses anything that is not one of these exact shapes.
# There is no shell involved (argv is exec'd directly), so the risk is not injection
# but a caller using apt/dpkg as a way to run something unexpected. Package names and
# local archive paths are the only non-flag arguments accepted, and neither may carry
# whitespace or a leading dash that could be read as an option.
_ALLOWED_PROGRAMS = {"apt-get", "dpkg", "snap", "flatpak"}
_PKG_ACTIONS = {"install", "remove", "purge"}
_NAME_ONLY_ACTIONS = {"autoremove", "update", "upgrade"}
_SAFE_ARG = re.compile(r"^[A-Za-z0-9/.][A-Za-z0-9+._:/=,-]*$")
# Flags that turn off apt's or dpkg's own safety checks. SLPM asks the user to confirm
# instead, so these must never reach a privileged package tool.
_FORBIDDEN_FLAGS = {
    "--force-yes", "-y--force-yes", "--force-all", "--force-remove-essential",
    "--force-depends", "--force-architecture", "--allow-change-held-packages",
}

# The one exception, and it is deliberately narrow: Advanced Mode offers removal for
# every package, so removing an Essential one has to be expressible. apt refuses those
# removals outright without this flag. It is accepted only on a removal action - never
# on an install, where it would defeat a different check - and it forces nothing else:
# dpkg's --force-* flags stay refused above.
_ALLOW_REMOVE_ESSENTIAL = "--allow-remove-essential"
_REMOVAL_ACTIONS = {"remove", "purge", "-r", "--remove", "-P", "--purge"}


def _safe_flag(arg):
    """Any flag that is not --allow-remove-essential is judged by the forbidden list.

    The exception is decided in _safe_args, which knows whether the action is a removal;
    this function must not wave it through on its own, or it would also be accepted on
    install and update.
    """
    if arg == _ALLOW_REMOVE_ESSENTIAL:
        return False
    return not any(arg.startswith(f) for f in _FORBIDDEN_FLAGS)


def _safe_operand(arg):
    """A package name or a local file path.

    Must not start with '-' (that would be read as an option by apt/dpkg) and must not
    contain whitespace or shell metacharacters. A path with spaces arrives as a single
    argv element here, but apt/dpkg would treat it as several, so it is refused.
    """
    return bool(_SAFE_ARG.match(arg))


def _safe_args(rest, require_operand=False, allow_remove_essential=False):
    if require_operand and not any(not a.startswith("-") for a in rest):
        return False
    for a in rest:
        if a.startswith("-"):
            if _safe_flag(a):
                continue
            # The single sanctioned exception, and only where a removal is happening.
            if allow_remove_essential and a == _ALLOW_REMOVE_ESSENTIAL:
                continue
            return False
        if not _safe_operand(a):
            return False
    return True


def _allowed(argv):
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        return False
    if len(argv) < 2 or argv[0] not in _ALLOWED_PROGRAMS:
        return False
    program, action, rest = argv[0], argv[1], argv[2:]
    removal = action in _REMOVAL_ACTIONS

    if program == "apt-get":
        if action in _PKG_ACTIONS:
            # e.g. apt-get remove -y vlc  /  apt-get install -y /tmp/app.deb
            # "install -f -y" is the dependency repair pass: flags only, no target.
            if not any(not a.startswith("-") for a in rest):
                return _safe_args(rest, allow_remove_essential=removal)
            return _safe_args(rest, require_operand=True, allow_remove_essential=removal)
        if action in _NAME_ONLY_ACTIONS:
            return _safe_args(rest)
        return False

    if program == "dpkg":
        if action in {"-i", "--install", "-r", "--remove", "-P", "--purge"}:
            return _safe_args(rest, require_operand=True, allow_remove_essential=removal)
        if action == "--configure":
            return _safe_args(rest)
        return False

    if program == "snap":
        if action in {"remove", "refresh"}:
            return _safe_args(rest, require_operand=True)
        if action == "install":
            return _safe_args(rest, require_operand=True)
        return False

    return False


def _cli():
    sock = sys.argv[1] if len(sys.argv) > 1 else "/tmp/slpm-helper.sock"
    if os.geteuid() != 0:
        print("warning: running unprivileged, package operations will fail", file=sys.stderr)
    print(f"slpm-helper listening on {sock}", file=sys.stderr)
    serve(Path(sock))


if __name__ == "__main__":
    _cli()
