#!/usr/bin/env python3
"""
Self-check for SLPM's parsing and safety logic. No test framework, no network,
no system changes: run with

    .venv/bin/python selftest.py

Covers the parts that are easy to get subtly wrong: Exec= parsing, desktop-entry
filtering, package classification, archive launcher discovery, and the helper's
command allowlist.
"""
import ast
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from slpm import (apps, apt, appimage, autostart, desktop, helper, i18n, installer,  # noqa: E402
                  proc)

# Runs inside node: load the browser catalog twice, once per language, and report every
# T() call whose {placeholder} survives. Prints one line per failure, nothing on success.
JS_CATALOG_CHECK = r"""
import fs from 'node:fs';
const SRC = fs.readFileSync('static/js/prefs.js', 'utf8');
const CASES = [
  ['Removing {name}…', { name: 'vlc' }],
  ['Removing {name}', { name: 'vlc' }],
  ['Remove {name}?', { name: 'vlc' }],
  ['Remove {name}', { name: 'vlc' }],
  ['Package: {name}', { name: 'vlc' }],
  ['Nothing matched “{q}”.', { q: 'foo' }],
  ['Showing the first 600 of {n} items — narrow the search to see the rest.', { n: 900 }],
];
const bad = [];
for (const lang of ['en', 'fa']) {
  globalThis.document = { documentElement: { dataset: { lang, theme: 'light' } },
                          cookie: '', querySelector: () => null };
  globalThis.window = { location: { href: 'http://x/', replace() {} } };
  globalThis.fetch = () => Promise.resolve({ json: () => Promise.resolve({}) });
  const TT = eval(SRC + '\nTT');
  for (const [text, values] of CASES) {
    const out = TT(text, values);
    if (/\{\w+\}/.test(out)) bad.push(`${lang}: ${JSON.stringify(text)} -> ${JSON.stringify(out)}`);
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
             ["apt-get", "remove", "-y", "vlc"],
             ["apt-get", "purge", "-y", "vlc"],
             ["apt-get", "remove", "-y", "a", "b"],
             ["apt-get", "autoremove", "-y"],
             ["apt-get", "install", "-f", "-y"],
             ["dpkg", "-i", "/tmp/x.deb"],
             ["dpkg", "--purge", "vlc"],
             ["dpkg", "--configure", "-a"],
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
js_check = subprocess.run(
    ["node", "--input-type=module", "-e", JS_CATALOG_CHECK],
    cwd=str(ROOT), capture_output=True, text=True,
)
if js_check.returncode == 127 or "node: not found" in js_check.stderr:
    print("skip  browser catalog (node not installed)")
else:
    check("browser catalog substitutes values in both languages",
          js_check.stdout.strip().splitlines(), [])

print()
if FAILED:
    print(f"{len(FAILED)} check(s) FAILED: {', '.join(FAILED)}")
    sys.exit(1)
print("All checks passed.")
