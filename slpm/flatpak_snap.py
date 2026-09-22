"""Flatpak and Snap, when present."""
import re

from . import proc
from .i18n import tr as _tr


def _t(english, **values):
    """Translate a message into the language of the request being served."""
    return _tr(proc.lang(), english, **values)


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
    rc, out, err = proc.run(["flatpak", "uninstall", "-y", app_id], timeout=300)
    if rc == 0:
        return True, _t("{app_id} was removed.", app_id=app_id), ""
    return False, _t("Could not remove {app_id}.", app_id=app_id), _last_line(out, err)


def _last_line(out, err):
    text = (err or out or "").strip()
    return text.splitlines()[-1] if text else _t("No details reported.")


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
    rc, out, err = proc.privileged(["snap", "remove", name], timeout=300)
    if rc == 0:
        return True, _t("{name} was removed.", name=name), ""
    if rc == -2:
        return False, _t("Could not remove {name}.", name=name), proc._auth_message("")
    return False, _t("Could not remove {name}.", name=name), _last_line(out, err)
