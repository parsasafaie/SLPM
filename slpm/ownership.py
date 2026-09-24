"""Which software did the user install, and which was already on the computer?

Simple Mode's whole promise is that it shows only what the user put on the machine
themselves. Deciding that is the hard part, and the obvious signals are all wrong:

  * The directory a .desktop entry lives in says nothing. `apt install ./v2rayN.deb`
    puts its entry in /usr/share/applications, exactly like a package that shipped with
    the distribution. Judging by directory would hide the user's own apps and show
    pre-installed ones.

  * The mtime of /var/lib/dpkg/info/<pkg>.list says nothing either: every upgrade
    rewrites it, so a base package updated last week looks newer than a program the
    user installed a month ago.

  * "Is it in the application menu" says nothing: Firefox and the user's own Telegram
    are both menu entries.

What does work is the record the package managers themselves keep of *when* a package
first arrived, compared against the date the operating system was installed:

  * dpkg writes every action to /var/log/dpkg.log. The first date a package appears
    there is when it first arrived on this machine. The earliest date in the whole log
    is the OS install itself - the installer's first dpkg action is the first line.

  * snapd keeps /var/lib/snapd/seed/seed.yaml, the list of snaps baked into the
    system image. A snap in the seed shipped with the OS; a snap that is not in the
    seed was installed afterwards.

  * Flatpak keeps a per-installation deployment directory whose creation time marks
    when the app arrived.

Everything is cached: the log is millions of bytes and is read once per process, and
the answer cannot change while SLPM is running without a new install happening.
"""
import re
import shutil
import time
from functools import lru_cache
from pathlib import Path

from . import proc

# dpkg rotates its log, and a machine that has been up for a while has the older
# entries in the rotated files. They are read oldest-first so the earliest date wins.
DPKG_LOGS = (
    "/var/log/dpkg.log.3",
    "/var/log/dpkg.log.2",
    "/var/log/dpkg.log.1",
    "/var/log/dpkg.log",
)

SNAP_SEED = Path("/var/lib/snapd/seed/seed.yaml")
FLATPAK_SYSTEM = Path("/var/lib/flatpak/app")
FLATPAK_USER = Path.home() / ".local/share/flatpak/app"

# A date line in dpkg.log: "2026-04-23 01:15:04 install base-files:amd64 <none> 14ubuntu6"
_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} (\w+) (\S+)")
# Only these actions mean "this package is present on the system now".
_PRESENCE_ACTIONS = frozenset(("install", "configure", "status", "unpack", "upgrade"))

# The line the distribution installer writes before it installs anything, which is what
# marks a log as beginning at the OS install rather than having been rotated past it.
_INSTALLER_MARKER = "startup archives install"

# How long a "user install" has to be after the OS install to be believed. The
# installer's own run can stretch over hours on a slow disk or a slow network, and a
# package configured just after midnight can land on the next day, so the boundary is
# deliberately generous. Five months of real data cleanly separated at zero days here;
# the slack exists for machines where the install runs longer.
_INSTALL_WINDOW_DAYS = 2

# dpkg.log only goes back so far before rotation drops the OS install out of it. When
# the earliest date we can see is not the OS install, the comparison has no anchor and
# every answer must be "unknown" rather than a guess.
_CACHE_TTL = 300.0


class _Cache:
    """A value computed once, then reused until it goes stale.

    A running SLPM can install a package, which changes the answer, so the result is
    held for a few minutes rather than forever.
    """

    def __init__(self):
        self._value = None
        self._at = 0.0

    def get(self, build):
        now = time.monotonic()
        if self._value is None or now - self._at > _CACHE_TTL:
            self._value = build()
            self._at = now
        return self._value


_log_dates = _Cache()
_seed_snaps = _Cache()
_flatpak_times = _Cache()


