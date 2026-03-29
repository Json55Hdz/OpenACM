import os
import secrets
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import set_key, load_dotenv
import structlog

log = structlog.get_logger()

ENV_FILE = Path("config/.env")


def get_media_dir() -> Path:
    """Return the absolute path to data/media/, creating it if needed.

    Uses OPENACM_PROJECT_ROOT (set by app.py) so the path is always
    correct regardless of the process working directory.
    """
    root = os.environ.get("OPENACM_PROJECT_ROOT", str(Path.cwd()))
    media = Path(root) / "data" / "media"
    media.mkdir(parents=True, exist_ok=True)
    return media


def get_or_create_key() -> bytes:
    """Retrieve the encryption key from .env or generate a new one if missing."""
    load_dotenv(ENV_FILE)
    key_str = os.environ.get("MEDIA_ENCRYPTION_KEY")

    if not key_str:
        # Generate a securely random Fernet key
        key_bytes = Fernet.generate_key()
        key_str = key_bytes.decode("utf-8")

        # Save to .env securely without loading the whole file config overwrites
        if not ENV_FILE.parent.exists():
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

        set_key(str(ENV_FILE), "MEDIA_ENCRYPTION_KEY", key_str)
        os.environ["MEDIA_ENCRYPTION_KEY"] = key_str

    return key_str.encode("utf-8")


_fernet = None


def get_cipher() -> Fernet:
    """Get the Fernet cipher instance lazily."""
    global _fernet
    if _fernet is None:
        key = get_or_create_key()
        _fernet = Fernet(key)
    return _fernet


def encrypt_file(file_path: Path):
    """Encrypt a file in place."""
    cipher = get_cipher()
    with open(file_path, "rb") as f:
        data = f.read()
    encrypted = cipher.encrypt(data)
    with open(file_path, "wb") as f:
        f.write(encrypted)


def decrypt_file(file_path: Path) -> bytes:
    """Read a media file from disk.

    Encryption has been removed. This function tries a plain read first;
    if the data looks like a Fernet token (legacy encrypted files), it
    decrypts transparently so old files still work.
    """
    with open(file_path, "rb") as f:
        data = f.read()
    # Legacy Fernet tokens start with 'gAAAAA' (base64-encoded header)
    if data[:6] == b"gAAAAA":
        try:
            return get_cipher().decrypt(data)
        except Exception:
            pass
    return data


def save_encrypted(data: bytes, dest_path: Path):
    """Save bytes to disk (plain, encryption removed)."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(data)


def get_or_create_dashboard_token() -> str:
    """Retrieve or generate the dashboard access token."""
    load_dotenv(ENV_FILE)
    # SECURITY: POR DISEÑO - Carga segura de token desde variables de entorno
    token = os.environ.get("DASHBOARD_TOKEN")

    if not token:
        token = secrets.token_urlsafe(48)

        if not ENV_FILE.parent.exists():
            ENV_FILE.parent.mkdir(parents=True, exist_ok=True)

        set_key(str(ENV_FILE), "DASHBOARD_TOKEN", token)
        os.environ["DASHBOARD_TOKEN"] = token
        log.info("Generated new dashboard token")

    return token
