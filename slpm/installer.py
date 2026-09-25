"""Decide what a dropped file is and install it the right way."""
import shutil
import zipfile
from pathlib import Path

from . import appimage, apt, desktop, flatpak_snap, proc, util

_t = proc.t

SUPPORTED = ("deb", "AppImage", "flatpakref", "snap", "tar.gz", "tgz", "tar.xz", "txz",
             "tar.bz2", "tar.zst", "zip", "run", "sh")

EXTRACT_ROOT = Path.home() / ".local/share/slpm/apps"


def detect(path):
    """Classify a file. Returns dict(kind, label, detail, installable)."""
    if not str(path or "").strip():
        return {"path": "", "name": "", "exists": False, "kind": "missing",
                "label": _t("No file chosen"),
                "detail": _t("Type or paste the path of the file you downloaded."),
                "installable": False}
    p = Path(path).expanduser()
    name = p.name
    low = name.lower()
    if p.is_dir():
        return {"path": str(p), "name": name, "exists": True, "kind": "directory",
                "label": _t("Folder"),
                "detail": _t("Provide the file to install, not a folder."),
                "installable": False}
    rec = {"path": str(p), "name": name, "exists": p.is_file()}
    if not rec["exists"]:
        return {**rec, "kind": "missing", "label": _t("File not found"),
                "detail": _t("Check the path - this file does not exist."),
                "installable": False}
    if low.endswith(".deb"):
        return {**rec, "kind": "deb", "label": _t("Debian package (.deb)"),
                "detail": _t("Will be installed system-wide with apt/dpkg."), "installable": True}
    if low.endswith(".appimage"):
        return {**rec, "kind": "appimage", "label": _t("AppImage"),
                "detail": _t("Will be placed in ~/Applications with a menu shortcut."),
                "installable": True}
    if low.endswith(".flatpakref"):
        return {**rec, "kind": "flatpakref", "label": _t("Flatpak reference"),
                "detail": _t("Will be installed with flatpak."), "installable": True}
    if low.endswith(".snap"):
        return {**rec, "kind": "snap", "label": _t("Snap package"),
                "detail": _t("Will be installed with snap."), "installable": True}
    if appimage.is_archive(low):
        return {**rec, "kind": "archive", "label": _t("Archive"),
                "detail": _t("Will be extracted to ~/.local/share/slpm/apps, then you "
                             "pick which program inside to register."),
                "installable": True}
    if low.endswith((".run", ".sh")):
        return {**rec, "kind": "executable", "label": _t("Installer script"),
                "detail": _t("Installer scripts run arbitrary commands. SLPM will "
                             "extract nothing and only offer to register it as a menu "
                             "entry."),
                "installable": True}
    return {**rec, "kind": "unknown", "label": _t("Unsupported file type"),
            "detail": _t("SLPM installs .deb, .AppImage, .flatpakref, .snap and "
                         "archives ({formats}). Convert this file first.",
                         formats=", ".join(SUPPORTED[4:])),
            "installable": False}


def install(path, opts=None):
    """
    Returns dict(ok, kind, title, message, detail, needs_choice, choices, desktop_file)
    """
    opts = opts or {}
    info = detect(path)
    kind = info["kind"]
    if kind == "missing" or kind == "unknown" or kind == "directory":
        return _fail(info["label"], info["detail"], kind)

    if kind == "deb":
        try:
            ok, msg, steps = apt.install_deb(path)
        except Exception as exc:  # server must survive anything a package tool throws
            return _fail(_t("Installation failed"), str(exc), kind)
        return {
            "ok": ok, "kind": kind, "title": _t("Debian package"),
            "message": msg if ok else _t("The package was not installed."),
            "detail": "" if ok else msg,
            "desktop_file": None, "needs_choice": False, "choices": [],
        }

    if kind == "appimage":
        try:
            ok, msg, df = appimage.install(path)
        except Exception as exc:
            return _fail(_t("Installation failed"), str(exc), kind)
        return {"ok": ok, "kind": kind, "title": "AppImage",
                "message": msg,
                "detail": "" if ok else msg,
                "desktop_file": str(df) if df else None,
                "needs_choice": False, "choices": []}
    if kind == "flatpakref":
        return _flatpakref(path)

    if kind == "snap":
        try:
            ok, msg, detail = flatpak_snap.snap_install_file(path)
        except Exception as exc:
            return _fail(_t("Installation failed"), str(exc), "snap")
        return {"ok": ok, "kind": "snap", "title": _t("Snap package"),
                "message": msg,
                "detail": "" if ok else detail,
                "desktop_file": None, "needs_choice": False, "choices": []}

    if kind == "archive":
        return _archive(path, opts)

    if kind == "executable":
        return _register_script(path, opts)

    return _fail(_t("Unsupported file type"), info["detail"], kind)


