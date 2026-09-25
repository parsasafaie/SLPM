#!/usr/bin/env python3
"""
Self-check for SLPM's parsing and safety logic. No test framework, no network,
no system changes: run with

    .venv/bin/python selftest.py

Most checks are machine-independent and run anywhere (that is the CI mode). A few
read this machine's real state - the dpkg log, the installed app list, the startup
entries - to prove the classifier works end to end; they run by default and can be
skipped with

    .venv/bin/python selftest.py --skip-machine

Covers the parts that are easy to get subtly wrong: Exec= parsing, desktop-entry
filtering, package classification, archive launcher discovery, the helper's
command allowlist, and the HTTP endpoints' refusal behaviour.
"""
import ast
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Checks that read this machine's real state (the dpkg log, the installed apps, the
# autostart entries) are skipped in this mode. CI runs on a clean Ubuntu box where
# "the user has installed apps" is simply not true, and a check built around this
# machine's state would fail there for reasons that have nothing to do with the code.
SKIP_MACHINE = "--skip-machine" in sys.argv

from slpm import (apps, apt, appimage, autostart, desktop, download, flatpak_snap,  # noqa: E402
                  helper, i18n, installer, ownership as ow, proc)

# Runs inside node: collect every T()/TT()/tt() literal across all the page scripts,
# check that each one is in the browser catalog, and that its {placeholder}s are
# filled in both languages. Prints one line per failure, nothing on success.
JS_CATALOG_CHECK = r"""
import fs from 'node:fs';

// Drop // and /* */ comments without touching string literals, so a URL like
// 'http://x' is not mistaken for a comment.
function stripComments(src) {
  let out = '';
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (c === "'" || c === '"' || c === '`') {
      out += c;
      i++;
      while (i < src.length) {
        if (src[i] === '\\') { out += src[i] + src[i + 1]; i += 2; continue; }
        out += src[i];
        if (src[i] === c) { i++; break; }
        i++;
      }
      continue;
    }
    if (c === '/' && src[i + 1] === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
    if (c === '/' && src[i + 1] === '*') {
      i += 2;
      while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++;
      i += 2;
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

// The source of the first { ... } after marker, with string-aware brace matching.
function extractObject(src, marker) {
  const start = src.indexOf(marker);
  if (start < 0) throw new Error('marker not found: ' + marker);
  const i = src.indexOf('{', start);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    const c = src[j];
    if (c === "'" || c === '"' || c === '`') {
      j++;
      while (j < src.length) {
        if (src[j] === '\\') j++;
        else if (src[j] === c) break;
        j++;
      }
      continue;
    }
    if (c === '{') depth++;
    else if (c === '}' && --depth === 0) return src.slice(i, j + 1);
  }
  throw new Error('unbalanced braces after ' + marker);
}

const PREFS = stripComments(fs.readFileSync('static/js/prefs.js', 'utf8'));
const FA = eval('(' + extractObject(PREFS, 'const FA = {') + ')');

// Every literal key any page script hands to the catalog, including keys built by
// concatenating string pieces. The closing quote is part of the pattern: without it
// the last piece of a concatenated key is silently dropped.
const KEY_RE = /(?:\bT\(|\bTT\(|\btt\()\s*((?:'[^']*'\s*\+\s*)*'[^']*')/g;
const calls = new Set();
for (const f of fs.readdirSync('static/js').filter(f => f.endsWith('.js'))) {
  const code = stripComments(fs.readFileSync('static/js/' + f, 'utf8'));
  for (const m of code.matchAll(KEY_RE)) {
    calls.add([...m[1].matchAll(/'([^']*)'/g)].map(x => x[1]).join(''));
  }
}

const bad = [];
for (const key of [...calls].sort()) {
  if (!(key in FA)) bad.push('missing from catalog: ' + JSON.stringify(key));
}

// The same {placeholder} contract as the Python catalog: a key's values must be
// filled in English too, not just Persian.
const SRC = fs.readFileSync('static/js/prefs.js', 'utf8');
for (const lang of ['en', 'fa']) {
  globalThis.document = { documentElement: { dataset: { lang, theme: 'light' } },
                          cookie: '', querySelector: () => null };
  globalThis.window = { location: { href: 'http://x/', replace() {} } };
  globalThis.fetch = () => Promise.resolve({ json: () => Promise.resolve({}) });
  const TT = eval(SRC + '\nTT');
  for (const key of calls) {
    const values = {};
    for (const p of key.matchAll(/\{(\w+)\}/g)) values[p[1]] = 'x' + p[1];
    let out;
    try { out = TT(key, values); } catch (e) { out = 'ERROR: ' + e.message; }
    if (/\{\w+\}/.test(out))
      bad.push(`${lang}: unfilled ${JSON.stringify(key)} -> ${JSON.stringify(out)}`);
  }
}
for (const line of bad) console.log(line);
"""

FAILED = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}\n       got:  {got!r}\n       want: {want!r}")
        FAILED.append(label)


def section(name):
    print(f"\n{name}")


# ------------------------------------------------------------------ Exec=

section("Exec= parsing (quotes are legal and SLPM writes them itself)")
check("quoted path", desktop.exec_argv('"/home/u/Applications/App.AppImage"'),
      ["/home/u/Applications/App.AppImage"])
check("single quotes", desktop.exec_argv("'/opt/a b/run.sh'"), ["/opt/a b/run.sh"])
check("field codes dropped", desktop.exec_argv("vlc --started-from-file %U"),
      ["vlc", "--started-from-file"])
check("quoted arg + flag", desktop.exec_argv('"/opt/My App/run.sh" --flag'),
      ["/opt/My App/run.sh", "--flag"])
check("plain command", desktop.exec_argv("/usr/bin/code --unity-launch"),
      ["/usr/bin/code", "--unity-launch"])
check("empty stays empty", desktop.exec_argv(""), [])


# ------------------------------------------------------- desktop filtering

section("Desktop-entry parsing and Simple/Advanced filtering")
DESKTOP = """[Desktop Entry]
Type=Application
Name=Test App
Name[de]=Test Anwendung
Comment=A comment
Exec="/opt/test/run.sh" %U
Icon=test-icon
Categories=Graphics;
NoDisplay=false
"""

