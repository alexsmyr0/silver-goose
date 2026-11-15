"""Allowlisted central asset library and production settings. No account directories."""

from pathlib import Path
from datetime import datetime, timezone
import math, os, re, tempfile, uuid
import csvfile, paths, tutorial_libraries as TL
from install_config import atomic_write_json

VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
AUDIO = (".m4a", ".mp3", ".wav", ".aac")
POOLS = {}


def pool(key, label, folder, kind="video", **extra):
    POOLS[key] = dict(id=key, label=label, folder=folder, kind=kind, **extra)


pool("hooks", "Opening scenes", "hooks")
pool("hooks_short", "Short scenes", "hooks_short")
pool("logos", "Logo pairs", "logos", "image")
pool("song", "Main song", "", "audio", fixed="song.m4a")
pool("song_short", "Card song", "", "audio", fixed="song_short.m4a")
pool("font", "Classic font", "", "font", fixed="font.ttf")
for spec in TL.LIBRARIES:
    pool("tutorial_" + spec["id"], spec["label"], spec["kind"], library=spec["id"])
for fmt, root in [("farm", "farm"), ("mcp_farm", "mcp content farm")]:
    for role, label in [
        ("scenes", "Starting scenes"),
        ("speaking", "Speaking A/B pairs"),
        ("songs", "Songs"),
    ]:
        pool(
            fmt + "_" + role,
            label,
            root + "/" + role,
            "audio" if role == "songs" else "video",
            format=fmt,
            role=role,
        )
pool("mcp_farm_tutorials", "MCP tutorials", "mcp content farm/tutorials")
for role, label in [
    ("hooks", "Hook stories"),
    ("intros", "Spoken openings"),
    ("reactions", "Reactions"),
    ("bridges", "Bridges"),
    ("endings", "End of video"),
]:
    pool("reaction_" + role, label, "reaction/" + role, format="reaction", role=role)
pool(
    "reaction_music",
    "Music",
    "reaction/music",
    "audio",
    format="reaction",
    role="music",
)
for role, label in [
    ("scenes", "Starting scenes"),
    ("endings", "Final talking clips"),
    ("music", "Songs"),
]:
    pool(
        "tutorial_story_" + role,
        label,
        "tutorial_story/" + role,
        "audio" if role == "music" else "video",
        format="tutorial_story",
        role=role,
    )
for role, label in [
    ("originals", "Original clips"),
    ("ai", "AI versions"),
    ("music", "Songs"),
]:
    pool(
        "ai_larp_" + role,
        label,
        "ai_larp/" + role,
        "audio" if role == "music" else "video",
        format="ai_larp",
        role=role,
    )

TABLES = {
    # No use limit on these two: they never retire (see wording_allowances.unlimited).
    # A saved retire_at value stays in the file, untouched, because rows are merged on save.
    "hook_lines": ("Opening lines", ["hook_text", "enabled"]),
    "compare_lines": ("Comparison wording", ["bad", "good", "enabled"]),
    "farm_hooks": ("Titles", ["hook_text", "enabled", "retire_at"]),
    "mcp_farm_hooks": ("Titles", ["hook_text", "enabled", "retire_at"]),
    "money_cards": ("Money cards", ["amount", "per"]),
    "captions": ("Post captions", ["caption"]),
    "caption_fixes": ("Caption corrections", ["heard", "correct"]),
}


def spec(key):
    if key not in POOLS:
        raise ValueError("Choose an asset folder.")
    return POOLS[key]


def root(key):
    return paths.asset(spec(key)["folder"])


