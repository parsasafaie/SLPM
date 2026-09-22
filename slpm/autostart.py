"""The programs a session starts by itself, and the files that decide it.

Two directories matter. `/etc/xdg/autostart` is where packages and the desktop
environment put their own starters, and `~/.config/autostart` is where the user's files
live. A user file with the same name as a system file wins, which is the override the
Desktop Entry Specification defines and the mechanism a desktop environment's own
"startup applications" panel uses.

Nothing here needs root and nothing deletes a file SLPM did not write. A system entry is
switched off by writing a user entry of the same name that carries `Hidden=true`, so the
packaged file stays exactly where its package put it and reinstalling that package does
not silently turn the program back on.
"""
import os
import re
import shutil
import tempfile
from pathlib import Path

from . import desktop, proc
from .i18n import tr as _tr


def _t(english, **values):
    """Translate a message into the language of the request being served."""
    return _tr(proc.lang(), english, **values)


USER_AUTOSTART = Path.home() / ".config/autostart"
SYSTEM_AUTOSTART = Path("/etc/xdg/autostart")

# SLPM's own entries carry this prefix, so adding an app can never overwrite a file the
# user or a package already put in ~/.config/autostart under a name of its own.
PREFIX = "slpm-"

# The two keys that record "do not start this". Hidden= is the spec's flag;
# X-GNOME-Autostart-enabled= is what GNOME's startup panel writes and several other
# desktops still honour, so both are maintained together.
_HIDDEN = "Hidden"
_GNOME_ENABLED = "X-GNOME-Autostart-enabled"

_TRUE = frozenset(("true", "1", "yes", "on"))
_FALSE = frozenset(("false", "0", "no", "off"))

# %f %F %u %U %d %D %n %N %i %c %k %v %m are the spec's field codes. An autostart
# command is given no file or URL to expand, so they are dropped rather than handed to a
# program that will never receive one.
_FIELD_CODE = re.compile(r"%[fFuUdDnNickvm]")


def _flag(value):
    """True/False/None for a .desktop boolean, so 'unset' is distinct from 'false'."""
    text = (value or "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return None


def is_disabled(entry):
    """Is this entry switched off?

    An entry carrying neither flag starts, which is why an absent value is not read as
    false anywhere below.
    """
    if _flag(entry.get(_HIDDEN)) is True:
        return True
    return _flag(entry.get(_GNOME_ENABLED)) is False


def clean_exec(exec_line):
    """Turn an Exec= line into a command that runs unchanged outside a menu.

    `%%` is the spec's escape for a literal percent sign, so it becomes one before the
    real field codes are removed - otherwise "echo 100%%" would lose both signs.
    """
    return _FIELD_CODE.sub("", (exec_line or "").replace("%%", "%")).strip()


def _command_ok(argv):
    """Can this command actually start something on this computer?"""
    if not argv:
        return False
    program = argv[0]
    if program.startswith("/"):
        return os.access(program, os.X_OK)
    return bool(proc.which(program))


def _slug(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-").lower() or "app"


def _body(name, command, icon="", comment=""):
    """A complete, enabled user autostart entry."""
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={name}",
    ]
    if comment:
        lines.append(f"Comment={comment}")
    lines.append(f"Exec={command}")
    if icon:
        lines.append(f"Icon={icon}")
    lines += [f"{_GNOME_ENABLED}=true", f"{_HIDDEN}=false", ""]
    return "\n".join(lines)


def _with_state(text, enabled):
    """Set both on/off flags in a .desktop body, leaving every other line alone.

    The flags are placed inside [Desktop Entry] - a file can carry further groups, such
    as desktop actions, and a key appended to the wrong group is simply ignored.
    """
    flags = {_HIDDEN: "true" if not enabled else "false",
             _GNOME_ENABLED: "true" if enabled else "false"}
    lines = (text or "").splitlines()
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip().lower() == "[desktop entry]"), None)
    if start is None:
        lines = ["[Desktop Entry]"] + lines
        start = 0
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip().startswith("[")), len(lines))

    kept, replaced = [], set()
    for line in lines[start + 1:end]:
        key = line.partition("=")[0].strip() if "=" in line else ""
        if key in flags and key not in replaced:
            kept.append(f"{key}={flags[key]}")
            replaced.add(key)
        elif key in flags:
            continue  # a repeated flag: the first one already carries the decision
        else:
            kept.append(line)
    for key in (_HIDDEN, _GNOME_ENABLED):
        if key not in replaced:
            kept.append(f"{key}={flags[key]}")

    return "\n".join(lines[:start + 1] + kept + lines[end:]) + "\n"


