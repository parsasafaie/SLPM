"""Application shortcuts (.desktop entries) management.

Simple Mode shows application shortcuts that appear in the user's menu.
Advanced Mode shows all shortcuts, including system and hidden entries.
Users can inspect details, delete shortcuts, and add custom shortcuts for any program.
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from . import desktop, proc, util

_t = proc.t

PREFIX = "slpm-"
DEFAULT_ICON = "application-x-executable"


def _clean_field(text):
    """Strip newlines and control characters to prevent corrupted .desktop keys."""
    return re.sub(r"[\r\n\x00-\x1f\x7f]", "", text or "").strip()


def _get_all_rows(fresh=False):
    """Scan all desktop directories and return records with TTL caching."""
    now = time.monotonic()
    if (
        not fresh
        and desktop._COLLECT_CACHE["rows"] is not None
        and now - desktop._COLLECT_CACHE["at"] < desktop._COLLECT_TTL
    ):
        return desktop._COLLECT_CACHE["rows"]
    rows = desktop._scan_all()
    desktop._COLLECT_CACHE["at"] = now
    desktop._COLLECT_CACHE["rows"] = rows
    return rows


def collect(mode="simple"):
    """Collect shortcut records for the requested view mode.

    mode='simple': only shortcuts that appear in the application menu.
    mode='advanced': all desktop entries, including hidden and system ones.
    """
    rows = []
    raw_entries = _get_all_rows()
    for rec in raw_entries:
        entry_id = rec["id"]
        source = rec.get("source", "system")
        user_owned = (source == "user")
        hidden = rec.get("hidden", False)
        visible = rec.get("visible", False)

        no_display = False
        try:
            p_entry = desktop.parse(rec.get("file", ""))
            no_display = (p_entry.get("NoDisplay", "").strip().lower() == "true")
        except Exception:
            pass

        if mode == "simple":
            # In simple mode, exclude explicitly hidden entries and non-menu helpers
            if hidden or no_display:
                continue
            # For system entries, must pass Desktop Entry spec menu visibility check
            if not user_owned and not visible:
                continue

        is_override = False
        if user_owned:
            for d in desktop.APP_DIRS:
                if d != desktop.USER_APPS and (d / entry_id).exists():
                    is_override = True
                    break

        item = {
            "id": entry_id,
            "name": rec.get("name") or entry_id.replace(".desktop", ""),
            "comment": rec.get("comment", "") or rec.get("generic", ""),
            "exec": rec.get("exec", ""),
            "binary": rec.get("binary", ""),
            "icon": rec.get("icon", ""),
            "icon_url": (
                f"/api/icon?name={quote(rec['icon'])}&app={quote(entry_id)}"
                if rec.get("icon")
                else ""
            ),
            "categories": rec.get("categories", []),
            "terminal": bool(rec.get("terminal")),
            "file": rec.get("file", ""),
            "source": source,
            "user_owned": user_owned,
            "is_override": is_override,
            "visible": visible,
            "hidden": bool(hidden or no_display),
            # /api/launch resolves ids against the non-hidden set, so a Hidden entry
            # would only ever answer "no longer installed" - do not offer Launch.
            "can_launch": bool(rec.get("can_launch")) and not rec.get("hidden", False),
            # A hidden entry is already out of the menu; its Delete button would either
            # do nothing (system entry) or delete the hiding marker and put the system
            # shortcut back (user marker), so it is not offered.
            "removable": not (hidden or no_display),
        }
        rows.append(item)
    return sorted(rows, key=lambda r: r["name"].lower())


def add(name, exec_line, icon="", comment="", categories=("Utility",), terminal=False):
    """Add a new desktop shortcut in ~/.local/share/applications."""
    name = _clean_field(name)
    exec_line = _clean_field(exec_line)
    icon = _clean_field(icon) or DEFAULT_ICON
    comment = _clean_field(comment)

    if not name:
        return False, _t("This program has no name, so it cannot be added."), ""
    if not exec_line:
        return False, _t("This program has no command to run."), ""

    # Quote a path that contains spaces, but only when the whole line is that one
    # path: quoting a command like "/usr/bin/python3 app.py" would fuse program and
    # argument into a single filename that does not exist.
    if (
        exec_line.startswith("/")
        and " " in exec_line
        and not (exec_line.startswith('"') or exec_line.startswith("'"))
        and Path(exec_line).exists()
    ):
        exec_line = f'"{exec_line}"'

    # If pointing to an existing file that lacks execute permission, grant it
    argv = desktop.exec_argv(exec_line)
    if argv and argv[0].startswith("/"):
        try:
            target_path = Path(argv[0])
            if target_path.is_file() and not os.access(target_path, os.X_OK):
                target_path.chmod(target_path.stat().st_mode | 0o111)
        except OSError:
            pass

    desktop.USER_APPS.mkdir(parents=True, exist_ok=True)
    slug = util.slug(name)
    base = f"{PREFIX}{slug}" if slug else f"{PREFIX}app"
    target = desktop.USER_APPS / f"{base}.desktop"
    counter = 2
    while target.exists():
        target = desktop.USER_APPS / f"{base}-{counter}.desktop"
        counter += 1

    cats = (
        tuple(c.strip() for c in categories if c.strip())
        if categories
        else ("Utility",)
    )

    desktop.desktop_file(
        name=name,
        exec_line=exec_line,
        icon=icon,
        comment=comment,
        categories=cats,
        terminal=terminal,
        path_override=target.name,
    )
    desktop.bust_collect_cache()
    return True, _t("Shortcut for {name} was created.", name=name), ""


def remove(entry_id):
    """Delete a user shortcut or hide a system shortcut from the menu."""
    entry_id = str(entry_id or "").strip()
    if not entry_id or "/" in entry_id or "\\" in entry_id or not entry_id.endswith(".desktop"):
        return False, _t("This shortcut is no longer there."), ""

    user_file = desktop.USER_APPS / entry_id
    if user_file.exists():
        try:
            entry = desktop.parse(user_file)
        except OSError as exc:
            return False, _t("The shortcut could not be removed."), str(exc)
        # A user file that carries no Exec but hides a system entry is the marker
        # remove() writes when hiding a system shortcut. Deleting it would put that
        # system shortcut back into the menu - the opposite of what was asked - so
        # the request is refused instead.
        if (
            not entry.get("Exec")
            and (desktop._is_true(entry.get("Hidden")) or desktop._is_true(entry.get("NoDisplay")))
            and any((d / entry_id).exists() for d in desktop.APP_DIRS if d != desktop.USER_APPS)
        ):
            return False, _t("This shortcut is only hidden from the menu, so there is nothing to delete."), ""
        name = entry.get("Name") or entry_id.replace(".desktop", "")
        try:
            user_file.unlink()
        except OSError as exc:
            return False, _t("The shortcut could not be removed."), str(exc)
        desktop.refresh()
        desktop.bust_collect_cache()
        return True, _t("{name} was removed from your shortcuts.", name=name), ""

    # System entry: find across scanned dirs and hide via user override
    all_rows = desktop._scan_all()
    rec = next((r for r in all_rows if r["id"] == entry_id), None)
    if rec is None:
        return False, _t("This shortcut is no longer there."), ""

    desktop.USER_APPS.mkdir(parents=True, exist_ok=True)
    override_body = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        f"Name={rec['name']}",
        "NoDisplay=true",
        "Hidden=true",
        "",
    ]
    util.atomic_write(user_file, "\n".join(override_body))
    desktop.refresh()
    desktop.bust_collect_cache()
    return True, _t("{name} was removed from your menu.", name=rec["name"]), ""
