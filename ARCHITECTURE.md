# SLPM Architecture

SLPM is a local Flask application for Linux desktops. The browser is the user interface; the server performs file detection, package operations and desktop integration on the same machine. It is intentionally a single-process application with a small set of focused Python modules.

## System overview

```text
Browser
  ├─ HTML/CSS templates and static JavaScript
  └─ JSON requests
       ↓
Flask application (`app.py`)
  ├─ language/theme and request context
  ├─ route validation and job locking
  └─ domain modules (`slpm/`)
       ├─ package managers: apt/dpkg, Flatpak, Snap
       ├─ local installers: AppImage, archives, scripts
       ├─ desktop-entry integration
       └─ subprocess and privileged-command boundary
```

The application does not use a database or a remote service. Package-manager commands and local filesystem changes happen on the user's Linux machine.

## Runtime flow

1. `app.py` creates the Flask application and registers request handlers.
2. A request selects its language from `?lang=` or a browser cookie; theme is also read from a cookie.
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
- `slpm/desktop.py`: parses `.desktop` files, filters entries for Simple mode and creates/updates launchers.
- `slpm/apps.py`: combines desktop entries and package-manager data into Simple and Advanced views.
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

### Archives and scripts

Supported archives are extracted below `~/.local/share/slpm/apps/`. SLPM searches the extracted tree for launchable programs or desktop entries and asks the user to choose when there is more than one candidate. `.run` and `.sh` files are not executed as arbitrary installation commands; they are treated as entries that can be registered.

## HTTP and frontend layers

Flask serves the page templates and static assets. JSON endpoints cover browser preferences, installed-application lists, file-type detection, installation, launch, removal and operation status. The frontend submits paths and explicit choices back to the server; the server repeats validation rather than trusting client-side state.

The separate `docs/` site is a static GitHub Pages website. `docs/site.js` detects the Pages repository, falls back to `https://github.com/parsasafaie/SLPM`, and creates links to repository files on branch `main`.

## Security model

The server binds to `127.0.0.1` by default and should not be exposed publicly without an intentional deployment decision. Privileged commands are passed as argument arrays, never as shell strings. `proc.py` checks executable availability, applies timeouts and captures output without shell expansion.

The helper accepts only explicitly allowlisted package-manager calls, validates package names and paths, rejects shell-like arguments, and exits after an idle timeout. Essential-package removal uses a separate confirmation path and an explicit allow-remove-essential flag. Passwords are delegated to polkit/sudo and are never stored by SLPM.

## State, files and concurrency

Language and theme are browser cookies. The current request language is held in a `ContextVar`, so concurrent requests do not overwrite one another. Installation/removal jobs are protected by a process-local lock and expose active-job status to the UI.

- User launchers and extracted archives: `~/.local/share/slpm/`
- AppImages: `~/Applications`
- Helper socket and runtime state: paths defined by `slpm/state.py`
- Source dependencies: `requirements.txt`

Because state is local and the lock is process-local, this architecture is intended for one local Flask process rather than a multi-worker public service.

## Verification and maintenance

`selftest.py` exercises desktop-entry parsing, Simple/Advanced filtering, package safety classification, archive extraction, path-choice validation, privileged-command allowlisting, command probing, human-readable sizes and translations. It avoids actually installing or removing packages. Run it after changes with:

```bash
source .venv/bin/activate
.venv/bin/python selftest.py
```

The project has no migration layer or database schema. Changes to package-manager behavior should be isolated in the corresponding `slpm/` module and covered by focused self-tests before updating the UI or documentation.
