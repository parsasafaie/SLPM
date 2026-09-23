# SLPM Architecture

SLPM is a local Flask application for Linux desktops. The browser is the user interface; the server performs file detection, package operations and desktop integration on the same machine. It is intentionally a single-process application with a small set of focused Python modules.

## System overview

```text
Browser
  ├─ HTML/CSS templates and static JavaScript
  └─ JSON requests
       ↓
Flask application (`app.py`)
  ├─ language/theme/mode and request context
  ├─ route validation, job locking, mode enforcement
  └─ domain modules (`slpm/`)
       ├─ package managers: apt/dpkg, Flatpak, Snap
       ├─ local installers: AppImage, archives, scripts
       ├─ downloads: background fetch with pause, continue and stop
       ├─ desktop-entry integration
       ├─ ownership classification (user-installed vs pre-installed)
       └─ subprocess and privileged-command boundary
```

The application does not use a database or a remote service. Package-manager commands and local filesystem changes happen on the user's Linux machine.

## Runtime flow

1. `app.py` creates the Flask application and registers request handlers.
2. A request selects its language from `?lang=` or a browser cookie; theme and view mode (`simple`/`advanced`, default `simple`) are also read from cookies.
3. `before_request` stores the normalized language in a `ContextVar`, making translations safe when requests overlap.
4. HTML routes render `templates/`; browser code in `static/js/` calls JSON endpoints for lists, detection and operations.
5. A route validates user input and delegates to the relevant module under `slpm/`.
6. The domain module checks command availability, validates paths and arguments, and calls `proc.run()` or the privileged helper.
7. Results are returned as JSON. User-facing messages are translated in the active request language.

## Main components

- `app.py`: Flask entry point, routes, request preferences, job state and error boundaries.
- `slpm/installer.py`: classifies `.deb`, AppImage, Flatpak references, archives and executable scripts, then selects the installation path.
- `slpm/apt.py`: reads apt/dpkg data and handles Debian package installation and removal.
- `slpm/flatpak_snap.py`: discovers installed Flatpak/Snap applications and performs their package operations.
- `slpm/appimage.py`: validates AppImages, places them under `~/Applications` and prepares menu launchers.
- `slpm/download.py`: fetches a URL into the Downloads folder in a background thread, resuming with an HTTP `Range` request, and reports progress for the status bar.
- `slpm/desktop.py`: parses `.desktop` files, filters entries by visibility and creates/updates launchers.
- `slpm/apps.py`: combines desktop entries and package-manager data, then keeps or drops each row according to its ownership verdict and the requested mode.
- `slpm/ownership.py`: decides, for each app and startup entry, whether the user installed it or it came with the system. See "Simple and Advanced modes".
- `slpm/autostart.py`: reads the session's autostart entries, marks each one user-owned or packaged, adds an entry for an installed application, and switches one off.
- `slpm/proc.py`: the general subprocess boundary; uses argument arrays, fixed timeouts, environment normalization and structured `(return code, stdout, stderr)` results.
- `slpm/helper.py`: short-lived Unix-socket bridge for privileged operations started through polkit or sudo.
- `slpm/i18n.py`: English/Persian translations, locale normalization, interpolation and text direction.
- `slpm/state.py`: paths for application state, logs and the helper socket.

## Installation and package flows

### Debian packages

A `.deb` is sent through the apt/dpkg path. The package operation runs with the required privilege, and the result is reported without exposing a shell. Package lists and safety classifications are read before removal.

### AppImages

An AppImage is kept in the user's application area, inspected for metadata and connected to a `.desktop` launcher so it can appear in the desktop menu. No system package database entry is created.

### Flatpak and Snap

The application checks whether `flatpak` or `snap` exists before showing or executing the corresponding operation. Unsupported managers are not offered as available actions.

### Startup applications

