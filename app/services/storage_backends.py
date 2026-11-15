"""Storage destination backends.

Each backend implements the same small interface:
    test() -> (ok, message, capacity)
    upload(local_path, remote_name) -> remote_path
    download(remote_path, local_path)
    delete(remote_path)
    exists(remote_path) -> bool

Local, SFTP and FTP/FTPS are implemented with the stdlib / paramiko.
S3-compatible storage (AWS S3, MinIO, Backblaze B2, ...) is implemented
natively with SigV4 signing so no boto3 dependency is required.
"""
from __future__ import annotations

import ftplib
import hashlib
import hmac
import mimetypes
import os
import posixpath
import shutil
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.logging import get_logger
from app.utils import disk_usage

log = get_logger(__name__)


class StorageError(RuntimeError):
    pass


@dataclass
class BackendResult:
    ok: bool
    message: str
    capacity: dict[str, Any]


class BaseBackend:
    def __init__(self, config: dict[str, Any], secrets: dict[str, str]):
        self.config = config or {}
        self.secrets = secrets or {}

    def test(self) -> BackendResult:  # pragma: no cover - interface
        raise NotImplementedError

    def upload(self, local_path: str, remote_name: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def download(self, remote_path: str, local_path: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete(self, remote_path: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def exists(self, remote_path: str) -> bool:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Local filesystem
# ---------------------------------------------------------------------------
class LocalBackend(BaseBackend):
    def _root(self) -> Path:
        root = self.config.get("path") or ""
        if not root:
            raise StorageError("Local storage path is not configured")
        p = Path(root).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def test(self) -> BackendResult:
        try:
            root = self._root()
            probe = root / ".tbm_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            usage = disk_usage(root)
            return BackendResult(True, f"Writable: {root}", usage)
        except Exception as exc:
            return BackendResult(False, f"Local storage error: {exc}", {})

    def upload(self, local_path: str, remote_name: str) -> str:
        root = self._root()
        target = root / remote_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if Path(local_path).resolve() == target.resolve():
            return str(target)
        tmp = target.with_name(target.name + ".part")
        shutil.copyfile(local_path, tmp)
        os.replace(tmp, target)
        return str(target)

    def download(self, remote_path: str, local_path: str) -> None:
        src = Path(remote_path)
        if not src.exists():
            raise StorageError(f"File not found: {remote_path}")
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, local_path)

    def delete(self, remote_path: str) -> None:
        try:
            Path(remote_path).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(f"Cannot delete {remote_path}: {exc}") from exc

    def exists(self, remote_path: str) -> bool:
        return Path(remote_path).exists()


# ---------------------------------------------------------------------------
# SFTP
# ---------------------------------------------------------------------------
class SFTPBackend(BaseBackend):
    def _connect(self):
        import paramiko

        host = self.config.get("host")
        port = int(self.config.get("port") or 22)
        username = self.config.get("username") or ""
        password = self.secrets.get("password") or ""
        key_path = self.config.get("private_key_path") or ""
        if not host:
            raise StorageError("SFTP host is not configured")
        transport = paramiko.Transport((host, port))
        transport.banner_timeout = 20
        if key_path:
            key = paramiko.RSAKey.from_private_key_file(key_path, password=password or None)
            transport.connect(username=username, pkey=key)
        else:
            transport.connect(username=username, password=password)
        return transport, paramiko.SFTPClient.from_transport(transport)

    def _remote_dir(self) -> str:
        return (self.config.get("path") or "/").rstrip("/") or "/"

    def test(self) -> BackendResult:
        transport = None
        try:
            transport, sftp = self._connect()
            remote_dir = self._remote_dir()
            try:
                sftp.stat(remote_dir)
            except IOError:
                sftp.mkdir(remote_dir)
            probe = posixpath.join(remote_dir, ".tbm_write_test")
            with sftp.open(probe, "w") as fh:
                fh.write("ok")
            sftp.remove(probe)
            usage: dict[str, Any] = {}
            try:
                st = sftp.statvfs(remote_dir)
                total = st.f_blocks * st.f_frsize
                free = st.f_bavail * st.f_frsize
                usage = {"total": total, "free": free, "used": total - free}
            except Exception:
                pass
            return BackendResult(True, f"Connected to {self.config.get('host')}", usage)
        except Exception as exc:
            return BackendResult(False, f"SFTP connection failed: {exc}", {})
        finally:
            if transport:
                transport.close()

    def upload(self, local_path: str, remote_name: str) -> str:
        transport = None
        try:
            transport, sftp = self._connect()
            remote_dir = self._remote_dir()
            remote_path = posixpath.join(remote_dir, remote_name)
            parts = remote_path.split("/")
            cur = ""
            for part in parts[:-1]:
                cur += "/" + part if cur else part
                if not cur:
                    continue
                try:
                    sftp.stat(cur)
                except IOError:
                    sftp.mkdir(cur)
            tmp = remote_path + ".part"
            sftp.put(local_path, tmp)
            try:
                sftp.posix_rename(tmp, remote_path)
            except IOError:
                try:
                    sftp.remove(remote_path)
                except IOError:
                    pass
                sftp.rename(tmp, remote_path)
            return remote_path
        except Exception as exc:
            raise StorageError(f"SFTP upload failed: {exc}") from exc
        finally:
            if transport:
                transport.close()

    def download(self, remote_path: str, local_path: str) -> None:
        transport = None
        try:
            transport, sftp = self._connect()
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            sftp.get(remote_path, local_path)
        except Exception as exc:
            raise StorageError(f"SFTP download failed: {exc}") from exc
        finally:
            if transport:
                transport.close()

    def delete(self, remote_path: str) -> None:
        transport = None
        try:
            transport, sftp = self._connect()
            sftp.remove(remote_path)
        except Exception as exc:
            raise StorageError(f"SFTP delete failed: {exc}") from exc
        finally:
            if transport:
                transport.close()

    def exists(self, remote_path: str) -> bool:
        transport = None
        try:
            transport, sftp = self._connect()
            try:
                sftp.stat(remote_path)
                return True
            except IOError:
                return False
        finally:
            if transport:
                transport.close()


# ---------------------------------------------------------------------------
# FTP / FTPS
# ---------------------------------------------------------------------------
class FTPBackend(BaseBackend):
    def _connect(self) -> ftplib.FTP:
        host = self.config.get("host")
        port = int(self.config.get("port") or 21)
        if not host:
            raise StorageError("FTP host is not configured")
        use_tls = bool(self.config.get("tls", True))
        if use_tls:
            ctx = ssl.create_default_context()
            if self.config.get("allow_insecure_tls"):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            ftp: ftplib.FTP = ftplib.FTP_TLS(context=ctx)
        else:
            ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=30)
        ftp.login(self.config.get("username") or "anonymous", self.secrets.get("password") or "")
        if use_tls:
            ftp.prot_p()  # type: ignore[attr-defined]
        ftp.set_pasv(bool(self.config.get("passive", True)))
        return ftp

    def _remote_dir(self) -> str:
        return (self.config.get("path") or "/").rstrip("/") or "/"

    def _ensure_dir(self, ftp: ftplib.FTP, remote_dir: str) -> None:
        if remote_dir in ("", "/"):
            return
        cur = ""
        for part in remote_dir.strip("/").split("/"):
            cur += "/" + part
            try:
                ftp.cwd(cur)
            except ftplib.error_perm:
                ftp.mkd(cur)

    def test(self) -> BackendResult:
        try:
            ftp = self._connect()
            try:
                remote_dir = self._remote_dir()
                self._ensure_dir(ftp, remote_dir)
                ftp.cwd(remote_dir)
                import io

                ftp.storbinary("STOR .tbm_write_test", io.BytesIO(b"ok"))
                ftp.delete(".tbm_write_test")
                return BackendResult(True, f"Connected to {self.config.get('host')}", {})
            finally:
                try:
                    ftp.quit()
                except Exception:
                    ftp.close()
        except Exception as exc:
            return BackendResult(False, f"FTP connection failed: {exc}", {})

    def upload(self, local_path: str, remote_name: str) -> str:
        ftp = self._connect()
        try:
            remote_dir = self._remote_dir()
            self._ensure_dir(ftp, remote_dir)
            ftp.cwd(remote_dir)
            remote_path = posixpath.join(remote_dir, remote_name)
            tmp_name = remote_name + ".part"
            with open(local_path, "rb") as fh:
                ftp.storbinary(f"STOR {tmp_name}", fh, blocksize=1024 * 1024)
            try:
                ftp.delete(remote_name)
            except ftplib.error_perm:
                pass
            ftp.rename(tmp_name, remote_name)
            return remote_path
        except Exception as exc:
            raise StorageError(f"FTP upload failed: {exc}") from exc
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def download(self, remote_path: str, local_path: str) -> None:
        ftp = self._connect()
        try:
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as fh:
                ftp.retrbinary(f"RETR {remote_path}", fh.write, blocksize=1024 * 1024)
        except Exception as exc:
            raise StorageError(f"FTP download failed: {exc}") from exc
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def delete(self, remote_path: str) -> None:
        ftp = self._connect()
        try:
            ftp.delete(remote_path)
        except Exception as exc:
            raise StorageError(f"FTP delete failed: {exc}") from exc
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()

    def exists(self, remote_path: str) -> bool:
        ftp = self._connect()
        try:
            try:
                ftp.size(remote_path)
                return True
            except ftplib.error_perm:
                return False
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()


# ---------------------------------------------------------------------------
# S3-compatible (native SigV4)
# ---------------------------------------------------------------------------
class S3Backend(BaseBackend):
    def _endpoint(self) -> str:
        endpoint = self.config.get("endpoint") or ""
        if endpoint:
            return endpoint.rstrip("/")
        region = self.config.get("region") or "us-east-1"
        return f"https://s3.{region}.amazonaws.com"

    def _bucket(self) -> str:
        bucket = self.config.get("bucket")
        if not bucket:
            raise StorageError("S3 bucket is not configured")
        return bucket

    def _prefix(self) -> str:
        return (self.config.get("prefix") or "").strip("/")

    def _key(self, remote_name: str) -> str:
        prefix = self._prefix()
        return f"{prefix}/{remote_name}" if prefix else remote_name

    def _sign(self, method: str, url_path: str, query: str, headers: dict[str, str], payload_hash: str):
        region = self.config.get("region") or "us-east-1"
        service = "s3"
        access_key = self.config.get("access_key") or ""
        secret_key = self.secrets.get("secret_key") or ""
        if not access_key or not secret_key:
            raise StorageError("S3 access key / secret key missing")

        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        headers = {k.lower(): v for k, v in headers.items()}
        headers["host"] = headers.get("host", "")
        headers["x-amz-date"] = amz_date
        headers["x-amz-content-sha256"] = payload_hash

        signed_headers = ";".join(sorted(headers))
        canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in sorted(headers))
        canonical_request = "\n".join(
            [method, url_path, query, canonical_headers, signed_headers, payload_hash]
        )
        scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode()).hexdigest(),
            ]
        )

        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode(), hashlib.sha256).digest()

        k_date = _hmac(("AWS4" + secret_key).encode(), date_stamp)
        k_region = _hmac(k_date, region)
        k_service = _hmac(k_region, service)
        k_signing = _hmac(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return headers

    def _request(self, method: str, key: str = "", data: bytes | None = None, extra_query: str = ""):
        endpoint = self._endpoint()
        bucket = self._bucket()
        url_path = f"/{bucket}"
        if key:
            url_path += "/" + key.lstrip("/")
        from urllib.parse import quote, urlparse

        parsed = urlparse(endpoint)
        host = parsed.netloc
        base = f"{parsed.scheme or 'https'}://{host}"
        payload = data or b""
        payload_hash = hashlib.sha256(payload).hexdigest()
        headers = {"host": host}
        if data is not None:
            headers["content-type"] = "application/octet-stream"
        headers = self._sign(method, url_path, extra_query, headers, payload_hash)
        url = base + url_path + (f"?{extra_query}" if extra_query else "")
        return httpx.request(
            method,
            url,
            content=data,
            headers=headers,
            timeout=120.0,
            follow_redirects=True,
            verify=bool(self.config.get("verify_tls", True)),
        )

    def test(self) -> BackendResult:
        try:
            resp = self._request("GET", extra_query="list-type=2&max-keys=1")
            if resp.status_code in (200, 204):
                return BackendResult(True, f"Bucket '{self._bucket()}' reachable", {})
            return BackendResult(False, f"S3 responded {resp.status_code}: {resp.text[:200]}", {})
        except Exception as exc:
            return BackendResult(False, f"S3 connection failed: {exc}", {})

    def upload(self, local_path: str, remote_name: str) -> str:
        key = self._key(remote_name)
        try:
            size = os.path.getsize(local_path)
            if size <= 64 * 1024 * 1024:
                with open(local_path, "rb") as fh:
                    data = fh.read()
                resp = self._request("PUT", key, data=data)
                if resp.status_code not in (200, 201):
                    raise StorageError(f"S3 PUT failed {resp.status_code}: {resp.text[:200]}")
                return key
            return self._multipart_upload(local_path, key)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"S3 upload failed: {exc}") from exc

    def _multipart_upload(self, local_path: str, key: str) -> str:
        import xml.etree.ElementTree as ET

        resp = self._request("POST", key, data=b"", extra_query="uploads=")
        if resp.status_code != 200:
            raise StorageError(f"S3 multipart init failed {resp.status_code}")
        root = ET.fromstring(resp.text)
        upload_id = None
        for el in root.iter():
            if el.tag.endswith("UploadId"):
                upload_id = el.text
                break
        if not upload_id:
            raise StorageError("S3 multipart init returned no UploadId")

        part_size = 32 * 1024 * 1024
        parts: list[tuple[int, str]] = []
        try:
            with open(local_path, "rb") as fh:
                num = 1
                while True:
                    chunk = fh.read(part_size)
                    if not chunk:
                        break
                    q = f"partNumber={num}&uploadId={upload_id}"
                    r = self._request("PUT", key, data=chunk, extra_query=q)
                    if r.status_code not in (200, 201):
                        raise StorageError(f"S3 part {num} failed {r.status_code}")
                    etag = r.headers.get("etag", "").strip('"')
                    parts.append((num, etag))
                    num += 1
            body = "<CompleteMultipartUpload>" + "".join(
                f"<Part><PartNumber>{n}</PartNumber><ETag>\"{e}\"</ETag></Part>" for n, e in parts
            ) + "</CompleteMultipartUpload>"
            r = self._request(
                "POST", key, data=body.encode(), extra_query=f"uploadId={upload_id}"
            )
            if r.status_code != 200:
                raise StorageError(f"S3 complete failed {r.status_code}: {r.text[:200]}")
        except Exception:
            try:
                self._request("DELETE", key, extra_query=f"uploadId={upload_id}")
            except Exception:
                pass
            raise
        return key

    def download(self, remote_path: str, local_path: str) -> None:
        try:
            resp = self._request("GET", remote_path)
            if resp.status_code != 200:
                raise StorageError(f"S3 GET failed {resp.status_code}")
            Path(local_path).parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as fh:
                fh.write(resp.content)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"S3 download failed: {exc}") from exc

    def delete(self, remote_path: str) -> None:
        resp = self._request("DELETE", remote_path)
        if resp.status_code not in (200, 204):
            raise StorageError(f"S3 DELETE failed {resp.status_code}")

    def exists(self, remote_path: str) -> bool:
        resp = self._request("HEAD", remote_path)
        return resp.status_code == 200


def build_backend(storage_type: str, config: dict, secrets: dict) -> BaseBackend:
    st = (storage_type or "local").lower()
    if st == "local":
        return LocalBackend(config, secrets)
    if st == "sftp":
        return SFTPBackend(config, secrets)
    if st == "ftp":
        return FTPBackend(config, secrets)
    if st in {"s3", "minio"}:
        return S3Backend(config, secrets)
    raise StorageError(f"Unsupported storage type: {storage_type}")
