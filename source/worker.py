"""Render an explicit batch. No schedules or maintenance work."""

from pathlib import Path
import os, subprocess, sys, traceback
import jobs, paths, manifest as M, production


def run(job_id, lock_fd):
    job = jobs.read(job_id)
    before = {r["video_id"] for r in M.read_rows()}
    try:
        for fmt, args in production.commands(job["counts"]):
            job["current"] = fmt
            jobs.save(job)
            print("\nBuilding " + fmt + "…", flush=True)
            result = subprocess.run(
                [sys.executable, "-u", str(Path(paths.BASE) / args[0]), *args[1:]],
                stdin=subprocess.DEVNULL,
                cwd=paths.BASE,
                pass_fds=(lock_fd,),
            )
            fresh = [
                r
                for r in M.read_rows()
                if r["video_id"] not in before and r["status"] == "ok"
            ]
            job["outputs"] = [r["file"] for r in fresh]
            job["made"] = len(fresh)
            got = sum(r["format"] == fmt for r in fresh)
            if result.returncode or got < job["counts"][fmt]:
                job["failures"].append(
                    {
                        "format": fmt,
                        "made": got,
                        "requested": job["counts"][fmt],
                        "exit_code": result.returncode,
                    }
                )
            jobs.save(job)
        job["status"] = (
            "complete"
            if job["made"] == job["requested"] and not job["failures"]
            else "partial"
            if job["made"]
            else "failed"
        )
    except BaseException as error:
        traceback.print_exc()
        job.update(status="failed", error=str(error))
    finally:
        job.update(current="", ended=jobs.now())
        jobs.save(job)
        print(
            "\nFinished: %d/%d videos. %s"
            % (job["made"], job["requested"], job["status"]),
            flush=True,
        )


if __name__ == "__main__":
    if len(sys.argv) == 3:
        with os.fdopen(int(sys.argv[2]), "a+"):
            run(sys.argv[1], int(sys.argv[2]))
    else:
        with jobs.exclusive() as lock:
            run(sys.argv[1], lock.fileno())
