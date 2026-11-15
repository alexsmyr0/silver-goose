#!/usr/bin/env python3
"""Explicit, one-time copy from Golden Goose. Never imports or writes its code/data."""

import argparse, csv, hashlib, json, pathlib, shutil, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
import paths

SETTINGS = (
    "hook_lines.csv",
    "compare_lines.csv",
    "farm_hooks.csv",
    "mcp_farm_hooks.csv",
    "money_cards.csv",
    "captions.csv",
    "farm_songs.csv",
    "mcp_farm_songs.csv",
    "farm_levels.csv",
    "mcp_farm_levels.csv",
    "caption_fixes.csv",
    "caption_vocab.txt",
    "hook_lines_avoid.csv",
    "tutorial_libraries.json",
    "tutorial_story_music.json",
    "ai_larp_music.json",
    "formulas.csv",
)
POOLS = (
    "hooks",
    "hooks_short",
    "farm/scenes",
    "mcp content farm/scenes",
    "reaction/intros",
    "tutorial_story/scenes",
    "ai_larp/originals",
    "ai_larp/ai",
)
SHARED = (
    "song.m4a",
    "song_short.m4a",
    "font.ttf",
    "emoji.txt",
    "logos",
    "tutorials",
    "farm",
    "mcp content farm",
    "reaction",
    "tutorial_story",
    "ai_larp",
)


def digest(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("golden_goose", type=pathlib.Path)
    args = ap.parse_args()
    campaigns = json.loads((args.golden_goose / "data/campaigns.json").read_text())
    matches = [
        c for c in campaigns if pathlib.Path(c.get("folder", "")).name == "openfart"
    ]
    if len(matches) != 1:
        raise ValueError("Cannot identify the local OpenArt campaign.")
    campaign = matches[0]
    old = pathlib.Path(campaign["folder"])
    target = paths.LIBRARY
    if target.exists() and any(target.iterdir()):
        raise ValueError("Import requires an empty Silver Goose library.")
    if old == target or old in target.parents or target in old.parents:
        raise ValueError("Source and destination must be separate.")
    receipt = {
        "version": 1,
        "assets": [],
        "settings": [],
        "duplicates": [],
        "missing": [],
    }
    hashes = {}

    def copy(p, relative, dedupe=False):
        if p.is_symlink() or not p.is_file():
            raise ValueError("Import only regular files: " + p.name)
        h = digest(p)
        dest = pathlib.Path(paths.ASSETS) / relative
        key = (str(relative.parent), h)
        if dedupe and key in hashes:
            receipt["duplicates"].append(
                {"name": str(relative), "same_as": hashes[key]}
            )
            return
        if dest.exists():
            if digest(dest) != h:
                raise ValueError("Conflicting asset names: " + str(relative))
            receipt["duplicates"].append(
                {"name": str(relative), "same_as": str(relative)}
            )
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        if digest(p) != h or digest(dest) != h:
            raise ValueError("Asset changed while copying: " + p.name)
        hashes[key] = str(relative)
        receipt["assets"].append(
            {"file": str(relative), "sha256": h, "bytes": dest.stat().st_size}
        )

    for name in SHARED:
        p = old / "shared-assets" / name
        if p.is_file():
            copy(p, pathlib.Path(name))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(
                    a.startswith(".") for a in f.relative_to(p).parts
                ):
                    copy(f, f.relative_to(old / "shared-assets"))
    for account in campaign["accounts"]:
        for pool in POOLS:
            # Used silent takes become fresh source footage for the recipient's independent history.
            for origin in [pool] + (
                [pool + "_used"] if pool in ("hooks", "hooks_short") else []
            ):
                root = old / account / "assets" / origin
                for f in sorted(root.glob("*")):
                    if f.is_file() and not f.name.startswith("."):
                        copy(f, pathlib.Path(pool) / f.name, dedupe=True)
    paths.prepare()
    for name in SETTINGS:
        source = old / "data" / name
        if not source.exists():
            continue
        dest = pathlib.Path(paths.data(name))
        if name.endswith(".csv"):
            rows = list(csv.DictReader(source.open()))
            fields = next(csv.reader(source.open()))
            if "your_uses" in fields:
                if "enabled" not in fields:
                    fields.append("enabled")
                for r in rows:
                    # Preserve explicitly retired wording, reset successful build usage only.
                    retired = (
                        r.get("retire_at", "") in ("0", "-1") or r.get("enabled") == "0"
                    )
                    r["your_uses"] = "0"
                    r["enabled"] = "0" if retired else "1"
            with dest.open("w", newline="") as out:
                writer = csv.DictWriter(out, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        else:
            shutil.copy2(source, dest)
        receipt["settings"].append({"file": name, "sha256": digest(dest)})
    # Discard tags for missing media; never create an eligible phantom tutorial.
    import tutorial_libraries as TL

    store = TL.read_store()
    for library, entries in store.get("tutorials", {}).items():
        for name in list(entries):
            if not pathlib.Path(TL.folder(library), name).is_file():
                receipt["missing"].append({"library": library, "file": name})
                del entries[name]
    TL._write_store(store)
    (target / "import-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "assets": len(receipt["assets"]),
                "bytes": sum(a["bytes"] for a in receipt["assets"]),
                "settings": len(receipt["settings"]),
                "duplicates": len(receipt["duplicates"]),
                "missing_tutorials": len(receipt["missing"]),
            }
        )
    )


if __name__ == "__main__":
    main()
