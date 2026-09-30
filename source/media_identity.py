"""Physical source identity, shared by import and production."""

import hashlib
import os


def source_fingerprint(path):
    before = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = os.stat(path)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("A source file changed while it was being read.")
    return digest.hexdigest()
