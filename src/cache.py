"""Auditable raw-source cache with checksum and corruption handling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
from uuid import uuid4
import zipfile

from .http_client import ReliableHttpClient
from .providers.base import InvalidSourceResponse


SHA256_PATTERN = re.compile(r"\b([0-9a-fA-F]{64})\b")


@dataclass(frozen=True, slots=True)
class CacheResult:
    payload: bytes
    path: Path
    from_cache: bool
    source_url: str


def validate_zip_payload(payload: bytes) -> None:
    """Require a readable ZIP containing exactly one non-empty CSV."""

    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            bad_member = archive.testzip()
            csv_members = [
                name for name in archive.namelist() if name.lower().endswith(".csv")
            ]
            if bad_member is not None or len(csv_members) != 1:
                raise InvalidSourceResponse("Official archive ZIP failed validation.")
            if archive.getinfo(csv_members[0]).file_size <= 0:
                raise InvalidSourceResponse("Official archive CSV is empty.")
    except zipfile.BadZipFile as error:
        raise InvalidSourceResponse("Official archive is not a valid ZIP.") from error


def parse_sha256(checksum_payload: bytes) -> str:
    try:
        text = checksum_payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidSourceResponse("Official checksum is not UTF-8 text.") from error
    match = SHA256_PATTERN.search(text)
    if match is None:
        raise InvalidSourceResponse("Official checksum does not contain SHA-256.")
    return match.group(1).lower()


class RawDataCache:
    """Cache raw official bytes; corrupted entries are quarantined, not trusted."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, relative_directory: Path, filename: str) -> Path:
        path = (self.root / relative_directory / filename).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Cache path escapes the configured cache root")
        return path

    @staticmethod
    def _atomic_write_new(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(f"Raw cache target already exists: {path}")
        temporary = path.with_name(f"{path.name}.part-{uuid4().hex}")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @staticmethod
    def _stage_payload(path: Path, payload: bytes) -> Path:
        """Flush bytes before replacing any existing cache entry (Windows-safe)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.part-{uuid4().hex}")
        try:
            with temporary.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            return temporary
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    @classmethod
    def _replace_generated_pair(cls, path: Path, digest_path: Path, payload: bytes, digest: bytes) -> None:
        """Stage both files, atomically replace each, roll back a failed commit.

        Two files cannot be renamed as one filesystem transaction. Readers must
        still verify their checksum: a crash between renames can never make a
        torn pair trusted. Ordinary failures restore already-replaced files.
        No timestamped payload history is retained on successful refresh.
        """
        previous = {p: p.read_bytes() if p.exists() else None for p in (path, digest_path)}
        staged = {}
        replaced = []
        try:
            staged[path] = cls._stage_payload(path, payload)
            staged[digest_path] = cls._stage_payload(digest_path, digest)
            for target, temporary in staged.items():
                temporary.replace(target)
                replaced.append(target)
        except BaseException:
            for target in reversed(replaced):
                if previous[target] is None:
                    target.unlink(missing_ok=True)
                else:
                    recovery = cls._stage_payload(target, previous[target])
                    try:
                        recovery.replace(target)
                    finally:
                        recovery.unlink(missing_ok=True)
            raise
        finally:
            for temporary in staged.values():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _quarantine(paths: list[Path]) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        for path in paths:
            if path.exists():
                path.replace(path.with_name(f"{path.name}.corrupt-{stamp}"))

    def ensure_official_archive(
        self,
        *,
        relative_directory: Path,
        filename: str,
        source_url: str,
        http: ReliableHttpClient,
    ) -> CacheResult:
        archive_path = self._path(relative_directory, filename)
        checksum_path = self._path(relative_directory, f"{filename}.CHECKSUM")
        if archive_path.exists() and checksum_path.exists():
            try:
                archive = archive_path.read_bytes()
                expected = parse_sha256(checksum_path.read_bytes())
                if hashlib.sha256(archive).hexdigest() != expected:
                    raise InvalidSourceResponse("Cached archive checksum mismatch.")
                validate_zip_payload(archive)
                return CacheResult(archive, archive_path, True, source_url)
            except (OSError, InvalidSourceResponse):
                self._quarantine([archive_path, checksum_path])
        elif archive_path.exists() or checksum_path.exists():
            self._quarantine([archive_path, checksum_path])

        checksum = http.get_bytes(f"{source_url}.CHECKSUM")
        expected = parse_sha256(checksum)
        archive = http.get_bytes(source_url)
        if hashlib.sha256(archive).hexdigest() != expected:
            raise InvalidSourceResponse("Downloaded archive checksum mismatch.")
        validate_zip_payload(archive)
        self._atomic_write_new(checksum_path, checksum)
        self._atomic_write_new(archive_path, archive)
        return CacheResult(archive, archive_path, False, source_url)

    def ensure_generated_payload(
        self,
        *,
        relative_directory: Path,
        filename: str,
        source_url: str,
        fetch: Callable[[], bytes],
        validate: Callable[[bytes], None],
        refresh_existing: bool = False,
    ) -> CacheResult:
        """Cache exact REST bytes; refresh growing dates without trusting old data.

        A failed refresh propagates instead of returning a stale cached payload.
        Fetch and validation complete before any healthy entry is replaced.
        """

        path = self._path(relative_directory, filename)
        digest_path = self._path(relative_directory, f"{filename}.sha256")
        if path.exists() and digest_path.exists():
            try:
                payload = path.read_bytes()
                expected = digest_path.read_text(encoding="ascii").strip()
                if hashlib.sha256(payload).hexdigest() != expected:
                    raise InvalidSourceResponse("Cached REST payload checksum mismatch.")
                validate(payload)
                if not refresh_existing:
                    return CacheResult(payload, path, True, source_url)
            except (OSError, UnicodeError, InvalidSourceResponse):
                self._quarantine([path, digest_path])
        elif path.exists() or digest_path.exists():
            self._quarantine([path, digest_path])

        payload = fetch()
        validate(payload)
        digest = hashlib.sha256(payload).hexdigest().encode("ascii")
        if refresh_existing:
            self._replace_generated_pair(path, digest_path, payload, digest)
        else:
            self._atomic_write_new(digest_path, digest)
            self._atomic_write_new(path, payload)
        return CacheResult(payload, path, False, source_url)
