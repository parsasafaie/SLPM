"""SLPM's own update check, against the GitHub releases of its repository.

SLPM deliberately does not update itself in place: replacing a running AppImage
means stopping the very server that is answering this request, and a silent
self-replacement is exactly the kind of act the user should see coming. What
this module does instead is the honest half of the same job: read the current
version, ask the release server for the latest one, verify which of the two
published AppImage assets matches the variant the user is actually running
(the web dashboard or the desktop window), and produce two short terminal
commands - one to download the new AppImage together with the release's
published SHA256SUMS and check them, one to make the file executable and run
it. The commands are derived entirely from the release's own asset list, so
the browser never supplies a URL, a version or a file name.

The variant matters because the two images have different file names and,
beyond that, different run environments: the desktop image runs on the host's
python3 while the web image bundles its own interpreter. Copying the wrong one
still works, but the user would download a program they did not ask for - so
``$APPIMAGE`` is read here and the commands follow it. When the check runs
from a source checkout (no ``$APPIMAGE``) there is nothing to know, so the
answer carries both command pairs and lets the page ask which one is wanted.
"""
import json
import os
import re
import urllib.error
import urllib.request

from . import __version__
from . import proc

_t = proc.t

REPO_OWNER = "parsasafaie"
REPO_NAME = "SLPM"
LATEST_API = "https://api.github.com/repos/{owner}/{repo}/releases/latest"

# The file name pattern of each asset a release ships (see
# .github/workflows/release.yml - the names are pinned there, so they are
# pinned here too: any other shape is treated as missing).
VARIANT_ASSETS = {
    "web": "SLPM_{version}-x86_64.AppImage",
    "desktop": "SLPM-Desktop_{version}-x86_64.AppImage",
}
SUMS_ASSET = "SHA256SUMS.txt"


class CheckFailure(Exception):
    """A user-facing reason the check could not be answered."""


def current_version():
    """The version this instance is running (``slpm/__init__.py``)."""
    return __version__


def running_variant():
    """Which published AppImage this instance is, from ``$APPIMAGE``.

    The AppImage runtime exports the path of the running image; its file name
    is one of the two pinned shapes above. Anything else - a source checkout,
    a renamed file - comes back as ``unknown`` and the caller must not guess.
    """
    name = os.path.basename(os.environ.get("APPIMAGE", "") or "")
    if name.startswith("SLPM-Desktop_"):
        return "desktop"
    if name.startswith("SLPM_"):
        return "web"
    return "unknown"


def _version_key(version):
    """A sortable key for a version string, or None when it is not plain dotted
    numbers (``v`` prefix allowed). A tag the comparator cannot order must not
    be compared at all - an unknown shape stays honest as ``unknown``."""
    text = str(version or "").strip().lstrip("v")
    if not text:
        return None
    parts = []
    for piece in text.split("."):
        if not re.fullmatch(r"\d+", piece or ""):
            return None
        parts.append(int(piece))
    return tuple(parts)


def compare_status(current, latest_tag):
    """``up_to_date`` if the installed version is the newest, else
    ``update_available``. Returns ``unknown`` when either side is not a plain
    dotted version, instead of guessing an order for what it cannot parse."""
    here, there = _version_key(current), _version_key(latest_tag)
    if here is None or there is None:
        return "unknown"
    return "up_to_date" if here >= there else "update_available"


def _find_asset(release, name):
    """The download URL of one release asset by exact name, or None."""
    for asset in release.get("assets") or ():
        if asset.get("name") == name and asset.get("browser_download_url"):
            return asset["browser_download_url"]
    return None


def _plan(release, variant):
    """The user-visible plan for one release: status plus terminal commands.

    ``release`` is a decoded GitHub releases/latest body. Only file names that
    exist in the asset list reach the commands, and the version in the file
    names is the release's own tag, derived server-side - never quoted back
    from a request.
    """
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise CheckFailure(_t("The release server answered, but no release was there."))
    version = tag.lstrip("v")

    status = compare_status(current_version(), tag)

    html_url = str(release.get("html_url") or "")
    sums_url = _find_asset(release, SUMS_ASSET)
    plans = {}
    for name, pattern in VARIANT_ASSETS.items():
        url = _find_asset(release, pattern.format(version=version))
        if not url:
            continue
        file_name = pattern.format(version=version)
        download = [
            "cd ~/Downloads",
            f"wget -O {file_name} {url}",
        ]
        if sums_url:
            download += [
                f"wget -O {SUMS_ASSET} {sums_url}",
                "sha256sum --ignore-missing -c SHA256SUMS.txt",
            ]
        plans[name] = {
            "file": file_name,
            "url": url,
            "download_cmd": "\n".join(download),
            "run_cmd": f"chmod +x {file_name}\n./{file_name}",
        }

    return {
        "ok": True,
        "current": current_version(),
        "latest": {"tag": tag, "version": version, "url": html_url},
        "variant": variant,
        "status": status,
        "sums_verified": bool(sums_url),
        "releases_page": "https://github.com/{}/{}/releases".format(REPO_OWNER, REPO_NAME),
        "plan": plans,
    }


def _fetch_latest():
    """Ask GitHub (releases/latest) for the newest published release."""
    request = urllib.request.Request(
        LATEST_API.format(owner=REPO_OWNER, repo=REPO_NAME),
        headers={
            "User-Agent": "SLPM/{}".format(current_version()),
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise CheckFailure(_t(
                "The release server set a limit on this request. Try again later."))
        raise CheckFailure(_t(
            "The update check failed with HTTP {code}.", code=exc.code))
    except (urllib.error.URLError, OSError, ValueError):
        raise CheckFailure(_t(
            "The release server could not be reached. Check the connection and try again."))


def check():
    """The full answer for the top-bar button: status, commands, variant."""
    return _plan(_fetch_latest(), running_variant())