def _flatpakref(path):
    if not proc.which("flatpak"):
        return _fail(_t("Flatpak is not installed"),
                     _t("This computer has no flatpak command. Install flatpak first "
                        "(Advanced mode -> flatpak)."), "flatpakref")
    # User level on purpose: this must land where flatpak_uninstall looks again. A
    # root install goes to the system installation, which this UI could not remove.
    rc, out, err = proc.run(["flatpak", "install", "-y", "--from", str(path)], timeout=900)
    if rc == 0:
        return {"ok": True, "kind": "flatpakref", "title": "Flatpak",
                "message": _t("Installed."), "detail": "", "desktop_file": None,
                "needs_choice": False, "choices": []}
    return _fail(_t("Flatpak installation failed"),
                 (err or out).strip().splitlines()[-1] if (out or err).strip() else "",
                 "flatpakref")


def _archive(path, opts):
    dest = EXTRACT_ROOT / _safe_slug(Path(path).stem)
    ok, msg, root = appimage.extract(path, dest)
    if not ok:
        return _fail(_t("Could not extract the archive"), msg, "archive")

    launchers = appimage.find_launchers(root)
    if not launchers:
        return {
            "ok": True, "kind": "archive", "title": _t("Archive"),
            "message": _t("Extracted to {root}. No runnable program was found inside, "
                          "so nothing was added to your menu.", root=root),
            "detail": "", "desktop_file": None, "needs_choice": False, "choices": [],
            "extracted_to": str(root),
        }

    # The choice comes back from the browser, so resolve it against what we actually
    # found on disk instead of trusting the submitted path.
    chosen = _resolve_choice(opts.get("choice"), launchers)
    if chosen is None:
        if len(launchers) == 1:
            chosen = launchers[0]
        else:
            return {
                "ok": False, "kind": "archive",
                "title": _t("Which program should I add?"),
                "message": _t("Extracted to {root}. This archive contains several "
                              "runnable items - pick one to add to your menu.",
                              root=root),
                "detail": "", "desktop_file": None, "needs_choice": True,
                "choices": launchers, "extracted_to": str(root),
            }
    return _register_launcher(chosen, root)


def _resolve_choice(choice, launchers):
    """Match the browser's selection to a launcher we actually discovered."""
    if not isinstance(choice, dict):
        return None
    want = str(choice.get("path", ""))
    if not want:
        return None
    try:
        target = Path(want).resolve()
    except OSError:
        return None
    for cand in launchers:
        try:
            if Path(cand["path"]).resolve() == target:
                return cand
        except OSError:
            continue
    return None


