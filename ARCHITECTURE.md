# SLPM Architecture

SLPM is a local Flask application for Linux desktops. The browser — or the native desktop window hosted by the second AppImage, which loads the same pages — is the user interface; the server detects files, performs package operations and integrates applications with the desktop environment on the same machine. It is intentionally a single-process application built from a small set of focused Python modules.

## System overview

```text
Browser / desktop window
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

- `app.py`: the web layer — Flask entry point, routes, browser preferences (cookies), JSON/HTTP details and error boundaries. It builds `/api/icon` URLs from the icon name and id each scan row carries; the URL shape is the web layer's business.
- `slpm/core.py`: the service layer between the interfaces and the domain modules — the exclusive install/removal job (`run_exclusive`), the Simple Mode ownership gate, the operation log and the environment summary. It imports no HTTP and builds no URL, so a desktop window or a CLI can call the very same logic.
- `desktop_app.py`: the desktop window — pywebview (WebKitGTK) hosting the very web interface the browser shows. It starts or reuses a local server, resolves the initial language from `--lang`, `$SLPM_LANG`, `~/.config/slpm/prefs.json` or the system locale, seeds it once through `/api/prefs` so the in-app switch keeps working, and falls back to opening the default browser when pywebview or the GUI toolkit is unavailable (`requirements-desktop.txt` lists the optional dependencies). Nothing about the UI is re-implemented, so the desktop and web apps cannot drift apart.
- `slpm/installer.py`: detects `.deb`, AppImage, Flatpak references, archives and executable files, then chooses the appropriate installation or registration path.
- `slpm/apt.py`: reads `dpkg` data and installs or removes Debian packages.
- `slpm/flatpak_snap.py`: finds installed Flatpak and Snap applications and performs their package operations.
- `slpm/appimage.py`: validates AppImages, places them under `~/Applications`, installs their icons and creates menu launchers.
- `slpm/desktop.py`: reads and writes `.desktop` files, applies path precedence, finds icons and launches an application safely by its list id.
- `slpm/apps.py`: combines desktop entries and package-manager metadata and builds the simple list according to the ownership result.
- `slpm/ownership.py`: decides whether the user installed an application or startup entry, or whether it came with the system.
- `slpm/autostart.py`: reads `/etc/xdg/autostart` and `~/.config/autostart`, adds startup applications and enables or disables each entry.
- `slpm/shortcuts.py`: the Shortcuts tab — collects the application-menu entries for each view mode from the shared desktop scan, creates user shortcuts in `~/.local/share/applications`, and removes or hides them.
- `slpm/download.py`: downloads a URL into the Downloads folder with one background thread per job, resume support and background status reporting.
- `slpm/proc.py`: the general subprocess boundary, using argument arrays, fixed timeouts, a normalised environment and structured `(return code, stdout, stderr)` results.
- `slpm/helper.py`: a short-lived Unix-socket bridge for package operations with administrator access, started through polkit or `sudo`.
- `slpm/i18n.py`: English and Persian translations, language normalisation, value interpolation and text direction.
- `slpm/state.py`: cache, operation-log, socket and helper-log paths at runtime.

## Simple and Advanced modes

View mode is a per-browser preference: the `slpm_mode` cookie is rendered onto `<html data-mode>` and remembered across visits. The default is `simple`. The first entry into Advanced Mode on each page load asks for confirmation because this mode can expose and remove system packages. The switch sits in the top bar next to the tabs and affects both Installed Apps and Startup Apps; the Install and Updates tabs have no mode switch, because they behave the same in either mode.

Capabilities are enforced on the server:

- In Simple Mode, `/api/apps` returns only applications for which `ownership.py` confirms a user install.
- In Simple Mode, `/api/startup` returns only user-owned startup entries.
- In Simple Mode, `/api/shortcuts` returns the entries that pass the menu-visibility check plus every non-hidden user-owned entry, so the user's own shortcuts stay manageable even when they would not pass it (a run-in-terminal shortcut, for example). In Advanced Mode it returns every scanned entry, including hidden ones, each marked as such.
- `/api/packages*` and `/api/apt/search` return 403 in Simple Mode. The 403 body carries an `advanced_only` flag so the browser can explain the refusal instead of showing a generic error.
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

The interface builds the add list from applications with an available launch command in the current mode. The server's add endpoint accepts only the list id of the application; the command line is re-derived from the server's own scan of that entry, never taken from the request. A hand-made request therefore cannot put an arbitrary command on the user's auto-start list. To avoid overwriting a file the user or a package already has, a new entry is written under a name such as `slpm-<name>.desktop` in `~/.config/autostart`. If the same command already exists, no duplicate entry is created; the application therefore does not start twice at login. If two names normalise to the same filename, numbering prevents a collision.

Disabling an entry depends on its source:

- A normal user file is deleted at the user's request. This includes files the user created manually and SLPM did not create.
- A packaged file, or a user file overriding a packaged entry, is never changed. SLPM creates or rewrites the user file with the same name and sets `Hidden=true` and `X-GNOME-Autostart-enabled=false` in `[Desktop Entry]`. The package's original file is untouched; the user override remains after the package is reinstalled.
- Enabling the entry again changes both keys in the user file back to `true`.

These operations do not require `root` and never launch a program. Removal only deletes a user file; a packaged entry must be disabled rather than deleted.

## Application shortcuts

`slpm/shortcuts.py` serves the Shortcuts tab from the same desktop scan the application list uses, so both views describe one set of files and a change made on one tab is visible on the other. Simple Mode shows what the applications menu shows; Advanced Mode shows every scanned entry, including hidden ones, each marked as such.

`POST /api/shortcuts/add` writes a new entry into `~/.local/share/applications` under an `slpm-` name, numbered when the name is already taken. Every field is stripped of newlines and control characters first, because a newline inside a value would inject another key into the `.desktop` file. A command that is one absolute path containing spaces is wrapped in quotes — and only that case: quoting a command like `/usr/bin/python3 app.py` as a whole would fuse program and argument into a filename that does not exist. If the command points at a file that lacks execute permission, the permission is granted. Nothing is executed and no administrator access is needed.

`POST /api/shortcuts/remove` accepts only a bare `.desktop` file name — path separators are rejected, so the request cannot reach outside the applications directory. A user file is deleted. A system entry is never modified; SLPM writes a user override with `Hidden=true` and `NoDisplay=true` — the same pattern the startup tab uses — and the entry disappears from the applications menu. Deleting that override would put the system entry back into the menu, the opposite of what was asked, so the endpoint refuses to remove a hiding marker and the page does not offer Delete for a hidden entry at all.

Launching and icons reuse the existing guarded endpoints: launch goes through `/api/launch` and its id resolution against the server's own scan, so `/api/shortcuts` reports a hidden entry as not launchable, because the launch endpoint would only answer that the app is no longer installed.

## Local file installation

### Debian packages

A `.deb` is first tried with `apt-get install` and then with `dpkg -i` if that fails. If `dpkg` opens the file but dependencies are incomplete, SLPM runs `apt-get install -f -y`. All of these commands cross the administrator boundary as argument arrays; no shell string is constructed.

### AppImages

SLPM makes the file executable and tries to open a type-2 AppImage with `--appimage-extract`. This step runs the AppImage itself, so choose a file only when you trust its source. If the file cannot be opened with the supported method, nothing is copied to `~/Applications`. After confirmation, the file is placed under `~/Applications` with a unique name, its icon is copied to the user icon directory, and a `.desktop` file is created in `~/.local/share/applications`. The application appears in the system menu, but no synthetic entry is added to the system package database. During removal, SLPM deletes the launcher, the AppImage below the user's home directory and the icon it copied itself.

### Flatpak references

The `flatpak` command is checked first. When available, a `.flatpakref` file is installed with `flatpak install -y <remote> <app-id>`.

Flatpak operations always run at user level, never as root. A root `flatpak` would install into the *system* installation — a place a per-user account cannot remove from again through this UI — so `slpm/helper.py` deliberately has no flatpak branch in its allowlist: the privilege bridge cannot be asked for a root flatpak at all.

### Archives

The archive is extracted below `~/.local/share/slpm/apps/`. Depending on its extension, SLPM uses `unzip`, `bsdtar`, `7z` or `tar`. It then searches the extracted tree for `.desktop` files and executable programs. If more than one candidate exists, the user chooses; the selected path is compared again with the real list on disk, so a fabricated browser path is not accepted.

For a discovered `.desktop` file, a relative command is converted to a real path when needed, the icon is installed in the user directory, and an `slpm-...` shortcut is created. A normal executable is added to the menu after being made executable. If the selected candidate is a `.sh` file, SLPM does not execute it; the user is told to run it in a terminal only after trusting its source.

### Executable files

A direct `.run` or `.sh` input is not executed. SLPM only sets its executable permission and registers the same file as a shortcut in `~/.local/share/applications`. Registering a script therefore does not mean trusting or automatically running it.

## Background downloads

`slpm/download.py` accepts only URLs beginning with `http://` or `https://`. The host is then checked before any connection is made: every address the name resolves to must be a public one. Loopback, private LAN, link-local (including the cloud metadata address `169.254.169.254`), reserved and unspecified ranges are refused, and a name that does not resolve is refused too — the endpoint runs with the user's rights and follows redirects, so it must not become a way to probe or pull data from the local network. Redirect hops are capped, because urllib otherwise follows them without a count.

