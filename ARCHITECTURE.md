# SLPM Architecture

SLPM is a local Flask application for Linux desktops. The browser is the user interface; the server detects files, performs package operations and integrates applications with the desktop environment on the same machine. It is intentionally a single-process application built from a small set of focused Python modules.

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

The application has no database or remote service. Package-manager commands and local filesystem changes happen on the user's Linux machine.

## Runtime flow and language

1. `app.py` creates the Flask application and registers page and API routes.
2. Each request first takes its language from `?lang=` and then from the browser cookie, normalising it to `en` or `fa`. Theme and view mode are also read from cookies; the default mode is `simple`.
3. `before_request` calls `proc.set_lang()`. `slpm/proc.py` stores the language in a `ContextVar`, so i18n remains scoped to that Flask request and concurrent requests do not overwrite one another's language.
4. The `context_processor` gives templates the same language, theme, text direction and translation function. JSON messages are also created in the language of the request.
5. HTML routes render templates in `templates/`, while JavaScript in `static/js/` sends JSON requests for lists, detection and operations.
6. Each route validates its input and delegates the work to the relevant module in `slpm/`. The module checks command availability, paths and arguments before calling `proc.run()` or the privileged helper.
7. The normal result is JSON. Errors are shown to the user without exposing a traceback in the interface.

A background download thread does not inherit the Flask request's `ContextVar`; it must remain independent of request state. The other server modules use the language registered in `proc.lang()`.

## Main components

- `app.py`: Flask entry point, routes, browser preferences, installation and removal job state, and error boundaries.
- `slpm/installer.py`: detects `.deb`, AppImage, Flatpak references, archives and executable files, then chooses the appropriate installation or registration path.
- `slpm/apt.py`: reads `dpkg` data and installs or removes Debian packages.
- `slpm/flatpak_snap.py`: finds installed Flatpak and Snap applications and performs their package operations.
- `slpm/appimage.py`: validates AppImages, places them under `~/Applications`, installs their icons and creates menu launchers.
- `slpm/desktop.py`: reads and writes `.desktop` files, applies path precedence, finds icons and launches an application safely by its list id.
- `slpm/apps.py`: combines desktop entries and package-manager metadata and builds the simple list according to the ownership result.
- `slpm/ownership.py`: decides whether the user installed an application or startup entry, or whether it came with the system.
- `slpm/autostart.py`: reads `/etc/xdg/autostart` and `~/.config/autostart`, adds startup applications and enables or disables each entry.
- `slpm/download.py`: downloads a URL into the Downloads folder with one background thread per job, resume support and background status reporting.
- `slpm/proc.py`: the general subprocess boundary, using argument arrays, fixed timeouts, a normalised environment and structured `(return code, stdout, stderr)` results.
- `slpm/helper.py`: a short-lived Unix-socket bridge for package operations with administrator access, started through polkit or `sudo`.
- `slpm/i18n.py`: English and Persian translations, language normalisation, value interpolation and text direction.
- `slpm/state.py`: cache, operation-log, socket and helper-log paths at runtime.

## Simple and Advanced modes

View mode is a per-browser preference: the `slpm_mode` cookie is rendered onto `<html data-mode>` and remembered across visits. The default is `simple`. The first entry into Advanced Mode on each page load asks for confirmation because this mode can expose and remove system packages. The switch sits in the top bar next to the tabs and affects both Installed Apps and Startup Apps; the Install tab has no mode switch.

Capabilities are enforced on the server:

- In Simple Mode, `/api/apps` returns only applications for which `ownership.py` confirms a user install.
- In Simple Mode, `/api/startup` returns only user-owned startup entries.
- `/api/packages*` endpoints return 403 in Simple Mode.
- In Advanced Mode, the Installed Apps page uses `/api/packages` and shows the installed `dpkg`/`apt` packages, including pre-installed applications, libraries, system components and essential packages. Startup Apps collects both user entries and entries supplied by system packages.
- Advanced Mode is not a unified list of every software source. The Installed Apps list is specifically the `dpkg`/`apt` package list, not a complete database of every package source.
- In Simple Mode, `/api/uninstall` derives the target's ownership again from the simple list and rejects pre-installed applications. Startup enable and disable paths reject entries that are not user-owned.

