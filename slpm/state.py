"""Runtime paths for user-scoped state."""
import os
from pathlib import Path

UID = os.getuid()
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/slpm-{UID}")
HELPER_SOCK = RUNTIME / "helper.sock"
HELPER_LOG = RUNTIME / "helper.log"
CACHE = Path.home() / ".cache/slpm"
ACTIONS_LOG = CACHE / "actions.log"