with tempfile.TemporaryDirectory() as tmp:
    f = Path(tmp) / "a.desktop"
    f.write_text(DESKTOP)
    entry = desktop.parse(f)
    check("Name read", entry["Name"], "Test App")
    check("localized key ignored", entry.get("Name[de]"), None)
    check("Comment read", entry["Comment"], "A comment")
    check("visible in simple mode", desktop.is_visible(entry), True)

    def entry_for(extra):
        d = dict(entry)
        d.update(extra)
        return d

    check("NoDisplay hidden", desktop.is_visible(entry_for({"NoDisplay": "true"})), False)
    check("Terminal app hidden", desktop.is_visible(entry_for({"Terminal": "true"})), False)
    # A .desktop file can carry several categories; only a non-application one among
    # them hides the entry. A Library entry is hidden, a Graphics one is not.
    check("library-only entry hidden",
          desktop.is_visible(entry_for({"Categories": "Library;"})), False)
    check("Graphics entry kept",
          desktop.is_visible(entry_for({"Categories": "Graphics;"})), True)
    check("Settings entry kept (a real menu entry)",
          desktop.is_visible(entry_for({"Categories": "Settings;"})), True)
    check("non-Application hidden", desktop.is_visible(entry_for({"Type": "Link"})), False)
    check("bare shell hidden", desktop.is_visible(entry_for({"Exec": "/bin/bash"})), False)
    check("real app kept", desktop.is_visible(entry_for({"Categories": "AudioVideo;"})), True)


# -------------------------------------------------------- classification

section("Package safety classification (Advanced mode)")
for name in ("libc6", "linux-image-generic", "systemd", "grub-common", "python3.12",
             "sudo", "ubuntu-desktop", "apt"):
    check(f"{name} flagged as system", apt.is_system_package(name), True)
for name in ("vlc", "gimp", "firefox", "hello", "code"):
    check(f"{name} not flagged", apt.is_system_package(name), False)

# Advanced Mode offers removal for every package, so nothing is classified as
# unremovable any more.
check("no is_unremovable classifier left",
      hasattr(apt, "is_unremovable"), False)
# The Essential check that decides whether to escalate to --allow-remove-essential.
check("apt is not dpkg-Essential", apt._is_essential("apt"), False)
check("base-files is dpkg-Essential", apt._is_essential("base-files"), True)
check("nonexistent package is not Essential", apt._is_essential("slpm-no-such-pkg"), False)


# ------------------------------------------------- ownership (Simple vs Advanced)

section("Ownership: user-installed vs pre-installed")

# The classifier reads the package manager's own logs, which cannot be redirected from a
# test, so the parsing and the boundary logic are exercised on synthetic log text. The
# real files are then checked for the one property that matters - that the OS install
# date is found - because without it nothing can be classified, and Simple Mode would
# have to either show everything or nothing.
_LOG = (
    "2026-04-23 01:15:04 startup archives install\n"
    "2026-04-23 01:15:04 install base-files:amd64 <none> 14ubuntu6\n"
    "2026-04-23 01:15:05 configure base-files:amd64 14ubuntu6 <none>\n"
    "2026-04-23 01:18:10 install firefox:amd64 <none> 149.0\n"
    "2026-04-23 01:18:10 status unpacked firefox:amd64 149.0\n"
    "2026-04-23 01:20:00 upgrade firefox:amd64 149.0 150.0\n"
    "2026-09-21 00:44:53 install claude-desktop:amd64 <none> 1.0\n"
    "2026-09-21 00:44:53 configure claude-desktop:amd64 1.0 <none>\n"
)

# A log with no installer marker at the top is a log we cannot date the OS from, even
# with no rotated file in the way: the earliest entry is only the earliest entry.
_LOG_NO_MARKER = _LOG.replace("2026-04-23 01:15:04 startup archives install\n", "")


