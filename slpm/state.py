"""Runtime paths for user-scoped state."""
import os
from pathlib import Path

UID = os.getuid()

# Where the privileged helper keeps its socket and log. XDG_RUNTIME_DIR is the
# per-user private directory the spec defines for exactly this (0700, owner-only,
# removed at logout). The fallback must be private too, because the log holds the
# output of commands run as root and the socket grants root package operations:
# a predictable /tmp path would let another local user pre-create the directory
# or the socket and race the bind. ~/.cache is already where SLPM keeps its other
# per-user state, so the fallback goes there.
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR")
               or (Path.home() / ".cache" / f"slpm-{UID}"))
HELPER_SOCK = RUNTIME / "helper.sock"
HELPER_LOG = RUNTIME / "helper.log"
CACHE = Path.home() / ".cache/slpm"
ACTIONS_LOG = CACHE / "actions.log"