The Startup Apps tab lists the `.desktop` files under `/etc/xdg/autostart` (what packages and
the desktop environment start by themselves) and `~/.config/autostart` (the user's own).
A user file with the same name as a packaged one overrides it, which is the Desktop Entry
Specification's mechanism and the same one a desktop environment's own startup panel uses.

Adding an application writes `~/.config/autostart/slpm-<name>.desktop` running the same command
the application menu runs, so nothing has to be typed by hand. The name is prefixed so an entry
SLPM writes can never overwrite a file the user already had under its own name. Adding a command
that is already listed does not create a second entry, which would start the program twice.

Switching an entry off is a deletion, and the UI asks for confirmation first because the entry
then has to be added again to come back. A file SLPM wrote is removed. A packaged file cannot be
deleted - it belongs to a package, and a reinstall would restore it - so it is masked with a user
entry of the same name carrying `Hidden=true` instead. That keeps the operation free of root and
never modifies a file the system owns.

The tab performs no privileged work and never launches a program.

### Archives and scripts

Supported archives are extracted below `~/.local/share/slpm/apps/`. SLPM searches the extracted tree for launchable programs or desktop entries and asks the user to choose when there is more than one candidate. `.run` and `.sh` files are not executed as arbitrary installation commands; they are treated as entries that can be registered.

### Downloads

The Install page has two views side by side: install a file you already have, or download one from a link. Pointing it at a link starts a background download to the Downloads folder, and the download bar lists each job with a progress bar and pause, continue and stop controls.

Each job runs in its own thread and resumes from the last byte it has with an HTTP `Range` request. A server that cannot resume either rejects the range with a 416 or sends the whole file instead of the remainder (200); SLPM notices both, discards the partial file and starts again so the same bytes are never written twice. When the download finishes the file is installed automatically — its type is recognised and installed the right way — so the user does not have to find and open it.

## Simple and Advanced modes

The mode is a browser preference, like language and theme: the `slpm_mode` cookie, rendered onto `<html data-mode>`, remembered across visits. `simple` is the default — Advanced is entered, never assumed — and the first entry into it on a page asks for confirmation, because that view can remove system components. The switch sits in the top bar next to the tabs, applies to the whole application, and is shared by the Installed Apps and Startup Apps tabs (the Install tab ignores it).

What each mode shows is decided server-side, so the distinction cannot be bypassed by calling the API directly:

- `/api/apps` and `/api/startup` return only user-owned rows in Simple mode.
- The package-database endpoints (`/api/packages*`) answer 403 in Simple mode.
- `/api/uninstall` re-derives the target's ownership from the Simple list and refuses pre-installed apps; startup toggle/remove refuse entries that are not user-owned.

### How ownership is classified

The question — "did the user put this on the machine, or did it come with the OS?" — is answered from the records the package managers keep themselves, in `slpm/ownership.py`:

- **dpkg/apt**: the first date a package appears in `/var/log/dpkg.log` (including the rotated `.1`–`.3` files) is when it arrived. The earliest date in the log is the OS install *only* when the log demonstrably reaches back to it: the oldest kept file (`.3`) must be absent and the log's first line must contain the distribution installer's marker (`startup archives install`). Without that anchor — for example after the log has rotated past the OS install — every answer is "unknown" rather than a guess, and unknown entries are treated as not user-installed. A few days of slack after the anchor absorb a long installer run.
- **snap**: `/var/lib/snapd/seed/seed.yaml` lists the snaps baked into the system image; absence from the seed means installed afterwards.
- **Flatpak**: the creation time of the per-app deployment directory, compared to the OS install time.
- **autostart**: a user file with no packaged counterpart of the same name is the user's; the same name as a packaged entry is an override and follows the package; the `slpm-` prefix marks entries SLPM itself added.

For `.desktop` entries the owning package is found from the `Exec=` command via `dpkg-query -S` (resolving PATH lookups and symlinks); when the command cannot be traced (empty `Exec=`, `TryExec` binary absent), the package that ships the `.desktop` file itself is the same evidence. Snap and Flatpak entries are decided by their own managers before any dpkg lookup.

The deliberately rejected signals: which directory the `.desktop` file sits in (`apt install ./x.deb` lands in the same place as a base package), the mtime of `/var/lib/dpkg/info/*.list` (rewritten by every upgrade), and menu visibility.

## HTTP and frontend layers

Flask serves the page templates and static assets. JSON endpoints cover browser preferences, installed-application lists, file-type detection, installation, downloading, launch, removal and operation status. The frontend submits paths and explicit choices back to the server; the server repeats validation rather than trusting client-side state.

The separate `docs/` site is a static GitHub Pages website. `docs/site.js` detects the Pages repository, falls back to `https://github.com/parsasafaie/SLPM`, and creates links to repository files on branch `main`.

## Security model

The server binds to `127.0.0.1` by default and should not be exposed publicly without an intentional deployment decision. Privileged commands are passed as argument arrays, never as shell strings. `proc.py` checks executable availability, applies timeouts and captures output without shell expansion.

The helper accepts only explicitly allowlisted package-manager calls, validates package names and paths, rejects shell-like arguments, and exits after an idle timeout. Essential-package removal uses a separate confirmation path and an explicit allow-remove-essential flag. Passwords are delegated to polkit/sudo and are never stored by SLPM.

## State, files and concurrency

Language, theme and view mode are browser cookies. The current request language is held in a `ContextVar`, so concurrent requests do not overwrite one another. Installation/removal jobs are protected by a process-local lock and expose active-job status to the UI. Download jobs run one thread per job, each guarded by its own lock, and report progress through the download status so the progress bar keeps updating while a file is fetched.

- User launchers and extracted archives: `~/.local/share/slpm/`
- Startup entries added or overridden by hand: `~/.config/autostart/`
- AppImages: `~/Applications`
- Helper socket and runtime state: paths defined by `slpm/state.py`
- Source dependencies: `requirements.txt`

Because state is local and the lock is process-local, this architecture is intended for one local Flask process rather than a multi-worker public service.

## Verification and maintenance

`selftest.py` exercises desktop-entry parsing, Simple/Advanced filtering, ownership classification (synthetic dpkg logs, the installer marker, rotation past the anchor, and every real entry on the running machine), package safety classification, archive extraction, path-choice validation, startup-entry flags and overrides, privileged-command allowlisting, command probing, human-readable sizes and translations. It avoids actually installing or removing packages. Run it after changes with:

```bash
source .venv/bin/activate
.venv/bin/python selftest.py
```

The project has no migration layer or database schema. Changes to package-manager behavior should be isolated in the corresponding `slpm/` module and covered by focused self-tests before updating the UI or documentation.