`xdg-user-dir` determines the Downloads path; when it is unavailable, SLPM uses `~/Downloads`. The filename is derived from the URL after decoding it, then reduced to a bare file name: an encoded separator (`%2F`) used to re-introduce slashes after the split and turn a download into a write at an attacker-chosen path. Dot files, `.`/`..` and names without an extension all fall back to a generic `download` name, and a colliding name is made unique so an existing file is never overwritten.

Each `DownloadJob` has its own background thread and `threading.Lock`. The job list is protected by a short global lock. Statuses are `queued`, `running`, `paused`, `done`, `failed` and `stopped`, and each data chunk is written only after checking state under that job's lock. Pausing closes the download stream; continuing opens a fresh connection at the same byte. A full stop removes the partial file.

After receiving part of a file, the next request sends `Range: bytes=<downloaded>-`:

- `206 Partial Content` is the normal resume path. `Content-Length` is added to the existing offset and only the remaining bytes are written.
- If a resume request receives `200 OK`, the server sent the complete file. The partial file is discarded and the request is retried from the beginning without `Range`, so bytes are not duplicated.
- If the server returns `416 Range Not Satisfiable`, the partial file is emptied and the complete request is restarted without `Range`.
- Any other network or HTTP error marks the job `failed`.

The browser polls job status every second. After a job becomes `done`, if no other file is selected in the form, the saved path is sent through the same detection and installation flow. Automatic installation happens in the browser rather than in the download thread, so it uses the same install lock and validation checks. The job list keeps only the newest finished jobs: the page has already drawn a finished row by the time it is pruned, and the list (and the memory behind it) does not grow for the life of the server.

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

