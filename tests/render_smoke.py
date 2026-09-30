#!/usr/bin/env python3
"""Real Mac renders in a disposable copy of an explicitly supplied ingredient library."""

import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True, type=pathlib.Path)
    args = ap.parse_args()
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="silver-render-"))
    library = scratch / "library"
    shutil.copytree(args.library / "assets", library / "assets")
    shutil.copytree(
        args.library / "data",
        library / "data",
        ignore=shutil.ignore_patterns("manifest.csv*", "next_video_id.json*", "*.lock"),
    )
    os.environ["SG_LIBRARY"] = str(library)
    sys.path.insert(0, str(ROOT / "source"))
    import paths, tutorial_libraries as TL, reaction as R

    paths.prepare()
    A = pathlib.Path(paths.ASSETS)

    def clip(source, dest, seconds):
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(source),
                "-t",
                str(seconds),
                "-vf",
                "scale=360:640:force_original_aspect_ratio=increase,crop=360:640",
                "-r",
                "30",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "24",
                "-c:a",
                "aac",
                str(dest),
            ],
            check=True,
        )

    clip(next((A / "hooks").glob("*.mp4")), A / "hooks_short/test-short.mp4", 2.2)
    ending = next((A / "tutorial_story/endings").glob("*.mp4"))
    tutorial = next((A / "tutorial_story/tutorials").glob("*.mp4"))
    for relative, source, length in [
        ("ai_larp/originals/larp-9001.mp4", ending, 4),
        ("ai_larp/ai/larp-9001-ai-1.mp4", ending, 4),
        ("ai_larp/tutorials/smoke-tutorial.mp4", tutorial, 5),
        ("reaction/hooks/smoke-story.mp4", ending, 4),
        ("reaction/demos/smoke-demo.mp4", tutorial, 5),
        ("reaction/reactions/smoke-reaction.mp4", ending, 4),
    ]:
        clip(source, A / relative, length)
    TL.assign("ai_larp", ["smoke-tutorial.mp4"], "director")
    TL.assign("reaction", ["smoke-demo.mp4"], "mcp")
    R.save_asset(
        "hooks", "smoke-story.mp4", dict(use_case="YouTube Shorts", join="answer")
    )
    R.save_asset(
        "demos",
        "smoke-demo.mp4",
        dict(use_case="YouTube Shorts", join="answer", assembly="finished"),
    )
    R.save_asset("reactions", "smoke-reaction.mp4", dict(loop=True, background="keep"))
    jobs = [
        (f, "mcp", ["make_videos.py", "--make", "1", "--formats", f])
        for f in ("line", "card", "compare")
    ]
    jobs += [
        ("farm", "director", ["make_farm.py", "--make", "1"]),
        ("mcp_farm", "mcp", ["make_mcp_farm.py", "--make", "1"]),
        ("reaction", "mcp", ["make_reaction.py", "--make", "1"]),
        ("tutorial_story", "director", ["make_tutorial_story.py", "--make", "1"]),
        ("ai_larp", "director", ["make_ai_larp.py", "--tutorial", "2"]),
    ]
    report = {"scratch": str(scratch), "formats": [], "outputs": []}
    for fmt, product, args in jobs:
        with (scratch / (fmt + ".log")).open("w") as log:
            result = subprocess.run(
                [sys.executable, "-u", str(ROOT / "source" / args[0]), *args[1:]],
                env=dict(os.environ, SG_PRODUCT=product),
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        report["formats"].append(dict(format=fmt, exit_code=result.returncode))
        print(fmt, result.returncode, flush=True)
    from manifest import read_rows

    rows = read_rows()
    for row in rows:
        if row["status"] != "ok":
            continue
        output = pathlib.Path(paths.VIDEOS) / row["file"]
        info = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(output),
                ]
            )
        )
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
        expected = (
            (720, 1280, "h264") if row["format"] == "ai_larp" else (1080, 1920, "h264")
        )
        assert (video["width"], video["height"], video["codec_name"]) == expected, row
        assert video.get("sample_aspect_ratio") == "1:1", video
        assert audio["codec_name"] == "aac", row
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
            capture_output=True,
        )
        assert decoded.returncode == 0, decoded.stderr
        report["outputs"].append(
            dict(
                file=row["file"],
                format=row["format"],
                duration=float(info["format"]["duration"]),
            )
        )
    assert len(rows) == 9 and all(r["status"] == "ok" for r in rows), rows
    assert {r["format"] for r in rows} == {j[0] for j in jobs}
    assert all(j["exit_code"] == 0 for j in report["formats"]), report
    (scratch / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Passed. Evidence: " + str(scratch / "report.json"))


if __name__ == "__main__":
    main()
