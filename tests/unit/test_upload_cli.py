from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UPLOAD_SCRIPT = ROOT / "scripts" / "upload.sh"


def _fake_curl(tmp_path: Path) -> tuple[Path, Path]:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    capture = tmp_path / "capture"
    curl = binary_dir / "curl"
    curl.write_text(
        """#!/bin/sh
set -eu
: > "${CORPUSGATE_TEST_CAPTURE}.args"
previous=
header_path=
for argument in "$@"; do
    printf '%s\n' "$argument" >> "${CORPUSGATE_TEST_CAPTURE}.args"
    if [ "$previous" = "--header" ]; then
        header_path=${argument#@}
        cp "$header_path" "${CORPUSGATE_TEST_CAPTURE}.header"
    fi
    previous=$argument
done
printf '%s\n' "$header_path" > "${CORPUSGATE_TEST_CAPTURE}.header-path"
cat > "${CORPUSGATE_TEST_CAPTURE}.body"
printf '%s' '{"document_id":"doc-123","original_filename":"guide.md","status":"ready"}'
""",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return binary_dir, capture


def _environment(binary_dir: Path, capture: Path, secret: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{binary_dir}:{environment['PATH']}",
            "CORPUSGATE_BASE_URL": "http://127.0.0.1:8000",
            "CORPUSGATE_CLIENT_API_KEY": secret,
            "CORPUSGATE_TEST_CAPTURE": str(capture),
        }
    )
    return environment


def test_upload_cli_streams_file_without_exposing_api_key(tmp_path: Path) -> None:
    binary_dir, capture = _fake_curl(tmp_path)
    source = tmp_path / "guide.md"
    content = b"# Private guide\n\nBounded retrieval."
    source.write_bytes(content)
    secret = "unit-" + ("s" * 32)

    result = subprocess.run(
        [str(UPLOAD_SCRIPT), str(source)],
        cwd=ROOT,
        env=_environment(binary_dir, capture, secret),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["document_id"] == "doc-123"
    assert (capture.with_suffix(".body")).read_bytes() == content
    arguments = (capture.with_suffix(".args")).read_text(encoding="utf-8")
    assert "filename=guide.md;type=text/markdown" in arguments
    assert "http://127.0.0.1:8000/api/v1/documents" in arguments
    assert secret not in arguments
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert (capture.with_suffix(".header")).read_text(encoding="utf-8").strip() == (
        f"X-API-Key: {secret}"
    )
    temporary_header = Path(
        (capture.with_suffix(".header-path")).read_text(encoding="utf-8").strip()
    )
    assert not temporary_header.exists()


def test_upload_cli_rejects_insecure_remote_http(tmp_path: Path) -> None:
    binary_dir, capture = _fake_curl(tmp_path)
    source = tmp_path / "guide.txt"
    source.write_text("private", encoding="utf-8")
    environment = _environment(binary_dir, capture, "unit-" + ("x" * 32))
    environment["CORPUSGATE_BASE_URL"] = "http://documents.example.com"

    result = subprocess.run(
        [str(UPLOAD_SCRIPT), str(source)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "require HTTPS" in result.stderr
    assert not capture.with_suffix(".args").exists()


def test_upload_cli_rejects_symlink_and_unsupported_file(tmp_path: Path) -> None:
    binary_dir, capture = _fake_curl(tmp_path)
    environment = _environment(binary_dir, capture, "unit-" + ("y" * 32))
    source = tmp_path / "guide.md"
    source.write_text("private", encoding="utf-8")
    link = tmp_path / "linked.md"
    link.symlink_to(source)

    symlink_result = subprocess.run(
        [str(UPLOAD_SCRIPT), str(link)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    unsupported = tmp_path / "archive.zip"
    unsupported.write_bytes(b"PK")
    unsupported_result = subprocess.run(
        [str(UPLOAD_SCRIPT), str(unsupported)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert symlink_result.returncode == 2
    assert "Symlink uploads are not allowed" in symlink_result.stderr
    assert unsupported_result.returncode == 2
    assert "Unsupported file extension" in unsupported_result.stderr
    assert not capture.with_suffix(".args").exists()
