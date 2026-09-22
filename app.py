#!/usr/bin/env python3
"""SLPM - Simple Linux Package Manager. Flask entry point."""
import io
import os
import shutil
import sys
import threading
import traceback
from pathlib import Path

from flask import Flask, jsonify, make_response, render_template, request, send_file

sys.path.insert(0, str(Path(__file__).resolve().parent))

from slpm import apps as apps_mod
from slpm import (appimage, apt, autostart, desktop, flatpak_snap, helper, installer,
                  i18n, proc, state)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

LANG_COOKIE = "slpm_lang"
THEME_COOKIE = "slpm_theme"
THEMES = ("light", "dark")

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
        "html_lang": i18n.HTML_LANGS[lang],
        "html_dir": i18n.DIRECTIONS[lang],
        "t": lambda english, **values: i18n.tr(lang, english, **values),
    }


@app.post("/api/prefs")
def api_prefs():
    """Remember the language and/or theme choice for this browser."""
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
    return resp


# ------------------------------------------------------------------ helpers

def _err(exc):
    """Never leak a traceback to the UI; log it and return an explanation."""
    traceback.print_exc()
    return jsonify({"ok": False, "message": proc.t("SLPM hit an unexpected problem."),
                    "detail": str(exc)}), 500


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
    if _job["active"]:
        return _busy_reply()
    with _install_lock:
        _job.update(active=True, label=proc.t("Installation"))
        try:
            result = installer.install(data.get("path", ""), data.get("opts") or {})
            _log_action("install", data.get("path", ""), result.get("ok"), result.get("message"))
            return jsonify(result)
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")


@app.post("/api/helper/start")
def api_helper_start():
    try:
        ok, msg = helper.spawn(state.HELPER_SOCK, state.HELPER_LOG)
        return jsonify({"ok": ok, "message": msg})
    except Exception as exc:
        return _err(exc)


# ------------------------------------------------------ installed (simple)

@app.get("/api/apps")
def api_apps():
    try:
        return jsonify({"ok": True, "apps": apps_mod.apps()})
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
    data = request.json or {}
    rec = {
        "exec": data.get("exec", ""),
        "terminal": bool(data.get("terminal")),
        "file": data.get("file", ""),
        "manager": data.get("manager", ""),
        "package": data.get("package", ""),
    }
    try:
        if rec["manager"] == "flatpak" and rec["package"]:
            rc, out, err = proc.run(["flatpak", "run", rec["package"]], timeout=20)
            if rc == 0:
                return jsonify({"ok": True, "message": proc.t("Launching.")})
        elif rec["manager"] == "snap" and rec["package"]:
            import subprocess

            subprocess.Popen(["snap", "run", rec["package"]], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return jsonify({"ok": True, "message": proc.t("Launching.")})
        rc, out, err = desktop.launch(rec)
        if rc == 0:
            return jsonify({"ok": True, "message": proc.t("Launching.")})
        return jsonify({"ok": False, "message": proc.t("Could not start this app."),
                        "detail": err or out})
    except Exception as exc:
        return _err(exc)


@app.post("/api/uninstall")
def api_uninstall():
    """One-click removal from Simple Mode."""
    data = request.json or {}
    if _job["active"]:
        return _busy_reply()
    manager, target = data.get("manager"), data.get("target", "")
    if not target:
        return jsonify({"ok": False,
                        "message": proc.t("Nothing was named to remove.")}), 400
    with _install_lock:
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


# -------------------------------------------------------------------- startup

@app.get("/api/startup")
def api_startup():
    try:
        return jsonify({"ok": True, "apps": autostart.collect()})
    except Exception as exc:
        return _err(exc)


@app.get("/api/startup/candidates")
def api_startup_candidates():
    """Installed applications a startup entry could point at.

    The add dialog lists these instead of asking for a command line, so an added entry
    runs the same program the menu runs. Only entries with a launch command are offered.
    """
    try:
        rows = []
        for rec in desktop.collect("simple"):
            command = autostart.clean_exec(rec["exec"])
            if not command:
                continue
            rows.append({
                "name": rec["name"],
                "exec": command,
                "icon": rec["icon"],
                "icon_url": (f"/api/icon?name={rec['icon']}&app={rec['id']}"
                             if rec["icon"] else ""),
                "comment": rec["comment"] or rec["generic"],
            })
        return jsonify({"ok": True, "apps": rows})
    except Exception as exc:
        return _err(exc)


@app.post("/api/startup/add")
def api_startup_add():
    data = request.json or {}
    try:
        ok, msg, detail = autostart.add(
            data.get("name", ""), data.get("exec", ""),
            data.get("icon", ""), data.get("comment", ""),
        )
        return jsonify({"ok": ok, "message": msg, "detail": detail})
    except Exception as exc:
        return _err(exc)


@app.post("/api/startup/toggle")
def api_startup_toggle():
    data = request.json or {}
    try:
        ok, msg, detail = autostart.set_enabled(data.get("id", ""),
                                                bool(data.get("enabled")))
        return jsonify({"ok": ok, "message": msg, "detail": detail})
    except Exception as exc:
        return _err(exc)


@app.post("/api/startup/remove")
def api_startup_remove():
    data = request.json or {}
    try:
        ok, msg, detail = autostart.remove(data.get("id", ""))
        return jsonify({"ok": ok, "message": msg, "detail": detail})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------- installed (advanced)

@app.get("/api/packages")
def api_packages():
    try:
        pkgs = apt.list_installed()
        return jsonify({"ok": True, "count": len(pkgs), "packages": pkgs})
    except Exception as exc:
        return _err(exc)


@app.get("/api/packages/<name>")
def api_package(name):
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
    data = request.json or {}
    if _job["active"]:
        return _busy_reply()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False,
                        "message": proc.t("No package name given.")}), 400
    if data.get("confirmed") != name:
        return jsonify({"ok": False, "message": proc.t(
            "Confirmation text did not match the package name. Nothing was "
            "removed.")}), 400
    with _install_lock:
        _job.update(active=True, label=proc.t("Removing {name}", name=name))
        try:
            ok, msg, detail = (apt.purge if data.get("purge") else apt.uninstall)(name)
            _log_action("remove", name, ok, msg)
            return jsonify({"ok": ok, "message": msg, "detail": detail})
        except Exception as exc:
            return _err(exc)
        finally:
            _job.update(active=False, label="")


@app.post("/api/packages/autoremove")
def api_autoremove():
    if _job["active"]:
        return _busy_reply()
    with _install_lock:
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


# ------------------------------------------------------------------- status

@app.get("/api/status")
def api_status():
    return jsonify({"ok": True, "busy": _job, "env": _env()})


@app.post("/api/pick")
def api_pick():
    """Native file chooser, when one is available. Falls back to typing a path."""
    for tool in (["zenity", "--file-selection", "--title=Choose a file to install"],
                 ["kdialog", "--getopenfilename", os.path.expanduser("~")]):
        if proc.which(tool[0]):
            rc, out, _ = proc.run(tool, timeout=300)
            if rc == 0 and out.strip():
                return jsonify({"ok": True, "path": out.strip()})
            return jsonify({"ok": False, "cancelled": True})
    return jsonify({"ok": False, "message": proc.t(
        "No file chooser is installed on this computer. Paste the file path "
        "instead.")})


def _log_action(kind, target, ok, message):
    try:
        state.CACHE.mkdir(parents=True, exist_ok=True)
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
    host = os.environ.get("SLPM_HOST", "127.0.0.1")
    port = int(os.environ.get("SLPM_PORT", "8686"))
    print(f"SLPM running at http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
