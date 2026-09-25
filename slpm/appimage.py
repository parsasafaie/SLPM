"""AppImage: install to ~/Applications, extract an icon, register a .desktop shortcut."""
import os
import posixpath
import re
import shutil
import tempfile
import tarfile
import zipfile
from pathlib import Path

from . import desktop, proc, util

_t = proc.t

TARGET_DIR = Path.home() / "Applications"


def _slug(name):
    """A short, file-safe name for an AppImage: architecture and version dropped."""
    stem = re.sub(r"[-_.]?(x86_64|amd64|aarch64|arm64|i386|i686)\b", "", name, flags=re.I)
    stem = re.sub(r"[-_.]?v?\d+(\.\d+){1,3}.*$", "", stem)
    return util.slug(stem, "app")[:48]


def _appimage_meta(path, tmpdir):
    """Ask the AppImage to unpack itself; return (name, icon_path, payload_root, error)."""
    AppImage = Path(path).resolve()
    os.chmod(AppImage, 0o755)
    # --appimage-extract is supported by type-2 AppImages and needs no sandbox.
    rc, out, err = proc.run(
        [str(AppImage), "--appimage-extract"], cwd=tmpdir, timeout=180
    )
    root = Path(tmpdir) / "squashfs-root"
    if rc != 0 or not root.is_dir():
        # Not a type-2 AppImage, or it needs FUSE to unpack and could not.
        detail = (err or out or "").strip().splitlines()
        detail = detail[-1][:200] if detail else ""
        return None, None, None, (
            _t("This file is not a working AppImage. Only self-contained AppImage "
               "files can be installed this way") + (f" ({detail})." if detail else ".")
        )
    name, icon = None, None
    for f in root.glob("*.desktop"):
        entry = desktop.parse(f)
        if entry.get("Name") and not entry.get("NoDisplay", "").lower() == "true":
            name = entry["Name"]
            icon = entry.get("Icon")
            break
    if not icon:
        for pat in (".DirIcon", "*.png", "*.svg"):
            hits = sorted(root.glob(pat))
            if hits:
                icon = str(hits[0])
                break
    else:
        cand = root / icon
        for ext in ("", ".png", ".svg", ".xpm"):
            if (root / f"{icon}{ext}").exists():
                cand = root / f"{icon}{ext}"
                break
        icon = str(cand) if cand.exists() else None
    if not name:
        name = _slug(AppImage.stem).replace("-", " ").title()
    return name, icon, root, ""


