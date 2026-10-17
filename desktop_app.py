#!/usr/bin/env python3
"""SLPM desktop: a native window over the local SLPM server.

The desktop interface and the web interface are one thing by design: slpm/core.py
holds the behaviour, app.py+templates give it a dashboard presentation, and this
script just hosts that presentation in a real application window instead of a
browser tab. Nothing about the UI is re-implemented here, so the desktop app and
the web app can never drift apart.

How it runs:

  1. Language: --lang, then $SLPM_LANG, then ~/.config/slpm/prefs.json, then the
     system locale (fa* -> Persian, anything else -> English). The choice is sent
     to /api/prefs when the window first loads, so the webview keeps it in its
     own cookies afterwards and the switch inside the app keeps working.
  2. Server: if an SLPM server already answers on the port (one started by the
     AppImage, a running web session, another desktop window), it is reused.
     Otherwise a threaded waitress server for app.app is started as a daemon
     thread. The server lives inside this process; closing the window ends it.
  3. Window: pywebview (WebKitGTK). If pywebview is not installed, the same URL
     opens in the default browser instead and the script stays alive while its
     server runs - the browser is the fallback, not a second code path.

Optional dependency (the web app does not need it):

  pip install -r requirements-desktop.txt      # pywebview
  # plus the system WebKitGTK 4.1 runtime, which desktop distributions of
  # Debian/Ubuntu/Fedora already ship (libwebkit2gtk-4.1 / webkit2gtk4.1)

Run:

  .venv/bin/python desktop_app.py                       # window
  .venv/bin/python desktop_app.py --serve-only          # server, no GUI
  .venv/bin/python desktop_app.py --check               # probe and exit
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PREFERRED_PORT = 8686
PREFS_FILE = Path.home() / ".config" / "slpm" / "prefs.json"

try:
    import webview  # optional; the browser fallback covers machines without it
except ImportError:
    webview = None


def _import_system_gi():
    """Let the interpreter find the system's PyGObject (gi).

    Ubuntu/Debian ship python3-gi as a system package, outside a project
    virtualenv. Appending /usr/lib/python3/dist-packages at the very end of
    sys.path exposes only what the venv does not already provide - the venv's
    own site-packages keep priority - and it is what lets pywebview use the
    system WebKitGTK. If it is not there either, the window start below fails
    and the browser fallback takes over.
    """
    try:
        import gi  # noqa: F401
    except ImportError:
        candidate = "/usr/lib/python3/dist-packages"
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.append(candidate)
            import importlib

            importlib.invalidate_caches()


# ------------------------------------------------------------------- language

def resolve_default_lang():
    from slpm import i18n

    forced = (os.environ.get("SLPM_LANG") or "").strip()
    if forced:
        return i18n.normalize(forced)
    if PREFS_FILE.is_file():
        try:
            return i18n.normalize(json.loads(PREFS_FILE.read_text()).get("lang"))
        except (OSError, ValueError):
            pass
    # The system locale decides when nothing else did: a fa* system gets the
    # Persian interface, everything else the English one.
    return "fa" if (os.environ.get("LANG") or "").lower().startswith("fa") else "en"


def initial_prefs():
    """(lang, theme) the window asks for on its very first load."""
    lang = resolve_default_lang()
    theme = ""
    if PREFS_FILE.is_file():
        try:
            saved = json.loads(PREFS_FILE.read_text())
        except (OSError, ValueError):
            saved = {}
        theme = str(saved.get("theme") or "")
        if saved.get("lang"):
            from slpm import i18n

            lang = i18n.normalize(saved.get("lang"))
    from slpm import i18n

    return i18n.normalize(lang), (theme if theme in ("light", "dark") else "")


# -------------------------------------------------------------------- server

def _is_slpm(base):
    """Does the server answering on this port belong to SLPM?

    /api/status returns {"ok": true, "busy": ..., "env": ...}; anything else on
    the port - another program, a half-open socket - is not ours to reuse.
    """
    try:
        with urllib.request.urlopen(f"{base}/api/status", timeout=2) as resp:
            data = json.loads(resp.read(4096))
        return bool(data.get("ok")) and isinstance(data.get("env"), dict)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port):
    """Serve app.app on the port inside a daemon thread. Returns the thread."""
    from app import app
    from waitress import serve

    thread = threading.Thread(
        target=serve, args=(app,),
        kwargs={"host": "127.0.0.1", "port": port, "threads": 16, "ident": "slpm"},
        daemon=True, name="slpm-server")
    thread.start()
    return thread


def ensure_server():
    """Reuse a running SLPM server, or start one. Returns its base URL."""
    preferred = f"http://127.0.0.1:{PREFERRED_PORT}"
    if _is_slpm(preferred):
        print(f"{preferred} (existing server)")
        return preferred
    port = PREFERRED_PORT if _port_free(PREFERRED_PORT) else _free_port()
    base = f"http://127.0.0.1:{port}"
    start_server(port)
    deadline = time.time() + 15
    while time.time() < deadline:
        if _is_slpm(base):
            print(f"{base} (started)")
            return base
        time.sleep(0.15)
    raise RuntimeError(f"the SLPM server did not come up on {base}")


# ----------------------------------------------------------------- ui surface

def apply_prefs_once(base, lang, theme):
    """Store the initial language (and theme) as webview cookies, then reload.

    The first page load answers in the right language via ?lang=, but the API
    calls behind it would still read the cookie default until one /api/prefs
    round-trip lands; the reload makes the very first screen fully consistent.
    The switch inside the app keeps working afterwards - it writes the same
    cookie this only seeds.
    """
    payload = {"lang": lang}
    if theme:
        payload["theme"] = theme
    # The body is one JSON string literal (json.dumps of the payload text gives a
    # quoted, escaped string), which keeps the surrounding braces to just the one
    # options object - no nested literals to miscount.
    return (
        "fetch('/api/prefs',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        "body:" + json.dumps(json.dumps(payload)) + "})"
        ".finally(function(){location.reload()})"
    )


def open_window(base, lang, theme):
    """Native window via pywebview. Returns False when the window did not start."""
    _import_system_gi()
    seeded = [False]

    def on_loaded():
        if not seeded[0]:
            seeded[0] = True
            window.evaluate_js(apply_prefs_once(base, lang, theme))

    window = webview.create_window(
        "SLPM — Simple Linux Package Manager",
        url=base, width=1150, height=780, min_size=(900, 600),
        background_color="#f6f7f9",
    )
    window.events.loaded += on_loaded
    webview.start()  # blocks until the window closes; the daemon server dies with it


def open_browser(base):
    """The fallback: same URL, default browser, server stays alive meanwhile."""
    import webbrowser

    webbrowser.open(base)
    try:
        # Keep the process - and any server it hosts - alive for this session.
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(description="SLPM desktop window")
    parser.add_argument("--lang", help="en or fa (default: system locale / prefs file)")
    parser.add_argument("--serve-only", action="store_true",
                        help="run the server without any window or browser")
    parser.add_argument("--check", action="store_true",
                        help="make sure a server is up, report it, exit")
    args = parser.parse_args()

    if args.lang:
        os.environ["SLPM_LANG"] = args.lang

    base = ensure_server()
    if args.check:
        return 0
    if args.serve_only:
        print("Ctrl+C to stop.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        return 0

    lang, theme = initial_prefs()
    if webview is not None:
        try:
            open_window(base, lang, theme)
            return 0
        except Exception as exc:
            print(f"the application window did not start ({exc}) - "
                  "opening the browser instead.")
    else:
        print("pywebview is not installed - opening the browser instead "
              "(pip install -r requirements-desktop.txt).")
    open_browser(base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
