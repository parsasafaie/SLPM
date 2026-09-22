"""Reading and writing .desktop entries - the source of truth for 'an app is installed'.

Simple Mode shows exactly what the desktop environment's application menu shows, so
the list of directories here is the list of places an application menu looks. Flatpak
and Snap both export real .desktop files into these directories, which is why they are
not enumerated separately anywhere: a snap with no visible entry (a runtime, a base, a
driver) simply has nothing to list.
"""
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import proc
from .i18n import tr as _tr


def _t(english, **values):
    """Translate a message into the language of the request being served."""
    return _tr(proc.lang(), english, **values)


USER_APPS = Path.home() / ".local/share/applications"
SYSTEM_APPS = Path("/usr/share/applications")
LOCAL_BIN = Path.home() / ".local/bin"
APPLICATIONS = Path.home() / "Applications"
ICON_DIR = Path.home() / ".local/share/icons/hicolor"

# Exactly the paths xdg-spec-based menus search, in the same precedence order.
APP_DIRS = (
    USER_APPS,
    Path("/usr/local/share/applications"),
    SYSTEM_APPS,
    Path("/var/lib/snapd/desktop/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path.home() / ".local/share/flatpak/exports/share/applications",
)

SECTIONS = ("Desktop Entry",)

# Categories that mean "not an application at all". Deliberately narrow: Settings,
# System, Core, PackageManager and HardwareSettings are used by real menu entries
# (Synaptic, GNOME Files, Terminal, Settings, App Center), so blocking those would
# hide applications the user can see in their launcher. NoDisplay is the spec's own
# mechanism for "keep this out of the menu" and is the signal that actually matters.
_NON_APP_CATEGORIES = {
    "screensaver",     # not a launcher command
    "consoleonly",     # text-only program, no GUI
    "library",         # a library, never launched directly
}

# Exec values that cannot possibly start a GUI application.
_STUB_EXECV = re.compile(r"^/(usr/)?bin/(false|true)$")
_NOISE_EXEC = re.compile(
    r"(^|/)(bash|zsh|dash|dbus-send)\b|"
    r"\b(xterm|gnome-terminal|konsole|--help|--version)\b",
    re.I,
)


def parse(path):
    """Parse a .desktop file. Returns dict with keys of the [Desktop Entry] group."""
    data = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return data
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section not in SECTIONS or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.endswith("[") or key.lower().endswith(("$", "]")):
            continue  # localized key like Name[de]
        if "[" in key:
            continue
        data.setdefault(key, value.strip())
    return data


def is_visible(entry, environ=None):
    """Would this entry put an icon in the user's application menu?

    This is the Simple Mode gate. It follows the Desktop Entry Specification using the
    same conditions a menu implementation applies, so anything that passes really does
    appear in the launcher, and anything that fails really does not.
    """
    environ = environ if environ is not None else os.environ

    # --- Type and display flags
    if entry.get("Type", "Application") != "Application":
        return False  # Link/Directory are not launchable programs
    if _is_true(entry.get("NoDisplay")):
        return False
    if _is_true(entry.get("Hidden")):
        return False

    # --- Required keys, and a name a human can read
    if not entry.get("Name") or not entry.get("Exec") or not entry.get("Icon"):
        return False

    # --- Environment restrictions (Getting/OnlyShowIn in the spec)
    desktops = {d for d in environ.get("XDG_CURRENT_DESKTOP", "").split(":") if d}
    only = {v for v in entry.get("OnlyShowIn", "").split(";") if v}
    if only and desktops and not (only & desktops):
        return False
    not_show = {v for v in entry.get("NotShowIn", "").split(";") if v}
    if not_show and desktops and (not_show & desktops):
        return False

    # --- Launch command must be able to start something graphical
    argv = exec_argv(entry["Exec"])
    if not argv:
        return False
    program = argv[0]
    if _STUB_EXECV.match(program):
        # /usr/bin/false is what a snap exports when it has no real launcher.
        return False
    if not (program.startswith("/") or proc.which(program)):
        return False  # points at a program that is not installed

    # --- Non-application categories
    cats = {c.strip().lower() for c in entry.get("Categories", "").split(";") if c.strip()}
    if cats & _NON_APP_CATEGORIES:
        return False
    if "terminal" in cats or _is_true(entry.get("Terminal")):
        return False

    # --- CLI tools masquerading as entries
    if _NOISE_EXEC.search(program):
        return False

    return True


def _is_true(value):
    return (value or "").strip().lower() == "true"


def exec_argv(exec_line):
    """Turn a .desktop Exec= line into an argv list, dropping field codes and quotes.

    Quoting is legal in Exec= (SLPM writes it itself for paths with spaces), so the
    quotes have to come off before the arguments are used as filesystem paths.
    """
    parts = []
    buf = ""
    field = False
    quote = None
    for ch in exec_line:
        if field:
            field = False
            continue
        if quote:
            if ch == quote:
                quote = None
            else:
                buf += ch
            continue
        if ch in "\"'":
            quote = ch
            continue
        if ch == "%":
            field = True
            continue
        if ch == " ":
            if buf:
                parts.append(buf)
                buf = ""
            continue
        buf += ch
    if buf:
        parts.append(buf)
    return [p for p in parts if p]


def _resolve_localized(data, key):
    return data.get(key) or data.get(f"{key}[en]") or ""


def collect(mode="simple"):
    """
    One record per installed .desktop entry, scanned from every directory an
    application menu searches.

    mode='simple'   only entries that would appear in the user's application menu.
    mode='advanced' everything with an entry, including hidden ones.

    Entries are keyed by file name so a user override replaces the system one, and a
    snap/flatpak export never duplicates an entry already listed.
    """
    seen = {}
    for rank, root in enumerate(APP_DIRS):
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.desktop")):
            entry = parse(f)
            if not entry:
                continue
            if mode == "simple" and not is_visible(entry):
                continue
            if mode == "advanced" and _is_true(entry.get("Hidden")):
                continue

            key = f.name
            prev = seen.get(key)
            if prev is not None and prev["_rank"] <= rank:
                continue  # a higher-precedence directory already claimed this id

            exec_line = entry.get("Exec", "")
            argv = exec_argv(exec_line)
            rec = {
                "id": key,
                "name": _resolve_localized(entry, "Name") or f.stem,
                "comment": _resolve_localized(entry, "Comment"),
                "icon": entry.get("Icon", ""),
                "exec": exec_line,
                "binary": argv[0] if argv else "",
                "categories": [c for c in entry.get("Categories", "").split(";") if c],
                "terminal": _is_true(entry.get("Terminal")),
                "file": str(f),
                "source": _source_of(root),
                "version": entry.get("Version", ""),
                "keywords": entry.get("Keywords", ""),
                "generic": entry.get("GenericName", ""),
                # Which packaging system put this entry here, if it can be told.
                "provided_by": _provided_by(root, entry, f),
                "_rank": rank,
            }
            rec["can_launch"] = bool(exec_line) and argv and (
                proc.have_graphical_session() or rec["terminal"]
            )
            seen[key] = rec

    rows = sorted(seen.values(), key=lambda r: r["name"].lower())
    for r in rows:
        r.pop("_rank", None)
    return rows


def _source_of(root):
    if root == USER_APPS:
        return "user"
    if "snapd" in str(root):
        return "snap"
    if "flatpak" in str(root):
        return "flatpak"
    return "system"


def _provided_by(root, entry, path):
    """The snap or flatpak this entry belongs to, when the entry says so."""
    if entry.get("X-SnapInstanceName"):
        return f"snap:{entry['X-SnapInstanceName']}"
    if "snapd" in str(root):
        return f"snap:{entry.get('X-SnapAppName', '')}".rstrip(":")
    if "flatpak" in str(root):
        # The file name is the app id: org.telegram.desktop.desktop
        return f"flatpak:{Path(path).name[:-len('.desktop')]}"
    return ""


def icon_path(icon_name, app_id=""):
    """Resolve an Icon= value to a real file path, or None."""
    if not icon_name:
        return None
    p = Path(icon_name)
    if p.is_absolute() and p.exists():
        return str(p)
    if icon_name.startswith("applications-"):
        pass
    search_roots = [
        ICON_DIR / "scalable/apps",
        ICON_DIR / "48x48/apps",
        ICON_DIR / "256x256/apps",
        Path("/usr/share/icons/hicolor/256x256/apps"),
        Path("/usr/share/icons/hicolor/128x128/apps"),
        Path("/usr/share/icons/hicolor/64x64/apps"),
        Path("/usr/share/icons/hicolor/48x48/apps"),
        Path("/usr/share/pixmaps"),
    ]
    exts = ("", ".png", ".svg", ".xpm")
    for root in search_roots:
        for ext in exts:
            cand = root / f"{icon_name}{ext}"
            if cand.exists():
                return str(cand)
    name = app_id or icon_name
    rc, out, _ = proc.run(
        ["find", "/usr/share/icons", str(ICON_DIR), "-iname", f"{name}.*",
         "-o", "-iname", f"{icon_name}.*"], timeout=15
    )
    if rc == 0:
        for line in proc.lines(out):
            if line.lower().endswith((".png", ".svg", ".xpm")):
                return line
    return None


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    shutil.move(tmp, path)


def desktop_file(name, exec_line, icon=None, comment="", categories=("Utility",),
                 terminal=False, path_override=None, mime=None):
    """Create ~/.local/share/applications/<slug>.desktop and refresh the database."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower() or "app"
    target = USER_APPS / (path_override or f"{slug}.desktop")
    body = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={name}",
    ]
    if comment:
        body.append(f"Comment={comment}")
    body.append(f"Exec={exec_line}")
    if icon:
        body.append(f"Icon={icon}")
    if terminal:
        body.append("Terminal=true")
    body.append(f"Categories={';'.join(categories)};")
    if mime:
        body.append(f"MimeType={mime}")
    body.append("StartupNotify=true")
    body.append("")
    _write(target, "\n".join(body))
    refresh()
    return target


def refresh():
    if proc.which("update-desktop-database"):
        proc.run(["update-desktop-database", str(USER_APPS)], timeout=30)
    elif USER_APPS.is_dir():
        # No tool available: touch the dir mtime so menus notice.
        os.utime(USER_APPS, None)


def remove(path):
    try:
        Path(path).unlink()
    except OSError:
        return False
    refresh()
    return True


def launch(desktop_record):
    if desktop_record["terminal"] and proc.which("x-terminal-emulator"):
        return proc.run(["x-terminal-emulator", "-e", desktop_record["exec"]])
    argv = exec_argv(desktop_record["exec"])
    if not argv:
        return 1, "", _t("This app has no launch command.")
    env = {}
    if not proc.have_graphical_session():
        # Launching a GUI app headless is pointless; report instead of silently failing.
        return 1, "", _t("No graphical session detected - cannot launch apps.")
    try:
        subprocess_popen(argv, desktop_record.get("file", ""))
    except OSError as exc:
        return 126, "", str(exc)
    return 0, "", ""


def subprocess_popen(argv, desktop_path):
    import subprocess

    env = dict(os.environ)
    env["SLPM_DESKTOP_FILE"] = desktop_path
    subprocess.Popen(
        argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
