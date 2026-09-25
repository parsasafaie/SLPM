#!/usr/bin/env python3
"""SLPM - Simple Linux Package Manager. Flask entry point."""
import io
import logging
import os
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, make_response, render_template, request, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent))

from slpm import apps as apps_mod
from slpm import (apt, autostart, desktop, flatpak_snap, download, helper,
                  installer, i18n, proc, state)

log = logging.getLogger("slpm")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
# Cap request bodies; nothing SLPM accepts is larger than a path plus options.
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
# Flask >= 3.1 rejects requests whose Host header is not in this list. Without it a
# page on another origin can reach the local server through DNS rebinding, and every
# endpoint here acts on the user's machine. (On an older Flask the key is simply
# ignored, which is why requirements pins Flask >= 3.1.)
app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", "[::1]", "::1"]

LANG_COOKIE = "slpm_lang"
THEME_COOKIE = "slpm_theme"
MODE_COOKIE = "slpm_mode"
THEMES = ("light", "dark")
MODES = ("simple", "advanced")

_install_lock = threading.Lock()
_job = {"active": False, "label": ""}


# ---------------------------------------------------------------- ui prefs
#
# Both preferences are cookies rather than server state: the two buttons in the top
# bar are a per-browser preference, and storing them server-side would mean one
# person's choice following the next person to open the page on the same machine.

def _ui_lang():
    """The language for this request: an explicit ?lang= wins over the cookie.

    The query flag exists so the switch works on the very first load, before the
    browser has stored anything. It is never echoed into a link or a redirect, so it
    does not stick around in the address bar after the cookie takes over.
    """
    asked = request.args.get("lang")
    if asked:
        return i18n.normalize(asked)
    return i18n.normalize(request.cookies.get(LANG_COOKIE))


def _ui_theme():
    theme = (request.cookies.get(THEME_COOKIE) or "").strip().lower()
    return theme if theme in THEMES else "light"


def _ui_mode():
    """Simple or Advanced, for this request.

    A cookie like the theme and the language, and for the same reason: it is one
    person's choice on one browser, and a server-side setting would hand the next
    person to open the page a view they did not ask for.

    Simple is the default. Advanced is the view that can remove a package the machine
    needs to boot, so it has to be entered deliberately - never arrived at by opening a
    fresh browser.
    """
    mode = (request.cookies.get(MODE_COOKIE) or "").strip().lower()
    return mode if mode in MODES else "simple"


@app.before_request
def _adopt_language():
    """Make this request's language visible to every backend module.

    The contextvar is what module-level helpers (proc.t, apt._t, installer._t) read,
    so a message built deep inside a package operation comes back in the same
    language the page was loaded in.
    """
    proc.set_lang(_ui_lang())


@app.context_processor
def _template_defaults():
    lang = _ui_lang()
    return {
        "lang": lang,
        "theme": _ui_theme(),
        "mode": _ui_mode(),
        "html_lang": i18n.HTML_LANGS[lang],
        "html_dir": i18n.DIRECTIONS[lang],
        "t": lambda english, **values: i18n.tr(lang, english, **values),
    }


@app.post("/api/prefs")
def api_prefs():
    """Remember the language, theme and/or view mode choice for this browser."""
    data = request.json or {}
    resp = make_response(jsonify({"ok": True}))
    max_age = 60 * 60 * 24 * 365
    if "lang" in data:
        lang = i18n.normalize(data.get("lang"))
        resp.set_cookie(LANG_COOKIE, lang, max_age=max_age, samesite="Lax")
    if "theme" in data:
        theme = str(data.get("theme") or "").strip().lower()
        if theme in THEMES:
            resp.set_cookie(THEME_COOKIE, theme, max_age=max_age, samesite="Lax")
    if "mode" in data:
        mode = str(data.get("mode") or "").strip().lower()
        if mode in MODES:
            resp.set_cookie(MODE_COOKIE, mode, max_age=max_age, samesite="Lax")
    return resp


# ------------------------------------------------------------------ helpers

def _err(exc):
    """Never leak a traceback to the UI; log it and return an explanation.

    The exception text goes to the log only: it may carry paths or tool output that
    says nothing to the person looking at the page, and the log is where a developer
    fixing the bug will look.
    """
    log.exception("SLPM request failed")
    return jsonify({"ok": False, "message": proc.t("SLPM hit an unexpected problem.")}), 500