## Updates and install by name

Updates are a both-modes feature: an update brings installed items to their newest version and never removes anything, so the simple view is not kept out of it the way it is from the package database. Install by name works on the repository database and remains Advanced Mode only, refused with 403 in Simple Mode.

- `GET /api/updates` is read-only and reports, per manager, what can be updated: apt gives an exact list from a dry run, Flatpak and Snap give the applications that have a newer version or revision. Each snap item also carries a `running` flag from a single `/proc` scan that maps every readable process to its executable path, so the page can mark snaps that still have live processes. The manager detection flags come along so the page can explain a manager that is not installed.
- `POST /api/updates/run` takes a manager and a step. `refresh` (apt only) updates the package lists; `update` runs the manager's update. With a `name` it updates one item instead of the whole manager (for apt, pinned to the exact version the list showed); the name must pass the manager's shape check before any command is built. Every run goes through the same install lock and job state as an installation.
- A failed run reports the tail of the tool's output — the last few lines, capped in length — rather than a single line, so the browser can show the explanatory error the tool printed instead of a bare list of process ids.
- `GET /api/apt/search` searches the apt repositories by name for the install-by-name box on the Apps page.
- `POST /api/packages/install` installs a package by its repository name through one of the three managers. The name must pass the manager's shape check before the privileged command is built.