def _register_launcher(launcher, root):
    p = Path(launcher["path"])
    name = launcher["name"]
    if not p.exists():
        return _fail(_t("The extracted file is gone"),
                     _t("{name} is no longer in {root}. Extract the archive again.",
                        name=name, root=root), "archive")
    if launcher["kind"] == "desktop":
        entry = desktop.parse(p)
        exec_line = entry.get("Exec", "")
        argv = desktop.exec_argv(exec_line)
        if argv and not argv[0].startswith("/"):
            resolved = shutil.which(argv[0]) or str((root / argv[0]).resolve())
            exec_line = exec_line.replace(argv[0], f'"{resolved}"', 1)
        icon = entry.get("Icon")
        icon_path = None
        if icon:
            for ext in ("", ".png", ".svg", ".xpm"):
                cand = root / f"{icon}{ext}"
                if cand.exists():
                    icon_path = str(cand)
                    break
            else:
                icon_path = desktop.icon_path(icon, p.stem)
        slug = _safe_slug(name)
        icon_ref = appimage._install_icon(Path(icon_path), slug) if icon_path else None
        df = desktop.desktop_file(
            name=entry.get("Name") or name, exec_line=exec_line, icon=icon_ref,
            comment=entry.get("Comment") or _t("Installed with SLPM"),
            categories=tuple(c for c in entry.get("Categories", "Utility;").split(";") if c) or ("Utility",),
            terminal=entry.get("Terminal", "").lower() == "true",
            path_override=f"slpm-{slug}.desktop",
        )
        return {"ok": True, "kind": "archive", "title": _t("Archive"),
                "message": _t("{name} was added to your applications menu.",
                              name=entry.get('Name') or name),
                "detail": "", "desktop_file": str(df), "needs_choice": False, "choices": []}

    if launcher["kind"] == "script":
        return {"ok": False, "kind": "script", "title": _t("Installer script"),
                "message": _t("{name} is a script that installs itself. SLPM will not "
                              "run it for you, but you can register it as a menu entry.",
                              name=name),
                "detail": _t("Run it in a terminal if you trust its source."),
                "desktop_file": None, "needs_choice": False, "choices": []}

    p.chmod(p.stat().st_mode | 0o111)
    slug = _safe_slug(name)
    df = desktop.desktop_file(
        name=Path(name).stem.replace("-", " ").replace("_", " ").title(),
        exec_line=f'"{p}"', comment=_t("Installed with SLPM"), categories=("Utility",),
        path_override=f"slpm-{slug}.desktop",
    )
    return {"ok": True, "kind": "archive", "title": _t("Archive"),
            "message": _t("{name} was added to your applications menu.", name=name),
            "detail": "", "desktop_file": str(df), "needs_choice": False, "choices": []}


def _register_script(path, opts):
    p = Path(path).expanduser().resolve()
    p.chmod(p.stat().st_mode | 0o111)
    slug = _safe_slug(p.stem)
    df = desktop.desktop_file(
        name=p.stem.replace("-", " ").replace("_", " ").title(),
        exec_line=f'"{p}"', comment=_t("Registered with SLPM"), categories=("Utility",),
        path_override=f"slpm-{slug}.desktop",
    )
    return {"ok": True, "kind": "executable", "title": _t("Installer script"),
            "message": _t("{name} was added to your applications menu.", name=p.name),
            "detail": _t("SLPM did not execute it."), "desktop_file": str(df),
            "needs_choice": False, "choices": []}


def _safe_slug(text):
    return util.slug(text, "package")


def _fail(title, detail, kind):
    return {"ok": False, "kind": kind, "title": title, "message": detail, "detail": detail,
            "desktop_file": None, "needs_choice": False, "choices": []}


def uninstall_desktop_entry(desktop_path):
    """Used for apps SLPM owns (AppImages registered in ~/.local/share/applications).

    Every path returns (ok, message, detail): the endpoint unpacks three values from
    this, so the branches that returned only two raised ValueError and turned a routine
    "not there any more" into a 500.
    """
    p = Path(desktop_path)
    if p.suffix != ".desktop" or not p.exists():
        return False, _t("That shortcut no longer exists."), ""
    try:
        p.resolve().relative_to(desktop.USER_APPS.resolve())
    except ValueError:
        return False, _t("SLPM only removes shortcuts it created itself."), ""
    if p.name.startswith("slpm-"):
        ok, msg = appimage.uninstall(p)
        return ok, msg, ""
    if not desktop.remove(p):
        return False, _t("The shortcut could not be removed."), ""
    return True, _t("The shortcut was removed."), ""
