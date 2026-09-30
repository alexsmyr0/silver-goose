#!/usr/bin/env python3
"""Package source plus private ingredients, excluding history, keys, caches and outputs."""

from pathlib import Path
import hashlib, json, shutil, stat, sys, zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
from importlib.util import spec_from_file_location, module_from_spec

s = spec_from_file_location("library_import", ROOT / "scripts/import_local_library.py")
mod = module_from_spec(s)
s.loader.exec_module(mod)
DATA = set(mod.SETTINGS) | {"reaction_assets.json"}


def package():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    target = dist / "Silver Goose"
    if target.exists():
        raise SystemExit(
            "dist/Silver Goose already exists. Move it aside before packaging again."
        )
    target.mkdir()
    shutil.copytree(
        ROOT / "source",
        target / "source",
        ignore=shutil.ignore_patterns("__pycache__", ".*", "*.pyc"),
    )
    shutil.copy2(
        ROOT / "Start Silver Goose.command", target / "Start Silver Goose.command"
    )
    (target / "README.md").write_text(
        (ROOT / "README.md").read_text().split("## Development")[0]
    )
    for name in ("assets/openart", "data/openart", "videos/openart", "work"):
        (target / "library" / name).mkdir(parents=True, exist_ok=True)
    source = ROOT / "library/assets/openart"
    for p in source.rglob("*"):
        relative = p.relative_to(source)
        if not p.is_file() or any(x.startswith(".") for x in relative.parts):
            continue
        if p.is_symlink():
            raise ValueError("The handoff must not contain symlinks: " + str(relative))
        dest = target / "library/assets/openart" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    for name in DATA:
        p = ROOT / "library/data/openart" / name
        if p.exists():
            shutil.copy2(p, target / "library/data/openart" / name)
    for name in ("import-receipt.json",):
        p = ROOT / "library" / name
        if p.exists():
            shutil.copy2(p, target / "library" / name)
    manifest = []
    for p in sorted(target.rglob("*")):
        if p.is_file():
            with p.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            manifest.append(
                dict(
                    file=str(p.relative_to(target)), bytes=p.stat().st_size, sha256=sha
                )
            )
    (target / "CONTENTS.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = dist / "Silver Goose for John.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(target.rglob("*")):
            if p.is_file():
                z.write(p, Path("Silver Goose") / p.relative_to(target))
    with zipfile.ZipFile(archive) as z:
        if z.testzip():
            raise ValueError("Archive integrity check failed.")
        launcher = z.getinfo("Silver Goose/Start Silver Goose.command")
        assert (launcher.external_attr >> 16) & stat.S_IXUSR
        banned = (
            "/.venv/",
            "/__pycache__/",
            "/config.json",
            "/manifest.csv",
            "/next_video_id.json",
        )
        assert not any(any(x in n for x in banned) for n in z.namelist())
    print(
        json.dumps(
            {
                "archive": str(archive),
                "bytes": archive.stat().st_size,
                "files": len(manifest),
            }
        )
    )


if __name__ == "__main__":
    package()