def _build_log_dates():
    """{package: first date seen in the dpkg log} plus the log's earliest date.

    Returns (dates, anchor). The anchor is the OS install date, or None when the log
    does not reach back far enough to contain it - in which case nothing can be
    classified, because there is no baseline to compare against.
    """
    dates = {}
    earliest = None

    files = [Path(p) for p in DPKG_LOGS if Path(p).exists()]

    # The anchor is only trustworthy when the log reaches back to the machine's very
    # first dpkg action, and two things have to hold for that:
    #
    #   * no rotated file is present. logrotate names the oldest kept file .3 and shifts
    #     the rest down, so a .3 on disk means older entries were dropped and the
    #     earliest date we can see is not the OS install.
    #   * the log's first line is the installer's own marker. The distribution installer
    #     drives dpkg through `startup archives install` before it installs anything, so
    #     that line at the top is direct evidence of where the log begins. Without it -
    #     a machine whose log has simply not been written to for a while, or a
    #     container built from a copy - the earliest date is just the earliest date.
    #
    # Both checks are cheap and both fail closed: no evidence, no anchor, and every
    # package is then reported as unclassifiable rather than guessed at.
    reached_start = False
    if files and not Path(DPKG_LOGS[0]).exists():
        try:
            with files[0].open(encoding="utf-8", errors="replace") as fh:
                reached_start = _INSTALLER_MARKER in fh.readline()
        except OSError:
            reached_start = False

    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = _LOG_LINE.match(line)
            if not m:
                continue
            date, action, package = m.group(1), m.group(2), m.group(3)
            if action not in _PRESENCE_ACTIONS:
                continue
            if earliest is None or date < earliest:
                earliest = date
            name = package.split(":", 1)[0]
            if name not in dates or date < dates[name]:
                dates[name] = date

    # The anchor is the OS install only when the log actually starts there. The first
    # line of a freshly installed machine's log is the installer's own dpkg run, so
    # "the log contains this date" is the evidence; rotation is what breaks it.
    anchor = earliest if reached_start else None
    return dates, anchor


def _build_seed_snaps():
    """Snap names baked into the system image, or None when the seed cannot be read.

    None - not an empty set - on a read failure: an unreadable seed says nothing about
    which snaps came with the image, and an empty set would silently claim that every
    snap was installed by the user. The caller treats None as "cannot tell" (see
    seeded_snap), which is what keeps Simple Mode failing closed here as everywhere else.
    """
    try:
        text = SNAP_SEED.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return set(re.findall(r"^\s*name:\s*(\S+)", text, re.M))


def _build_flatpak_times():
    """{app id: install time} for flatpak deployments, system and user.

    The layout is ``<app-id>/<arch>/<branch>/<commit>``, so the app id is the *first*
    level under the root - the level below it is the architecture (x86_64, aarch64),
    not the app. The commit directory is created when the app (or that branch) is
    installed and is not rewritten by a plain update, so its mtime is used as the
    arrival time; st_ctime is not, because on Linux it tracks metadata changes (a chmod
    moves it) rather than creation.
    """
    times = {}
    for root in (FLATPAK_SYSTEM, FLATPAK_USER):
        if not root.is_dir():
            continue
        try:
            for app_dir in root.iterdir():
                if not app_dir.is_dir():
                    continue
                best = None
                for arch_dir in app_dir.iterdir():
                    if not arch_dir.is_dir():
                        continue
                    for branch_dir in arch_dir.iterdir():
                        if not branch_dir.is_dir():
                            continue
                        for commit in branch_dir.iterdir():
                            try:
                                stamp = commit.stat().st_mtime
                            except OSError:
                                continue
                            if best is None or stamp < best:
                                best = stamp
                if best is not None:
                    times[app_dir.name] = best
        except OSError:
            continue
    return times


def _os_install_time():
    """The OS install as a unix time, for comparing with flatpak directory times."""
    dates, anchor = _log_dates.get(_build_log_dates)
    if not anchor:
        return None
    try:
        return time.mktime(time.strptime(anchor, "%Y-%m-%d"))
    except ValueError:
        return None


@lru_cache(maxsize=8192)
def installed_by_user_package(package):
    """Did the user install this dpkg package, or did it come with the OS?

    Returns True for a user install, False for a pre-installed one, and None when it
    cannot be told - an unknown package, or a machine whose log has been rotated past
    the OS install.
    """
    if not package:
        return None
    dates, anchor = _log_dates.get(_build_log_dates)
    if not anchor:
        return None
    date = dates.get(package.split(":", 1)[0])
    if not date:
        # A package with no log entry at all: dpkg never recorded installing it, which
        # means it arrived with the image rather than through the package manager.
        return False
    try:
        seen = time.mktime(time.strptime(date, "%Y-%m-%d"))
        base = time.mktime(time.strptime(anchor, "%Y-%m-%d"))
    except ValueError:
        return None
    # Same day or the next one after the OS install is still the OS install.
    return seen - base > _INSTALL_WINDOW_DAYS * 86400


def seeded_snap(snap_name):
    """Was this snap in the system image rather than installed afterwards?"""
    if not snap_name:
        return None
    seed = _seed_snaps.get(_build_seed_snaps)
    if seed is None:
        return None
    return snap_name in seed


def user_flatpak(app_id):
    """Did the user install this flatpak after the OS? None when it cannot be told."""
    if not app_id:
        return None
    times = _flatpak_times.get(_build_flatpak_times)
    created = times.get(app_id)
    if created is None:
        return None
    base = _os_install_time()
    if base is None:
        return None
    return created - base > _INSTALL_WINDOW_DAYS * 86400


