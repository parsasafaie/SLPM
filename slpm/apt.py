"""apt / dpkg backend."""
import re
from functools import lru_cache
from pathlib import Path

from . import proc
from .i18n import tr as _tr


def _t(english, **values):
    """Translate a message into the language of the request being served."""
    return _tr(proc.lang(), english, **values)


HEADER = {"Package", "Status", "Version", "Architecture", "Maintainer", "Installed-Size",
          "Description", "Homepage", "Section", "Priority", "Depends", "Recommends",
          "Suggests", "Conflicts", "Replaces", "Provides", "Essential", "Source",
          "Original-Maintainer", "Task", "Multi-Arch", "Breaks", "Enhances", "Pre-Depends"}

# Packages that are plumbing, not apps. Nothing here is a candidate for "uninstall
# this because I don't use it" from a Windows migrant's point of view.
#
#   is_system_package()  - "would removing this break the machine?" Used to decide what
#                          Simple Mode hides and what deserves a warning. It never hides
#                          the Remove button: Advanced Mode offers removal for every
#                          package, and the typed confirmation is the guard.
#
# This matters because the earlier single heuristic flagged 66% of the system, including
# things like vlc and gimp, and used that to hide the Remove button in Advanced Mode -
# the one view whose entire purpose is removing packages.
_PROTECTED_PREFIXES = (
    "lib", "linux-image", "linux-headers", "linux-modules", "linux-generic",
    "linux-firmware", "linux-base", "linux-libc-dev", "linux-signed",
    "grub", "shim", "systemd", "init", "dbus", "apt", "dpkg", "base-", "coreutils",
    "bash", "dash", "util-linux", "mount", "login", "passwd", "sudo", "pkexec",
    "policykit", "polkit", "udev", "kmod", "procps", "kbd", "console-setup",
    "python3", "perl", "gcc", "g++", "make", "binutils", "x11-", "xserver",
    "wayland", "mesa", "gnome-shell", "gnome-session", "plasma-", "kwin",
    "network-manager", "pulseaudio", "pipewire", "gdm", "sddm", "lightdm",
)
_PROTECTED_EXACT = {
    "ubuntu-minimal", "ubuntu-standard", "ubuntu-desktop", "ubuntu-desktop-minimal",
    "kubuntu-desktop", "xubuntu-desktop", "debian-systemd", "essential-packages",
    "gnome-control-center", "sudo", "openssh-server", "ca-certificates",
}

# Packages whose removal destroys package management itself. They are still offered a
# Remove button like everything else; this set only sharpens the warning shown for them.
_NEVER_REMOVE = {"apt", "dpkg", "libc6", "base-files", "base-passwd", "dash",
                 "coreutils", "debconf", "dpkg-dev"}


def is_system_package(name, essential="", priority=""):
    """Would a normal user consider this part of the operating system itself?"""
    low = (name or "").lower()
    if essential in ("yes", "true") or priority in ("required", "important"):
        return True
    if low in _PROTECTED_EXACT or low in _NEVER_REMOVE:
        return True
    return any(low.startswith(p) for p in _PROTECTED_PREFIXES)


def list_installed():
    """All installed packages via dpkg-query. Returns list of dicts."""
    fields = "Package,Version,Architecture,Status,Installed-Size,Section,Priority," \
             "Essential,Maintainer,Homepage,Summary"
    rc, out, err = proc.run(
        ["dpkg-query", "-W", "-f",
         "${Package}\\t${Version}\\t${Architecture}\\t${Status}\\t${Installed-Size}\\t"
         "${Section}\\t${Priority}\\t${Essential}\\t${Maintainer}\\t${Homepage}\\t"
         "${binary:Summary}\\n"],
        timeout=120,
    )
    if rc != 0:
        return []
    pkgs = []
    for line in proc.lines(out):
        parts = line.split("\t")
        if len(parts) < 11:
            continue
        (name, version, arch, status, size, section, prio, ess,
         maint, home, summary) = parts[:11]
        if "installed" not in status:
            continue
        try:
            kb = int(size)
        except ValueError:
            kb = 0
        pkgs.append({
            "id": name,
            "name": name,
            "version": version,
            "arch": arch,
            "section": section or "unknown",
            "priority": prio,
            "maintainer": maint,
            "homepage": home,
            "summary": summary or _t("(no description)"),
            "size_kb": kb,
            "size": _human(kb * 1024),
            "essential": "yes" in ess.lower(),
            "dangerous": is_system_package(name, essential=ess, priority=prio),
            # Every installed package is offered a Remove button, Essential included.
            # `dangerous` and `essential` are what the UI uses to warn and to demand a
            # typed confirmation; they no longer hide the button. Removal of an
            # Essential package is escalated to apt's --allow-remove-essential at the
            # point of execution - see apt.uninstall() and the helper allowlist.
            "removable": True,
            "manager": "apt",
        })
    pkgs.sort(key=lambda p: p["name"].lower())
    return pkgs


def show(name):
    rc, out, _ = proc.run(["dpkg-query", "-s", name], timeout=30)
    if rc != 0:
        return None
    info, last_key = {}, None
    desc = []
    for line in out.splitlines():
        if line.startswith(" ") and last_key == "Description":
            desc.append(line.strip())
            continue
        if ":" not in line:
            last_key = None
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k in HEADER:
            last_key = k
            info[k] = v
        else:
            last_key = None
    if desc:
        info["Description"] = (info.get("Description", "") + "\n" + "\n".join(desc)).strip()
    files_rc, files_out, _ = proc.run(["dpkg-query", "-L", name], timeout=30)
    info["files"] = proc.lines(files_out) if files_rc == 0 else []
    info["installed_size"] = _human(int(info.get("Installed-Size", "0") or 0) * 1024)
    return info


