"""Archive creation, verification, listing and extraction.

All operations stream to/from disk; archives are never loaded into RAM.
Supports tar, tar.gz, zip and zstd-compressed tar, plus optional
AES-256-GCM encryption of the finished archive.
"""
from __future__ import annotations

import os
import secrets
import shutil
import struct
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger
from app.utils import is_safe_archive_member, matches_any

log = get_logger(__name__)

ProgressCb = Callable[[int, int, str], None]  # (processed_bytes, total_bytes, current_path)
CancelCb = Callable[[], bool]

CHUNK = 1024 * 1024

MAGIC = b"TBME1\n"
SALT_LEN = 16
NONCE_PREFIX_LEN = 8
TAG_LEN = 16


class ArchiveError(RuntimeError):
    pass


class CancelledError(RuntimeError):
    pass


@dataclass
class ArchiveEntry:
    path: str
    size: int
    mtime: float
    is_dir: bool = False


@dataclass
class ArchiveResult:
    path: str
    size: int
    file_count: int
    source_size: int
    entries: list[ArchiveEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------
def collect_files(
    sources: Iterable[tuple[str, list[str]]],
    *,
    follow_symlinks: bool = False,
    global_excludes: list[str] | None = None,
    cancel: CancelCb | None = None,
) -> tuple[list[tuple[Path, str]], int]:
    """Return ([(absolute_path, archive_relative_path)], total_size).

    ``sources`` is a list of (root_path, exclude_patterns). The archive keeps
    the path relative to the filesystem root (e.g. ``var/www/index.php``) so
    restores can recreate the original layout.
    """
    files: list[tuple[Path, str]] = []
    total = 0
    seen: set[str] = set()

    for root_path, excludes in sources:
        root = Path(root_path)
        if not root.exists():
            log.warning("Source path missing, skipping: %s", root_path)
            continue
        patterns = list(global_excludes or []) + list(excludes or [])

        if root.is_file():
            arc = _arc_name(root)
            if arc not in seen and not matches_any(arc, patterns):
                seen.add(arc)
                try:
                    size = root.stat().st_size
                except OSError:
                    size = 0
                files.append((root, arc))
                total += size
            continue

        for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            if cancel and cancel():
                raise CancelledError("Backup cancelled during file scan")
            # Prune excluded directories early (big performance win)
            dirnames[:] = [
                d for d in dirnames
                if not matches_any(_arc_name(Path(dirpath) / d), patterns)
            ]
            for fname in filenames:
                full = Path(dirpath) / fname
                arc = _arc_name(full)
                if arc in seen or matches_any(arc, patterns):
                    continue
                try:
                    is_link = full.is_symlink()
                    # lstat never follows a link, so it succeeds for dangling
                    # symlinks too — those must be preserved in the archive.
                    st = full.stat() if (follow_symlinks and not is_link) else full.lstat()
                except OSError:
                    continue
                if is_link and not follow_symlinks:
                    # Stored as a symlink entry; its own size is the link text.
                    seen.add(arc)
                    files.append((full, arc))
                    continue
                if not full.is_file():
                    continue
                seen.add(arc)
                files.append((full, arc))
                total += st.st_size
    return files, total


def _arc_name(path: Path) -> str:
    """Filesystem-root-relative POSIX path used inside the archive.

    ``abspath`` (not ``resolve``) is used deliberately: resolving would follow
    symlinks and change the stored path to the link *target*, which would then
    no longer match the file that was read. ``os.walk`` already yields
    absolute-style paths, so no normalisation beyond separators is needed.
    """
    absolute = os.path.abspath(str(path))
    drive, tail = os.path.splitdrive(absolute)
    tail = tail.replace("\\", "/").strip("/")
    if drive:
        # Windows: keep the drive letter as a top-level directory (C/Users/...)
        tail = f"{drive.rstrip(':').upper()}/{tail}" if tail else drive.rstrip(":").upper()
    # A source at the filesystem root must still yield a non-empty member name.
    return tail or "root"


# ---------------------------------------------------------------------------
# Encryption helpers (AES-256-GCM, chunked)
# ---------------------------------------------------------------------------
def _derive_key(password: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=390_000)
    return kdf.derive(password.encode("utf-8"))


def encrypt_file(src: str | Path, dst: str | Path, password: str) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = secrets.token_bytes(SALT_LEN)
    prefix = secrets.token_bytes(NONCE_PREFIX_LEN)
    key = _derive_key(password, salt)
    aes = AESGCM(key)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(MAGIC)
        fout.write(struct.pack(">B", SALT_LEN))
        fout.write(salt)
        fout.write(prefix)
        index = 0
        while True:
            chunk = fin.read(CHUNK)
            if not chunk:
                break
            nonce = prefix + struct.pack(">I", index)
            fout.write(struct.pack(">I", len(chunk)))
            fout.write(aes.encrypt(nonce, chunk, None))
            index += 1
        fout.write(struct.pack(">I", 0))


def is_encrypted(path: str | Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def decrypt_file(src: str | Path, dst: str | Path, password: str) -> None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    with open(src, "rb") as fin, open(dst, "wb") as fout:
        if fin.read(len(MAGIC)) != MAGIC:
            raise ArchiveError("Not a Tokser encrypted archive")
        salt_len = struct.unpack(">B", fin.read(1))[0]
        salt = fin.read(salt_len)
        prefix = fin.read(NONCE_PREFIX_LEN)
        key = _derive_key(password, salt)
        aes = AESGCM(key)
        index = 0
        while True:
            raw_len = fin.read(4)
            if len(raw_len) < 4:
                raise ArchiveError("Truncated encrypted archive")
            length = struct.unpack(">I", raw_len)[0]
            if length == 0:
                break
            payload = fin.read(length + TAG_LEN)
            if len(payload) != length + TAG_LEN:
                raise ArchiveError("Truncated encrypted archive")
            nonce = prefix + struct.pack(">I", index)
            try:
                fout.write(aes.decrypt(nonce, payload, None))
            except InvalidTag as exc:
                raise ArchiveError("Wrong password or corrupted archive") from exc
            index += 1


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
def _zstd_compressor(level: int):
    import zstandard as zstd

    return zstd.ZstdCompressor(level=max(1, min(19, level)))


def create_archive(
    files: list[tuple[Path, str]],
    total_size: int,
    out_path: str | Path,
    *,
    fmt: str = "tar.gz",
    level: int = 6,
    progress: ProgressCb | None = None,
    cancel: CancelCb | None = None,
    preserve_permissions: bool = True,
) -> ArchiveResult:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(out_path.name + ".partial")
    entries: list[ArchiveEntry] = []
    processed = 0
    count = 0

    try:
        if fmt == "zip":
            _write_zip(files, tmp_path, level, progress, cancel, entries,
                       lambda n: None)
            processed = sum(e.size for e in entries)
            count = len(entries)
        else:
            _write_tar(files, tmp_path, fmt, level, progress, cancel, entries,
                       preserve_permissions)
            processed = sum(e.size for e in entries)
            count = len(entries)

        if cancel and cancel():
            raise CancelledError("Backup cancelled")

        os.replace(tmp_path, out_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    if progress:
        progress(total_size or processed, total_size or processed, "finalize")

    return ArchiveResult(
        path=str(out_path),
        size=out_path.stat().st_size,
        file_count=count,
        source_size=processed,
        entries=entries,
    )


def _write_tar(files, out_path: Path, fmt: str, level: int, progress, cancel, entries, preserve_permissions):
    mode = "w|"
    compressor = None
    if fmt == "tar.gz":
        mode = "w|gz"
    elif fmt == "zst":
        compressor = _zstd_compressor(level)

    processed = 0
    total = 0
    for f, _ in files:
        # Per-file guard: one dangling symlink must not zero the whole total.
        try:
            if not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            continue

    raw = open(out_path, "wb")
    stream = raw
    try:
        if compressor is not None:
            stream = compressor.stream_writer(raw, closefd=False)
        tar_kwargs = {"compresslevel": max(1, min(9, level))} if mode == "w|gz" else {}
        with tarfile.open(fileobj=stream, mode=mode, **tar_kwargs) as tar:
            for fpath, arcname in files:
                if cancel and cancel():
                    raise CancelledError("Backup cancelled")
                try:
                    st = fpath.lstat()
                except OSError:
                    continue
                info = tarfile.TarInfo(name=arcname)
                info.size = 0 if fpath.is_symlink() else st.st_size
                info.mtime = int(st.st_mtime)
                info.mode = (st.st_mode & 0o777) if preserve_permissions else 0o644
                info.uid = st.st_uid if hasattr(st, "st_uid") else 0
                info.gid = st.st_gid if hasattr(st, "st_gid") else 0
                info.uname = ""
                info.gname = ""

                if fpath.is_symlink():
                    info.type = tarfile.SYMTYPE
                    try:
                        info.linkname = os.readlink(fpath)
                    except OSError:
                        continue
                    tar.addfile(info)
                    entries.append(ArchiveEntry(arcname, 0, st.st_mtime))
                    continue

                info.type = tarfile.REGTYPE
                try:
                    with open(fpath, "rb") as fh:
                        if info.size == 0:
                            tar.addfile(info)
                        else:
                            tar.addfile(info, fh)
                except (OSError, PermissionError) as exc:
                    log.warning("Skipping unreadable file %s: %s", fpath, exc)
                    continue
                processed += info.size
                entries.append(ArchiveEntry(arcname, info.size, st.st_mtime))
                if progress:
                    progress(processed, total, arcname)
    finally:
        if stream is not raw:
            stream.close()
        raw.close()


def _write_zip(files, out_path: Path, level: int, progress, cancel, entries, _cb):
    comp = zipfile.ZIP_DEFLATED if level > 0 else zipfile.ZIP_STORED
    total = 0
    for f, _ in files:
        # Per-file guard: one dangling symlink must not zero the whole total.
        try:
            if not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            continue
    processed = 0
    with zipfile.ZipFile(out_path, "w", compression=comp, compresslevel=max(1, min(9, level))) as zf:
        for fpath, arcname in files:
            if cancel and cancel():
                raise CancelledError("Backup cancelled")
            try:
                st = fpath.lstat()
            except OSError:
                continue
            if fpath.is_symlink():
                try:
                    zf.writestr(arcname, os.readlink(fpath))
                except OSError:
                    continue
                entries.append(ArchiveEntry(arcname, 0, st.st_mtime))
                continue
            try:
                zf.write(fpath, arcname)
            except (OSError, PermissionError) as exc:
                log.warning("Skipping unreadable file %s: %s", fpath, exc)
                continue
            processed += st.st_size
            entries.append(ArchiveEntry(arcname, st.st_size, st.st_mtime))
            if progress:
                progress(processed, total, arcname)


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------
def _open_tar(path: str | Path, fmt: str):
    if fmt == "zst":
        import zstandard as zstd

        fh = open(path, "rb")
        reader = zstd.ZstdDecompressor().stream_reader(fh)
        return tarfile.open(fileobj=reader, mode="r|"), (fh, reader)
    mode = "r:gz" if fmt == "tar.gz" else "r:"
    return tarfile.open(str(path), mode), None


def list_archive(path: str | Path, fmt: str, password: str = "") -> list[ArchiveEntry]:
    path = Path(path)
    if not path.exists():
        raise ArchiveError("Archive not found")
    cleanup_tmp: Path | None = None
    if is_encrypted(path):
        if not password:
            raise ArchiveError("Archive is encrypted; password required")
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".dec")
        os.close(fd)
        cleanup_tmp = Path(tmp)
        decrypt_file(path, cleanup_tmp, password)
        path = cleanup_tmp
    try:
        if fmt == "zip":
            with zipfile.ZipFile(path) as zf:
                return [
                    ArchiveEntry(i.filename, i.file_size, 0.0, i.is_dir())
                    for i in zf.infolist()
                ]
        tar, extra = _open_tar(path, fmt)
        try:
            out = []
            for m in tar:
                out.append(ArchiveEntry(m.name, m.size, float(m.mtime), m.isdir()))
                if len(out) > 500_000:
                    break
            return out
        finally:
            tar.close()
            if extra:
                extra[0].close()
    finally:
        if cleanup_tmp:
            cleanup_tmp.unlink(missing_ok=True)


def verify_archive(path: str | Path, fmt: str, password: str = "") -> tuple[bool, str]:
    """Full integrity check: read every member to EOF."""
    path = Path(path)
    if not path.exists():
        return False, "Archive file missing"
    if path.stat().st_size == 0:
        return False, "Archive is empty"
    cleanup_tmp: Path | None = None
    try:
        if is_encrypted(path):
            if not password:
                return False, "Encrypted archive requires a password to verify"
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".dec")
            os.close(fd)
            cleanup_tmp = Path(tmp)
            decrypt_file(path, cleanup_tmp, password)
            path = cleanup_tmp
        if fmt == "zip":
            with zipfile.ZipFile(path) as zf:
                bad = zf.testzip()
                if bad:
                    return False, f"Corrupt member: {bad}"
            return True, "OK"
        tar, extra = _open_tar(path, fmt)
        try:
            for member in tar:
                if member.isfile():
                    fh = tar.extractfile(member)
                    if fh is not None:
                        while fh.read(CHUNK):
                            pass
        finally:
            tar.close()
            if extra:
                extra[0].close()
        return True, "OK"
    except Exception as exc:
        return False, f"Verification failed: {exc}"
    finally:
        if cleanup_tmp:
            cleanup_tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def extract_archive(
    path: str | Path,
    fmt: str,
    destination: str | Path,
    *,
    selected_paths: list[str] | None = None,
    overwrite: bool = False,
    preserve_permissions: bool = True,
    password: str = "",
    progress: ProgressCb | None = None,
    cancel: CancelCb | None = None,
) -> tuple[int, int]:
    """Safely extract an archive. Returns (files_restored, bytes_restored).

    Guards against path traversal and Zip Slip, refuses to overwrite unless
    explicitly allowed, and never follows symlinks outside the destination.
    """
    path = Path(path)
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    selected = {p.strip("/") for p in (selected_paths or []) if p.strip()}

    cleanup_tmp: Path | None = None
    if is_encrypted(path):
        if not password:
            raise ArchiveError("Archive is encrypted; password required")
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".dec")
        os.close(fd)
        cleanup_tmp = Path(tmp)
        decrypt_file(path, cleanup_tmp, password)
        path = cleanup_tmp

    restored_files = 0
    restored_bytes = 0
    try:
        if fmt == "zip":
            with zipfile.ZipFile(path) as zf:
                infos = zf.infolist()
                total = sum(i.file_size for i in infos) or 1
                done = 0
                for info in infos:
                    if cancel and cancel():
                        raise CancelledError("Restore cancelled")
                    name = info.filename
                    if selected and not _is_selected(name, selected):
                        continue
                    target = _safe_target(dest_resolved, name)
                    if target is None:
                        log.warning("Blocked unsafe archive member: %s", name)
                        continue
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and not overwrite:
                        raise ArchiveError(f"Refusing to overwrite {target}")
                    with zf.open(info) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, CHUNK)
                    restored_files += 1
                    restored_bytes += info.file_size
                    done += info.file_size
                    if progress:
                        progress(done, total, name)
        else:
            # Stream the archive once. A second pass for a total-size
            # calculation would require reopening a non-seekable zstd stream,
            # so progress is reported by accumulated bytes instead.
            tar, extra = _open_tar(path, fmt)
            try:
                iterator = tar
                total = 1
                done = 0
                for member in iterator:
                    if cancel and cancel():
                        raise CancelledError("Restore cancelled")
                    name = member.name
                    if selected and not _is_selected(name, selected):
                        continue
                    target = _safe_target(dest_resolved, name)
                    if target is None:
                        log.warning("Blocked unsafe archive member: %s", name)
                        continue
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    if member.issym() or member.islnk():
                        # Only allow links that resolve inside the destination
                        link_target = _safe_target(dest_resolved, member.linkname)
                        if link_target is None:
                            log.warning("Blocked unsafe link member: %s -> %s", name, member.linkname)
                            continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and not overwrite:
                        raise ArchiveError(f"Refusing to overwrite {target}")
                    src = tar.extractfile(member)
                    if src is None:
                        continue
                    with src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, CHUNK)
                    if preserve_permissions:
                        try:
                            os.chmod(target, member.mode & 0o777)
                        except OSError:
                            pass
                    restored_files += 1
                    restored_bytes += member.size
                    done += member.size
                    if progress:
                        progress(done, total, name)
            finally:
                tar.close()
                if extra:
                    extra[0].close()
    finally:
        if cleanup_tmp:
            cleanup_tmp.unlink(missing_ok=True)

    return restored_files, restored_bytes


def _is_selected(name: str, selected: set[str]) -> bool:
    clean = name.strip("/")
    for sel in selected:
        if clean == sel or clean.startswith(sel + "/"):
            return True
    return False


def _safe_target(base: Path, member: str) -> Path | None:
    if not is_safe_archive_member(member, base):
        return None
    normalized = member.replace("\\", "/").lstrip("/")
    target = (base / normalized).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target
