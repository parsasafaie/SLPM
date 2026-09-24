"""Build the Installed Apps list.

The list is driven purely by .desktop entries: an app is listed only if a desktop
environment would put its icon in the application menu. Snap and Flatpak are never
queried to decide *what* to list - they are visible only through the entries they
export, which is what excludes their runtimes, bases and platforms (mesa-2404, core22,
gtk-common-themes, org.freedesktop.Platform) without needing a list of names to block.

They are queried for *metadata* and for *removal target*: a listed snap or flatpak app
is removed through `snap remove` / `flatpak uninstall`, not by deleting its exported
.desktop file. Deleting the entry would leave the package installed with no icon to
find it by again.

Two views come out of the same scan:

  simple    only applications the user installed themselves.
  advanced  everything in the menu, the software the system came with included.

Which of the two an app belongs to is decided by slpm/ownership.py, from the package
manager's own record of when it arrived - never from the directory its entry sits in,
which is identical for `apt install ./vryon.deb` and for a package that shipped with
the distribution.
"""
from functools import lru_cache
from urllib.parse import quote

from . import apt, desktop, ownership
from .i18n import tr as _tr


def _t(english, **values):
    """Translate a message into the language of the request being served."""
    from . import proc

    return _tr(proc.lang(), english, **values)


def _owner(binary, file_path):
    """Which installed package provides this app, if any.

    Exec= holds either an absolute path or a bare command name, and dpkg-query -S only
    understands paths, so a bare name is resolved on PATH first. Without this, most
    entries (libreoffice, rhythmbox, transmission-gtk) would look unowned and be
    offered no way to remove them. When the command itself cannot be traced (empty
    Exec=, TryExec binary absent), the package that ships the .desktop file is the
    same evidence, and keeps removal aimed at the real package rather than the file.
    """
    return ownership.owning_package(binary) or ownership.owning_package_of_file(file_path)


def apps(mode="simple"):
    """Rows for one view: the user's own apps, or every app including the system's.

    `mode` is 'simple' or 'advanced'. The filtering happens here rather than in the
    browser so that Simple Mode cannot be made to show or remove a pre-installed app by
    calling the API directly.
    """
    rows = []
    for rec in desktop.collect("simple" if mode == "simple" else "advanced"):
        binary = rec.get("binary", "")
        provided_by = rec.get("provided_by", "")
        pkg = _owner(binary, rec.get("file", ""))

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

        # Ownership decides membership, so it has to be resolved before the entry can be
        # kept or dropped. The owning package is already known here, so it is passed in
        # rather than looked up a second time.
        user_installed, reason = ownership.classify_desktop_entry({**rec, "package": pkg})
        rec["user_installed"] = bool(user_installed)
        rec["ownership"] = reason
        if mode == "simple" and not user_installed:
            continue

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
        # their own manager.
        rec["removable"] = bool(meta) or manager == "appimage"
        rec["icon_url"] = (f"/api/icon?name={quote(rec['icon'])}&app={quote(rec['id'])}"
                           if rec["icon"] else "")
        rows.append(rec)

    return sorted(rows, key=lambda r: r["name"].lower())


def bust_meta_cache():
    """Drop every remembered package/snap/flatpak row.

    The caches below make repeat /api/apps calls cheap, but a package operation
    (install, remove, upgrade) changes exactly the facts they hold: a newly
    installed package would keep showing an empty row, and a removed one its old
    version, until the server restarts. Call this after any such operation.
    """
    _pkg_meta.cache_clear()
    _snap_meta.cache_clear()
    _flatpak_meta.cache_clear()


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