def file_path(key, name):
    s = spec(key)
    if (
        not isinstance(name, str)
        or not name
        or name.startswith(".")
        or Path(name).name != name
        or "\\" in name
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Use a plain filename.")
    if s.get("fixed") and name != s["fixed"]:
        raise ValueError("Choose this format’s fixed asset.")
    return paths.contained(root(key), name)


def names(key):
    s = spec(key)
    folder = Path(root(key))
    if s.get("fixed"):
        return [s["fixed"]] if (folder / s["fixed"]).is_file() else []
    ext = (
        VIDEO if s["kind"] == "video" else AUDIO if s["kind"] == "audio" else (".png",)
    )
    return (
        sorted(
            p.name
            for p in folder.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in ext
        )
        if folder.exists()
        else []
    )


def inventory(key, context=None):
    s = dict(spec(key))
    out = []
    if context in (None, "farm") and s.get("library") == TL.library_for("farm"):
        s.update(format="farm", role="tutorials")
    is_demo = context in (None, "reaction") and s.get("library") == TL.library_for(
        "reaction"
    )
    if (s.get("format") == "reaction" and s.get("role") != "music") or is_demo:
        import reaction as R

        entries = {x["name"]: x for x in R.assets()["demos" if is_demo else s["role"]]}
    else:
        entries = {}
    for name in names(key):
        item = dict(
            name=name, bytes=Path(file_path(key, name)).stat().st_size, kind=s["kind"]
        )
        if s.get("library"):
            item["product"] = TL.product_for(s["library"], name)
        if name in entries:
            item.update(
                {
                    k: v
                    for k, v in entries[name].items()
                    if k in ("settings", "seconds", "error")
                }
            )
        if s.get("format") == "reaction" and s.get("role") == "music":
            import reaction as R

            saved = R.read_store().get("music")
            if saved and saved.get("name") == name:
                item["settings"] = {
                    k: saved[k]
                    for k in ("enabled", "song_start", "offset", "gain_db")
                    if k in saved
                }
        if s["kind"] == "audio" and s.get("format") in ("tutorial_story", "ai_larp"):
            import tutorial_story as TS, tutorial_story_music as TM, ai_larp_music as AM

            try:
                info = TS.inspect_music(file_path(key, name))
                store = TM.read() if s["format"] == "tutorial_story" else AM.read()
                item.update(
                    seconds=info["seconds"],
                    settings=TM.validate(
                        store["tracks"].get(info["id"], {}), info["seconds"]
                    ),
                )
            except (OSError, ValueError) as e:
                item["error"] = str(e)
        if s.get("format") in ("farm", "mcp_farm"):
            import make_farm as MF

            if s["role"] == "songs":
                row = MF.read_song_settings_for(s["format"]).get(name, {})
                item["settings"] = dict(
                    start=row.get("start", MF.SONG_FROM),
                    gain_db=float(row.get("db") or -17),
                    chance=row.get("chance"),
                )
            else:
                rows, _ = csvfile.read(paths.data(s["format"] + "_levels.csv"))
                row = next(
                    (
                        r
                        for r in rows
                        if r.get("pool") == s["role"]
                        and r.get("clip") == _level_name(s, name)
                    ),
                    {},
                )
                item["settings"] = dict(gain_db=float(row.get("gain_db") or 0))
        out.append(item)
    return dict(pool=s, files=out)


def upload(key, uploads, product="", new_names=None):
    s = spec(key)
    Path(root(key)).mkdir(parents=True, exist_ok=True)
    if new_names is not None and (
        not isinstance(new_names, list)
        or len(new_names) != len(uploads)
        or not all(isinstance(n, str) for n in new_names)
    ):
        raise ValueError("Provide one filename per upload.")
    if not uploads:
        raise ValueError("Choose files to add.")
    if s.get("fixed") and len(uploads) != 1:
        raise ValueError("Choose one file.")
    staged = []
    added = []
    try:
        for i, upload in enumerate(uploads):
            name = s.get("fixed") or (new_names[i] if new_names else upload.filename)
            dest = file_path(key, name)
            if Path(dest).exists():
                raise ValueError(
                    name
                    + " already exists. Remove it first, or choose a different name."
                )
            if any(d == dest for _, d in staged):
                raise ValueError("Two files have the same name.")
            suffix = Path(name).suffix.lower()
            expected = (
                VIDEO
                if s["kind"] == "video"
                else AUDIO
                if s["kind"] == "audio"
                else (".png",)
                if s["kind"] == "image"
                else (".ttf",)
            )
            if suffix not in expected:
                raise ValueError("Unsupported file type: " + name)
            fd, temp = tempfile.mkstemp(prefix=".upload-", suffix=suffix, dir=root(key))
            os.close(fd)
            staged.append((temp, dest))
            upload.save(temp)
            if s["kind"] == "video":
                import ai_larp as L

                info = L.inspect(temp)
                if s.get("role") == "originals" and not info["audio"]:
                    raise ValueError("Original AI LARP clips need sound.")
            elif s["kind"] == "audio":
                import tutorial_story as TS

                TS.inspect_music(temp)
                if s.get("fixed"):
                    # Fixed music must actually be AAC in M4A, not an MP3 with a renamed extension.
                    import subprocess

                    converted = temp + ".m4a"
                    r = subprocess.run(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-y",
                            "-i",
                            temp,
                            "-vn",
                            "-c:a",
                            "aac",
                            "-b:a",
                            "192k",
                            converted,
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if r.returncode:
                        raise ValueError(
                            "Could not convert the song: " + r.stderr[-200:]
                        )
                    os.replace(converted, temp)
            elif s["kind"] == "image":
                from PIL import Image

                with Image.open(temp) as im:
                    if im.format != "PNG":
                        raise ValueError("Logo pairs use PNG images.")
                    im.verify()
            else:
                from render_support import font_name, FONT_NAME

                if font_name(temp) != FONT_NAME:
                    raise ValueError("Choose TikTok Display Medium font.ttf.")
            if s.get("role") == "speaking" and not re.fullmatch(
                r".+-[ab]\.[^.]+", name, re.I
            ):
                raise ValueError(
                    "Name speaking pairs like take-1-a.mp4 and take-1-b.mp4."
                )
            if key == "ai_larp_originals" and not re.fullmatch(
                r"larp-\d+\.[^.]+", name
            ):
                raise ValueError("Name originals larp-1.mp4, larp-2.mp4, …")
            if key == "ai_larp_ai" and not re.fullmatch(
                r"larp-\d+-ai-\d+\.[^.]+", name
            ):
                raise ValueError(
                    "Match an original: larp-1-ai-1.mp4, larp-1-ai-2.mp4, …"
                )
        if s.get("role") == "speaking":
            combined = names(key) + [Path(d).name for _, d in staged]
            for _, d in staged:
                base, side = Path(d).stem.rsplit("-", 1)
                partners = [
                    n
                    for n in combined
                    if Path(n).stem.lower()
                    == (base + "-" + ("b" if side.lower() == "a" else "a")).lower()
                ]
                if len(partners) != 1:
                    raise ValueError(
                        "Upload both A and B of each speaking pair together."
                    )
        if s.get("library") and product not in TL.PRODUCTS:
            raise ValueError("Choose MCP, Chat or Director for tutorials.")
        for temp, dest in staged:
            # Hard-link creation refuses collisions even if another process copied a file mid-upload.
            os.link(temp, dest)
            added.append(dest)
        if s.get("library"):
            TL.assign(s["library"], [Path(d).name for d in added], product)
        return [Path(d).name for d in added]
    except Exception:
        for dest in added:
            Path(dest).unlink(missing_ok=True)
        raise
    finally:
        for temp, _ in staged:
            Path(temp).unlink(missing_ok=True)


def remove(key, name):
    p = Path(file_path(key, name))
    if not p.is_file():
        raise ValueError("That asset is already missing.")
    trash = (
        paths.LIBRARY
        / "trash"
        / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        / uuid.uuid4().hex[:8]
    )
    trash.mkdir(parents=True, exist_ok=True)
    os.replace(p, trash / name)
    # Keep identity settings and history: restoring the same file must not refresh allowances.
    return str(trash.relative_to(paths.LIBRARY))


def table(key):
    if key not in TABLES:
        raise ValueError("Choose a text pool.")
    rows, _ = csvfile.read(paths.data(key + ".csv"))
    if key in ("hook_lines", "compare_lines", "farm_hooks", "mcp_farm_hooks"):
        import wording_allowances as WA

        rows, _ = WA.read(paths.data(key + ".csv"))
    return dict(id=key, label=TABLES[key][0], fields=TABLES[key][1], rows=rows)


def save_table(key, values):
    if key not in TABLES or not isinstance(values, list):
        raise ValueError("Choose a text pool.")
    current, fields = csvfile.read(paths.data(key + ".csv"))
    known = {str(r.get("id", i)): r for i, r in enumerate(current)}
    cols = TABLES[key][1]
    rows = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("Invalid text row.")
        rid = str(value.get("id") or uuid.uuid4().hex[:12])
        if rid in seen:
            raise ValueError("Duplicate text row.")
        seen.add(rid)
        row = dict(known.get(rid, {}))
        row["id"] = rid
        for k in cols:
            row[k] = str(value.get(k, "")).strip()
        if any(
            not row[c] for c in cols if c not in ("enabled", "retire_at", "correct")
        ):
            raise ValueError("Fill each text field, or remove the empty row.")
        if any(len(row[c]) > 2000 for c in cols):
            raise ValueError("Text is too long.")
        if "enabled" in cols:
            row["enabled"] = "0" if row["enabled"] in ("0", "false") else "1"
            row["your_uses"] = "0"
        if "retire_at" in cols:
            default = 40 if "farm" in key else 25
            try:
                n = int(row["retire_at"] or default)
            except ValueError:
                raise ValueError("Wording limits must be whole numbers.")
            if not 1 <= n <= 1000:
                raise ValueError("Wording limits must be from 1 to 1000.")
            row["retire_at"] = str(n)
        rows.append(row)
    csvfile.write(
        paths.data(key + ".csv"),
        rows,
        list(dict.fromkeys(["id"] + fields + cols + [k for row in rows for k in row])),
        had_rows=False,
    )


def _level_name(pool, name):
    library = pool.get("library")
    return library + "/" + name if library and library != "farm" else name


def save_settings(key, name, value, context=None):
    s = dict(spec(key))
    file_path(key, name)
    if context in (None, "farm") and s.get("library") == TL.library_for("farm"):
        s.update(format="farm", role="tutorials")
    if s.get("format") == "reaction":
        import reaction as R

        if s["role"] == "music":
            import reaction_music as RM, tutorial_story as TS

            info = TS.inspect_music(file_path(key, name))
            db = R.read_store()
            db["music"] = RM.settings(
                dict(value, name=name, id=info["id"], seconds=info["seconds"])
            )
            atomic_write_json(R.store_path(), db)
            return db["music"]
        return R.save_asset(s["role"], name, value)
    if context in (None, "reaction") and s.get("library") == TL.library_for("reaction"):
        import reaction as R

        return R.save_asset("demos", name, value, library=s["library"])
    if s.get("format") == "tutorial_story" and s["role"] == "music":
        import tutorial_story as TS

        return TS.save_music(name, value)
    if s.get("format") == "ai_larp" and s["role"] == "music":
        import ai_larp_music as AM

        return AM.save(name, value)
    if s.get("format") in ("farm", "mcp_farm"):

        def finite(k, default, lo, hi):
            try:
                n = float(value.get(k, default))
            except (TypeError, ValueError):
                raise ValueError(k + " must be a number.")
            if not math.isfinite(n) or not lo <= n <= hi:
                raise ValueError(
                    k + " must be between " + str(lo) + " and " + str(hi) + "."
                )
            return str(n)

        if s["role"] == "songs":
            import tutorial_story as TS

            seconds = TS.inspect_music(file_path(key, name))["seconds"]
            row = dict(
                song=name,
                start=finite("start", 0, 0, max(0, seconds - 0.01)),
                gain_db=finite("gain_db", -17, -60, 12),
                chance="",
            )
            if value.get("chance") not in ("", None):
                row["chance"] = finite("chance", 0, 0, 100)
            filename = s["format"] + "_songs.csv"
            identity = lambda r: r.get("song") == name
        else:
            level_name = _level_name(s, name)
            row = dict(
                pool=s["role"], clip=level_name, gain_db=finite("gain_db", 0, -60, 12)
            )
            filename = s["format"] + "_levels.csv"
            identity = (
                lambda r: r.get("pool") == s["role"] and r.get("clip") == level_name
            )
        rows, fields = csvfile.read(paths.data(filename))
        existing = next((r for r in rows if identity(r)), {})
        merged = dict(existing, **row)
        rows = [r for r in rows if not identity(r)] + [merged]
        csvfile.write(
            paths.data(filename),
            rows,
            list(dict.fromkeys(fields + list(merged))),
            had_rows=False,
        )
        return row
    raise ValueError("This asset has no editable media settings.")
