"""Check known output-size requirements, without a fixed disk reserve."""

from pathlib import Path
import shutil

BUILD_HEADROOM = 0


def require_space(path, needed=0, **kwargs):
    target = Path(path)
    while not target.exists() and target != target.parent:
        target = target.parent
    required = max(0, int(needed), int(kwargs.get("extra_bytes", 0)))
    if required and shutil.disk_usage(target).free < required:
        raise OSError("Not enough free disk space for this video.")