def install(path):
    """Returns (ok, message, desktop_path)."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return False, _t("File not found: {path}", path=path), None

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(path.stem)
    target = _unique(TARGET_DIR / f"{slug}.AppImage")

    name, icon_src, root, reason = None, None, None, ""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            name, icon_src, root, reason = _appimage_meta(path, tmp)
        except OSError as exc:
            return False, _t("Could not read the AppImage: {exc}", exc=exc), None

        if name is None:
            return False, reason or _t(
                "This file could not be unpacked as an AppImage. If it came out of a "
                ".zip or .tar.gz, extract it first and install the AppImage inside."
            ), None

        # Copy only once the file has proven it is a real AppImage, so a failed
        # install never leaves a stray binary behind.
        shutil.copy2(path, target)
        target.chmod(0o755)

        icon_ref = None
        if icon_src and Path(icon_src).exists():
            icon_ref = _install_icon(Path(icon_src), slug)

    df = desktop.desktop_file(
        name=name,
        exec_line=f'"{target}"',
        icon=icon_ref,
        comment=_t("Installed with SLPM"),
        categories=("Utility",),
        path_override=f"slpm-{slug}.desktop",
    )
    return True, _t("{name} was installed. A shortcut is available in your "
                    "applications menu.", name=name), df


def _install_icon(src, slug):
    ext = src.suffix.lower() or ".png"
    dest_dir = desktop.ICON_DIR / "256x256/apps"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"slpm-{slug}{ext}"
    shutil.copy2(src, dest)
    if proc.which("gtk-update-icon-cache") and (desktop.ICON_DIR / "index.theme").exists():
        proc.run(["gtk-update-icon-cache", "-f", "-t", str(desktop.ICON_DIR)], timeout=30)
    return f"slpm-{slug}"


def uninstall(desktop_path):
    """Remove the .desktop file, the AppImage it points at, and the icon we copied."""
    desktop_path = Path(desktop_path)
    entry = desktop.parse(desktop_path)
    argv = desktop.exec_argv(entry.get("Exec", ""))
    removed = []
    if argv:
        binary = Path(argv[0])
        try:
            binary.relative_to(Path.home())
        except ValueError:
            binary = None  # never delete outside the user's home
        if binary and binary.exists() and binary.suffix == ".AppImage":
            binary.unlink()
            removed.append(str(binary))
    desktop.remove(desktop_path)
    _remove_icon(desktop_path.stem)
    if not removed:
        return True, _t("The shortcut was removed. The application files were left "
                       "in place (they are not managed by SLPM).")
    return True, _t("Removed {name} and its shortcut.", name=Path(removed[0]).name)


def _remove_icon(desktop_stem):
    """Drop the icon copied at install time, so removing an app leaves nothing behind."""
    slug = desktop_stem[5:] if desktop_stem.startswith("slpm-") else desktop_stem
    removed = False
    for root in (desktop.ICON_DIR, Path("/usr/share/icons/hicolor")):
        if not root.is_dir():
            continue
        for cand in root.glob(f"*/apps/slpm-{slug}.*"):
            try:
                cand.unlink()
                removed = True
            except OSError:
                pass
    if removed and proc.which("gtk-update-icon-cache") and (desktop.ICON_DIR / "index.theme").exists():
        proc.run(["gtk-update-icon-cache", "-f", "-t", str(desktop.ICON_DIR)], timeout=30)


def _unique(path):
    if not path.exists():
        return path
    for i in range(2, 100):
        cand = path.with_name(f"{path.stem}-{i}{path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem}-{os.getpid()}{path.suffix}")


# ------------------------------------------------------------------- archives

_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tar.zst",
                     ".tar", ".zip", ".7z", ".rar", ".xz", ".gz")


def is_archive(name):
    return name.lower().endswith(_ARCHIVE_SUFFIXES)


def _member_escapes(base, name, target=None):
    """Would this archive member - or, for a link, where the link points - land
    outside base?

    Judged with path algebra only (normpath), because the members do not exist yet:
    an absolute name, a ".." that climbs past base, or a link whose resolved target
    points outside base all count as escaping.
    """
    base = posixpath.normpath(str(base))
    if not name or name.startswith("/"):
        return True
    path = posixpath.normpath(posixpath.join(base, name))
    if path != base and not path.startswith(base + "/"):
        return True
    if target is None:
        return False
    if target.startswith("/"):
        target = posixpath.normpath(target)
    else:
        target = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
    return target != base and not target.startswith(base + "/")


def _tar_members_escape(path, dest):
    """None if every member of a tar archive stays inside dest, else an error message.

    The check mirrors what tarfile's "data" filter rejects - absolute paths, ".."
    climbing out, links that point out - and refuses special files (devices, fifos),
    which a user archive has no business containing.
    """
    escape = _t("The archive contains paths that would be written outside the "
                "destination folder.")
    unsafe = _t("The archive could not be extracted safely.")
    try:
        with tarfile.open(path) as tf:
            members = tf.getmembers()
    except Exception:
        # A compression the stdlib cannot read (e.g. .tar.zst on an old interpreter):
        # list the members through the system tar and judge that instead.
        if not proc.which("tar"):
            return unsafe
        rc, out, _ = proc.run(["tar", "-tf", str(path)], timeout=120)
        if rc != 0:
            return unsafe
        for name in proc.lines(out):
            if _member_escapes(dest, name):
                return escape
        return None
    for m in members:
        if not (m.isfile() or m.isdir() or m.issym() or m.islnk()):
            return unsafe
        target = m.linkname if (m.issym() or m.islnk()) else None
        if _member_escapes(dest, m.name, target):
            return escape
    return None


def _zip_members_escape(path, dest):
    """Same judgment for a zip, over the entry names."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return None  # unreadable header: the extractor below will report its own error
    for name in names:
        if _member_escapes(dest, name):
            return _t("The archive contains paths that would be written outside the "
                      "destination folder.")
    return None