def _parse_log(text, rotation_dropped=False):
    """Run the module's own parser over synthetic log text."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "dpkg.log"
        log.write_text(text)
        saved_logs, saved_cache = ow.DPKG_LOGS, ow._log_dates
        # Slot 0 is the most-rotated file (dpkg.log.3); its absence is what says the log
        # reaches back to the machine's first dpkg action. The fake log stands in for the
        # live file, so slot 0 is pointed at a path that does not exist unless the test
        # is exercising the rotated-past case.
        oldest = Path(tmp) / "dpkg.log.3"
        if rotation_dropped:
            oldest.write_text("2026-04-01 00:00:00 install dropped:amd64 <none> 1\n")
        ow.DPKG_LOGS = (str(oldest), str(log))
        ow._log_dates = ow._Cache()
        try:
            ow.installed_by_user_package.cache_clear()
            return ow._build_log_dates()
        finally:
            ow.DPKG_LOGS, ow._log_dates = saved_logs, saved_cache
            ow.installed_by_user_package.cache_clear()


_dates, _anchor = _parse_log(_LOG)
check("the OS install date is the earliest log entry", _anchor, "2026-04-23")
check("an OS-install package is dated to the OS install",
      _dates.get("base-files"), "2026-04-23")
check("a later install keeps its own date",
      _dates.get("claude-desktop"), "2026-09-21")
# An upgrade after the fact must not move a package's first-seen date forward: the
# earliest entry is what says when the package arrived.
check("an upgrade does not re-date a package",
      _dates.get("firefox"), "2026-04-23")

# With the oldest rotated log present the true start has been dropped, so the earliest
# date visible is not the OS install and no package can be classified from it.
_, _anchor2 = _parse_log(_LOG, rotation_dropped=True)
check("a rotated-past log yields no anchor", _anchor2, None)

# With no installer marker the log cannot be dated, so no package can be classified.
_, _anchor_nomark = _parse_log(_LOG_NO_MARKER)
check("a log without the installer marker yields no anchor", _anchor_nomark, None)

# A command that cannot be traced to a package (empty Exec=, TryExec binary absent)
# must still be dated through the package that ships the .desktop file, so no
# system-sourced entry with a dpkg-owned file may end up "unowned". The probe path does
# not exist, so this needs no real package database.
check("a path no package owns has no owning package",
      ow.owning_package_of_file(str(Path(tempfile.gettempdir()) / "slpm-no-such-file")),
      None)

if not SKIP_MACHINE:
    # The real machine: the anchor must be readable, or Simple Mode cannot work at all.
    check("this machine's OS install date is readable",
          bool(ow.os_install_date()), True)

    # End-to-end on the real system: every entry must get a verdict. An "unknown" means
    # the classifier has stopped working, and Simple Mode would have to hide the app to
    # stay safe - which is exactly the failure this module exists to prevent.
    _real = [ow.classify_desktop_entry(r) for r in desktop.collect("simple")]
    check("every real entry is classified, none unknown",
          all(v is not None for v, _ in _real), True)

    def _file_untraceable(r):
        return (r.get("source") == "system"
                and not ow.owning_package(r.get("binary", ""))
                and ow.owning_package_of_file(r.get("file", "")))

    _left_unowned = [r["name"] for r in desktop.collect("advanced")
                     if _file_untraceable(r)
                     and ow.classify_desktop_entry(r)[1] == "unowned"]
    check("an untraceable command still classifies via the file's owning package",
          _left_unowned, [])
else:
    print("skip  real-machine ownership checks (--skip-machine)")

# Startup entries: a user file with no packaged counterpart is the user's; the same file
# shadowing a packaged entry follows the package instead.
check("a user-owned startup file is the user's",
      ow.classify_startup_entry({"source": "user"})[0], True)
check("a packaged startup entry is not",
      ow.classify_startup_entry({"source": "system"})[0], False)
check("an override of a packaged entry is not the user's",
      ow.classify_startup_entry({"source": "user", "_shadows_packaged": True})[0], False)
check("an entry SLPM added is the user's",
      ow.classify_startup_entry({"source": "user", "_slpm_added": True})[0], True)


# ------------------------------------------------------- the two views differ

section("Simple and Advanced views")

if not SKIP_MACHINE:
    # The whole point of the split: Simple Mode must be a strict subset of Advanced, and
    # the two must not be the same list. Both halves are checked, because a filter that
    # silently stopped filtering would still look correct from the Simple side alone.
    # All of it reads this machine's real app and startup lists, so it is the part CI
    # skips: on a clean box "the user installed apps" is not true.
    _simple = apps.apps("simple")
    _adv = apps.apps("advanced")
    check("simple is not empty on this machine", bool(_simple), True)
    check("advanced is a strict superset of simple",
          len(_adv) > len(_simple), True)
    check("every simple app is marked as the user's",
          all(a["user_installed"] for a in _simple), True)
    check("no pre-installed app leaks into simple",
          all(a.get("ownership") in ("package-added", "snap-added", "flatpak-added",
                                     "user-file")
              for a in _simple), True)
    check("the advanced view still marks ownership",
          all("user_installed" in a for a in _adv), True)

    _su = autostart.collect("simple")
    _sa = autostart.collect("advanced")
    check("advanced startup shows more than simple",
          len(_sa) > len(_su), True)
    check("every simple startup entry is the user's",
          all(a["user_owned"] for a in _su), True)
else:
    print("skip  real-machine view checks (--skip-machine)")

# The flag is added only where apt would otherwise refuse the removal, so ordinary
# removals keep the exact command shape they had before.
check("essential removal escalates",
      apt._essential_flag("base-files"), ["--allow-remove-essential"])
check("ordinary removal does not escalate", apt._essential_flag("vlc"), [])


# ------------------------------------------------------------ detection

section("Installer file-type detection")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    cases = {
        "a.deb": "deb",
        "b.AppImage": "appimage",
        "c.tar.gz": "archive",
        "d.zip": "archive",
        "e.txz": "archive",
        "f.run": "executable",
        "g.txt": "unknown",
    }
    for name, want in cases.items():
        p = tmp / name
        p.write_text("x")
        check(f"{name} -> {want}", installer.detect(str(p))["kind"], want)
    check("missing file", installer.detect(str(tmp / "nope.deb"))["kind"], "missing")
    check("directory rejected", installer.detect(str(tmp))["kind"], "directory")


# ------------------------------------------------- archive launchers

section("Archive extraction and launcher discovery")


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)


def make_tar_gz(path, files):
    with tarfile.open(path, "w:gz") as t:
        for name, body in files.items():
            info = tarfile.TarInfo(name)
            data = body.encode()
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


# The pre-checks below refuse an archive before a byte is written, so they need no
# extractor at all; the positive extractions do, and are skipped where the tool is
# absent rather than failing the run.
section("Archive members that escape the destination are refused (tar slip)")
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    slip = tmp / "slip.tar.gz"
    make_tar_gz(slip, {"../../evil-out.txt": "pwned", "ok/readme": "fine"})
    dest = tmp / "e-slip"
    ok, msg, _ = appimage.extract(slip, dest)
    check("escaping tar member refused", ok, False)
    check("refusal says where the path would land",
          "outside the destination" in msg, True)
    check("nothing was written outside the destination",
          (tmp / "evil-out.txt").exists(), False)

    abs_tar = tmp / "abs.tar.gz"
    make_tar_gz(abs_tar, {"/tmp/slpm-evil-abs.txt": "pwned"})
    ok, _, _ = appimage.extract(abs_tar, tmp / "e-abs")
    check("absolute tar member refused", ok, False)

    link_tar = tmp / "link.tar.gz"
    with tarfile.open(link_tar, "w:gz") as t:
        info = tarfile.TarInfo("payload")
        data = b"x"
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("out-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../escape.txt"
        t.addfile(link)
    ok, _, _ = appimage.extract(link_tar, tmp / "e-link")
    check("escaping symlink refused", ok, False)

    # A member inside the destination is the whole point of extraction: a good archive
    # must still unpack, flattened to its single top-level folder.
    good = tmp / "good.tar.gz"
    make_tar_gz(good, {"App/tool": "#!/bin/sh\necho hi\n", "App/readme": "x"})
    if proc.which("tar"):
        ok, _, root = appimage.extract(good, tmp / "e-good")
        check("a safe tar.gz extracts", ok, True)
        check("single top-level folder is flattened",
              [f["name"] for f in appimage.find_launchers(root)], ["tool"])
    else:
        print("skip  tar extraction (tar not installed)")

    slip_zip = tmp / "slip.zip"
    make_zip(slip_zip, {"../evil-zip.txt": "pwned", "ok/readme": "fine"})
    ok, msg, _ = appimage.extract(slip_zip, tmp / "e-zip")
    check("escaping zip member refused", ok, False)
    check("zip refusal names the destination", "outside the destination" in msg, True)
    check("zip: nothing was written outside", (tmp / "evil-zip.txt").exists(), False)


if proc.which("unzip") or proc.which("bsdtar") or proc.which("7z"):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # A nested folder holding one executable and a readme.
        z1 = tmp / "one.zip"
        make_zip(z1, {"Tool/run.sh": "#!/bin/sh\necho hi\n", "Tool/README": "x"})
        ok, _, root = appimage.extract(z1, tmp / "e1")
        check("extract succeeds", ok, True)
        found = appimage.find_launchers(root)
        check("finds the script", [f["name"] for f in found], ["run.sh"])

        # A payload whose directory is named bin: the file itself is still a launcher.
        z2 = tmp / "two.zip"
        make_zip(z2, {"App/bin/tool": "#!/bin/sh\necho t\n"})
        ok, _, root2 = appimage.extract(z2, tmp / "e2")
        check("extract 2 succeeds", ok, True)
        check("tool under bin/ still found",
              [f["name"] for f in appimage.find_launchers(root2)], ["tool"])

        # A .desktop entry inside the archive wins over loose files.
        z3 = tmp / "three.zip"
        make_zip(z3, {
            "Suite/launcher.desktop":
                "[Desktop Entry]\nType=Application\nName=Suite App\nExec=suite\n",
            "Suite/suite": "#!/bin/sh\n",
            "Suite/helper.sh": "#!/bin/sh\n",
        })
        ok, _, root3 = appimage.extract(z3, tmp / "e3")
        check("extract 3 succeeds", ok, True)
        found3 = appimage.find_launchers(root3)
        check("desktop entry ranked first", found3[0]["kind"], "desktop")
        check("desktop entry name used", found3[0]["name"], "Suite App")

        # Nothing runnable at all.
        z4 = tmp / "four.zip"
        make_zip(z4, {"Docs/readme.txt": "nothing here"})
        ok, _, root4 = appimage.extract(z4, tmp / "e4")
        check("extract 4 succeeds", ok, True)
        check("no launchers found", appimage.find_launchers(root4), [])
else:
    print("skip  zip extraction (no unzip/bsdtar/7z installed)")


section("Client-supplied archive choice is validated, never trusted")
with tempfile.TemporaryDirectory() as tmp:
    real = Path(tmp) / "real-tool"
    real.write_text("#!/bin/sh\n")
    launchers = [{"kind": "exec", "path": str(real), "name": "real-tool"}]
    check("matching choice accepted",
          installer._resolve_choice({"path": str(real)}, launchers)["name"], "real-tool")
    check("fabricated path rejected",
          installer._resolve_choice({"path": "/root/nope"}, launchers), None)
    check("outside path rejected",
          installer._resolve_choice({"path": str(Path(tmp) / ".." / "other")}, launchers), None)
    check("non-dict rejected", installer._resolve_choice("tool", launchers), None)
    check("missing path rejected", installer._resolve_choice({}, launchers), None)


# --------------------------------------------------------- autostart files

section("Startup apps: flags, overrides and the add/toggle/remove flow")

# autostart.py keeps its two directories as module globals, so the flow test can point
# them at a temporary pair. Nothing here reads or writes the real autostart directories,
# and no program is launched.
_REAL_AUTOSTART_DIRS = (autostart.USER_AUTOSTART, autostart.SYSTEM_AUTOSTART)


def _desktop_text(name, exec_line, extra=""):
    return ("[Desktop Entry]\nType=Application\nVersion=1.0\n"
            f"Name={name}\nExec={exec_line}\n{extra}")


# --- the two flags that together mean "do not start this"
check("an entry with no flags starts", autostart.is_disabled({"Name": "x"}), False)
check("Hidden=true is off", autostart.is_disabled({"Hidden": "true"}), True)
check("Hidden=false stays on", autostart.is_disabled({"Hidden": "false"}), False)
check("Hidden=True reads case-insensitively",
      autostart.is_disabled({"Hidden": "True"}), True)
check("X-GNOME-Autostart-enabled=false is off",
      autostart.is_disabled({"X-GNOME-Autostart-enabled": "false"}), True)
# An unrecognised value is not a decision, and must not be read as one: defaulting to
# "off" here would disable entries whose flag is merely misspelled.
check("an unreadable flag is not treated as off",
      autostart.is_disabled({"Hidden": "maybe"}), False)
check("Hidden wins over an enabled GNOME key",
      autostart.is_disabled({"Hidden": "true",
                             "X-GNOME-Autostart-enabled": "true"}), True)

# --- Exec= field codes
check("field codes are dropped", autostart.clean_exec("app --flag %U"), "app --flag")
# %% is the spec's escape for one literal percent, so it must collapse to one and not be
# eaten along with the real field codes.
check("a literal percent survives as one",
      autostart.clean_exec("sh -c 'echo 100%%'"), "sh -c 'echo 100%'")
check("a command with no field codes is unchanged",
      autostart.clean_exec("/usr/bin/app"), "/usr/bin/app")
check("an empty command stays empty", autostart.clean_exec(""), "")

# --- flags are written into [Desktop Entry], never appended to the file
_BODY = ("[Desktop Entry]\nType=Application\nName=A\nExec=a\n"
         "[Desktop Action New]\nName=New\nExec=a --new\n")
_off = autostart._with_state(_BODY, False)
check("turning off sets Hidden", "Hidden=true" in _off, True)
check("turning off sets the GNOME key",
      "X-GNOME-Autostart-enabled=false" in _off, True)
# A key written into the wrong group is silently ignored by every desktop, so the
# desktop-action group has to keep its own keys exactly as they were.
check("the desktop-action group is left alone",
      "[Desktop Action New]\nName=New\nExec=a --new" in _off, True)
_on = autostart._with_state(_off, True)
check("turning on clears Hidden", "Hidden=true" not in _on, True)
check("turning on clears the GNOME key",
      "X-GNOME-Autostart-enabled=false" not in _on, True)
_dup = autostart._with_state(
    "[Desktop Entry]\nName=A\nHidden=false\nHidden=false\n", False)
check("a repeated flag collapses to one line", _dup.count("Hidden="), 1)
check("a repeated flag takes the requested value", "Hidden=true" in _dup, True)
_bare = autostart._with_state("Name=A\nExec=a\n", False)
check("a group is created when there is none",
      _bare.startswith("[Desktop Entry]"), True)
check("...and the flags land inside it", "Hidden=true" in _bare, True)


def _flow():
    """collect/add/set_enabled/remove against a temporary system/user pair."""
    with tempfile.TemporaryDirectory() as tmp:
        system = Path(tmp) / "system"
        user = Path(tmp) / "user"
        system.mkdir()
        user.mkdir()
        autostart.SYSTEM_AUTOSTART = system
        autostart.USER_AUTOSTART = user

        (system / "Vendor.desktop").write_text(_desktop_text("Vendor", "sh"))
        (system / "Hidden-vendor.desktop").write_text(_desktop_text("Hidden Vendor", "sh"))
        # A packaged entry with no user counterpart at all: this is the one removal must
        # refuse, because there is no user file to delete.
        (system / "System-only.desktop").write_text(_desktop_text("System Only", "sh"))
        (user / "Hidden-vendor.desktop").write_text(
            _desktop_text("Hidden Vendor", "sh", "Hidden=true\n"))
        # Two entries a session would never start, and neither should be listed.
        (system / "NotAnApp.desktop").write_text(
            "[Desktop Entry]\nType=Link\nName=Shortcut\nExec=sh\n")
        (system / "NoCommand.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=No Command\n")

        rows = {r["id"]: r for r in autostart.collect()}
        check("a packaged starter is listed", "Vendor.desktop" in rows, True)
        check("a Link entry is not listed", "NotAnApp.desktop" in rows, False)
        check("an entry with no Exec= is not listed", "NoCommand.desktop" in rows, False)
        check("a packaged entry is on", rows["Vendor.desktop"]["enabled"], True)
        check("a packaged entry is not removable",
              rows["Vendor.desktop"]["removable"], False)
        check("a user entry overrides the packaged one of the same name",
              rows["Hidden-vendor.desktop"]["enabled"], False)
        check("the override is reported as the user's",
              rows["Hidden-vendor.desktop"]["source"], "user")
        check("the override is removable",
              rows["Hidden-vendor.desktop"]["removable"], True)

        # Switching a packaged entry off writes an override and leaves the package's own
        # file byte-for-byte as it was, so a reinstall cannot silently re-enable it.
        packaged = system / "Vendor.desktop"
        before = packaged.read_text()
        ok, _, _ = autostart.set_enabled("Vendor.desktop", False)
        check("a packaged entry can be switched off", ok, True)
        check("the packaged file is untouched", packaged.read_text(), before)
        check("an override file was written", (user / "Vendor.desktop").is_file(), True)
        rows = {r["id"]: r for r in autostart.collect()}
        check("the entry now reads as off", rows["Vendor.desktop"]["enabled"], False)
        check("...and now comes from the user's directory",
              rows["Vendor.desktop"]["source"], "user")

        ok, _, _ = autostart.set_enabled("Vendor.desktop", True)
        check("a packaged entry can be switched back on", ok, True)
        rows = {r["id"]: r for r in autostart.collect()}
        check("the entry reads as on again", rows["Vendor.desktop"]["enabled"], True)

        # Adding an installed program.
        ok, _, _ = autostart.add("My App", "sh --flag %U")
        check("an installed program can be added", ok, True)
        target = user / "slpm-my-app.desktop"
        check("the entry is written under a reserved prefix", target.is_file(), True)
        rows = {r["id"]: r for r in autostart.collect()}
        check("the added entry is on", rows["slpm-my-app.desktop"]["enabled"], True)
        check("the field code was stripped before storing",
              "%U" not in rows["slpm-my-app.desktop"]["exec"], True)

        # The same command twice must not produce two entries, which would start the
        # program twice at login.
        ok, _, _ = autostart.add("My App Again", "sh --flag")
        check("adding a duplicate command is accepted", ok, True)
        check("...without writing a second file",
              len(list(user.glob("slpm-*.desktop"))), 1)

        # Closing an entry takes the file away, so the way back is add() again: it must
        # recreate the entry, and the command must not be treated as a duplicate of the
        # entry that no longer exists.
        ok, _, _ = autostart.set_enabled("slpm-my-app.desktop", False)
        check("closing a user entry removes its file",
              (user / "slpm-my-app.desktop").is_file(), False)
        rows = {r["id"]: r for r in autostart.collect()}
        check("...so it is gone from the list", "slpm-my-app.desktop" in rows, False)
        ok, _, _ = autostart.add("My App", "sh --flag")
        check("adding it again succeeds", ok, True)
        rows = {r["id"]: r for r in autostart.collect()}
        check("...and the entry is back on",
              rows["slpm-my-app.desktop"]["enabled"], True)

        # Rejections.
        check("a nameless program is refused", autostart.add("", "sh")[0], False)
        check("a program with no command is refused", autostart.add("Nope", "")[0], False)
        check("a command that is not on this computer is refused",
              autostart.add("Nope", "/no/such/command-xyz")[0], False)

        # Removal is for files SLPM may delete. A packaged entry with no user override
        # is only ever switched off; its file belongs to a package, not to the user.
        check("a user entry can be removed",
              autostart.remove("slpm-my-app.desktop")[0], True)
        check("the file is gone", (user / "slpm-my-app.desktop").is_file(), False)
        check("a packaged entry with no override cannot be deleted",
              autostart.remove("System-only.desktop")[0], False)
        check("...and its packaged file is still there",
              (system / "System-only.desktop").is_file(), True)
        # Vendor.desktop has a user override by now (written by the toggle above), so
        # what is being removed is the user's own file - which is exactly what should
        # be deleted, and it is why the override step reports it as removable.
        check("an override can be deleted once the user owns it",
              autostart.remove("Vendor.desktop")[0], True)
        check("...leaving the packaged file in place",
              (system / "Vendor.desktop").is_file(), True)
        check("an unknown entry is refused",
              autostart.set_enabled("no-such-file.desktop", False)[0], False)


try:
    _flow()
finally:
    autostart.USER_AUTOSTART, autostart.SYSTEM_AUTOSTART = _REAL_AUTOSTART_DIRS

# The browser catalog carries these as patterns (FA_PATTERNS in prefs.js, because the
# program name varies); on the server side they are ordinary rows with one placeholder.
for _sentence in ("{name} will now start when you log in.",
                  "{name} already starts when you log in.",
                  "{name} will no longer start when you log in.",
                  "{name} was removed from your startup apps."):
    check(f"startup message translated: {_sentence[:36]}…",
          i18n.tr("fa", _sentence, name="vlc") != _sentence, True)


# ------------------------------------------------------- helper allowlist

section("Privileged helper allowlist")
for argv in (["apt-get", "install", "-y", "/tmp/x.deb"],
             ["apt-get", "install", "-y", "--allow-downgrades", "/tmp/x.deb"],
             ["apt-get", "remove", "-y", "vlc"],
             ["apt-get", "purge", "-y", "vlc"],
             ["apt-get", "remove", "-y", "a", "b"],
             ["apt-get", "autoremove", "-y"],
             ["apt-get", "install", "-f", "-y"],
             ["dpkg", "-i", "/tmp/x.deb"],
             ["dpkg", "--purge", "vlc"],
             ["snap", "remove", "code"]):
    check(f"allowed: {' '.join(argv)}", helper._allowed(argv), True)

# Removing an Essential package is the one sanctioned use of --allow-remove-essential,
# and Advanced Mode needs it: apt refuses those removals outright without it.
for argv in (["apt-get", "remove", "-y", "--allow-remove-essential", "base-files"],
             ["apt-get", "purge", "-y", "--allow-remove-essential", "base-files"],
             ["dpkg", "--purge", "--allow-remove-essential", "base-files"]):
    check(f"allowed (essential removal): {' '.join(argv)}", helper._allowed(argv), True)

for argv in (["rm", "-rf", "/"],
             ["bash", "-c", "evil"],
             ["id"],
             ["apt-get"],
             ["apt-get", "--version"],
             ["apt-get", "install", "-y", "x; rm -rf /"],
             ["apt-get", "remove", "-y", "/tmp/my app.deb"],
             ["apt-get", "remove", "-y", "--force-yes"],
             # The new exception must not widen anything else: it is a removal-only flag.
             ["apt-get", "install", "-y", "--allow-remove-essential", "vlc"],
             ["apt-get", "update", "--allow-remove-essential"],
             ["apt-get", "remove", "-y", "--allow-change-held-packages", "vlc"],
             ["dpkg", "-i", "--allow-remove-essential", "/tmp/x.deb"],
             ["dpkg", "--configure-x"],
             # dpkg recovery shapes are not part of the UI's command set, so the
             # helper does not allow them either: repair goes through apt-get.
             ["dpkg", "--configure", "-a"],
             ["dpkg", "--configure"],
             ["dpkg", "-i", "-a", "/tmp/x.deb"],
             ["dpkg", "-i"],
             ["sh", "-c", "x"],
             ["apt-get", "remove", "-y", "x && curl evil.sh"],
             []):
    check(f"refused: {' '.join(argv) or '(empty)'}", helper._allowed(argv), False)


# --------------------------------------------------------------- size fmt

section("Human-readable sizes")
check("bytes", apt._human(512), "512 B")
check("kilobytes", apt._human(2048), "2.0 KB")
check("megabytes", apt._human(5 * 1024 * 1024), "5.0 MB")
check("gigabytes", apt._human(3 * 1024 ** 3), "3.0 GB")


# ------------------------------------------------- upgrade simulation parse

section("apt-get upgrade -s transcript parsing (both apt spellings)")
# Modern apt (3.x): bare Inst lines, name / [current] / (available suites [arch]).
modern = """Reading state information...
Calculating upgrade...
The following packages will be upgraded:
  apport-gtk bpftool dnsmasq-base
