"""
Secret management for the Maestro agent mesh.

Centralizes all credential storage in ~/.maestro/secrets.env (chmod 600)
with backup/restore, per-profile resolution, and sync from profile .env files.

Key conventions in secrets.env:
  - Global secrets: KEY=VALUE (shared across all profiles)
  - Per-profile secrets: <PROFILE>_KEY=VALUE (override globals for a specific profile)
  - The gateway loader resolves per-profile keys to their base name
    (e.g. PROTEUS_TELEGRAM_BOT_TOKEN -> TELEGRAM_BOT_TOKEN when profile=proteus)

Usage:
  from maestro.secrets import (
      load_secrets, save_secrets, backup_secrets, restore_secrets,
      resolve_secrets_for_profile, sync_from_profiles,
  )
"""

import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────

MAESTRO_HOME = Path(os.path.expanduser("~/.maestro"))
SECRETS_FILE = MAESTRO_HOME / "secrets.env"
BACKUPS_DIR = MAESTRO_HOME / "backups"

# Credential key suffixes that identify secrets (not config)
_SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_API_KEY")
# Exact key names that are secrets even without a suffix
_SECRET_EXACT = frozenset({
    "API_SERVER_KEY",  # shared gateway auth key
})

# ──────────────────────────────────────────────
# Low-level file I/O
# ──────────────────────────────────────────────

