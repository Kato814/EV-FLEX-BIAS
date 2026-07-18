from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Mapping


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def verify_rows(rows: Iterable[Mapping[str, str]]) -> None:
    errors: list[str] = []
    for row in rows:
        path = Path(row["path"])
        if not path.is_file():
            errors.append(f"missing: {path}")
            continue
        actual = sha256_file(path)
        expected = row["sha256"].lower()
        if actual != expected:
            errors.append(f"hash mismatch: {path}: {actual} != {expected}")
    if errors:
        raise ValueError("\n".join(errors))