When the evidence is insufficient, the result is `unknown`; SLPM does not guess, so an application or startup entry with an unknown result is not shown in Simple Mode.

## Ownership classification

The central question is whether the user added the application after installing the operating system or whether it was part of the initial system image. `slpm/ownership.py` answers it from records kept by the package managers and stores a short, testable reason for each decision.

### dpkg and apt

- `dpkg` records package operations in `/var/log/dpkg.log` and rotated files `.1` through `.3`. For a package, the oldest appearance in an `install`, `configure`, `status`, `unpack` or `upgrade` operation is its first appearance.
- The operating-system installation date is accepted only when the log can be shown to reach back to it: `/var/log/dpkg.log.3` must be absent and the first line of the oldest remaining log must contain the `startup archives install` marker.
- If rotation has lost that starting point, or the marker is not on the first line, the base date is `unknown` and all `dpkg` packages remain unclassified.
- A package seen more than two days after the base date is considered user-installed. The margin allows for an initial installation that took a long time on a slow disk or network. A package with no appearance in the log is treated as part of the initial image.

To connect a `.desktop` file to a package, the `Exec=` command is first resolved through `PATH`, its symlink is converted to the real path, and `dpkg-query -S` is run. If the command cannot be traced, the package that supplied the `.desktop` file is the same valid evidence. The apt path deliberately does not use misleading signals such as the file's location or the mtime of `/var/lib/dpkg/info/*.list` files.

### Snap

`/var/lib/snapd/seed/seed.yaml` contains the snaps baked into the initial system image. A snap listed there came with the operating system; a snap absent from the list was installed afterwards and is considered user-installed. If the seed cannot be read, the result is `unknown`; SLPM does not invent an empty seed.

### Flatpak

For each application, SLPM finds the earliest modification time (`mtime`) among the deployment commit directories under `/var/lib/flatpak/app` and `~/.local/share/flatpak/app`. The layout is `<app-id>/<arch>/<branch>/<commit>`, and the commit directory is created during deployment. This time is valid only when a valid operating-system anchor from `dpkg` is available; as with `dpkg` packages, an installation more than two days after that anchor indicates a user install.

### Local files and startup apps

- A user `.desktop` file with no owning package, such as an AppImage registered by SLPM or a manual shortcut, is considered user-installed.
- Files in `/etc/xdg/autostart` belong to a package or the desktop environment.
- A user file with the same name as a packaged file is an override and follows the package; for SLPM, it is not considered user-owned.
- A user file without a packaged file of the same name belongs to the user. The `slpm-` prefix identifies entries added by SLPM.

## Startup applications

`slpm/autostart.py` reads `/etc/xdg/autostart` and `~/.config/autostart` in priority order. Results are keyed by filename, so a user file with the same name takes precedence over a packaged file. Disabled entries remain listed so they can be enabled again.

The interface builds the add list from applications with an available launch command in the current mode. The server's add endpoint accepts a name and command directly, but strips standard `.desktop` field codes and verifies that the command exists on the system before writing a file. To avoid overwriting a file the user or a package already has, a new entry is written under a name such as `slpm-<name>.desktop` in `~/.config/autostart`. If the same command already exists, no duplicate entry is created; the application therefore does not start twice at login. If two names normalise to the same filename, numbering prevents a collision.

Disabling an entry depends on its source:

- A normal user file is deleted at the user's request. This includes files the user created manually and SLPM did not create.
- A packaged file, or a user file overriding a packaged entry, is never changed. SLPM creates or rewrites the user file with the same name and sets `Hidden=true` and `X-GNOME-Autostart-enabled=false` in `[Desktop Entry]`. The package's original file is untouched; the user override remains after the package is reinstalled.
- Enabling the entry again changes both keys in the user file back to `true`.

These operations do not require `root` and never launch a program. Removal only deletes a user file; a packaged entry must be disabled rather than deleted.

## Local file installation

### Debian packages