def _ensure_secrets_file() -> Path:
    """Create secrets.env with restrictive permissions if it doesn't exist."""
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SECRETS_FILE.exists():
        SECRETS_FILE.write_text("# Maestro centralized secrets\n# Auto-managed by maestro secrets commands\n", encoding="utf-8")
        os.chmod(SECRETS_FILE, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600
    return SECRETS_FILE


def _ensure_backups_dir() -> Path:
    """Create backups directory if it doesn't exist."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUPS_DIR


def _is_secret_key(key: str) -> bool:
    """Determine if an env var key is a secret/credential (vs config)."""
    if key in _SECRET_EXACT:
        return True
    return any(key.endswith(suffix) for suffix in _SECRET_SUFFIXES)


# ──────────────────────────────────────────────
# Parse & write secrets.env
# ──────────────────────────────────────────────

def parse_secrets_env(path: Path = None) -> Dict[str, str]:
    """Parse a secrets.env file into a dict of key=value pairs.

    Supports:
      - Comments (lines starting with #)
      - Blank lines
      - KEY=VALUE lines
      - Profile-prefixed keys: PROTEUS_TELEGRAM_BOT_TOKEN=xxx
    """
    target = path or SECRETS_FILE
    result: Dict[str, str] = {}
    if not target.exists():
        return result
    for line in target.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip("\"'")
    return result


def write_secrets_env(kv: Dict[str, str], path: Path = None, header: str = None) -> Path:
    """Write a secrets.env file atomically with chmod 600.

    Args:
        kv: Ordered dict of key=value pairs to write.
        path: Target file (defaults to ~/.maestro/secrets.env).
        header: Optional header comment. Defaults to standard header.

    Returns:
        Path to the written file.
    """
    target = path or _ensure_secrets_file()
    target.parent.mkdir(parents=True, exist_ok=True)

    if header is None:
        header = "# Maestro centralized secrets\n# Auto-managed by maestro secrets commands"

    lines = [header, ""]
    # Group: global secrets first, then per-profile secrets
    global_keys = sorted(k for k in kv if "_" not in k.split("=", 1)[0].split("_", 1)[0] or not _is_profile_prefixed(k))
    # Actually, let's just sort alphabetically for simplicity
    for key in sorted(kv.keys()):
        lines.append(f"{key}={kv[key]}")

    content = "\n".join(lines) + "\n"

    # Atomic write
    fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp", prefix=".secrets_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        # Atomic replace
        from utils import atomic_replace
        atomic_replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Enforce chmod 600
    os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    return target


# ──────────────────────────────────────────────
# Profile prefix resolution
# ──────────────────────────────────────────────

def _is_profile_prefixed(key: str) -> bool:
    """Check if a key has a profile prefix like PROTEUS_TELEGRAM_BOT_TOKEN."""
    # Known profile names in the mesh
    known_profiles = {"hermes", "proteus", "songbird", "lexicon", "mnemosyne", "stormtrooper", "braino", "cupcake"}
    prefix = key.split("_")[0].lower()
    return prefix in known_profiles and key != key.split("_", 1)[1] if "_" in key else False


def _strip_profile_prefix(key: str) -> Tuple[str, str]:
    """Strip profile prefix from a key, returning (profile, base_key).

    E.g. 'PROTEUS_TELEGRAM_BOT_TOKEN' -> ('proteus', 'TELEGRAM_BOT_TOKEN')
    If no profile prefix, returns ('', key).
    """
    known_profiles = {"hermes", "proteus", "songbird", "lexicon", "mnemosyne", "stormtrooper", "braino", "cupcake"}
    parts = key.split("_", 1)
    if len(parts) == 2:
        prefix_lower = parts[0].lower()
        if prefix_lower in known_profiles:
            return prefix_lower, parts[1]
    return "", key


def resolve_secrets_for_profile(profile: str, secrets: Dict[str, str] = None) -> Dict[str, str]:
    """Resolve secrets for a specific profile.

    Resolution order:
      1. Global keys (no profile prefix) are included for all profiles
      2. Profile-prefixed keys (e.g. PROTEUS_TELEGRAM_BOT_TOKEN) override
         the global key for that profile
      3. Other profiles' prefixed keys are ignored

    Args:
        profile: Profile name (e.g. 'proteus', 'hermes')
        secrets: Parsed secrets dict (loads from file if not provided)

    Returns:
        Dict of resolved {BASE_KEY: value} for this profile.
    """
    if secrets is None:
        secrets = parse_secrets_env()

    resolved: Dict[str, str] = {}

    # First pass: global keys
    for key, value in secrets.items():
        prefix, base_key = _strip_profile_prefix(key)
        if not prefix:
            # Global key
            resolved[key] = value

    # Second pass: profile-specific overrides
    profile_upper = profile.upper()
    for key, value in secrets.items():
        prefix, base_key = _strip_profile_prefix(key)
        if prefix and prefix.lower() == profile.lower():
            # This profile's override — replace the global key
            resolved[base_key] = value

    return resolved


def _sanitize_credential_value(key: str, value: str) -> str:
    """Strip non-ASCII from credential values (mirrors env_loader._sanitize_loaded_credentials)."""
    if not _is_secret_key(key):
        return value
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return value.encode("ascii", errors="ignore").decode("ascii")


def apply_secrets_to_env(profile: str, secrets: Dict[str, str] = None) -> Dict[str, str]:
    """Apply resolved secrets to os.environ for a given profile.

    Values for credential keys are sanitized to pure ASCII (stripping
    Unicode lookalike glyphs), mirroring the post-load sanitization in
    env_loader._sanitize_loaded_credentials.

    Returns the dict that was applied.
    """
    from hermes_cli.env_loader import _sanitize_loaded_credentials
    resolved = resolve_secrets_for_profile(profile, secrets)
    for key, value in resolved.items():
        os.environ[key] = _sanitize_credential_value(key, value)
    # Run the shared credential sanitizer to emit warnings for any
    # remaining non-ASCII credential values in the full environment.
    _sanitize_loaded_credentials()
    return resolved


# ──────────────────────────────────────────────
# Backup & Restore
# ──────────────────────────────────────────────

def backup_secrets(tag: str = None) -> Path:
    """Create a timestamped backup of secrets.env.

    Args:
        tag: Optional tag suffix (e.g. 'pre-migration').

    Returns:
        Path to the backup file.
    """
    _ensure_backups_dir()
    if not SECRETS_FILE.exists():
        _ensure_secrets_file()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = f"-{tag}" if tag else ""
    backup_name = f"secrets-{ts}{suffix}.env"
    backup_path = BACKUPS_DIR / backup_name

    shutil.copy2(SECRETS_FILE, backup_path)
    os.chmod(backup_path, stat.S_IRUSR | stat.S_IWUSR)  # chmod 600

    # Keep only last 10 backups to avoid unbounded growth
    backups = sorted(BACKUPS_DIR.glob("secrets-*.env"))
    if len(backups) > 10:
        for old in backups[:-10]:
            old.unlink(missing_ok=True)

    return backup_path


def restore_secrets(date_tag: str = None, backup_path: Path = None) -> Path:
    """Restore secrets.env from a backup.

    Args:
        date_tag: Date string to find backup (e.g. '20260518'). Uses the
                  most recent backup matching this prefix.
        backup_path: Explicit path to restore from.

    Returns:
        Path to the restored secrets.env.
    """
    if backup_path:
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")
    else:
        candidates = sorted(BACKUPS_DIR.glob("secrets-*.env"), reverse=True)
        if not candidates:
            raise FileNotFoundError("No backups found in ~/.maestro/backups/")
        if date_tag:
            matching = [c for c in candidates if date_tag in c.name]
            if not matching:
                raise FileNotFoundError(f"No backup matching '{date_tag}' in ~/.maestro/backups/")
            backup_path = matching[0]
        else:
            backup_path = candidates[0]

    # Backup current before overwriting
    if SECRETS_FILE.exists():
        backup_secrets(tag="pre-restore")

    shutil.copy2(backup_path, SECRETS_FILE)
    os.chmod(SECRETS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    return SECRETS_FILE


def list_backups() -> List[Dict[str, str]]:
    """List available backups with metadata.

    Returns:
        List of dicts with keys: name, path, size, modified.
    """
    if not BACKUPS_DIR.exists():
        return []
    backups = []
    for f in sorted(BACKUPS_DIR.glob("secrets-*.env"), reverse=True):
        st = f.stat()
        backups.append({
            "name": f.name,
            "path": str(f),
            "size": f"{st.st_size} bytes",
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return backups


# ──────────────────────────────────────────────
# Sync from profile .env files
# ──────────────────────────────────────────────

def _get_root_hermes_home() -> Path:
    """Get the root hermes home directory (not the active profile's home).

    When a profile is active, get_hermes_home() returns
    ~/.hermes/profiles/<profile>/.  We need ~/.hermes/ to find all
    profile .env files for sync.
    """
    from hermes_cli.profiles import _get_default_hermes_home
    return _get_default_hermes_home()


def _get_profile_home(profile: str) -> Path:
    """Get the hermes home directory for a profile.

    Uses the root hermes home (not the active profile's home) so all
    profiles can be discovered regardless of which profile is active.
    """
    base = _get_root_hermes_home()
    if profile == "hermes":
        return base
    return base / "profiles" / profile


def sync_from_profiles(profiles: List[str] = None) -> Dict[str, str]:
    """Synchronize secrets from profile .env files into centralized secrets.env.

    For each profile:
      1. Read the profile's .env file
      2. Extract all secret/credential keys (tokens, API keys, etc.)
      3. Add them to secrets.env with a profile prefix if the key already
         exists globally with a different value
      4. If the value matches the global value, skip (dedup)

    Args:
        profiles: List of profile names to sync. If None, syncs all profiles.

    Returns:
        Dict of all keys written to secrets.env.
    """
    base = _get_root_hermes_home()

    # Discover profiles from directories
    if profiles is None:
        profiles = []
        if base.exists():
            # Root profile
            if (base / ".env").exists():
                profiles.append("hermes")
            # Child profiles
            profiles_dir = base / "profiles"
            if profiles_dir.exists():
                for d in sorted(profiles_dir.iterdir()):
                    # Cupcake stores its .env in home/.env, others in .env
                    has_env = (d / ".env").exists() or (d / "home" / ".env").exists()
                    if d.is_dir() and has_env:
                        profiles.append(d.name)

    # Load current secrets.env (start fresh)
    secrets: Dict[str, str] = {}
    if SECRETS_FILE.exists():
        secrets = parse_secrets_env()

    # Track global values to detect per-profile overrides needed
    global_secrets: Dict[str, str] = {}

    for profile in profiles:
        if profile == "hermes":
            env_path = base / ".env"
        elif profile == "cupcake":
            env_path = base / "profiles" / profile / "home" / ".env"
        else:
            env_path = base / "profiles" / profile / ".env"

        if not env_path.exists():
            continue

        # Parse the profile's .env
        profile_env: Dict[str, str] = {}
        for line in env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            profile_env[key] = value

        for key, value in profile_env.items():
            if not _is_secret_key(key):
                continue

            if key in global_secrets:
                # Key exists globally with a different value — need profile prefix
                if global_secrets[key] != value:
                    profile_key = f"{profile.upper()}_{key}"
                    secrets[profile_key] = value
                # Same value as global — skip (dedup)
            else:
                # First occurrence — add as global
                secrets[key] = value
                global_secrets[key] = value

    # Write back
    if secrets:
        write_secrets_env(secrets)

    return secrets


def strip_secrets_from_profile(profile: str) -> List[str]:
    """Remove secret keys from a profile's .env file.

    After syncing to centralized secrets.env, profile .env files
    should only contain non-secret config (ports, hosts, etc.).

    Args:
        profile: Profile name to strip.

    Returns:
        List of keys that were removed.
    """
    base = _get_root_hermes_home()
    if profile == "hermes":
        env_path = base / ".env"
    elif profile == "cupcake":
        env_path = base / "profiles" / profile / "home" / ".env"
    else:
        env_path = base / "profiles" / profile / ".env"

    if not env_path.exists():
        return []

    lines = env_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    new_lines = []
    removed = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if _is_secret_key(key):
            removed.append(key)
            # Add a comment noting where the secret now lives
            new_lines.append(f"# {key} moved to ~/.maestro/secrets.env")
        else:
            new_lines.append(line)

    # Atomic write
    from utils import atomic_replace
    fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix=".tmp", prefix=".env_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
            f.flush()
            os.fsync(f.fileno())
        atomic_replace(tmp_path, env_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return removed


def list_secrets(profile: str = None) -> Dict[str, str]:
    """List secrets, optionally resolved for a specific profile.

    Values are REDACTED (showing only first 4 and last 4 chars).

    Args:
        profile: If provided, resolve per-profile overrides.

    Returns:
        Dict of {key: REDACTED_value} for display.
    """
    if profile:
        resolved = resolve_secrets_for_profile(profile)
    else:
        resolved = parse_secrets_env()

    # Redact values for display
    redacted = {}
    for key, value in resolved.items():
        if len(value) > 12:
            redacted[key] = f"{value[:4]}...{value[-4:]}"
        elif len(value) > 4:
            redacted[key] = f"{value[:2]}***"
        else:
            redacted[key] = "***"
    return redacted