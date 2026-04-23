"""Shared file safety rules used by both tools and ACP shims."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Thread-local read safe-root context
# ---------------------------------------------------------------------------
# Gateway sets this per-request thread so that platform-specific read
# restrictions apply only to that session, leaving CLI and other platforms
# completely unrestricted.
#
# Usage (in gateway):
#   with read_safe_root_context(["/allowed/path1", "/allowed/path2"]):
#       agent.run_conversation(...)
#
# file_tools.py calls is_read_denied() which reads from this context.
# ---------------------------------------------------------------------------

_tl = threading.local()


class read_safe_root_context:
    """Context manager that activates read-root restrictions for the current thread."""

    def __init__(self, roots: list[str]):
        resolved = []
        for r in roots:
            try:
                resolved.append(os.path.realpath(os.path.expanduser(r)))
            except Exception:
                pass
        self._roots = resolved

    def __enter__(self):
        self._prev = getattr(_tl, "read_safe_roots", None)
        _tl.read_safe_roots = self._roots
        return self

    def __exit__(self, *_):
        _tl.read_safe_roots = self._prev


def _hermes_home_path() -> Path:
    """Resolve the active HERMES_HOME (profile-aware) without circular imports."""
    try:
        from hermes_constants import get_hermes_home  # local import to avoid cycles
        return get_hermes_home()
    except Exception:
        return Path(os.path.expanduser("~/.hermes"))


def build_write_denied_paths(home: str) -> set[str]:
    """Return exact sensitive paths that must never be written."""
    hermes_home = _hermes_home_path()
    return {
        os.path.realpath(p)
        for p in [
            os.path.join(home, ".ssh", "authorized_keys"),
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "config"),
            str(hermes_home / ".env"),
            os.path.join(home, ".bashrc"),
            os.path.join(home, ".zshrc"),
            os.path.join(home, ".profile"),
            os.path.join(home, ".bash_profile"),
            os.path.join(home, ".zprofile"),
            os.path.join(home, ".netrc"),
            os.path.join(home, ".pgpass"),
            os.path.join(home, ".npmrc"),
            os.path.join(home, ".pypirc"),
            "/etc/sudoers",
            "/etc/passwd",
            "/etc/shadow",
        ]
    }


def build_write_denied_prefixes(home: str) -> list[str]:
    """Return sensitive directory prefixes that must never be written."""
    return [
        os.path.realpath(p) + os.sep
        for p in [
            os.path.join(home, ".ssh"),
            os.path.join(home, ".aws"),
            os.path.join(home, ".gnupg"),
            os.path.join(home, ".kube"),
            "/etc/sudoers.d",
            "/etc/systemd",
            os.path.join(home, ".docker"),
            os.path.join(home, ".azure"),
            os.path.join(home, ".config", "gh"),
        ]
    ]


def get_safe_read_roots() -> list[str]:
    """Return active read-root allowlist for the current thread.

    Priority order:
    1. Thread-local context set by gateway via read_safe_root_context()
    2. config.yaml security.gateway_read_safe_roots
    3. HERMES_READ_SAFE_ROOT env var (colon-separated, for manual testing)

    Returns an empty list when no restriction is configured.
    """
    # 1. Thread-local context (set by gateway per platform session)
    tl_roots = getattr(_tl, "read_safe_roots", None)
    if tl_roots is not None:
        return tl_roots

    # 2. config.yaml
    try:
        from hermes_cli.config import load_config
        cfg_roots = load_config().get("security", {}).get("gateway_read_safe_roots") or []
        if cfg_roots:
            resolved = []
            for r in cfg_roots:
                try:
                    resolved.append(os.path.realpath(os.path.expanduser(str(r))))
                except Exception:
                    pass
            return resolved
    except Exception:
        pass

    # 3. Env var fallback (e.g. for manual testing)
    raw = os.getenv("HERMES_READ_SAFE_ROOT", "")
    if not raw:
        return []
    roots = []
    for part in raw.split(":"):
        part = part.strip()
        if part:
            try:
                roots.append(os.path.realpath(os.path.expanduser(part)))
            except Exception:
                pass
    return roots


def is_read_denied(path: str) -> bool:
    """Return True if path falls outside all allowed read roots.

    Only active when a read-root allowlist is configured (via
    read_safe_root_context or HERMES_READ_SAFE_ROOT).
    Path traversal attacks are neutralised via os.path.realpath.
    """
    safe_roots = get_safe_read_roots()
    if not safe_roots:
        return False  # no restriction configured
    try:
        resolved = os.path.realpath(os.path.expanduser(str(path)))
    except Exception:
        return True
    for root in safe_roots:
        if resolved == root or resolved.startswith(root + os.sep):
            return False
    return True


def get_safe_write_root() -> Optional[str]:
    """Return the resolved HERMES_WRITE_SAFE_ROOT path, or None if unset."""
    root = os.getenv("HERMES_WRITE_SAFE_ROOT", "")
    if not root:
        return None
    try:
        return os.path.realpath(os.path.expanduser(root))
    except Exception:
        return None


def is_write_denied(path: str) -> bool:
    """Return True if path is blocked by the write denylist or safe root."""
    home = os.path.realpath(os.path.expanduser("~"))
    resolved = os.path.realpath(os.path.expanduser(str(path)))

    if resolved in build_write_denied_paths(home):
        return True
    for prefix in build_write_denied_prefixes(home):
        if resolved.startswith(prefix):
            return True

    safe_root = get_safe_write_root()
    if safe_root and not (resolved == safe_root or resolved.startswith(safe_root + os.sep)):
        return True

    return False


def get_read_block_error(path: str) -> Optional[str]:
    """Return an error message when a read targets internal Hermes cache files."""
    resolved = Path(path).expanduser().resolve()
    hermes_home = _hermes_home_path().resolve()
    blocked_dirs = [
        hermes_home / "skills" / ".hub" / "index-cache",
        hermes_home / "skills" / ".hub",
    ]
    for blocked in blocked_dirs:
        try:
            resolved.relative_to(blocked)
        except ValueError:
            continue
        return (
            f"Access denied: {path} is an internal Hermes cache file "
            "and cannot be read directly to prevent prompt injection. "
            "Use the skills_list or skill_view tools instead."
        )
    return None