def owning_package(binary):
    """The installed package that provides this program, if any.

    Exec= holds either an absolute path or a bare command name, and dpkg-query -S only
    understands paths, so a bare name is resolved on PATH first. The path is then
    resolved through any symlink, because a package may ship its executable under a
    different name than its launcher (rustdesk installs /usr/bin/rustdesk as a link into
    its own directory), and dpkg refuses to answer for a link it does not know.
    """
    if not binary:
        return None
    path = binary if binary.startswith("/") else shutil.which(binary)
    if not path:
        return None
    try:
        path = str(Path(path).resolve())
    except OSError:
        return None
    rc, out, _ = proc.run(["dpkg-query", "-S", path], timeout=20)
    if rc == 0 and ":" in out:
        return out.split(":", 1)[0].strip()
    return None


@lru_cache(maxsize=4096)
def owning_package_of_file(path):
    """The installed package that ships this exact file, or None.

    Fills the gap owning_package cannot reach: an entry whose Exec= is empty or points
    at a binary dpkg does not trace (a NoDisplay stub, a TryExec whose program is not
    installed). The .desktop file itself was still put there by a package, and dpkg
    remembers which one, so its arrival date is usable evidence either way.
    """
    if not path:
        return None
    if not Path(path).is_file():
        return None
    rc, out, _ = proc.run(["dpkg-query", "-S", str(path)], timeout=20)
    if rc == 0 and ":" in out:
        return out.split(":", 1)[0].strip()
    return None


def classify_desktop_entry(entry):
    """Is the application behind this .desktop entry the user's own install?

    Returns (user_installed, reason). `reason` is a short machine-readable tag naming
    the evidence, which the UI does not show but tests and debugging do.

    The decision follows where the entry came from, not where the file sits:

      * a snap or flatpak export is decided by that manager's own record;
      * an apt-backed entry is decided by the package that owns its command - or, when
        the command cannot be traced (empty Exec=, TryExec binary absent), by the
        package that ships the .desktop file itself;
      * anything else - an AppImage SLPM placed, a shortcut with no owning package -
        is the user's, because nothing else could have put it there.
    """
    provided_by = entry.get("provided_by") or ""
    if provided_by.startswith("snap:"):
        snap = provided_by.split(":", 1)[1]
        verdict = seeded_snap(snap)
        if verdict is None:
            return None, "snap-unknown"
        return (not verdict), ("snap-seeded" if verdict else "snap-added")
    if provided_by.startswith("flatpak:"):
        app_id = provided_by.split(":", 1)[1]
        verdict = user_flatpak(app_id)
        if verdict is None:
            return None, "flatpak-unknown"
        return verdict, ("flatpak-added" if verdict else "flatpak-base")

    # Prefer a package the caller already resolved; otherwise resolve it here, so a
    # caller that only has the raw desktop record still gets a correct answer.
    package = (entry.get("package")
               or owning_package(entry.get("binary", ""))
               or owning_package_of_file(entry.get("file", "")))
    if package:
        verdict = installed_by_user_package(package)
        if verdict is None:
            return None, "package-unknown"
        return verdict, ("package-added" if verdict else "package-base")

    # No package owns it. A .desktop file SLPM itself wrote for an AppImage, or one the
    # user dropped in by hand, is by definition not part of the distribution.
    if entry.get("source") == "user":
        return True, "user-file"
    return None, "unowned"


def classify_startup_entry(entry):
    """Is this startup entry one the user put there themselves?

    Returns (user_owned, reason). The rule is the override rule itself, which is what
    makes it trustworthy: a file in ~/.config/autostart with no /etc/xdg/autostart
    counterpart of the same name cannot have come from a package, because packages write
    to /etc/xdg/autostart. A user file that *does* shadow a packaged one is an override
    of that packaged entry, so it follows the package's ownership rather than the user's.

    An entry drawn from /etc/xdg/autostart is always pre-existing: only a package or the
    desktop environment can put a file there.
    """
    if entry.get("source") == "system":
        return False, "packaged"
    if entry.get("source") != "user":
        return None, "unknown-source"
    if entry.get("_shadows_packaged"):
        return False, "override-of-packaged"
    if entry.get("_slpm_added"):
        return True, "slpm-added"
    return True, "user-owned"


def os_install_date():
    """The date the operating system was installed, or None when it cannot be read."""
    _, anchor = _log_dates.get(_build_log_dates)
    return anchor


def reset_cache():
    """Forget everything cached. Used by the self-test, which fakes the log files."""
    _log_dates._value = None
    _log_dates._at = 0.0
    _seed_snaps._value = None
    _seed_snaps._at = 0.0
    _flatpak_times._value = None
    _flatpak_times._at = 0.0
    installed_by_user_package.cache_clear()
    owning_package_of_file.cache_clear()