## SLPM's own update check

The top bar carries a version pill (`/api/selfupdate`, served from `slpm/selfupdate.py`) that answers one question: is there a newer release of SLPM itself, and how would the user get it? The check is read-only and free of mode gating, because it reads nothing beyond the environment and changes nothing on the system.

- The running version comes from `slpm/__init__.py`. The newest one comes from the repository's `releases/latest` API, with a timeout, a User-Agent identifying SLPM, and an honest failure: rate limits, HTTP errors and unreachable servers each become their own message instead of a generic app error.
- Which of the two published AppImages matters is decided server-side from `$APPIMAGE`, the path the AppImage runtime exports. A file name of the pinned `SLPM_*` or `SLPM-Desktop_*` shape selects the web or desktop variant; anything else - a source checkout, a renamed file - is reported `unknown`, and the answer then carries the command pairs for both variants instead of guessing.
- The commands are derived only from the release's own asset list. If the release ships `SHA256SUMS.txt` (the release workflow generates it), the download command also fetches and verifies it with `sha256sum --ignore-missing -c`. The version comparison refuses to order what it cannot parse (`release-2`, a source checkout) and reports `unknown` instead of guessing an order.

SLPM does not install its own update: replacing a running AppImage means stopping the very server that is answering the request, so the honest output of the check is two short terminal commands - one to download and verify, one to run - for the user to paste. The release workflow pins both file-name shapes and this module pins the same shapes, so a changed name on either side stops producing commands rather than producing wrong ones.

## HTTP and web interface

Flask serves the pages and static assets in `static/`. The server is waitress when it is installed — threaded, and it stays alive across the long package operations — with the Flask development server as a fallback. JSON endpoints cover browser preferences, lists, file detection, installation, downloads, launching, removal and operation status. Browser code sends paths and explicit choices, but the server revalidates archive selection, removal paths, ownership, view mode and operation inputs.

`app.py` caps request bodies with `MAX_CONTENT_LENGTH = 256 * 1024`. The allowlist of `127.0.0.1`, `localhost`, `::1` and `[::1]` is enforced twice: by `TRUSTED_HOSTS` on Flask releases that support it (3.1+) and, regardless of version, by a `before_request` hook that repeats the same check on every request, because older Flask releases ignore the setting and the DNS-rebinding guard must not depend on the Flask version that happens to be on the user's machine (the bundled AppImage ships Flask 3.1, but source runs may not).

The `docs/` directory is a static GitHub Pages site and does not depend on Flask. `docs/site.js` derives the GitHub repository from the Pages URL, falling back to `https://github.com/parsasafaie/SLPM`, and creates links to the README and architecture files on branch `main`.

## Security model

The server listens on `127.0.0.1` by default. Environment variables can change the bind address, but exposing the local service to a network or the internet is a separate, high-risk deployment decision.

