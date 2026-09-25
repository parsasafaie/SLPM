"""Small shared helpers that used to be copy-pasted between modules."""
import os
import re
import shutil
import tempfile


def atomic_write(path, text):
    """Replace a file atomically, so a half-written file is never read back.

    Writes to a temporary file in the same directory and renames it over the target.
    A crash or a second writer racing the first can therefore leave either the old
    file or the new one, never a truncated mix of the two - which matters for
    .desktop files and autostart entries, because a truncated one makes the desktop
    environment drop the app from the menu.
    """
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".slpm-")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        shutil.move(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def slug(text, fallback="app"):
    """A file-safe name for user-supplied text: no separators, no case, no leading dot.

    Slashes, spaces and every other metacharacter collapse into a single dash, so the
    result can never be a path or a flag. Used for the names of generated .desktop
    files, AppImage shortcuts and download filenames.
    """
    s = _SLUG_RE.sub("-", str(text or "")).strip("-.")
    s = s.lower()
    return s or fallback