3 upgraded, 0 newly installed, 0 to remove and 10 not upgraded.
Inst apport-gtk [2.34.0-0ubuntu2] (2.34.1-0ubuntu0.1 Ubuntu:26.04/resolute-updates [all])
Inst bpftool [7.7.0+7.0.0-14.14] (7.7.0+7.0.0-34.34 Ubuntu:26.04/resolute-updates, Ubuntu:26.04/resolute-security [amd64])
Inst dnsmasq-base [2.92-1] (2.92-1ubuntu0.4 Ubuntu:26.04/resolute-updates, Ubuntu:26.04/resolute-security [amd64])
Conf apport-gtk (2.34.1-0ubuntu0.1 Ubuntu:26.04/resolute-updates [all])
"""
got = apt.parse_upgrade_sim(modern)
check("modern: three upgrades", [u["name"] for u in got], ["apport-gtk", "bpftool", "dnsmasq-base"])
check("modern: versions on both sides",
      {u["name"]: (u["current"], u["available"]) for u in got}["dnsmasq-base"],
      ("2.92-1", "2.92-1ubuntu0.4"))

# Older apt (1.x/2.x): the verb carries a sequence number and names keep the arch.
classic = """Calculating upgrade...
The following packages will be upgraded:
  libc6
1 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
Inst:1 libc6:amd64 [2.35-0ubuntu3.4] (2.35-0ubuntu3.5 Ubuntu:jammy-updates [amd64])
Conf:1 libc6 (2.35-0ubuntu3.5 Ubuntu:jammy-updates [amd64])
"""
got = apt.parse_upgrade_sim(classic)
check("classic: one upgrade", [u["name"] for u in got], ["libc6"])
check("classic: arch stripped, versions kept",
      (got[0]["current"], got[0]["available"]), ("2.35-0ubuntu3.4", "2.35-0ubuntu3.5"))

check("empty transcript", apt.parse_upgrade_sim(""), [])
check("nothing upgradable", apt.parse_upgrade_sim("0 upgraded, 0 newly installed, 0 to remove.\n"), [])

# The simulation is read-only and needs no privileges, so it is safe to run for real:
# whatever the machine's apt spells the transcript, every row must be well-formed.
if proc.which("apt-get"):
    live = apt.list_upgrades()
    check("live simulation rows are well-formed",
          all(set(u) == {"name", "current", "available"} for u in live), True)
else:
    print("skip  live apt simulation (apt-get not installed)")

# The per-row update button takes a name from the browser, so a bad one must die at
# the validator and never reach a command line or a privilege prompt. All three
# checks use names the validators reject, so nothing is executed.
section("Single-item update names are checked before anything runs")
ok, msg, _ = apt.upgrade_one("bad;name")
check("apt refuses a malformed name", ok, False)
check("apt says why", "does not look like a package name" in msg, True)
ok, msg, _ = flatpak_snap.snap_refresh_one("bad;name")
check("snap refuses a malformed name", ok, False)
ok, msg, _ = flatpak_snap.flatpak_update_one("bad id")
check("flatpak refuses a malformed id", ok, False)

# The refresh of a running snap (VS Code open) fails with a multi-line message that
# ends in the pid list it could not stop. A one-line detail made that list look like
# the whole error, so the detail keeps a tail of the output instead.
section("Snap error detail keeps the tail, not just the last line")
err = ('error: cannot refresh "code": cannot stop "code": 154522,154524,154525\n'
       'error: try closing the app first')
got = flatpak_snap._short_error("", err)
check("every line of the tail survives",
      "154522,154524,154525" in got and "try closing the app first" in got, True)
check("line breaks are kept", "\n" in got, True)
check("empty output still reports", flatpak_snap._short_error("", ""),
      "No details reported.")
long = "\n".join(f"line {i}" for i in range(100))
got = flatpak_snap._short_error(long, "")
check("a chatty failure is capped, still the latest lines",
      len(got) <= 2000 and "line 99" in got and "line 0" not in got, True)

# The same /proc scan that marks a snap as running in the UI, checked against this
# very process so the test does not depend on what happens to be installed.
section("Running-process detection (one /proc scan)")
if os.path.islink("/proc/self/exe"):
    real = os.readlink("/proc/self/exe")
    check("the scan sees this process",
          os.getpid() in proc.pids_with_exe_prefix(os.path.dirname(real) + os.sep),
          True)
    check("an impossible prefix matches nothing",
          proc.pids_with_exe_prefix("/no/such/dir/"), [])
else:
    print("skip  /proc scan (no /proc/self/exe here)")


# ------------------------------------------------------- helpers present

section("Command availability probing")
check("known command found", bool(proc.which("sh")), True)
check("absent command reported", proc.run(["slpm-no-such-binary"]), (127, "", "command not found: slpm-no-such-binary"))

# ------------------------------------------------------------- translation

section("Language selection and message translation")
check("English is the default", i18n.normalize(None), "en")
check("known language kept", i18n.normalize("fa"), "fa")
check("region dropped", i18n.normalize("fa-IR"), "fa")
check("case and separator tolerated", i18n.normalize("FA_ir"), "fa")
check("unknown language falls back", i18n.normalize("de"), "en")
check("empty falls back", i18n.normalize(""), "en")

check("Persian renders right to left", i18n.DIRECTIONS["fa"], "rtl")
check("English renders left to right", i18n.DIRECTIONS["en"], "ltr")

# The fallback is the safety net: a sentence with no Persian entry must come back
# unchanged rather than as a placeholder or an empty string.
check("known sentence translated",
      i18n.tr("fa", "Installed Apps"), "برنامه‌های نصب‌شده")
check("unknown sentence passes through",
      i18n.tr("fa", "Some sentence nobody translated."),
      "Some sentence nobody translated.")
check("English mode ignores the catalog",
      i18n.tr("en", "Installed Apps"), "Installed Apps")
check("values are interpolated",
      i18n.tr("fa", "{name} was removed.", name="vlc"), "vlc حذف شد.")
# English keeps the placeholders too: the untranslated sentence is the one most likely
# to reach the UI verbatim, so it must not show "{name}" to the user.
check("English also substitutes values",
      i18n.tr("en", "{name} was removed.", name="vlc"), "vlc was removed.")
check("English substitutes on the unknown-sentence path",
      i18n.tr("en", "No longer in {root}.", root="/tmp/x"), "No longer in /tmp/x.")
check("a missing value leaves English placeholders rather than raising",
      i18n.tr("en", "{name} was removed."), "{name} was removed.")
check("package names stay in Latin script",
      "vlc" in i18n.tr("fa", "{name} was removed.", name="vlc"), True)

# Every entry must declare exactly the same fields as its English key, or a
# translated message would raise (or silently drop a value) at format time.
mismatched = [key for key, value in i18n._FA.items()
              if i18n._template(key) != i18n._template(value)]
check("no placeholder mismatches in the Persian catalog", mismatched, [])

# A string wrapped in _t()/proc.t() but absent from the catalog stays English, which
# is safe but easy to miss: it looks translated in the source and is not. Walking the
# call sites catches it without running a package operation.
wrapped = set()
for source in list((ROOT / "slpm").glob("*.py")) + [ROOT / "app.py"]:
    for node in ast.walk(ast.parse(source.read_text())):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        owner = getattr(getattr(fn, "value", None), "id", None)
        if (name == "_t" or (name == "t" and owner == "proc")) \
                and node.args and isinstance(node.args[0], ast.Constant):
            wrapped.add(node.args[0].value)
untranslated = sorted(text for text in wrapped if text not in i18n._FA)
check("every _t() message has a Persian entry", untranslated, [])

# Every {{ t('...') }} key a template renders must have a Persian entry, or the page
# silently shows English in Persian mode. The keys are read from the templates rather
# than listed here, so a new one is covered the moment it is written.
template_keys = set()
for tpl in (ROOT / "templates").glob("*.html"):
    for m in re.finditer(r"t\('([^']*)'", tpl.read_text()):
        template_keys.add(m.group(1))
check("every template string has a Persian entry",
      sorted(k for k in template_keys if k not in i18n._FA), [])

# The contextvar is what lets a module deep in a package operation answer in the
# language of the request that triggered it.
proc.set_lang("fa")
check("proc.t follows the request language", proc.t("Installed Apps"), "برنامه‌های نصب‌شده")
proc.set_lang("en")
check("and switches back", proc.t("Installed Apps"), "Installed Apps")

# The browser-side catalog has the same contract as the Python one, and the same trap:
# a T() call with {name} values must be filled in *both* languages. Checking only the
# Persian path is what let "Removing {name}…" reach the screen in English mode.
try:
    js_check = subprocess.run(
        ["node", "--input-type=module", "-e", JS_CATALOG_CHECK],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
except FileNotFoundError:
    print("skip  browser catalog (node not installed)")
else:
    check("browser catalog substitutes values in both languages",
          js_check.stdout.strip().splitlines(), [])
    check("browser catalog script ran clean", js_check.returncode, 0)

# ------------------------------------------------- security regression tests
#
# Every check below pins a past vulnerability or a privilege boundary in place.
# They are all machine-independent: no privileged command runs, no network is
# touched, and the HTTP tests use Flask's test client (no server, no socket).

section("Name-shape validators (the gate on every privileged path)")
check("a normal apt name", proc.is_apt_pkg("libfoo1.2-3"), True)
check("an option-looking apt name is refused", proc.is_apt_pkg("-rf"), False)
check("an uppercase apt name is refused", proc.is_apt_pkg("VLC"), False)
check("a metacharacter apt name is refused", proc.is_apt_pkg("vlc;rm"), False)
check("a flatpak app id", proc.is_flatpak_app_id("org.gimp.GIMP"), True)
check("a dotless flatpak name is refused", proc.is_flatpak_app_id("gimp"), False)
check("an option-looking flatpak name is refused", proc.is_flatpak_app_id("-y"), False)
check("a normal snap name", proc.is_snap_name("code"), True)
check("an underscored snap name is refused", proc.is_snap_name("a_b"), False)
check("an option-looking snap name is refused", proc.is_snap_name("-rf"), False)

section("Icon paths that leave the icon directories are refused")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    icon_root = root / "icons"
    icon_root.mkdir()
    good = icon_root / "good.png"
    good.write_bytes(b"x")
    outside = root / "outside.png"
    outside.write_bytes(b"y")
    check("an icon inside the root is served",
          desktop._safe_icon_file(good, [icon_root]), str(good.resolve()))
    check("a relative path climbing out of the root is refused",
          desktop._safe_icon_file(icon_root / ".." / "outside.png", [icon_root]), None)
    check("an absolute path outside the root is refused",
          desktop._safe_icon_file(outside, [icon_root]), None)
    link = icon_root / "link.png"
    link.symlink_to(outside)
    check("a symlink inside the root pointing out is refused",
          desktop._safe_icon_file(link, [icon_root]), None)
    check("a missing file is refused",
          desktop._safe_icon_file(icon_root / "nope.png", [icon_root]), None)

section("Download file names and hosts")
check("a plain file name is kept",
      download._filename_from_url("https://example.com/dl/app.AppImage"), "app.AppImage")
check("an encoded separator cannot climb out",
      download._filename_from_url("https://example.com/a%2F..%2F..%2Fevil"), "download")
check("the last decoded segment becomes the name",
      download._filename_from_url("https://example.com/foo%2Fbar.deb"), "bar.deb")
check("a dotfile is not a name",
      download._filename_from_url("https://example.com/.hidden"), "download")
check("a bare dot is not a name",
      download._filename_from_url("https://example.com/.."), "download")
check("a name without an extension gets the default",
      download._filename_from_url("https://example.com/justname"), "download")
check("loopback is a blocked host", download._blocked_host("127.0.0.1"), True)
check("the cloud metadata address is a blocked host",
      download._blocked_host("169.254.169.254"), True)
check("a private LAN address is a blocked host", download._blocked_host("10.0.0.5"), True)
check("bracketed IPv6 loopback is a blocked host", download._blocked_host("[::1]"), True)
check("a public address is allowed", download._blocked_host("93.184.216.34"), False)
check("an empty host is a blocked host", download._blocked_host(""), True)

section("The root helper allowlist (exact shapes only)")
check("apt-get install with a name", helper._allowed(["apt-get", "install", "-y", "vlc"]), True)
check("apt-get install of a local deb with allow-downgrades",
      helper._allowed(["apt-get", "install", "-y", "--allow-downgrades",
                       "/tmp/app.deb"]), True)
check("apt-get dependency repair pass (flags only, no target)",
      helper._allowed(["apt-get", "install", "-f", "-y"]), True)
check("apt-get remove with a name", helper._allowed(["apt-get", "remove", "-y", "vlc"]), True)
check("apt-get purge an Essential package",
      helper._allowed(["apt-get", "purge", "-y", "--allow-remove-essential", "vlc"]), True)
check("apt-get update", helper._allowed(["apt-get", "update"]), True)
check("apt-get upgrade", helper._allowed(["apt-get", "upgrade", "-y"]), True)
check("dpkg install of a local file", helper._allowed(["dpkg", "-i", "/tmp/app.deb"]), True)
check("snap install with a name", helper._allowed(["snap", "install", "code"]), True)
check("snap refresh with no operand", helper._allowed(["snap", "refresh"]), True)
check("-o with a caller-chosen option is refused",
      helper._allowed(["apt-get", "install", "-o",
                       "DPkg::Pre-Install-Pkgs=/tmp/evil.sh"]), False)
check("a dpkg option flag is refused",
      helper._allowed(["dpkg", "-i", "-o", "conffile=old", "/tmp/app.deb"]), False)
check("a snap option flag is refused", helper._allowed(["snap", "refresh", "--amend"]), False)
check("flatpak install is refused (flatpak is user-level in SLPM)",
      helper._allowed(["flatpak", "install", "-y", "org.gimp.GIMP"]), False)
check("flatpak uninstall is refused (flatpak is user-level in SLPM)",
      helper._allowed(["flatpak", "uninstall", "org.gimp.GIMP"]), False)
check("a forbidden apt flag is refused",
      helper._allowed(["apt-get", "install", "-y", "--force-yes", "vlc"]), False)
check("allow-remove-essential is refused on install",
      helper._allowed(["apt-get", "install", "-y", "--allow-remove-essential", "vlc"]), False)
check("an option disguised as a package name is refused",
      helper._allowed(["apt-get", "install", "-y", "-rf"]), False)
check("a metacharacter in the name is refused",
      helper._allowed(["apt-get", "install", "-y", "vlc;rm"]), False)
check("dpkg without an operand is refused", helper._allowed(["dpkg", "-i"]), False)
check("an unknown program is refused", helper._allowed(["sh", "-c", "rm -rf /"]), False)
check("an unknown apt-get action is refused", helper._allowed(["apt-get", "chroot", "/"]), False)
check("a non-list argv is refused", helper._allowed("apt-get install vlc"), False)

section("The HTTP endpoints refuse what they should (test client, no server)")
import app as slpm_app  # noqa: E402

client = slpm_app.app.test_client()

r = client.get("/api/packages")
check("GET /api/packages is 403 in Simple Mode", r.status_code, 403)
check("... and says advanced_only", (r.get_json() or {}).get("advanced_only"), True)
# Updates moved to both modes in the same release: an update brings installed
# items to their newest version and removes nothing, so Simple Mode gets the list.
if proc.which("apt-get"):
    r = client.get("/api/updates")
    check("GET /api/updates answers in Simple Mode", r.status_code, 200)
else:
    print("skip  simple /api/updates (apt-get not installed)")
r = client.get("/api/apt/search", query_string={"q": "vlc"})
check("GET /api/apt/search is 403 in Simple Mode", r.status_code, 403)
r = client.post("/api/packages/install", json={"manager": "apt", "name": "vlc"})
check("POST /api/packages/install is 403 in Simple Mode", r.status_code, 403)

client.set_cookie("slpm_mode", "advanced")
r = client.post("/api/packages/install", json={"manager": "apt", "name": ""})
check("an empty package name is a 400", r.status_code, 400)
r = client.post("/api/packages/install", json={"manager": "git", "name": "x"})
check("an unknown manager is a 400", r.status_code, 400)
r = client.post("/api/packages/remove", json={"name": "-rf", "confirmed": "-rf"})
check("a non-package removal name is a 400", r.status_code, 400)
r = client.post("/api/updates/run", json={"manager": "git", "step": "update"})
check("an unknown update manager is a 400", r.status_code, 400)
# A per-row update with a bad name must be refused by the validator, not executed.
r = client.post("/api/updates/run", json={"manager": "apt", "step": "update",
                                          "name": "bad;name"})
j = r.get_json() or {}
check("a malformed single-update name is refused", (r.status_code, j.get("ok")), (200, False))
if proc.which("apt-get"):
    r = client.get("/api/packages")
    check("GET /api/packages answers in Advanced Mode", r.status_code, 200)
else:
    print("skip  advanced /api/packages (apt-get not installed)")

client.delete_cookie("slpm_mode")
r = client.post("/api/startup/add", json={"id": "no-such-app-xyz"})
check("an unknown startup app id is a 404", r.status_code, 404)
r = client.post("/api/launch", json={"id": "../../etc/passwd"})
check("launching by a path-like id runs nothing", (r.get_json() or {}).get("ok"), False)
r = client.post("/api/download/start", json={"url": "http://127.0.0.1/x"})
check("downloading from loopback is a 400", r.status_code, 400)
r = client.post("/api/download/start",
                json={"url": "http://169.254.169.254/latest/meta-data/"})
check("downloading from the metadata address is a 400", r.status_code, 400)
r = client.post("/api/download/start", json={"url": "file:///etc/passwd"})
check("a non-web scheme is a 400", r.status_code, 400)

print()
if FAILED:
    print(f"{len(FAILED)} check(s) FAILED: {', '.join(FAILED)}")
    sys.exit(1)
print("All checks passed.")