- External processes use argument arrays without `shell=True`; HTTP requests also use `urllib`.
- apt/dpkg and snap operations normally require administrator access. SLPM does not store a password in a form or terminal; the request passes through polkit or `sudo`, and SLPM reads only the result.
- A name that is about to go onto a privileged command line must pass its manager's shape check in `slpm/proc.py` (`is_apt_pkg`, `is_flatpak_app_id`, `is_snap_name`) on every privilege path, so the check holds no matter which endpoint or module built the command.
- `slpm/helper.py` accepts only explicitly allowlisted `apt-get`, `dpkg` and `snap` command shapes over a restricted socket. Package names and paths are checked with a restricted pattern, and arguments that could become options or have shell-like forms are rejected.
- Flags are judged by allowlist, not denylist: each command shape accepts only the flags SLPM itself sends (for apt-get: `-y`, `-f`, `--allow-downgrades`, and removal-only `--allow-remove-essential`). A denylist can never be complete — both apt and dpkg accept `-o`, and through it a caller can hand apt a script to run as root (`DPkg::Pre-Install-Pkgs`).
- If the helper does not accept a command (refusal code 126), the main process falls back to polkit or `sudo`. That fallback is safe only because the argv it receives is always one SLPM itself built from validated input — a browser request can never choose the argv — and the polkit dialog asks a person to confirm it.
- Removing a package in Advanced Mode requires typing its exact name. If `dpkg-query` reports a package as Essential, `apt.py` adds the real `--allow-remove-essential` option only to a remove or purge command. The helper accepts this option only for removal, never for install or update.
- The AppImage removal path must stay inside the user's home directory, and launcher removal is allowed only for a `.desktop` file under `~/.local/share/applications`.
- Shortcut creation writes a user-level `.desktop` file only; it needs no administrator access and executes nothing. The remove endpoint accepts a bare file name only and stays inside `~/.local/share/applications`; system files are never modified — hiding writes a user override instead — and every field written into a generated `.desktop` file is cleaned of newlines, so a value cannot forge additional keys.
- Warnings about system components and essential packages must be taken seriously. An incorrect removal can stop programs, make the operating system unbootable or permanently break package management.

## State and concurrency

Language, theme and view mode are browser cookies. The active install or removal state and its lock live in `slpm/core.py` (`run_exclusive`); a new request receives a busy response while an operation is running. Each download job has its own thread and lock, while `_jobs_lock` only coordinates access to the job list.

This state lives in the memory of one process; there is no database or distributed lock. The architecture is suitable for one local Flask process, not a public multi-process or multi-user service.

Important paths:

- Operation logs and application cache: `~/.cache/slpm/`
- Extracted archives: `~/.local/share/slpm/apps/`
- Local application launchers: `~/.local/share/applications/`
- User startup entries: `~/.config/autostart/`
- AppImages: `~/Applications/`
- Helper socket and logs: paths defined by `slpm/state.py`
- Python dependencies: `requirements.txt`

## Packaging and distribution

SLPM ships to end users as two self-contained AppImages that GitHub Actions builds from the same release tag and attaches to it:

- `SLPM_<version>-x86_64.AppImage` — the dashboard, opened in the browser.
- `SLPM-Desktop_<version>-x86_64.AppImage` — the same dashboard hosted in a native window.

The bundling rule differs between the two, for a concrete technical reason:

**The web image** carries its interpreter. The AppDir puts a python-build-standalone CPython under `usr/` (so `sys.prefix`, the standard library and pip-installed packages all resolve inside the image), the application itself under `usr/lib/slpm` (`app.py`, `slpm/`, `templates/`, `static/`), and `flask`, `waitress` and `certifi` into the bundled site-packages. AppRun, the `slpm.desktop` entry, the 256-px PNG icon (`.DirIcon`), the AppStream metadata and the license text complete the tree. Nothing reads the distribution's interpreter or its site-packages. The bundled CA bundle (`certifi`, exported as `SSL_CERT_FILE` by AppRun) covers the HTTPS downloads SLPM's own API performs, regardless of the host's certificate layout.

- Running as the regular user: nothing installed ever runs as root. AppRun starts the Flask server under the invoking user as its own foreground child, records its pid in `~/.cache/slpm/server.pid`, waits for `127.0.0.1:8686` to answer and then opens the page with `xdg-open`; a second launch detects a live server and only reopens the page. The launcher stays alive for as long as the server runs and `wait`s on it — deliberately, because an AppImage's files only exist while its runtime does, and a server that outlived its launcher would keep running from deleted files. An exit trap makes any end of the launcher (the pid-file `kill`, Ctrl+C, a session end) take the server down with it. Privileged package operations keep the in-application design — the server asks through `pkexec`/`sudo` at the moment of the operation, via the `slpm.helper` socket bridge. AppRun deliberately sets a plain `PATH` and no `LD_LIBRARY_PATH`, so the system's `apt`, `flatpak`, `snap` and `pkexec` binaries are found and run unaffected by the bundled interpreter.

