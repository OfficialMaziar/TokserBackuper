"""Archive engine tests: creation, verification, extraction, encryption, safety."""
from __future__ import annotations

import os
import zipfile

import pytest

from app.services import archive as arc


@pytest.fixture()
def files(sample_tree):
    collected, total = arc.collect_files([(str(sample_tree), ["*.log", "*.tmp"])])
    assert collected
    return collected, total


@pytest.mark.parametrize("fmt", ["tar", "tar.gz", "zip", "zst"])
def test_create_verify_list(files, tmp_path, fmt):
    collected, total = files
    out = tmp_path / f"archive.{fmt}"
    result = arc.create_archive(collected, total, out, fmt=fmt, level=6)
    assert out.exists() and out.stat().st_size > 0
    assert result.file_count == len(collected)

    ok, msg = arc.verify_archive(out, fmt)
    assert ok, msg

    entries = arc.list_archive(out, fmt)
    assert len(entries) == len(collected)
    paths = {e.path for e in entries}
    assert not any(p.endswith(".log") for p in paths), "exclude pattern not applied"
    assert not any(p.endswith(".tmp") for p in paths)


def test_exclude_directory_pattern(sample_tree):
    collected, _ = arc.collect_files([(str(sample_tree), ["deep"])])
    assert not any("/deep/" in p for _, p in collected)


def test_encryption_roundtrip(files, tmp_path):
    collected, total = files
    plain = tmp_path / "a.tar.gz"
    arc.create_archive(collected, total, plain, fmt="tar.gz")
    enc = tmp_path / "a.tar.gz.enc"
    arc.encrypt_file(plain, enc, "correct horse battery")
    assert arc.is_encrypted(enc)

    ok, msg = arc.verify_archive(enc, "tar.gz", "correct horse battery")
    assert ok, msg
    bad, _ = arc.verify_archive(enc, "tar.gz", "wrong password")
    assert not bad

    dest = tmp_path / "out"
    n, size = arc.extract_archive(enc, "tar.gz", dest, password="correct horse battery")
    assert n == len(collected) and size > 0


def test_extract_roundtrip_and_content(files, sample_tree, tmp_path):
    collected, total = files
    out = tmp_path / "a.tar.gz"
    arc.create_archive(collected, total, out, fmt="tar.gz")
    dest = tmp_path / "restore"
    n, size = arc.extract_archive(out, "tar.gz", dest)
    assert n == len(collected)
    extracted = [p for p in dest.rglob("*") if p.is_file()]
    assert len(extracted) == len(collected)
    # Content survives byte-for-byte
    original = sample_tree / "index.html"
    match = [p for p in extracted if p.name == "index.html"]
    assert match and match[0].read_bytes() == original.read_bytes()


def test_zip_slip_blocked(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../escaped.txt", "pwned")
        zf.writestr("safe.txt", "ok")
    dest = tmp_path / "dest"
    n, _ = arc.extract_archive(evil, "zip", dest)
    assert n == 1
    assert not (tmp_path.parent / "escaped.txt").exists()
    assert (dest / "safe.txt").exists()


def test_absolute_path_member_blocked(tmp_path):
    evil = tmp_path / "abs.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("/etc/evil.conf", "pwned")
    dest = tmp_path / "dest"
    arc.extract_archive(evil, "zip", dest)
    assert not (dest / "etc" / "evil.conf").exists()


def test_overwrite_refused_by_default(files, tmp_path):
    collected, total = files
    out = tmp_path / "a.tar.gz"
    arc.create_archive(collected, total, out, fmt="tar.gz")
    dest = tmp_path / "restore"
    arc.extract_archive(out, "tar.gz", dest)
    with pytest.raises(arc.ArchiveError):
        arc.extract_archive(out, "tar.gz", dest, overwrite=False)
    # Explicit overwrite succeeds
    n, _ = arc.extract_archive(out, "tar.gz", dest, overwrite=True)
    assert n == len(collected)


def test_selective_extraction(files, tmp_path):
    collected, total = files
    out = tmp_path / "a.tar.gz"
    arc.create_archive(collected, total, out, fmt="tar.gz")
    entries = arc.list_archive(out, "tar.gz")
    target = [e.path for e in entries if e.path.endswith("index.html")][0]
    dest = tmp_path / "sel"
    n, _ = arc.extract_archive(out, "tar.gz", dest, selected_paths=[target])
    assert n == 1
    assert [p.name for p in dest.rglob("*") if p.is_file()] == ["index.html"]


def test_cancellation_leaves_no_partial(tmp_path, sample_tree):
    collected, total = arc.collect_files([(str(sample_tree), [])])
    out = tmp_path / "cancel.tar.gz"
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(arc.CancelledError):
        arc.create_archive(collected, total, out, fmt="tar.gz", cancel=cancel)
    assert not out.exists()
    assert not out.with_name(out.name + ".partial").exists()


def test_verify_detects_corruption(files, tmp_path):
    collected, total = files
    out = tmp_path / "a.tar.gz"
    arc.create_archive(collected, total, out, fmt="tar.gz")
    data = bytearray(out.read_bytes())
    for i in range(100, min(len(data), 400)):
        data[i] ^= 0xFF
    out.write_bytes(bytes(data))
    ok, msg = arc.verify_archive(out, "tar.gz")
    assert not ok and msg


def test_matches_any_patterns():
    from app.utils import matches_any

    assert matches_any("var/www/app.log", ["*.log"])
    assert matches_any("home/user/.git/config", [".git"])
    assert matches_any("var/cache/x", ["cache"])
    assert not matches_any("var/www/index.php", ["*.log", ".git"])
