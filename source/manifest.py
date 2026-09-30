"""Build-only ledger and durable, campaign-wide video ID reservations.

Deleting an output never refunds a successful build. Failed renders spend no ingredient
allowance. There are no accounts, queues or publication records in this ledger.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
import re
import csvfile
import paths
from ledger_lock import locked as file_lock
from install_config import atomic_write_json

FIELDS = [
    "video_id",
    "file",
    "format",
    "product",
    "created_at",
    "status",
    "batch",
    "source",
    "source_sha256",
    "scene",
    "tutorial",
    "tutorial_library",
    "speaking",
    "hook_line",
    "wording_id",
    "money",
    "logo_pair",
    "emoji",
    "song",
    "look",
    "hook_speed",
    "head_speed",
    "frame_mark",
    "music_at",
    "caption",
    "recipe",
    "reaction_recipe",
    "reaction_intro",
    "reaction_presenter",
    "hook_len",
    "cut_at",
    "error",
]


def _manifest():
    return globals().get("MANIFEST") or paths.data("manifest.csv")


@contextmanager
def locked(path=None):
    with file_lock(path or _manifest()):
        yield


def read_rows():
    rows, fields = csvfile.read(_manifest())
    if os.path.exists(_manifest()) and not set(
        ("video_id", "status", "format")
    ).issubset(fields):
        raise ValueError(
            "Build history is unreadable. Restore manifest.csv before building."
        )
    return rows


def all_rows(rows=None):
    return read_rows() if rows is None else list(rows)


def write_rows(rows):
    with locked():
        _, previous = csvfile.read(_manifest())
        fields = list(
            dict.fromkeys(FIELDS + previous + [k for row in rows for k in row])
        )
        csvfile.write(_manifest(), rows, fields, had_rows=False)


def append_row(row):
    with locked():
        rows = read_rows()
        if any(r["video_id"] == row["video_id"] for r in rows):
            raise ValueError("This video number is already recorded.")
        write_rows(rows + [row])


def record_result(row, output):
    """Keep failed or unrecorded exports out of the finished-video folders."""

    def recover(kind):
        import uuid

        folder = os.path.join(paths.WORK, kind)
        os.makedirs(folder, exist_ok=True)
        if os.path.isfile(output):
            if not os.path.getsize(output):
                os.unlink(output)
            else:
                os.replace(
                    output,
                    os.path.join(
                        folder, uuid.uuid4().hex[:8] + "-" + os.path.basename(output)
                    ),
                )

    if row.get("status") != "ok":
        recover("failed-renders")
    try:
        append_row(row)
    except Exception:
        recover("unrecorded-renders")
        raise


def blank_row(**values):
    # Retained renderers can still pass old unused columns; never persist posting state.
    values = {
        k: v
        for k, v in values.items()
        if k not in {"account", "post_status", "pan", "overlay", "farm_rest"}
    }
    row = dict.fromkeys(FIELDS, "")
    row.update(
        status="ok",
        product=paths.product(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    row.update(values)
    if row.get("file") and row.get("format"):
        row["file"] = row["format"] + "/" + os.path.basename(row["file"])
    return row


def next_id():
    import json

    target = paths.data("next_video_id.json")
    try:
        with open(target) as stream:
            saved = json.load(stream)["next"]
        if not isinstance(saved, int) or saved < 1:
            raise ValueError("Invalid next video number.")
    except FileNotFoundError:
        saved = 1
    ids = [
        int(r["video_id"][6:])
        for r in read_rows()
        if re.fullmatch(r"final_\d+", r.get("video_id", ""))
    ]
    for root, _, files in os.walk(paths.VIDEOS):
        ids.extend(
            int(m.group(1))
            for f in files
            if (m := re.fullmatch(r"final_(\d+)\.mp4", f))
        )
    return max([saved] + [n + 1 for n in ids])


def claim_id(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with locked():
        index = next_id()
        while True:
            target = os.path.join(out_dir, "final_%04d.mp4" % index)
            # Persist the reservation before creating a file, so interruptions never reuse IDs.
            atomic_write_json(paths.data("next_video_id.json"), {"next": index + 1})
            try:
                fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.close(fd)
                return index, target
            except FileExistsError:
                index += 1


def drop_claim(path):
    try:
        if os.path.getsize(path) == 0:
            os.unlink(path)
    except FileNotFoundError:
        pass


def scene_key(name):
    return re.sub(r"(-short)?\.(?:mp4|mov|m4v)$", "", str(name or ""), flags=re.I)


def scene_uses(rows=None):
    result = {}
    for row in all_rows(rows):
        if row.get("status") != "ok":
            continue
        key, fmt = scene_key(row.get("scene")), row.get("format")
        if key and fmt:
            counts = result.setdefault(key, {})
            counts[fmt] = counts.get(fmt, 0) + 1
    return result


def uses_of(uses, name, fmt):
    return int(uses.get(scene_key(name), {}).get(fmt, 0))


def __getattr__(name):
    if name == "MANIFEST":
        return _manifest()
    if name == "VIDEOS":
        return paths.VIDEOS
    raise AttributeError(name)
