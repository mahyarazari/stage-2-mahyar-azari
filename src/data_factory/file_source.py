"""File source: a fixed set of files, each pinned by its sha256 (stage 2, Olist; D35).

A file already in the raw folder with the pinned checksum is used as is (no download, so
later runs are offline). A missing file, or one whose bytes differ, is downloaded again;
the new bytes are written only after their checksum matches, under a temporary name that
is renamed at the end. A file that still does not match stops the run.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from data_factory.exceptions import ChecksumMismatchError
from data_factory.http_client import HttpClient

log = logging.getLogger(__name__)

TEMP_SUFFIX = ".tmp"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


@dataclass(frozen=True)
class FetchResult:
    downloaded: list[str]
    reused: list[str]


def fetch_files(http: HttpClient, base_url: str, files: dict[str, str], raw_dir: Path) -> FetchResult:
    raw_dir.mkdir(parents=True, exist_ok=True)
    downloaded, reused = [], []
    for name, expected in sorted(files.items()):
        path = raw_dir / name
        if path.exists() and sha256_file(path) == expected:
            reused.append(name)
            continue
        if path.exists():
            log.warning("%s: cached file has a different checksum; downloading it again", name)
        data = http.get_bytes(f"{base_url}/{name}")
        actual = sha256_bytes(data)
        if actual != expected:
            raise ChecksumMismatchError(f"{name}: sha256 {actual} does not match the pinned {expected}; "
                                        f"the copy at {base_url} is not the expected file")
        temporary = path.with_name(name + TEMP_SUFFIX)
        temporary.write_bytes(data)
        os.replace(temporary, path)
        downloaded.append(name)
        log.info("downloaded %s (%d bytes, checksum ok)", name, len(data))
    return FetchResult(downloaded=downloaded, reused=reused)
