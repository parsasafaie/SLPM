"""Flatpak and Snap, when present."""
import re
from pathlib import Path

from . import proc

_t = proc.t

_COL = re.compile(r"\s{2,}")  # snap list pads columns with 2+ spaces


def flatpak_installed():
    if not proc.which("flatpak"):
        return []
    rc, out, _ = proc.run(
        ["flatpak", "list", "--app", "--columns=application,name,version,size,origin"],
        timeout=60,
    )
    if rc != 0:
        return []
    apps = []
    for line in proc.lines(out):
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        apps.append({
            "id": parts[0].strip(),
            "name": (parts[1] or parts[0]).strip(),
            "version": parts[2].strip() if len(parts) > 2 else "",
            "size": parts[3].strip() if len(parts) > 3 else "",
            "origin": parts[4].strip() if len(parts) > 4 else "",
            "manager": "flatpak",
        })
    return apps


def flatpak_uninstall(app_id):
    """Flatpak is a per-user operation, so it needs no escalation at all."""
    if not proc.is_flatpak_app_id(app_id):
        return False, _t("This does not look like a Flatpak app id (org.gimp.GIMP)."), ""
    rc, out, err = proc.run(["flatpak", "uninstall", "-y", app_id], timeout=300)
    if rc == 0:
        return True, _t("{app_id} was removed.", app_id=app_id), ""
    return False, _t("Could not remove {app_id}.", app_id=app_id), _last_line(out, err)


def flatpak_install(app_id):
    """Install a flatpak app by id, at user level (no root needed).

    Runs as the user on purpose: a root-level flatpak install would land in the
    system installation, which is not what a user installing an app from the menu
    wants, and it would spend a polkit dialog for nothing.
    """
    if not proc.is_flatpak_app_id(app_id):
        return False, _t("This does not look like a Flatpak app id (org.gimp.GIMP)."), ""
    if not proc.which("flatpak"):
        return False, _t("Flatpak is not installed on this system."), ""
    rc, out, _ = proc.run(["flatpak", "remotes", "--columns=Name"], timeout=30)
    remotes = [r.strip() for r in proc.lines(out)] if rc == 0 else []
    remote = "flathub"
    if "flathub" not in remotes:
        # No flathub (or no remote at all): add it at user level, the standard one.
        proc.run(["flatpak", "remote-add", "--if-not-exists", "flathub",
                  "https://dl.flathub.org/repo/flathub.flatpakrepo"], timeout=120)
    rc, out, err = proc.run(["flatpak", "install", "-y", remote, app_id], timeout=900)
    if rc == 0:
        return True, _t("{app_id} was installed.", app_id=app_id), ""
    return False, _t("Could not install {app_id}.", app_id=app_id), _last_line(out, err)


def flatpak_updates():
    """The user-level flatpak apps that have a newer version."""
    if not proc.which("flatpak"):
        return []
    rc, out, _ = proc.run(
        ["flatpak", "list", "--app", "--updates", "--columns=application,name,version"],
        timeout=60,
    )
    apps = []
    if rc == 0:
        for line in proc.lines(out):
            parts = line.split("\t")
            if len(parts) >= 2:
                apps.append({"id": parts[0].strip(),
                             "name": (parts[1] or parts[0]).strip(),
                             "version": parts[2].strip() if len(parts) > 2 else ""})
    return apps


def flatpak_update():
    """Bring every user-level flatpak app to its newest version."""
    if not proc.which("flatpak"):
        return False, _t("Flatpak is not installed on this system."), ""
    rc, out, err = proc.run(["flatpak", "update", "-y"], timeout=900)
    if rc == 0:
        return True, _t("Flatpak apps were updated."), ""
    return False, _t("Updating Flatpak apps failed."), _last_line(out, err)


def flatpak_update_one(app_id):
    """Bring one user-level flatpak app to its newest version."""
    if not proc.is_flatpak_app_id(app_id):
        return False, _t("This does not look like a Flatpak app id (org.gimp.GIMP)."), ""
    if not proc.which("flatpak"):
        return False, _t("Flatpak is not installed on this system."), ""
    rc, out, err = proc.run(["flatpak", "update", "-y", app_id], timeout=900)
    if rc == 0:
        return True, _t("{name} was updated.", name=app_id), ""
    return False, _t("Updating {name} failed.", name=app_id), _last_line(out, err)


def _last_line(out, err):
    text = (err or out or "").strip()
    return text.splitlines()[-1] if text else _t("No details reported.")


def _short_error(out, err, limit=12):
    """The tail of an operation's output - enough to diagnose, capped to show.

    A single last line hid real failures: snapd explains a broken refresh over
    several lines and ends with a bare list of process ids, so the user saw the
    id list as the whole error. The detail now carries the last few lines, line
    breaks and all, cut at a hard maximum so a chatty failure cannot flood the
    toast.
    """
    text = (err or out or "").strip()
    if not text:
        return _t("No details reported.")
    return "\n".join(text.splitlines()[-limit:])[:2000]