def _busy_reply():
    return jsonify({"ok": False, "busy": True, "label": _job["label"],
                    "message": proc.t("{label} is still running. Wait for it to finish.",
                                      label=_job["label"])}), 409


# --------------------------------------------------------------------- pages

@app.route("/")
def page_install():
    return render_template("install.html", page="install", env=_env())


@app.route("/apps")
def page_apps():
    return render_template("apps.html", page="apps", env=_env())


@app.route("/startup")
def page_startup():
    return render_template("startup.html", page="startup", env=_env())


@app.route("/updates")
def page_updates():
    return render_template("updates.html", page="updates", env=_env())


def _env():
    return {
        "is_root": os.geteuid() == 0,
        "has_pkexec": bool(proc.which("pkexec")),
        "helper_up": not helper._stale(state.HELPER_SOCK),
        "distro": _distro(),
        "managers": {
            "apt": bool(proc.which("apt-get")),
            "flatpak": bool(proc.which("flatpak")),
            "snap": bool(proc.which("snap")),
        },
    }


def _distro():
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "Linux"


# ------------------------------------------------------------------ install

@app.post("/api/detect")
def api_detect():
    try:
        info = installer.detect((request.json or {}).get("path", ""))
        return jsonify({"ok": True, **info})
    except Exception as exc:
        return _err(exc)


@app.post("/api/install")
def api_install():
    data = request.json or {}
    with _install_lock:
        # The flag and the work that guards it must be decided under the same lock:
        # two requests that both read the flag first would otherwise both start.
        if _job["active"]:
            return _busy_reply()
        _job.update(active=True, label=proc.t("Installation"))
        try:
            result = installer.install(data.get("path", ""), data.get("opts") or {})
            _log_action("install", data.get("path", ""), result.get("ok"), result.get("message"))
            return jsonify(result)
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")
            apps_mod.bust_meta_cache()
            desktop.bust_collect_cache()


@app.post("/api/helper/start")
def api_helper_start():
    try:
        ok, msg = helper.spawn(state.HELPER_SOCK, state.HELPER_LOG)
        return jsonify({"ok": ok, "message": msg})
    except Exception as exc:
        return _err(exc)


# ------------------------------------------------------ downloads

@app.get("/api/downloads")
def api_downloads():
    """Every download job and its current progress, for the status bar."""
    return jsonify({"ok": True, "downloads": download.list_status()})


@app.post("/api/download/start")
def api_download_start():
    """Start downloading a URL into the Downloads folder."""
    result = download.start((request.json or {}).get("url", ""))
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


@app.post("/api/download/control")
def api_download_control():
    """Pause, continue or stop a running download."""
    data = request.json or {}
    job_id = data.get("id", "")
    action = data.get("action", "")
    result = download.control(job_id, action)
    if result is None:
        return jsonify({"ok": False, "message": proc.t("That download is no longer running.")}), 404
    if not result.get("ok"):
        return jsonify(result), 400
    return jsonify(result)


# ------------------------------------------------------ installed (simple)

@app.get("/api/apps")
def api_apps():
    """Applications in the current view.

    The mode comes from the request, never from the client's word alone: in Simple Mode
    the server itself drops everything the user did not install, so a hand-made request
    cannot make a pre-installed app appear in the simple list.
    """
    try:
        mode = _ui_mode()
        return jsonify({"ok": True, "mode": mode, "apps": apps_mod.apps(mode)})
    except Exception as exc:
        return _err(exc)


@app.get("/api/icon")
def api_icon():
    path = desktop.icon_path(request.args.get("name", ""), request.args.get("app", ""))
    if not path or not Path(path).is_file():
        return _placeholder()
    try:
        return send_file(path)
    except OSError:
        return _placeholder()


def _placeholder():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        '<rect width="64" height="64" rx="14" fill="#e5e7eb"/>'
        '<path d="M20 24h24v4H20zm0 8h24v4H20zm0 8h16v4H20z" fill="#9ca3af"/></svg>'
    )
    return send_file(io.BytesIO(svg.encode()), mimetype="image/svg+xml")