A `.deb` is first tried with `apt-get install` and then with `dpkg -i` if that fails. If `dpkg` opens the file but dependencies are incomplete, SLPM runs `apt-get install -f -y`. All of these commands cross the administrator boundary as argument arrays; no shell string is constructed.

### AppImages

SLPM makes the file executable and tries to open a type-2 AppImage with `--appimage-extract`. This step runs the AppImage itself, so choose a file only when you trust its source. If the file cannot be opened with the supported method, nothing is copied to `~/Applications`. After confirmation, the file is placed under `~/Applications` with a unique name, its icon is copied to the user icon directory, and a `.desktop` file is created in `~/.local/share/applications`. The application appears in the system menu, but no synthetic entry is added to the system package database. During removal, SLPM deletes the launcher, the AppImage below the user's home directory and the icon it copied itself.

### Flatpak references

The `flatpak` command is checked first. When available, a `.flatpakref` file is installed with `flatpak install -y --from`. Flatpak operations normally run at user level, but the current installation path still crosses the general privilege boundary and may request administrator access.

### Archives

The archive is extracted below `~/.local/share/slpm/apps/`. Depending on its extension, SLPM uses `unzip`, `bsdtar`, `7z` or `tar`. It then searches the extracted tree for `.desktop` files and executable programs. If more than one candidate exists, the user chooses; the selected path is compared again with the real list on disk, so a fabricated browser path is not accepted.

For a discovered `.desktop` file, a relative command is converted to a real path when needed, the icon is installed in the user directory, and an `slpm-...` shortcut is created. A normal executable is added to the menu after being made executable. If the selected candidate is a `.sh` file, SLPM does not execute it; the user is told to run it in a terminal only after trusting its source.

### Executable files

A direct `.run` or `.sh` input is not executed. SLPM only sets its executable permission and registers the same file as a shortcut in `~/.local/share/applications`. Registering a script therefore does not mean trusting or automatically running it.

## Background downloads

`slpm/download.py` accepts only URLs beginning with `http://` or `https://`. `xdg-user-dir` determines the Downloads path; when it is unavailable, SLPM uses `~/Downloads`. The filename is derived from the URL and made unique if necessary so an existing file is not overwritten.

Each `DownloadJob` has its own background thread and `threading.Lock`. The job list is protected by a short global lock. Statuses are `queued`, `running`, `paused`, `done`, `failed` and `stopped`, and each data chunk is written only after checking state under that job's lock. Pausing closes the download stream; continuing opens a fresh connection at the same byte. A full stop removes the partial file.

After receiving part of a file, the next request sends `Range: bytes=<downloaded>-`:

- `206 Partial Content` is the normal resume path. `Content-Length` is added to the existing offset and only the remaining bytes are written.
- If a resume request receives `200 OK`, the server sent the complete file. The partial file is discarded and the request is retried from the beginning without `Range`, so bytes are not duplicated.
- If the server returns `416 Range Not Satisfiable`, the partial file is emptied and the complete request is restarted without `Range`.
- Any other network or HTTP error marks the job `failed`.

The browser polls job status every second. After a job becomes `done`, if no other file is selected in the form, the saved path is sent through the same detection and installation flow. Automatic installation happens in the browser rather than in the download thread, so it uses the same install lock and validation checks.

## Application list and safe launching

`slpm/desktop.py` reads the directories that the desktop environment searches for application-menu entries:

- `~/.local/share/applications`
- `/usr/local/share/applications`
- `/usr/share/applications`
- `/var/lib/snapd/desktop/applications`
- `/var/lib/flatpak/exports/share/applications`
- `~/.local/share/flatpak/exports/share/applications`

Records are merged by filename, with higher-priority paths replacing lower-priority ones. The Simple list also checks the visibility requirements in the Desktop Entry Specification: type, `Name`, `Exec`, `Icon`, `NoDisplay`, `Hidden`, environment restrictions and command executability. Snap and Flatpak records come from their own `.desktop` files, so runtime and base snaps without a visible shortcut do not automatically become applications.

`POST /api/launch` never accepts an executable command from the browser. It carries only the `.desktop` id, which `desktop.launch_by_id()` resolves against the server's own complete scan. The matching `Exec=` command is then launched as an argument array without a shell; Snap applications use `snap run` and Flatpak applications use `flatpak run`. A hand-crafted request therefore cannot ask the server to run an arbitrary command as the user.

