"""A single cross-process mutation gate; jobs survive browser/server disconnection."""

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import fcntl, json, os, subprocess, sys, uuid
import catalog, paths
from install_config import atomic_write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def root():
    return Path(paths.WORK) / "jobs"


def lock_file():
    return Path(paths.WORK) / "build.lock"


@contextmanager
def exclusive():
    Path(paths.WORK).mkdir(parents=True, exist_ok=True)
    with lock_file().open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError(
                "A build or library edit is running. Try again when it finishes."
            )
        # Close, rather than LOCK_UN: a spawned worker may own the inherited description.
        yield f


def is_busy():
    try:
        with exclusive():
            return False
    except ValueError:
        return True


def job_path(job_id):
    if (
        not isinstance(job_id, str)
        or len(job_id) != 32
        or any(c not in "0123456789abcdef" for c in job_id)
    ):
        raise ValueError("Unknown build.")
    return root() / (job_id + ".json")


def read(job_id):
    return json.loads(job_path(job_id).read_text())


def save(job):
    atomic_write_json(str(job_path(job["id"])), job)


def status():
    pointer = root() / "latest.json"
    if not pointer.exists():
        return dict(status="idle", busy=is_busy(), made=0, requested=0, outputs=[])
    job = read(json.loads(pointer.read_text())["id"])
    job["busy"] = is_busy()
    if job["status"] == "running":
        import manifest as M

        fresh = [
            r
            for r in M.read_rows()
            if r.get("status") == "ok"
            and int(r["video_id"].removeprefix("final_")) >= job["first_id"]
        ]
        job["outputs"] = [r["file"] for r in fresh]
        job["made"] = len(fresh)
    if job["status"] == "running" and not job["busy"]:
        job.update(
            status="interrupted",
            error="Build stopped before completion. Finished videos remain in their folders.",
        )
    log = root() / (job["id"] + ".log")
    if log.exists():
        with log.open("rb") as f:
            f.seek(max(0, log.stat().st_size - 18000))
            job["log"] = f.read().decode("utf-8", errors="replace")
    return job


def start(product, counts):
    if not isinstance(counts, dict):
        raise ValueError("Choose video quantities.")
    clean = {}
    for fmt, value in counts.items():
        catalog.require(fmt, product)
        if type(value) is not int or not 0 <= value <= 500:
            raise ValueError("Use whole quantities from 0 to 500.")
        if value:
            clean[fmt] = value
    if not clean:
        raise ValueError("Choose at least one video.")
    with exclusive() as lock:
        from production import capacity

        with paths.use_product(product):
            for fmt, count in clean.items():
                left, reason = capacity(fmt)
                if not left:
                    raise ValueError(catalog.FORMATS[fmt] + ": " + reason)
                if count > left:
                    raise ValueError(
                        catalog.FORMATS[fmt] + ": at most " + str(left) + " available."
                    )
        root().mkdir(parents=True, exist_ok=True)
        job = dict(
            id=uuid.uuid4().hex,
            product=product,
            counts=clean,
            requested=sum(clean.values()),
            made=0,
            outputs=[],
            status="running",
            started=now(),
            current="",
            failures=[],
        )
        import manifest as M

        job["first_id"] = M.next_id()
        save(job)
        atomic_write_json(str(root() / "latest.json"), {"id": job["id"]})
        env = dict(
            os.environ,
            SG_LIBRARY=str(paths.LIBRARY),
            SG_PRODUCT=product,
            PYTHONUNBUFFERED="1",
        )
        try:
            with (root() / (job["id"] + ".log")).open("a") as log:
                subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(paths.BASE) / "worker.py"),
                        job["id"],
                        str(lock.fileno()),
                    ],
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    pass_fds=(lock.fileno(),),
                    start_new_session=True,
                )
        except Exception as e:
            job.update(status="failed", error=str(e), ended=now())
            save(job)
            raise
    return job