@app.post("/api/launch")
def api_launch():
    """Launch an installed app, identified only by its list id.

    The request carries no command line: the server resolves the id against its own
    scan and runs that entry's own Exec= (or its package's manager command). Taking
    ``exec`` from the request made this endpoint a way to run any command as the user.
    """
    data = request.json or {}
    entry_id = str(data.get("id", ""))
    try:
        rc, out, err = desktop.launch_by_id(entry_id)
        if rc == 0:
            return jsonify({"ok": True, "message": proc.t("Launching.")})
        return jsonify({"ok": False, "message": proc.t("Could not start this app."),
                        "detail": err or out})
    except Exception as exc:
        return _err(exc)


@app.post("/api/uninstall")
def api_uninstall():
    """Removal of one application from the Installed Apps list.

    In Simple Mode this must be the user's own app. The check re-derives ownership from
    the server's own records instead of trusting the request, so posting the id of a
    pre-installed app cannot remove it: the app has to be found in the very list Simple
    Mode would show.
    """
    data = request.json or {}
    manager, target = data.get("manager"), data.get("target", "")
    if not target:
        return jsonify({"ok": False,
                        "message": proc.t("Nothing was named to remove.")}), 400
    if _ui_mode() != "advanced" and not _user_installed_app(data):
        return _advanced_only()
    with _install_lock:
        if _job["active"]:
            return _busy_reply()
        _job.update(active=True, label=proc.t("Removal"))
        try:
            if manager == "apt":
                ok, msg, detail = apt.uninstall(target)
            elif manager == "flatpak":
                ok, msg, detail = flatpak_snap.flatpak_uninstall(target)
            elif manager == "snap":
                ok, msg, detail = flatpak_snap.snap_uninstall(target)
            elif manager in ("appimage", "desktop"):
                ok, msg, detail = installer.uninstall_desktop_entry(data.get("file", ""))
            else:
                ok, msg, detail = False, proc.t("SLPM does not manage this item."), ""
            _log_action("uninstall", f"{manager}:{target}", ok, msg)
            return jsonify({"ok": ok, "message": msg, "detail": detail})
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")
            apps_mod.bust_meta_cache()
            desktop.bust_collect_cache()


# -------------------------------------------------------------------- startup

@app.get("/api/startup")
def api_startup():
    """Startup entries in the current view.

    Simple Mode returns only the entries the user put there themselves; the entries
    packages installed are Advanced Mode's business. The split is made here rather than
    in the browser so the simple list cannot be padded out by a hand-made request.
    """
    try:
        mode = _ui_mode()
        return jsonify({"ok": True, "mode": mode, "apps": autostart.collect(mode)})
    except Exception as exc:
        return _err(exc)


@app.get("/api/startup/candidates")
def api_startup_candidates():
    """Installed applications a startup entry could point at.

    The add dialog lists these instead of asking for a command line, so an added entry
    runs the same program the menu runs. Only entries with a launch command are offered.

    The candidates follow the current view: in Simple Mode the list offers the user's own
    apps, so the dialog cannot be used to add an app the view does not show. A launch
    command is still required either way.
    """
    try:
        rows = []
        for rec in apps_mod.apps(_ui_mode()):
            command = autostart.clean_exec(rec["exec"])
            if not command:
                continue
            rows.append({
                # The id, not the command, is what the add endpoint takes: the
                # command line is re-derived on the server, never accepted from the
                # browser.
                "id": rec["id"],
                "name": rec["name"],
                "icon": rec["icon"],
                "icon_url": rec["icon_url"],
                "comment": rec["comment"] or rec["generic"],
            })
        return jsonify({"ok": True, "apps": rows})
    except Exception as exc:
        return _err(exc)


@app.post("/api/startup/add")
def api_startup_add():
    """Add a startup entry for an installed app, identified by its list id.

    The command line is re-derived from the server's own app list and never taken
    from the request: accepting an ``exec`` field made this endpoint a way to put
    any command on the user's auto-start list. The id must belong to the current
    view, so Simple Mode cannot add an app its list does not show.
    """
    data = request.json or {}
    app_id = str(data.get("id", ""))
    try:
        rec = next((r for r in apps_mod.apps(_ui_mode()) if r["id"] == app_id), None)
        if rec is None:
            return jsonify({"ok": False,
                            "message": proc.t("This app is no longer installed.")}), 404
        ok, msg, detail = autostart.add(
            rec["name"], rec.get("exec", ""),
            rec.get("icon", ""), rec.get("comment", "") or rec.get("generic", ""),
        )
        return jsonify({"ok": ok, "message": msg, "detail": detail})
    except Exception as exc:
        return _err(exc)


