"""Build the Simple Mode app list.

Simple Mode is driven purely by .desktop entries: an app is listed only if a desktop
environment would put its icon in the application menu. Snap and Flatpak are never
queried to decide *what* to list - they are visible only through the entries they
export, which is what excludes their runtimes, bases and platforms (mesa-2404, core22,
gtk-common-themes, org.freedesktop.Platform) without needing a list of names to block.

They are queried for *metadata* and for *removal target*: a listed snap or flatpak app
is removed through `snap remove` / `flatpak uninstall`, not by deleting its exported
.desktop file. Deleting the entry would leave the package installed with no icon to
find it by again.
"""
from functools import lru_cache
import shutil

from . import apt, desktop
from .i18n import tr as _tr


def _t(english, **values):
    """Translate a message into the language of the request being served."""
    from . import proc

    return _tr(proc.lang(), english, **values)


def _owner(binary):
    """Which installed package provides this program, if any.

    Exec= holds either an absolute path or a bare command name, and dpkg-query -S only
    understands paths, so a bare name is resolved on PATH first. Without this, most
    entries (libreoffice, rhythmbox, transmission-gtk) would look unowned and be
    offered no way to remove them.
    """
    if not binary:
        return None
    path = binary if binary.startswith("/") else shutil.which(binary)
    if not path:
        return None
    from . import proc

    rc, out, _ = proc.run(["dpkg-query", "-S", path], timeout=20)
    if rc == 0 and ":" in out:
        return out.split(":", 1)[0].strip()
    return None


def apps():
    """Simple Mode rows: one per application that appears in the user's app menu."""
    rows = []
    for rec in desktop.collect("simple"):
        binary = rec.get("binary", "")
        provided_by = rec.get("provided_by", "")
        pkg = _owner(binary)

        # A snap or flatpak entry is removed through its own manager; a packaged
        # binary through apt; an AppImage through the shortcut SLPM wrote.
        if provided_by:
            manager, target = provided_by.split(":", 1)
        elif pkg:
            manager, target = "apt", pkg
        elif rec["id"].startswith("slpm-") and binary.endswith(".AppImage"):
            manager, target = "appimage", rec["id"]
        else:
            manager, target = "desktop", rec["id"]

        rec["package"] = pkg or target
        rec["manager"] = manager
        rec["size"] = ""
        rec["version"] = ""
        if manager == "snap":
            meta = _snap_meta(target)
        elif manager == "flatpak":
            meta = _flatpak_meta(target)
        else:
            meta = _pkg_meta(pkg) if pkg else {}
        if meta:
            rec["version"] = meta.get("version", "")
            rec["size"] = meta.get("size", "")
            rec["summary"] = meta.get("summary") or rec["comment"]
        else:
            rec["summary"] = (rec["comment"] or rec["generic"]
                              or _t("Installed application"))

        # Everything in this list is an application the user can see in their menu, so
        # everything in it can be removed from here - snap and flatpak included, through
        # their own manager. Leaving them unremovable made Simple Mode show snap apps
        # that Advanced Mode could remove but Simple Mode could not, which is the view
        # most users are in.
        rec["removable"] = bool(meta) or manager == "appimage"
        rec["icon_url"] = f"/api/icon?name={rec['icon']}&app={rec['id']}" if rec["icon"] else ""
        rows.append(rec)

    return sorted(rows, key=lambda r: r["name"].lower())


@lru_cache(maxsize=4096)
def _pkg_meta(name):
    from . import proc

    rc, out, _ = proc.run(
        ["dpkg-query", "-W", "-f",
         "${Version}\t${Installed-Size}\t${binary:Summary}", name], timeout=20
    )
    if rc != 0:
        return {}
    parts = (out or "").split("\t")
    kb = 0
    try:
        kb = int(parts[1])
    except (IndexError, ValueError):
        pass
    return {"version": parts[0] if parts else "",
            "size": apt._human(kb * 1024),
            "summary": parts[2] if len(parts) > 2 else ""}


@lru_cache(maxsize=512)
def _snap_meta(name):
    """Version, size and summary for a snap, so its row is not blank next to apt apps."""
    from . import flatpak_snap

    for snap in flatpak_snap.snap_installed():
        if snap["id"] == name:
            return {"version": snap.get("version", ""),
                    "size": snap.get("size", ""),
                    "summary": ""}
    return {}


@lru_cache(maxsize=512)
def _flatpak_meta(app_id):
    from . import flatpak_snap

    for app in flatpak_snap.flatpak_installed():
        if app["id"] == app_id:
            return {"version": app.get("version", ""),
                    "size": app.get("size", ""),
                    "summary": ""}
    return {}