def extract(path, dest):
    """Extract into dest. Returns (ok, message, dest).

    Every member is checked to stay inside dest before anything is written: a
    malicious or broken archive whose paths climb out (a "tar slip") is refused
    rather than unpacked where it points.
    """
    path = Path(path).expanduser().resolve()
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    low = path.name.lower()
    if low.endswith(".zip"):
        problem = _zip_members_escape(path, dest)
        if problem:
            return False, problem, dest
        tool = None
        for cand in ("unzip", "bsdtar", "7z"):
            if proc.which(cand):
                tool = cand
                break
        if not tool:
            return False, _t("No zip extractor is installed (unzip)."), dest
        argv = {"unzip": ["unzip", "-o", "-q", str(path), "-d", str(dest)],
                "bsdtar": ["bsdtar", "-xf", str(path), "-C", str(dest)],
                "7z": ["7z", "x", "-y", f"-o{dest}", str(path)]}[tool]
    elif low.endswith((".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tar.zst", ".tar")):
        problem = _tar_members_escape(path, dest)
        if problem:
            return False, problem, dest
        argv = ["tar", "-xf", str(path), "-C", str(dest)]
    elif proc.which("7z"):
        # 7z itself refuses absolute paths and strips a leading drive on modern
        # releases, so no member pre-check is possible for formats this branch takes.
        argv = ["7z", "x", "-y", f"-o{dest}", str(path)]
    else:
        return False, _t("This archive format needs the '7z' tool, which is not "
                         "installed."), dest

    rc, out, err = proc.run(argv, timeout=300)
    if rc != 0:
        return False, (err or out).strip().splitlines()[-1] if (err or out).strip() else \
            _t("Extraction failed."), dest

    # A single top-level folder is common: flatten it so the launcher is easy to find.
    entries = [e for e in dest.iterdir() if not e.name.startswith("__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir():
        return True, _t("Extracted."), entries[0]
    return True, _t("Extracted."), dest


def unwrap_single_dir(root, depth=2):
    """If an archive nested one folder inside another, step in so the launcher search
    sees the real payload instead of a directory that looks empty."""
    root = Path(root)
    for _ in range(depth):
        entries = [e for e in root.iterdir() if not e.name.startswith("__MACOSX")]
        if len(entries) != 1 or not entries[0].is_dir():
            return root
        root = entries[0]
    return root


def find_launchers(root):
    """
    Look for something the user could actually run inside an extracted archive.
    Returns list of dicts: {kind: 'desktop'|'exec'|'script', path, name}
    """
    root = unwrap_single_dir(root)
    found = []
    for f in root.rglob("*.desktop"):
        if f.is_file() and "/squashfs-root/" not in str(f):
            entry = desktop.parse(f)
            found.append({"kind": "desktop", "path": str(f),
                          "name": entry.get("Name") or f.stem})
    for f in root.rglob("*"):
        if not f.is_file() or f.is_symlink():
            continue
        try:
            rel = f.relative_to(root)
        except ValueError:
            continue  # a file that vanished or moved under us between the two passes
        # Skip a FHS-style payload tree, but a plain "bin" folder holding the app's
        # own launcher is normal and must not be skipped.
        if rel.parts[:2] == ("usr", "bin") or any(
            part in ("lib", "lib64", "share", "include") for part in rel.parts[:-1]
        ):
            continue
        n = f.name.lower()
        # Archives often lose the executable bit, so a file that merely looks like a
        # program (shebang or ELF) is still offered; it gets chmod +x on registration.
        looks_runnable = n.endswith((".sh", ".run", ".bin", ".appimage")) or (
            f.suffix == "" and _looks_binary(f)
        )
        if looks_runnable:
            found.append({"kind": "script" if n.endswith(".sh") else "exec",
                          "path": str(f), "name": f.name})
    # Prefer .desktop entries, then top-most files.
    found.sort(key=lambda f: (f["kind"] != "desktop", str(f["path"]).count("/")))
    return found[:20]


def _looks_binary(f):
    try:
        with open(f, "rb") as fh:
            head = fh.read(4)
        return head.startswith(b"\x7fELF") or head[:2] == b"#!"
    except OSError:
        return False