@app.post("/api/startup/toggle")
def api_startup_toggle():
    """Turn one startup entry on or off.

    In Simple Mode the entry has to be one the user put there themselves. Ownership is
    re-derived from the server's own records, so posting the id of a package's entry
    cannot switch it off from Simple Mode.
    """
    data = request.json or {}
    entry_id = data.get("id", "")
    if _ui_mode() != "advanced" and autostart.user_owned(entry_id) is not True:
        return _advanced_only()
    try:
        ok, msg, detail = autostart.set_enabled(entry_id, bool(data.get("enabled")))
        return jsonify({"ok": ok, "message": msg, "detail": detail})
    except Exception as exc:
        return _err(exc)


@app.post("/api/startup/remove")
def api_startup_remove():
    data = request.json or {}
    entry_id = data.get("id", "")
    if _ui_mode() != "advanced" and autostart.user_owned(entry_id) is not True:
        return _advanced_only()
    try:
        ok, msg, detail = autostart.remove(entry_id)
        return jsonify({"ok": ok, "message": msg, "detail": detail})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------- installed (advanced)

@app.get("/api/packages")
def api_packages():
    """Every installed package - Advanced Mode only.

    This is the view that exposes libraries, drivers and core services, so it is refused
    outright outside Advanced Mode rather than filtered: a filtered package database
    would still be a package database, and the point of Simple Mode is that this list is
    not reachable at all.
    """
    if _ui_mode() != "advanced":
        return _advanced_only()
    try:
        pkgs = apt.list_installed()
        return jsonify({"ok": True, "count": len(pkgs), "packages": pkgs})
    except Exception as exc:
        return _err(exc)


def _advanced_only():
    return jsonify({"ok": False, "advanced_only": True,
                    "message": proc.t("This is only available in Advanced Mode.")}), 403


def _user_installed_app(data):
    """Is the app this removal request names one the user installed themselves?

    The request carries a removal target (a package name, a snap id, a desktop entry
    id), and the app it belongs to has to be found in the Simple list. Ownership is
    never taken from the request: an app that Simple Mode would not show is not
    removable from Simple Mode, whatever the request claims about it.
    """
    target = str(data.get("target") or "")
    file_name = str(data.get("file") or "")
    for rec in apps_mod.apps("simple"):
        if target and target in (rec.get("package"), rec.get("id")):
            return True
        if file_name and file_name == rec.get("file"):
            return True
    return False


@app.get("/api/packages/<name>")
def api_package(name):
    if _ui_mode() != "advanced":
        return _advanced_only()
    try:
        info = apt.show(name)
        if not info:
            return jsonify({"ok": False,
                            "message": proc.t("{name} is not installed.", name=name)}), 404
        info["dangerous"] = apt.is_system_package(
            name, essential=info.get("Essential", ""), priority=info.get("Priority", "")
        )
        return jsonify({"ok": True, "package": info})
    except Exception as exc:
        return _err(exc)


@app.post("/api/packages/remove")
def api_package_remove():
    if _ui_mode() != "advanced":
        return _advanced_only()
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False,
                        "message": proc.t("No package name given.")}), 400
    # The name goes on a privileged command line; a leading dash would be read as an
    # option and anything but a package name is not what the user typed to confirm.
    if not proc.is_apt_pkg(name):
        return jsonify({"ok": False,
                        "message": proc.t("This does not look like a package name: "
                                          "{name}", name=name)}), 400
    if data.get("confirmed") != name:
        return jsonify({"ok": False, "message": proc.t(
            "Confirmation text did not match the package name. Nothing was "
            "removed.")}), 400
    with _install_lock:
        if _job["active"]:
            return _busy_reply()
        _job.update(active=True, label=proc.t("Removing {name}", name=name))
        try:
            ok, msg, detail = (apt.purge if data.get("purge") else apt.uninstall)(name)
            _log_action("remove", name, ok, msg)
            return jsonify({"ok": ok, "message": msg, "detail": detail})
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")
            apps_mod.bust_meta_cache()
            desktop.bust_collect_cache()