def install_deb(path):
    """Install a local .deb. Tries apt first, repairs deps, reuses what the archive can supply."""
    path = str(Path(path).expanduser().resolve())
    steps = []
    if not Path(path).is_file():
        return False, _t("File not found: {path}", path=path), steps

    argv = ["apt-get", "install", "-y", "--allow-downgrades", path]
    rc, out, err = proc.privileged(argv)
    steps.append({"cmd": " ".join(argv), "rc": rc})
    if rc == 0:
        return True, _t("Installed."), steps
    if rc == -2:
        # Privileges were refused, so nothing ever reached apt. Falling through to dpkg
        # would ask for a password a second time and still install nothing, and the
        # caller unpacks three values, so the detail goes into the message.
        return False, _t("Installation failed\n{detail}",
                         detail=err or _t("No details reported.")), steps

    argv = ["dpkg", "-i", path]
    rc, out, err = proc.privileged(argv)
    steps.append({"cmd": " ".join(argv), "rc": rc})
    dpkg_ok = rc == 0
    dpkg_err = _last_error(out, err)
    if not dpkg_ok:
        return False, _t(
            "The package could not be installed. It may be built for a different "
            "distribution or architecture.\n{detail}", detail=dpkg_err
        ), steps

    argv = ["apt-get", "install", "-f", "-y"]
    rc, out, err = proc.privileged(argv)
    steps.append({"cmd": " ".join(argv), "rc": rc})
    if rc != 0:
        return False, _t(
            "The package was unpacked but its dependencies could not be installed.\n"
            "{detail}", detail=_last_error(out, err)
        ), steps
    return True, _t("Installed."), steps


def uninstall(name):
    rc, out, err = proc.privileged(["apt-get", "remove", "-y", *_essential_flag(name), name])
    if rc == 0:
        return True, _t("{name} was removed.", name=name), ""
    if rc == -2:
        # Privileges were refused, so nothing reached apt. Reporting an
        # architecture/dependency problem here would send the user chasing a
        # cause that does not exist.
        return False, _t("Could not remove {name}.", name=name), err or _t("No details reported.")
    return False, _t("Could not remove {name}.", name=name), _apt_reason(out, err)


def purge(name):
    rc, out, err = proc.privileged(["apt-get", "purge", "-y", *_essential_flag(name), name])
    if rc == 0:
        return True, _t("{name} was purged.", name=name), ""
    if rc == -2:
        return False, _t("Could not purge {name}.", name=name), err or _t("No details reported.")
    return False, _t("Could not purge {name}.", name=name), _apt_reason(out, err)


def _essential_flag(name):
    """apt refuses to remove an Essential package without this flag, and the user has
    already confirmed by typing the exact package name in Advanced Mode. An empty list
    for ordinary packages keeps the command shape unchanged."""
    return ["--allow-remove-essential"] if _is_essential(name) else []


@lru_cache(maxsize=8192)
def _is_essential(name):
    rc, out, _ = proc.run(["dpkg-query", "-W", "-f", "${Essential}", name], timeout=20)
    return rc == 0 and "yes" in (out or "").lower()


def search(term, installed_only=True):
    rc, out, _ = proc.run(["apt-cache", "search", "--names-only", term], timeout=60)
    results = []
    if rc == 0:
        for line in proc.lines(out):
            pkg, _, desc = line.partition(" - ")
            results.append({"name": pkg.strip(), "summary": desc.strip()})
    return results[:200]


def autoremove():
    return proc.privileged(["apt-get", "autoremove", "-y"])


# ------------------------------------------------------------------ messages

_NOISE = re.compile(
    r"^(reading package lists|building dependency tree|reading state information|"
    r"\(reading database|preparing to unpack|unpacking |setting up |selecting previously|"
    r"dpkg: warning: |the following additional|the following new|0 upgraded|"
    r"need to get|after this operation|get:\d|selecting |\(database)", re.I
)


def _last_error(out, err):
    candidates = []
    for blob in (err, out):
        for line in (blob or "").splitlines():
            s = line.strip()
            if s and not _NOISE.match(s):
                candidates.append(s)
    return "\n".join(candidates[-6:]) or _t("No details reported.")


def _apt_reason(out, err):
    text = f"{out}\n{err}"
    if "no authentication agent" in text.lower() or "password is required" in text.lower():
        return "Root permission was refused, so nothing was changed."
    if "held broken packages" in text or "unmet dependencies" in text:
        return _t("Dependencies are missing or broken. Try Advanced mode and install "
                  "the missing libraries first.")
    if "not going to be installed" in text:
        return _t("Required dependencies are not available from your configured "
                  "repositories.")
    if "could not get lock" in text or "unable to acquire the dpkg frontend lock" in text:
        return _t("Another package tool is already running. Close it and try again.")
    if "package architecture" in text and "does not match system" in text:
        return _t("This package was built for a different CPU architecture than this "
                  "computer.")
    if "no space left" in text:
        return _t("There is not enough free disk space.")
    return _last_error(out, err)


def _human(n):
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < step or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= step
