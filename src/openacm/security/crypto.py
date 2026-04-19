import os
import secrets
from pathlib import Path
from dotenv import set_key, load_dotenv
import structlog

log = structlog.get_logger()

ENV_FILE = Path("config/.env")


def get_media_dir() -> Path:
    """Return the absolute path to data/media/, creating it if needed."""
    root = os.environ.get("OPENACM_PROJECT_ROOT", str(Path.cwd()))
    media = Path(root) / "data" / "media"
    media.mkdir(parents=True, exist_ok=True)
    return media


def decrypt_file(file_path: Path) -> bytes:
    """Read a media file from disk.

    Handles legacy Fernet-encrypted files transparently so old files still work.
    New files are stored plain.
    """
    import os as _os
    media_root = _os.path.realpath(get_media_dir()) + _os.sep
    real = _os.path.realpath(file_path)
    if not real.startswith(media_root):
        raise ValueError(f"Access denied: path is outside media directory")
    with open(real, "rb") as f:
        data = f.read()
    # Legacy Fernet tokens start with 'gAAAAA' (base64-encoded header)
    if data[:6] == b"gAAAAA":
        try:
            from cryptography.fernet import Fernet
            key_str = os.environ.get("MEDIA_ENCRYPTION_KEY", "")
            if key_str:
                return Fernet(key_str.encode()).decrypt(data)
        except Exception:
            pass
    return data


def save_encrypted(data: bytes, dest_path: Path):
    """Save bytes to disk (plain, no encryption)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)


def get_or_create_dashboard_token() -> str:
    """Retrieve or generate the dashboard access token."""
    load_dotenv(ENV_FILE)
    token = os.environ.get("DASHBOARD_TOKEN")

    if not token:
        token = secrets.token_urlsafe(48)

        if not ENV_FILE.parent.exists():
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

        set_key(str(ENV_FILE), "DASHBOARD_TOKEN", token)
        os.environ["DASHBOARD_TOKEN"] = token
        log.info("Generated new dashboard token")

    return token