@app.post("/api/packages/autoremove")
def api_autoremove():
    if _ui_mode() != "advanced":
        return _advanced_only()
    with _install_lock:
        if _job["active"]:
            return _busy_reply()
        _job.update(active=True, label=proc.t("Cleaning up"))
        try:
            rc, out, err = apt.autoremove()
            ok = rc == 0
            msg = proc.t("Unused dependencies were cleaned up.") if ok \
                else proc.t("Cleanup failed.")
            return jsonify({"ok": ok, "message": msg,
                            "detail": "" if ok else apt._apt_reason(out, err)})
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")
            apps_mod.bust_meta_cache()
            desktop.bust_collect_cache()


# -------------------------------------------------------- install by name

@app.get("/api/apt/search")
def api_apt_search():
    """Search the apt repositories by package name - Advanced Mode only, like the
    install it feeds."""
    if _ui_mode() != "advanced":
        return _advanced_only()
    q = (request.args.get("q") or "").strip()[:100]
    if not q:
        return jsonify({"ok": True, "results": []})
    try:
        return jsonify({"ok": True, "results": apt.search(q)})
    except Exception as exc:
        return _err(exc)


@app.post("/api/packages/install")
def api_packages_install():
    """Install a package by its repository name, through one of the three managers.

    Advanced Mode only, for the same reason as the package list: choosing from the
    repository database is the kind of system-level act the simple view stays out of.
    The name must pass the manager's own shape check (in the backend modules, so it
    holds on every privilege path), and the busy flag is taken under the lock.
    """
    if _ui_mode() != "advanced":
        return _advanced_only()
    data = request.json or {}
    manager = str(data.get("manager") or "")
    name = str(data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False,
                        "message": proc.t("No package name given.")}), 400
    if manager not in ("apt", "snap", "flatpak"):
        return jsonify({"ok": False,
                        "message": proc.t("SLPM does not manage this item.")}), 400
    with _install_lock:
        if _job["active"]:
            return _busy_reply()
        _job.update(active=True, label=proc.t("Installing {name}", name=name))
        try:
            if manager == "apt":
                ok, msg, detail = apt.install_name(name)
            elif manager == "snap":
                ok, msg, detail = flatpak_snap.snap_install(name)
            else:
                ok, msg, detail = flatpak_snap.flatpak_install(name)
            _log_action("install", f"{manager}:{name}", ok, msg)
            return jsonify({"ok": ok, "message": msg, "detail": detail})
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")
            apps_mod.bust_meta_cache()
            desktop.bust_collect_cache()


# -------------------------------------------------------------- updates

@app.get("/api/updates")
def api_updates():
    """What can be updated, by manager.

    apt reports an exact list from a dry run; flatpak and snap report the apps that
    have a newer version or revision. All three are read-only queries. Simple Mode
    gets the same lists: updating what is already installed is not an operation that
    targets anything the user does not own, and the real protections (the confirm
    dialog and the polkit password) are on the run endpoint, which both modes share.
    """
    try:
        return jsonify({
            "ok": True,
            "apt": apt.list_upgrades(),
            "flatpak": flatpak_snap.flatpak_updates(),
            "snap": flatpak_snap.snap_updates(),
            "managers": _env()["managers"],
        })
    except Exception as exc:
        return _err(exc)