def _running_snaps():
    """Snap names with at least one live process.

    snapd has no query for this, but every process a snap starts executes from
    /snap/<name>/, so one /proc scan answers it. This is what tells the UI that a
    refresh would close a running app - the case that made `snap refresh code`
    fail mid-update while VS Code was open.
    """
    running = set()
    for exe in proc.exe_to_pids():
        m = re.match(r"^/snap/([a-z0-9-]+)/", exe)
        if m:
            running.add(m.group(1))
    return running


def snap_installed():
    if not proc.which("snap"):
        return []
    rc, out, _ = proc.run(["snap", "list"], timeout=60)
    if rc != 0:
        return []
    lines = proc.lines(out)
    if len(lines) < 2:
        return []
    apps = []
    for line in lines[1:]:
        # Columns: Name | Version | Rev | Tracking | Publisher | Notes
        p = _COL.split(line.strip())
        if len(p) < 3:
            continue
        apps.append({
            "id": p[0],
            "name": p[0],
            "version": p[1],
            "rev": p[2],
            "tracking": p[3] if len(p) > 3 else "",
            "publisher": (p[4] if len(p) > 4 else "").rstrip("*"),
            "notes": (p[5] if len(p) > 5 else "").strip("-"),
            "size": "",
            "manager": "snap",
        })
    return apps


def snap_uninstall(name):
    """Remove a snap through the same privilege path every other manager uses.

    Going straight to `sudo -n` would fail silently whenever the user has no
    passwordless sudo (the normal case), and the helper socket - already authenticated
    for this session - was never consulted at all.
    """
    if not proc.is_snap_name(name):
        return False, _t("This does not look like a snap name: {name}", name=name), ""
    rc, out, err = proc.privileged(["snap", "remove", name], timeout=300)
    if rc == 0:
        return True, _t("{name} was removed.", name=name), ""
    if rc == -2:
        return False, _t("Could not remove {name}.", name=name), proc._auth_message("")
    return False, _t("Could not remove {name}.", name=name), _last_line(out, err)


def snap_install(name):
    """Install a snap by its store name."""
    if not proc.is_snap_name(name):
        return False, _t("This does not look like a snap name: {name}", name=name), ""
    if not proc.which("snap"):
        return False, _t("Snap is not installed on this system."), ""
    rc, out, err = proc.privileged(["snap", "install", name], timeout=900)
    if rc == 0:
        return True, _t("{name} was installed.", name=name), ""
    if rc == -2:
        return False, _t("Could not install {name}.", name=name), proc._auth_message("")
    return False, _t("Could not install {name}.", name=name), _last_line(out, err)


def snap_install_file(path):
    """Install a local .snap file the user picked."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return False, _t("File not found: {path}", path=p), ""
    if not p.name.endswith(".snap"):
        return False, _t("This file is not a .snap package."), ""
    rc, out, err = proc.privileged(["snap", "install", str(p)], timeout=900)
    if rc == 0:
        return True, _t("{name} was installed.", name=p.name), ""
    if rc == -2:
        return False, _t("Could not install {name}.", name=p.name), proc._auth_message("")
    return False, _t("Could not install {name}.", name=p.name), _last_line(out, err)


def snap_updates():
    """The snaps that have a newer revision, as snap reports them.

    Each item also carries "running" - whether the snap has live processes right
    now - so the UI can warn before a refresh that would close the app.
    """
    if not proc.which("snap"):
        return []
    rc, out, _ = proc.run(["snap", "refresh", "--list"], timeout=120)
    if rc != 0:
        return []
    running = _running_snaps()
    apps = []
    lines = proc.lines(out)
    for line in lines[1:]:  # first line is the column header
        p = _COL.split(line.strip())
        if len(p) >= 2:
            apps.append({"id": p[0], "name": p[0], "version": p[1],
                         "running": p[0] in running})
    return apps


def snap_refresh():
    """Refresh every snap to its newest revision."""
    if not proc.which("snap"):
        return False, _t("Snap is not installed on this system."), ""
    rc, out, err = proc.privileged(["snap", "refresh"], timeout=900)
    if rc == 0:
        return True, _t("Snap apps were updated."), ""
    if rc == -2:
        return False, _t("Updating snap apps failed."), proc._auth_message("")
    return False, _t("Updating snap apps failed."), _short_error(out, err)


def snap_refresh_one(name):
    """Refresh one snap to its newest revision."""
    if not proc.is_snap_name(name):
        return False, _t("This does not look like a snap name: {name}", name=name), ""
    if not proc.which("snap"):
        return False, _t("Snap is not installed on this system."), ""
    rc, out, err = proc.privileged(["snap", "refresh", name], timeout=900)
    if rc == 0:
        return True, _t("{name} was updated.", name=name), ""
    if rc == -2:
        return False, _t("Updating {name} failed.", name=name), proc._auth_message("")
    return False, _t("Updating {name} failed.", name=name), _last_line(out, err)
