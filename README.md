# SLPM — Simple Linux Package Manager

[فارسی](README.fa.md)

A simple local web app for installing, viewing, launching, and removing Linux software without using package-manager commands directly — available either as a browser dashboard or as a native desktop window over the same dashboard.

> SLPM runs locally on your computer at `127.0.0.1:8686`.

## Features

- Simple and Advanced modes, switched from a control in the top bar on the tabs it applies to (Installed Apps, Startup Apps, and Shortcuts):
  - **Simple Mode** (the default) lists only apps that SLPM can identify as user-installed in the Installed Apps and Startup Apps tabs; the Shortcuts tab shows the entries that appear in your applications menu. This includes relevant apps from apt/dpkg, Snap, Flatpak, and local desktop entries.
  - **Advanced Mode** changes Installed Apps to the installed dpkg/apt package database, including pre-installed applications and system components, makes relevant packaged Startup Apps entries visible, and shows the Shortcuts tab every desktop entry, including hidden and system components. It is not a unified list of every software source.
  - The Install and Updates tabs are identical in both modes.
- A native desktop window: the second AppImage hosts the same dashboard in a real application window (pywebview on the system's WebKitGTK) instead of a browser tab — menu icon, taskbar presence, no browser chrome. Where WebKitGTK is missing the same image opens the browser instead, so it never loses functionality
- Telling your apps from pre-installed ones is evidence-based: SLPM reads the package managers' own records — the date each dpkg package first appears in the dpkg log, the snap seed file, and the earliest modification time of the Flatpak deployment commit directories. It does not infer ownership from where a desktop entry lives or from dpkg `.list` file dates, because those signals can mislead.
- A Startup Apps tab for viewing, adding, and turning off user-owned or packaged startup entries
- A Shortcuts tab for managing the application menu: launch an entry, inspect its details, delete your own shortcuts, and hide pre-installed ones from your menu without touching system files. You can also create a shortcut for any program — pick its file with the file chooser, then set the name, icon, category, or run-in-terminal flag
- An Updates tab (both modes) that lists what apt, Flatpak, and Snap each have available: expand a manager's list, update one item or the whole manager at once, and refresh the apt package lists. A snap that is still running is marked, and SLPM asks you to close it before updating it; a failed run shows the full error, not just a single line
- Install by name (Advanced Mode only): search the apt repositories as you type, or install an apt package, a snap, or a Flatpak app by its exact name
- Support for `.deb`, `.snap`, AppImage, `.flatpakref`, several archive formats, and `.run`/`.sh` files that can be registered without being executed — opening a local file or downloading one from a link
- Downloads run as background jobs with pause, continue and stop controls, a live progress bar, and automatic installation after completion unless another local file is already selected
- Automatic detection of available `apt`, Flatpak, and Snap tools
- English and Persian interface with light and dark themes
- Confirmations and safety warnings for package removal; system-level operations request administrator access through `pkexec` or `sudo`

## Requirements

- A Linux distribution with a desktop environment. Both released AppImages are built for **x86_64**.
  - The dashboard image bundles its own Python, so nothing needs to be installed from your repositories. Verified on Ubuntu 22.04, Debian 12, Ubuntu 24.04 and Ubuntu 26.04 (see the release notes); distributions older than those have not been tested, because they depend on the glibc version the bundled interpreter requires.
  - The desktop-window image runs on the distribution's own Python and paints with its WebKitGTK — both standard on desktop installs (Ubuntu 24.04+, Debian 13+ verified by CI; the WebKitGTK bindings must match the host Python, so on untested combinations the same image simply falls back to the browser).
- `pkexec` or `sudo` for package operations — SLPM asks for the administrator password only when an operation needs it, and the managers it drives (`apt`, Flatpak, Snap) are detected at runtime and are optional.

## Installation

Each release ships two self-contained AppImages — pick one (or both, many people run the desktop one daily and the dashboard one for a browser session):

1. Download from [Releases](https://github.com/parsasafaie/SLPM/releases/latest):
   - `SLPM_0.2.0-x86_64.AppImage` — the dashboard, opened in your browser
   - `SLPM-Desktop_0.2.0-x86_64.AppImage` — the dashboard in a native window
2. Make it executable — in the file manager's *Properties → Permissions* check *Allow executing*, or in a terminal:
   ```bash
   chmod +x SLPM-Desktop_0.2.0-x86_64.AppImage
   ```
3. Run it — double-click in the file manager, or:
   ```bash
   ./SLPM-Desktop_0.2.0-x86_64.AppImage
   ```

That's the whole installation: no root, no dependencies, nothing written system-wide. If you use [AppImageLauncher](https://github.com/TheAssassin/AppImageLauncher) or a desktop that offers it, the first run can also add SLPM to your applications menu; otherwise nothing is installed into the menu.

### Launching

The dashboard AppImage starts its local server under your own user and opens <http://127.0.0.1:8686> in your browser; launching it again detects the running server and just reopens the page. The server stays up for as long as the AppImage is running — closing the browser does not stop it. To stop SLPM:

```bash
kill "$(cat ~/.cache/slpm/server.pid)"
```

The desktop AppImage starts (or reuses) the same local server and shows the dashboard in its own window, remembering your language; the language/theme switch inside the app keeps working. Closing the window ends the server it started (a server from the dashboard AppImage keeps running, as above). Both images can run side by side — the desktop window detects an already-running server and reuses it.

Operations that need administrator access (package installation and removal, system updates) show a `pkexec` password dialog at the moment you perform them — SLPM never runs as root and never stores your password.

### Updating

Download the newer release's AppImage(s) and run instead of the old file(s). The local server keeps running the version it was started with, so stop SLPM first as shown above (a reboot has the same effect). Your settings and history (under `~/.cache/slpm`) are preserved. Delete the old AppImage files whenever you like — they are self-contained.

### Uninstalling

No uninstaller is needed: stop the server as shown above, delete the AppImage file(s), and — if you also want the operation log gone — delete `~/.cache/slpm`. Files SLPM created for you (installed applications, shortcuts, startup entries) are left in place.

### Running from source (developers)

```bash
sudo apt update && sudo apt install -y git python3 python3-venv
git clone https://github.com/parsasafaie/SLPM.git
cd SLPM
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-desktop.txt
python app.py           # dashboard: serves http://127.0.0.1:8686 — localhost only, never expose it
python desktop_app.py   # desktop window over it (needs the system WebKitGTK)
```

## Testing

```bash
source .venv/bin/activate
python selftest.py
```

The selftest is a plain script, no test framework. It covers the parsing and safety logic (Exec= handling, desktop filtering, shortcut creation and removal rules, the root helper's command allowlist, archive path checks, the HTTP endpoints' refusal behaviour, and the translation catalogs in both the backend and the browser). A few checks read this machine's real state — the dpkg log, the installed apps, the startup entries — to prove the ownership classifier works end to end. On a machine where that state is not interesting (CI, a fresh container), skip them with:

```bash
python selftest.py --skip-machine
```

## Project structure

```text
app.py                     Flask entry point — the web layer over slpm/core.py
slpm/                      The core: package and desktop-integration logic plus
                           slpm/core.py, the service layer every interface shares
                           (exclusive install job, ownership gates, operation log)
                           (ownership.py decides which software the user installed
                           and which came with the system, and download.py fetches a
                           link in the background with pause, continue and stop)
desktop_app.py             The native desktop window (pywebview) over the dashboard
templates/                 HTML templates
static/                    CSS and JavaScript assets
docs/                      GitHub Pages website
appimage/                  AppImage build inputs (AppRun and AppRun-desktop, menu
                           entries, icon, AppStream metadata)
.github/                   CI workflow (selftest) and the release workflow that
                           builds the two AppImages for each GitHub Release
selftest.py                Self-check script (no test framework needed)
requirements.txt           Python dependencies (dashboard)
requirements-desktop.txt   the desktop window's extra dependency (pywebview)
```

## License

This project is licensed under the [MIT License](LICENSE).