**The desktop image** deliberately runs on the host's `python3` instead of bundling one. The WebKitGTK bindings (`gi`) that paint the window are C extensions compiled for the host interpreter's ABI, so a bundled CPython could never load them on distributions shipping a different Python. What the image carries instead is the pure-Python layer (`flask`, `waitress`, `pywebview` under `usr/lib/python3`, placed on `PYTHONPATH` by `appimage/AppRun-desktop`), the application files, and its own AppStream metadata and `.desktop` entry. MarkupSafe's optional C speedups are stripped from the bundle so the pure-Python fallback import takes over on every host Python. The two host components are `python3` and WebKitGTK 4.1 — both standard on desktop installs — and when either is missing the window layer degrades to opening the browser, by design rather than failure. `appimagetool` receives an explicit `ARCH=x86_64` for this image: with no native binary inside, it cannot guess the architecture itself.

- Life cycle: there is none in the system sense — no files are written outside the user's home. The server process survives the launcher exiting (that is what the pid file is for); the desktop window's server is a daemon thread of the window's own process instead, so closing the window ends it while a dashboard-launched server keeps running. Both images detect an already-running server on the port and reuse it, which is what makes side-by-side use coherent. Updating means running the newer AppImage after stopping the old server, and uninstalling means deleting the file and stopping the server. Per-user state in `~/.cache/slpm` and software the user installed through SLPM are deliberately kept.
- Testing the packages: before upload, the workflow runs the web image in four clean containers — `ubuntu:22.04`, `debian:12`, `ubuntu:24.04` and `ubuntu:26.04` — with no system Python installed and FUSE unavailable (`--appimage-extract-and-run`, the same AppRun either way). Each run checks that the server process is the bundled interpreter, the endpoints answer, a foreign `Host` header is refused, a real HTTPS download through SLPM's own API completes, and the pid file's process dies when killed. The desktop image runs headless in three containers — `ubuntu:24.04`, `ubuntu:26.04` and `debian:13` — after APT-resolving `python3`, `python3-gi` and `gir1.2-webkit2-4.1` exactly as a target machine would: the pure-Python chain is imported under the host interpreter, the WebKitGTK binding chain is proven complete, and the extracted AppRun serves the dashboard headless. That verifies the images on the listed distributions; it is not a claim that every distribution works — older glibc versions have not been tested, and the double-click/FUSE path is exercised only in real desktop sessions.

## Verification and maintenance

`selftest.py` checks sensitive behaviour without installing or removing a package: `Exec=` parsing, desktop-entry visibility, Simple/Advanced filtering, ownership evidence and the dpkg log anchor, snap seed data, Flatpak timestamps, package safety classification, file detection, archive extraction (including archives whose paths would climb out of the destination), user-choice validation, startup flags and overrides, shortcut creation and removal (argument-preserving `Exec=` quoting, hiding markers that refuse a second removal), the name-shape validators, single-item update refusal, error-tail and running-snap detection, icon and download path guards, the helper allowlist, the real `--allow-remove-essential` option, command probing, translations in the backend and the browser, and the HTTP endpoints' refusal behaviour through Flask's test client.

Most checks are machine-independent and run anywhere. A few read this machine's real state — the dpkg log, the installed apps, the startup entries — to prove the classifier works end to end; they run by default and are skipped on a clean machine with:

```bash
source .venv/bin/activate
.venv/bin/python selftest.py
.venv/bin/python selftest.py --skip-machine   # CI mode
```

A GitHub Actions workflow (`.github/workflows/test.yml`) runs the same selftest with `--skip-machine` on Python 3.12 and 3.14 for every push and pull request, so the code is checked against the LTS Python and a clean machine, not only the developer's.

The project has no database schema or migration layer. Changes to package-manager behaviour should stay in the corresponding `slpm/` module and be covered by focused automated tests and manual review of the sensitive path before the UI or documentation is changed.
