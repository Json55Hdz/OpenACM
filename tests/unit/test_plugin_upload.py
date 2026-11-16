"""Plugin upload: strict archive validation, static scan, approval and tamper detection."""
import io
import json
import zipfile

import pytest

from openacm.plugins import uploads


@pytest.fixture(autouse=True)
def plugins_folder(tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("OPENACM_PLUGINS_DIR", str(tmp_path / "plugins"))
    before_path = list(sys.path)
    yield
    sys.path[:] = before_path
    for mod in [m for m in sys.modules if m == "hello_plugin" or m.startswith("hello_plugin.")]:
        del sys.modules[mod]


def make_zip(files, manifest=..., extra=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if manifest is ...:
            manifest = {"name": "hello_plugin", "version": "1.0.0", "entry": "hello_plugin:PLUGIN"}
        if manifest is not None:
            zf.writestr("openacm_plugin.json", json.dumps(manifest))
        for name, body in files.items():
            zf.writestr(name, body)
        for info, body in extra or []:
            zf.writestr(info, body)
    return buf.getvalue()


CODE = "from openacm.plugins import Plugin\nclass P(Plugin):\n    name = 'hello_plugin'\nPLUGIN = P()\n"
GOOD = {"hello_plugin/__init__.py": CODE}


class TestArchiveRules:
    def test_a_good_plugin_is_analysed_and_nothing_is_installed(self):
        a = uploads.analyse_upload(make_zip(GOOD))
        assert a.manifest["name"] == "hello_plugin" and len(a.sha256) == 64
        assert not uploads.uploaded_dir().exists() or not list(uploads.uploaded_dir().iterdir())

    @pytest.mark.parametrize("bad", ["../evil.py", "/abs.py", "pkg/.hidden.py", "C:/x.py"])
    def test_unsafe_names_are_rejected(self, bad):
        with pytest.raises(uploads.UploadError):
            uploads.analyse_upload(make_zip({**GOOD, bad: "x=1"}))

    @pytest.mark.parametrize("name", ["hello_plugin/lib.so", "hello_plugin/x.exe", "run.sh", "a.dll", "x.bat", "y.pyc"])
    def test_native_code_and_scripts_are_rejected(self, name):
        with pytest.raises(uploads.UploadError, match="not allowed"):
            uploads.analyse_upload(make_zip({**GOOD, name: b"x"}))

    def test_symlinks_are_rejected(self):
        info = zipfile.ZipInfo("hello_plugin/link.py")
        info.external_attr = 0o120777 << 16
        with pytest.raises(uploads.UploadError, match="Links"):
            uploads.analyse_upload(make_zip(GOOD, extra=[(info, "target.py")]))

    def test_decompression_bombs_are_rejected(self):
        with pytest.raises(uploads.UploadError):
            uploads.analyse_upload(make_zip({**GOOD, "hello_plugin/big.txt": "0" * 3_000_000}))

    def test_too_many_files(self):
        many = {f"hello_plugin/f{i}.txt": "x" for i in range(uploads.MAX_FILES + 1)}
        with pytest.raises(uploads.UploadError, match="Too many"):
            uploads.analyse_upload(make_zip({**GOOD, **many}))

    def test_not_a_zip(self):
        with pytest.raises(uploads.UploadError, match="valid .zip"):
            uploads.analyse_upload(b"MZ not a zip")

    @pytest.mark.parametrize("manifest", [
        None,
        {"name": "Bad-Name", "version": "1", "entry": "x:P"},
        {"name": "os", "version": "1", "entry": "os:PLUGIN"},
        {"name": "hello_plugin", "version": "1", "entry": "other_pkg:PLUGIN"},
        {"name": "hello_plugin", "version": "1", "entry": "hello_plugin.nope:PLUGIN"},
        {"name": "hello_plugin", "entry": "hello_plugin:PLUGIN"},
        {"name": "json", "version": "1", "entry": "json:PLUGIN"},
    ])
    def test_bad_manifests_are_rejected(self, manifest):
        with pytest.raises(uploads.UploadError):
            uploads.analyse_upload(make_zip(GOOD, manifest=manifest))

    def test_a_syntax_error_is_rejected(self):
        with pytest.raises(uploads.UploadError, match="syntax"):
            uploads.analyse_upload(make_zip({"hello_plugin/__init__.py": "def (:"}))


class TestScan:
    def test_risky_code_is_flagged(self):
        src = "import subprocess, os\nimport requests\nx = eval('1')\nos.system('ls')\nkey = os.environ['K']\n"
        a = uploads.analyse_upload(make_zip({"hello_plugin/__init__.py": src}))
        whats = " ".join(f.what for f in a.findings if f.level == "high")
        for needle in ("subprocess", "eval", "system", "environ"):
            assert needle in whats
        assert any(f.level == "info" and "requests" in f.what for f in a.findings)

    def test_a_quiet_plugin_has_no_high_findings(self):
        assert not [f for f in uploads.analyse_upload(make_zip(GOOD)).findings if f.level == "high"]


class TestApproval:
    def _upload(self):
        return uploads.analyse_upload(make_zip(GOOD))

    def test_install_needs_the_exact_name(self):
        a = self._upload()
        with pytest.raises(uploads.UploadError, match="name you typed"):
            uploads.install_approved(a.id, "hello", a.sha256)
        assert not (uploads.uploaded_dir() / "hello_plugin").exists()

    def test_install_needs_the_hash_from_the_report(self):
        a = self._upload()
        with pytest.raises(uploads.UploadError, match="does not match"):
            uploads.install_approved(a.id, "hello_plugin", "0" * 64)

    def test_approved_install_extracts_and_verifies(self):
        a = self._upload()
        uploads.install_approved(a.id, "hello_plugin", a.sha256)
        folder = uploads.uploaded_dir() / "hello_plugin"
        assert (folder / "hello_plugin" / "__init__.py").is_file()
        assert uploads.verified_manifest(folder)["name"] == "hello_plugin"

    def test_a_file_changed_after_approval_is_not_loaded(self):
        a = self._upload()
        uploads.install_approved(a.id, "hello_plugin", a.sha256)
        folder = uploads.uploaded_dir() / "hello_plugin"
        (folder / "hello_plugin" / "__init__.py").write_text("import os\nos.system('x')\n")
        assert uploads.verified_manifest(folder) is None

    def test_an_added_file_after_approval_is_not_loaded(self):
        a = self._upload()
        uploads.install_approved(a.id, "hello_plugin", a.sha256)
        folder = uploads.uploaded_dir() / "hello_plugin"
        (folder / "hello_plugin" / "extra.py").write_text("x=1")
        assert uploads.verified_manifest(folder) is None

    def test_the_quarantine_id_cannot_be_a_path(self):
        with pytest.raises(uploads.UploadError):
            uploads.install_approved("../../etc/passwd", "x", "0" * 64)

    def test_remove(self):
        a = self._upload()
        uploads.install_approved(a.id, "hello_plugin", a.sha256)
        assert uploads.remove_uploaded("hello_plugin") is True
        assert uploads.remove_uploaded("hello_plugin") is False
        with pytest.raises(uploads.UploadError):
            uploads.remove_uploaded("../x")


def test_the_loader_registers_only_verified_plugins():
    from openacm.plugins import PluginManager

    a = uploads.analyse_upload(make_zip(GOOD))
    uploads.install_approved(a.id, "hello_plugin", a.sha256)
    pm = PluginManager()
    pm._load_uploaded_plugins()
    assert [p.name for p in pm.plugins] == ["hello_plugin"]


def test_the_loader_skips_tampered_plugins():
    from openacm.plugins import PluginManager

    a = uploads.analyse_upload(make_zip(GOOD))
    uploads.install_approved(a.id, "hello_plugin", a.sha256)
    (uploads.uploaded_dir() / "hello_plugin" / "hello_plugin" / "__init__.py").write_text("raise SystemExit")
    pm = PluginManager()
    pm._load_uploaded_plugins()
    assert pm.plugins == []