@app.post("/api/updates/run")
def api_updates_run():
    """Refresh the package lists, or run one manager's update.

    Available in both modes: an update brings installed items to their newest
    version and never removes anything, so it is not gated the way install and
    removal are. The confirm dialog and the polkit password are the protections.
    """
    data = request.json or {}
    manager = str(data.get("manager") or "")
    step = str(data.get("step") or "update")
    name = str(data.get("name") or "").strip()
    version = str(data.get("version") or "").strip()
    if manager not in ("apt", "snap", "flatpak"):
        return jsonify({"ok": False,
                        "message": proc.t("SLPM does not manage this item.")}), 400
    with _install_lock:
        if _job["active"]:
            return _busy_reply()
        # With a name the run targets one row of the list instead of the whole manager;
        # the label follows so the status bar says which item is moving.
        _job.update(active=True,
                    label=proc.t("Updating {name}…", name=name) if name
                    else proc.t("Updating…"))
        try:
            if name:
                if manager == "apt":
                    ok, msg, detail = apt.upgrade_one(name, version)
                elif manager == "flatpak":
                    ok, msg, detail = flatpak_snap.flatpak_update_one(name)
                else:
                    ok, msg, detail = flatpak_snap.snap_refresh_one(name)
            elif manager == "apt" and step == "refresh":
                rc, out, err = apt.refresh_lists()
                ok = rc == 0
                msg = (proc.t("Package lists were refreshed.") if ok
                       else proc.t("Refreshing the package lists failed."))
                detail = "" if ok else apt._apt_reason(out, err)
            elif manager == "apt":
                rc, out, err = apt.do_upgrade()
                ok = rc == 0
                msg = (proc.t("System packages were updated.") if ok
                       else proc.t("Updating the system packages failed."))
                detail = "" if ok else apt._apt_reason(out, err)
            elif manager == "flatpak":
                ok, msg, detail = flatpak_snap.flatpak_update()
            else:
                ok, msg, detail = flatpak_snap.snap_refresh()
            _log_action("update", manager, ok, msg)
            return jsonify({"ok": ok, "message": msg, "detail": detail})
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")
            apps_mod.bust_meta_cache()
            desktop.bust_collect_cache()


# ------------------------------------------------------------------- status

@app.get("/api/status")
def api_status():
    return jsonify({"ok": True, "busy": _job, "env": _env()})


@app.post("/api/pick")
def api_pick():
    """Native file chooser, when one is available. Falls back to typing a path."""
    for tool in (["zenity", "--file-selection",
                  f"--title={proc.t('Choose a file to install')}"],
                 ["kdialog", "--getopenfilename", os.path.expanduser("~")]):
        if proc.which(tool[0]):
            rc, out, _ = proc.run(tool, timeout=300)
            if rc == 0 and out.strip():
                return jsonify({"ok": True, "path": out.strip()})
            return jsonify({"ok": False, "cancelled": True})
    return jsonify({"ok": False, "message": proc.t(
        "No file chooser is installed on this computer. Paste the file path "
        "instead.")})


MAX_ACTIONS_LOG = 1024 * 1024  # keep the log from growing for the life of the machine


def _log_action(kind, target, ok, message):
    """One line per package operation, rotated at about one megabyte.

    The old file is renamed, never truncated in place: a reader holding the file open
    keeps reading the old contents while the new log starts fresh.
    """
    try:
        state.CACHE.mkdir(parents=True, exist_ok=True)
        try:
            if state.ACTIONS_LOG.stat().st_size > MAX_ACTIONS_LOG:
                state.ACTIONS_LOG.replace(state.ACTIONS_LOG.with_name("actions.log.old"))
        except OSError:
            pass
        with open(state.ACTIONS_LOG, "a") as fh:
            fh.write(f"{_now()}\t{kind}\t{target}\t{'ok' if ok else 'failed'}\t"
                     f"{(message or '').splitlines()[0][:200]}\n")
    except OSError:
        pass


def _now():
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


@app.errorhandler(404)
def not_found(_):
    return jsonify({"ok": False, "message": proc.t("Unknown endpoint.")}), 404


@app.errorhandler(500)
def server_error(_):
    return jsonify({"ok": False,
                    "message": proc.t("SLPM hit an unexpected problem.")}), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("SLPM_HOST", "127.0.0.1")
    port = int(os.environ.get("SLPM_PORT", "8686"))
    try:
        from waitress import serve

        # waitress is a production WSGI server: threaded, keeps living across the
        # long package operations. The development server app.run() is the fallback
        # for a machine without it.
        print(f"SLPM running at http://{host}:{port}")
        serve(app, host=host, port=port, threads=16, ident="slpm")
    except ImportError:
        print(f"SLPM running at http://{host}:{port} (development server)")
        app.run(host=host, port=port, debug=False, threaded=True)
