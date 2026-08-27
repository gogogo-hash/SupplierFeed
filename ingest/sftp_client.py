from __future__ import annotations

import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

import paramiko

from .config import SftpConfig


class UnstableFileError(RuntimeError):
    """Raised when a remote file's size/mtime changes between stability checks."""


class StaleFileError(RuntimeError):
    """Raised when a remote file is older than the configured freshness threshold."""


@dataclass(frozen=True)
class FetchedFile:
    content: bytes
    size_bytes: int
    remote_modified_at: datetime
    checksum: str


@contextmanager
def _open_sftp(config: SftpConfig) -> Iterator[paramiko.SFTPClient]:
    transport = paramiko.Transport((config.host, config.port))
    try:
        transport.connect(username=config.username, password=config.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            yield sftp
        finally:
            sftp.close()
    finally:
        transport.close()


def check_stability(sftp: paramiko.SFTPClient, remote_path: str, interval_seconds: float) -> paramiko.SFTPAttributes:
    """Confirm a remote file isn't still mid-upload.

    Compares size + mtime across two stat() calls `interval_seconds` apart.
    Returns the second stat if they match; raises UnstableFileError if not.
    """
    first_stat = sftp.stat(remote_path)
    time.sleep(interval_seconds)
    second_stat = sftp.stat(remote_path)

    if (first_stat.st_size, first_stat.st_mtime) != (second_stat.st_size, second_stat.st_mtime):
        raise UnstableFileError(
            f"{remote_path} changed during stability check "
            f"({first_stat.st_size}b/{first_stat.st_mtime} -> "
            f"{second_stat.st_size}b/{second_stat.st_mtime})"
        )
    return second_stat


def check_freshness(remote_modified_at: datetime, max_age_hours: float | None) -> None:
    if max_age_hours is None:
        return
    age_hours = (datetime.now(timezone.utc) - remote_modified_at).total_seconds() / 3600
    if age_hours > max_age_hours:
        raise StaleFileError(
            f"file is {age_hours:.1f}h old, exceeding max_file_age_hours={max_age_hours}"
        )


def fetch_file(config: SftpConfig, remote_path: str) -> FetchedFile:
    """Connect, confirm the remote file is stable and fresh, then download it."""
    with _open_sftp(config) as sftp:
        stat = check_stability(sftp, remote_path, config.stability_check_interval_seconds)
        remote_modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        check_freshness(remote_modified_at, config.max_file_age_hours)

        with sftp.open(remote_path, "rb") as remote_file:
            content = remote_file.read()

    checksum = hashlib.sha256(content).hexdigest()
    return FetchedFile(
        content=content,
        size_bytes=stat.st_size,
        remote_modified_at=remote_modified_at,
        checksum=checksum,
    )
