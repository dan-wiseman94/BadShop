"""Limits needed before ZipFile eagerly allocates an untrusted directory."""

import os
import zipfile
from typing import BinaryIO


def check_directory(file: BinaryIO, *, archive_bytes: int, directory_bytes: int, members: int) -> None:
    """Check the same open stream the caller will give ZipFile.

    CPython's end-record reader reads at most the 64 KiB ZIP comment and fixed
    ZIP64 records. The supported Python versions are pinned in pyproject.toml.
    Member counts are checked again after parsing: headers need not be truthful.
    """
    file.seek(0, os.SEEK_END)
    if file.tell() > archive_bytes:
        raise ValueError("archive exceeds the on-disk size limit")
    end = zipfile._EndRecData(file)
    if end is not None and (end[zipfile._ECD_SIZE] > directory_bytes
                            or end[zipfile._ECD_ENTRIES_TOTAL] > members):
        raise ValueError("too many members or too much ZIP directory metadata")
    file.seek(0)