`/api/icon` maps `Icon=` to a real file. Absolute values and fallback search results are resolved and must remain inside the known standard icon directories. Accepted extensions are `.png`, `.svg` and `.xpm`. If no valid file is found, the endpoint returns a placeholder image.

## HTTP and web interface

Flask serves the pages and static assets in `static/`. JSON endpoints cover browser preferences, lists, file detection, installation, downloads, launching, removal and operation status. Browser code sends paths and explicit choices, but the server revalidates archive selection, removal paths, ownership, view mode and operation inputs.

`app.py` caps request bodies with `MAX_CONTENT_LENGTH = 256 * 1024`. When the installed Flask version supports it, `TRUSTED_HOSTS` accepts only `127.0.0.1`, `localhost`, `::1` and `[::1]`. This prevents a page on the internet from reaching the local service with an invalid `Host` header.

The `docs/` directory is a static GitHub Pages site and does not depend on Flask. `docs/site.js` derives the GitHub repository from the Pages URL, falling back to `https://github.com/parsasafaie/SLPM`, and creates links to the README and architecture files on branch `main`.

## Security model

The server listens on `127.0.0.1` by default. Environment variables can change the bind address, but exposing the local service to a network or the internet is a separate, high-risk deployment decision.

- External processes use argument arrays without `shell=True`; HTTP requests also use `urllib`.
- apt/dpkg and snap operations normally require administrator access. SLPM does not store a password in a form or terminal; the request passes through polkit or `sudo`, and SLPM reads only the result.
- `slpm/helper.py` accepts only explicitly allowlisted `apt-get`, `dpkg` and `snap` command shapes over a restricted socket. Package names and paths are checked with a restricted pattern, and arguments that could become options or have shell-like forms are rejected.
- Flags such as `--force-yes`, `--force-all` and `--force-remove-essential` are rejected. If the helper does not accept a command, the main process falls back to polkit or `sudo`; the helper allowlist therefore does not cover every possible invocation.
- Removing a package in Advanced Mode requires typing its exact name. If `dpkg-query` reports a package as Essential, `apt.py` adds the real `--allow-remove-essential` option only to a remove or purge command. The helper accepts this option only for removal, never for install or update.
- The AppImage removal path must stay inside the user's home directory, and launcher removal is allowed only for a `.desktop` file under `~/.local/share/applications`.
- Warnings about system components and essential packages must be taken seriously. An incorrect removal can stop programs, make the operating system unbootable or permanently break package management.

## State and concurrency

Language, theme and view mode are browser cookies. The active install or removal state is held in a process-local variable and protected by `_install_lock`; a new request receives a busy response while an operation is running. Each download job has its own thread and lock, while `_jobs_lock` only coordinates access to the job list.

This state lives in the memory of one process; there is no database or distributed lock. The architecture is suitable for one local Flask process, not a public multi-process or multi-user service.

Important paths:

- Operation logs and application cache: `~/.cache/slpm/`
- Extracted archives: `~/.local/share/slpm/apps/`
- Local application launchers: `~/.local/share/applications/`
- User startup entries: `~/.config/autostart/`
- AppImages: `~/Applications/`
- Helper socket and logs: paths defined by `slpm/state.py`
- Python dependencies: `requirements.txt`

## Verification and maintenance

`selftest.py` checks sensitive behaviour without installing or removing a package: `Exec=` parsing, desktop-entry visibility, Simple/Advanced filtering, ownership evidence and the dpkg log anchor, snap seed data, Flatpak timestamps, package safety classification, file detection, archive extraction, user-choice validation, startup flags and overrides, the helper allowlist, the real `--allow-remove-essential` option, command probing and translations.

Run it after every change with:

```bash
source .venv/bin/activate
.venv/bin/python selftest.py
```

The project has no database schema or migration layer. Changes to package-manager behaviour should stay in the corresponding `slpm/` module and be covered by focused automated tests and manual review of the sensitive path before the UI or documentation is changed.
