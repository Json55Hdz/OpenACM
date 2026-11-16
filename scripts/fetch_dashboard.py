"""Download the prebuilt dashboard for this version so Node.js and a 2-3 minute build are not needed.

Exit code 0: dashboard in place. Anything else: the caller falls back to building it with Node.
Only talks to github.com release downloads of the OpenACM repository (https, size capped).
"""
import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "openacm" / "web" / "static"
URL = "https://github.com/Json55Hdz/OpenACM/releases/download/v{version}/dashboard.tar.gz"
MAX_BYTES = 80 * 1024 * 1024


def version() -> str:
    for line in (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=")[1].strip().strip('"')
    raise SystemExit(1)


def main() -> int:
    try:
        with urllib.request.urlopen(URL.format(version=version()), timeout=30) as resp:
            data = resp.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            return 1
        tmp = STATIC.with_name("static.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                target = (tmp / m.name).resolve()
                if not (m.isfile() or m.isdir()) or tmp.resolve() not in (target, *target.parents):
                    return 1  # refuse links and paths that escape the folder
            tar.extractall(tmp)
        if not (tmp / "index.html").exists():
            return 1
        shutil.rmtree(STATIC, ignore_errors=True)
        tmp.rename(STATIC)
        print("[OK] Dashboard descargado (sin compilar).")
        return 0
    except Exception as exc:  # no release yet, offline, etc.
        print(f"[i] Dashboard prearmado no disponible ({type(exc).__name__}); se compilará.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
