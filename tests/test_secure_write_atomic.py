"""Tests for _secure_write() atomic permission handling."""
import os
import stat
from unittest.mock import patch


class TestSecureWriteAtomic:
    """_secure_write must create files with 0o600 in a single syscall."""

    def test_file_created_with_0600(self, tmp_path):
        from streamforge.schema_writer import _secure_write

        p = tmp_path / "test.yaml"
        _secure_write(p, "content here")
        assert p.exists()
        mode = stat.S_IMODE(os.stat(p).st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"

    def test_no_permission_window(self, tmp_path):
        """Verify os.open is called with O_CREAT and mode 0o600 together."""
        from streamforge.schema_writer import _secure_write

        calls = []
        original_open = os.open

        def tracking_open(path, flags, mode=0o777, *args, **kwargs):
            calls.append({"path": path, "flags": flags, "mode": mode})
            return original_open(path, flags, mode, *args, **kwargs)

        with patch("os.open", side_effect=tracking_open):
            _secure_write(tmp_path / "test.yaml", "content")

        # The tmp file creation must use O_CREAT with 0o600
        create_calls = [c for c in calls if c["flags"] & os.O_CREAT]
        assert len(create_calls) >= 1, "os.open with O_CREAT must be called"
        assert create_calls[0]["mode"] == 0o600, (
            f"Mode must be 0o600, got {oct(create_calls[0]['mode'])}"
        )

    def test_atomic_rename_no_tmp_remains(self, tmp_path):
        from streamforge.schema_writer import _secure_write

        p = tmp_path / "test.yaml"
        _secure_write(p, "content")
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, "No .tmp files should remain after write"

    def test_parent_dirs_created(self, tmp_path):
        from streamforge.schema_writer import _secure_write

        p = tmp_path / "a" / "b" / "c" / "test.yaml"
        _secure_write(p, "deep content")
        assert p.exists()
        assert p.read_text() == "deep content"

    def test_content_matches(self, tmp_path):
        from streamforge.schema_writer import _secure_write

        content = "stream: test\nversion: 1.0.0\nfields: []\n"
        p = tmp_path / "schema.yaml"
        _secure_write(p, content)
        assert p.read_text(encoding="utf-8") == content
