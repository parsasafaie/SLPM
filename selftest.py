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

from slpm import apps, apt, appimage, desktop, helper, i18n, installer, proc  # noqa: E402

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