def _write(path, text):
    """Replace a file atomically, so a half-written entry is never read back."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w") as fh:
        fh.write(text)
    shutil.move(tmp, path)


def _collect_from(roots):
    """One record per autostart entry, later roots overriding earlier ones by file name.

    Disabled entries are listed too: a startup manager that hides what it has switched
    off gives the user no way to switch it back on.
    """
    rows = {}
    for root, source in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.desktop")):
            entry = desktop.parse(path)
            if not entry or entry.get("Type", "Application") != "Application":
                continue
            exec_line = entry.get("Exec", "")
            if not exec_line:
                continue
            icon = entry.get("Icon", "")
            rows[path.name] = {
                "id": path.name,
                "name": entry.get("Name") or path.stem,
                "comment": entry.get("Comment", ""),
                "exec": exec_line,
                "icon": icon,
                "source": source,
                "file": str(path),
                "enabled": not is_disabled(entry),
                # Only a file SLPM can write counts as removable. A system entry is
                # switched off with an override, never deleted.
                "removable": source == "user",
                "icon_url": (f"/api/icon?name={icon}&app={path.name}" if icon else ""),
            }
    return sorted(rows.values(), key=lambda r: r["name"].lower())


def collect():
    """Everything that starts with the session, the user's files overriding system ones."""
    return _collect_from(((SYSTEM_AUTOSTART, "system"), (USER_AUTOSTART, "user")))


def _find(entry_id):
    return next((r for r in collect() if r["id"] == entry_id), None)


def add(name, exec_line, icon="", comment=""):
    """Add a program to the user's startup list.

    Returns (ok, message, detail). Adding the same command twice must not produce two
    files that would start the program twice: an entry already carrying that command is
    turned on and reported instead of being duplicated.
    """
    name = (name or "").strip()
    command = clean_exec(exec_line)
    if not name:
        return False, _t("This program has no name, so it cannot be added."), ""
    if not command:
        return False, _t("This program has no command to run."), ""
    if not _command_ok(desktop.exec_argv(command)):
        return False, _t("The command for this program was not found on this "
                         "computer."), ""

    for rec in collect():
        if clean_exec(rec["exec"]) == command:
            if rec["enabled"]:
                return True, _t("{name} already starts when you log in.",
                                name=rec["name"]), ""
            ok, msg, detail = set_enabled(rec["id"], True)
            if ok:
                return True, _t("{name} will now start when you log in.", name=name), ""
            return ok, msg, detail

    target = USER_AUTOSTART / f"{PREFIX}{_slug(name)}.desktop"
    _write(target, _body(name, command, icon, comment))
    return True, _t("{name} will now start when you log in.", name=name), ""


def set_enabled(entry_id, enabled):
    """Turn one entry on or off. Returns (ok, message, detail).

    Off means "gone from the startup list": a user's own file is deleted outright, which
    is why the UI asks for confirmation first. A packaged entry cannot be deleted - its
    file belongs to a package and a reinstall would bring it straight back - so it is
    switched off with a user override of the same name instead, and that override is what
    turns it on again later.

    On means the entry is restored. A user entry that was deleted is not remembered, so
    the caller re-adds it through add(); what remains here is clearing the override that
    masked a packaged entry.
    """
    rec = _find(entry_id)
    if rec is None:
        return False, _t("This startup entry is no longer there."), ""

    if not enabled:
        if rec["source"] == "user":
            try:
                Path(rec["file"]).unlink()
            except OSError as exc:
                return False, _t("This startup entry could not be removed."), str(exc)
            return True, _t("{name} was removed from your startup apps.",
                            name=rec["name"]), ""
        try:
            text = Path(rec["file"]).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return False, _t("This startup entry could not be read."), str(exc)
        _write(USER_AUTOSTART / entry_id, _with_state(text, False))
        return True, _t("{name} will no longer start when you log in.",
                        name=rec["name"]), ""

    # Switching on: rewrite the user file in place, or clear a packaged entry's override.
    if rec["source"] == "user":
        try:
            text = Path(rec["file"]).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return False, _t("This startup entry could not be read."), str(exc)
        _write(Path(rec["file"]), _with_state(text, True))
    else:
        try:
            text = Path(rec["file"]).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return False, _t("This startup entry could not be read."), str(exc)
        _write(USER_AUTOSTART / entry_id, _with_state(text, True))
    return True, _t("{name} will now start when you log in.", name=rec["name"]), ""


def remove(entry_id):
    """Delete a user autostart file, without touching a packaged one.

    The UI turns entries off through set_enabled(), which is the same deletion for a user
    file; this stays as the explicit removal primitive and as the guard that keeps a
    packaged entry's file out of reach.
    """
    rec = _find(entry_id)
    if rec is None:
        return False, _t("This startup entry is no longer there."), ""
    if rec["source"] != "user":
        return False, _t("This entry belongs to the system and cannot be deleted. "
                         "Turn it off instead."), ""
    try:
        Path(rec["file"]).unlink()
    except OSError as exc:
        return False, _t("This startup entry could not be removed."), str(exc)
    return True, _t("{name} was removed from your startup apps.", name=rec["name"]), ""
