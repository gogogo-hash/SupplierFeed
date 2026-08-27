from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ingest.sftp_client import (
    StaleFileError,
    UnstableFileError,
    check_freshness,
    check_stability,
)


class FakeSftp:
    """Stands in for paramiko.SFTPClient, returning queued stat() results."""

    def __init__(self, stats):
        self._stats = list(stats)

    def stat(self, remote_path):
        return self._stats.pop(0)


def make_stat(size: int, mtime: float) -> SimpleNamespace:
    return SimpleNamespace(st_size=size, st_mtime=mtime)


def test_check_stability_passes_when_unchanged():
    sftp = FakeSftp([make_stat(100, 1000.0), make_stat(100, 1000.0)])
    result = check_stability(sftp, "/upload/file.csv", interval_seconds=0)
    assert result.st_size == 100


def test_check_stability_raises_when_size_changes_mid_upload():
    sftp = FakeSftp([make_stat(100, 1000.0), make_stat(150, 1000.0)])
    with pytest.raises(UnstableFileError):
        check_stability(sftp, "/upload/file.csv", interval_seconds=0)


def test_check_stability_raises_when_mtime_changes():
    sftp = FakeSftp([make_stat(100, 1000.0), make_stat(100, 1005.0)])
    with pytest.raises(UnstableFileError):
        check_stability(sftp, "/upload/file.csv", interval_seconds=0)


def test_check_freshness_disabled_when_max_age_is_none():
    ancient = datetime.now(timezone.utc) - timedelta(days=365)
    check_freshness(ancient, max_age_hours=None)  # should not raise


def test_check_freshness_passes_within_threshold():
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    check_freshness(recent, max_age_hours=24)  # should not raise


def test_check_freshness_raises_when_stale():
    stale = datetime.now(timezone.utc) - timedelta(hours=48)
    with pytest.raises(StaleFileError):
        check_freshness(stale, max_age_hours=24)
