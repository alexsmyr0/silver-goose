"""Silent formats (line, card, compare): Golden Goose's builder as ported on 15 Nov 2026.

Safe like test_core: a disposable library is selected before any app module is imported.
Rendering itself (Swift captions, FFmpeg) is replaced by recorders; tests/render_smoke.py and
the real render check in docs/verification.md cover actual output.
"""

import os, pathlib, re, shutil, sys, tempfile, types, unittest
from unittest.mock import patch

TEST_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="silver-silent-"))
os.environ["SG_LIBRARY"] = str(TEST_ROOT / "library")
os.environ["SG_PRODUCT"] = "mcp"          # the only content type that builds these formats
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "source"))
import assets as A, csvfile, cover_match, manifest as M, paths, production
import make_videos as MV, micro_repurpose as MR, tutorial_libraries as TL, wording_allowances as WA


def write_csv(name, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    csvfile.write(paths.data(name), rows, fields, False)


def stocked_library(scenes=("scene-01.mp4",), lines=("bro get a job", "bro why")):
    """Ingredients the builder accepts; media bytes are placeholders, durations are patched."""
    assets = pathlib.Path(paths.ASSETS)
    for name in scenes:
        (assets / "hooks").mkdir(parents=True, exist_ok=True)
        (assets / "hooks" / name).write_bytes(b"scene " + name.encode())
    tutorials = pathlib.Path(TL.folder("regular"))
    tutorials.mkdir(parents=True, exist_ok=True)
    (tutorials / "tutorial-a.mp4").write_bytes(b"captioned tutorial")
    TL.assign("regular", ["tutorial-a.mp4"], "mcp")
    (assets / "logos").mkdir(parents=True, exist_ok=True)
    for logo in ("openart-1.png", "shorts-1.png"):
        (assets / "logos" / logo).write_bytes(b"logo")
    for song in ("song.m4a", "song_short.m4a"):
        (assets / song).write_bytes(b"song")
    (assets / "emoji.txt").write_text("\U0001F62D 1\n", encoding="utf-8")
    write_csv("hook_lines.csv", [dict(id=str(i + 1), hook_text=t, enabled="1", retire_at="1")
                                 for i, t in enumerate(lines)])
    write_csv("compare_lines.csv", [dict(id="1", bad="Part time job", good="OpenArt", enabled="1")])
    write_csv("money_cards.csv", [dict(id="1", amount="$478", per="day"),
                                  dict(id="2", amount="$500", per="day")])
    write_csv("captions.csv", [dict(id="1", caption="link in bio")])


class SilentBuilder(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(paths.LIBRARY, ignore_errors=True)
        paths.prepare()

    # ---- the Builder tab's number is the builder's exact-combination count ----------------

    def test_capacity_counts_unused_covers_not_wording_room(self):
        stocked_library()
        with patch.object(production, "ensure_font"), \
                patch.object(MV, "duration", return_value=5.0):
            # One scene, one tutorial (worth three), but only two opening lines: two videos
            # can carry a cover this scene has not shown. The old count said three.
            self.assertEqual(production.capacity("line"), (2, ""))
            rows, fields = csvfile.read(paths.data("hook_lines.csv"))
            rows[0]["enabled"] = "0"
            csvfile.write(paths.data("hook_lines.csv"), rows, fields, True)
            left, reason = production.capacity("line")
            self.assertEqual(left, 1)

    # ---- opening lines and tick-and-cross wording never retire ----------------------------

    def test_silent_wordings_have_no_use_limit_but_respect_enabled(self):
        stocked_library()
        for n in (1, 2, 3):
            M.append_row(M.blank_row(video_id="final_%04d" % n, format="line",
                                     wording_id="1", scene="scene-0%d" % n))
        path = paths.data("hook_lines.csv")
        rows, _ = WA.read(path)
        self.assertEqual(rows[0]["your_uses"], "3")        # counted, past retire_at=1
        self.assertEqual([r["id"] for r in WA.live(rows, path=path)], ["1", "2"])
        rows[1]["enabled"] = "0"
        self.assertEqual([r["id"] for r in WA.live(rows, path=path)], ["1"])
        # Farm titles keep their limit.
        self.assertEqual(WA.live([dict(id="1", your_uses="1", retire_at="1")],
                                 path=paths.data("farm_hooks.csv")), [])

    def test_saving_opening_lines_keeps_a_stored_limit_untouched(self):
        stocked_library()
        A.save_table("hook_lines", [dict(id="1", hook_text="New words", enabled="1"),
                                    dict(hook_text="A brand new line", enabled="1")])
        row, added = csvfile.read(paths.data("hook_lines.csv"))[0]
        self.assertEqual((row["hook_text"], row["retire_at"]), ("New words", "1"))
        self.assertEqual((added["hook_text"], added.get("retire_at", "")), ("A brand new line", ""))
        self.assertNotIn("retire_at", A.table("hook_lines")["fields"])

    # ---- the render command carries all four micro changes --------------------------------

    def render(self, song_shift):
        """Run the real build_one with the native renderer and FFmpeg recorded, not run."""
        stocked_library()
        hook = os.path.join(paths.ASSETS, "hooks", "scene-01.mp4")
        tut = os.path.join(TL.folder("regular"), "tutorial-a.mp4")
        out = os.path.join(paths.output("line"), "final_0001.mp4")
        seen = {}

        def ffmpeg(cmd, runner=None, label=None):
            seen["cmd"] = cmd
            pathlib.Path(cmd[-1]).write_bytes(b"video")
            return types.SimpleNamespace(returncode=0, stderr="")
        ok_run = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch.object(MV, "duration", side_effect=lambda p: 5.0 if p == hook else 8.0), \
                patch.object(MV, "clip_fps", return_value=60), \
                patch.object(MV, "run", return_value=ok_run), \
                patch.object(MV.VE, "run", side_effect=ffmpeg):
            result = MV.build_one(out, hook, tut, "bro get a job \U0001F62D", "\U0001F62D",
                                  "$478/day", paths.ASSETS, "font.ttf", "renderer", paths.WORK,
                                  "openart-1.png", "shorts-1.png", "line", look=MR.LOOKS[0],
                                  speed=1.02, mark="1.025/+3/-4", tutorial_speed=1.007,
                                  song_shift=song_shift)
        return result, seen["cmd"]

    def test_render_applies_micro_changes_and_fits_captioned_tutorial(self):
        (ok, _source, recipe, err), cmd = self.render(song_shift=0.1)
        self.assertTrue(ok, err)
        graph = cmd[cmd.index("-filter_complex") + 1]
        hook_chain = graph.split("[h];")[0]
        tutorial_chain = graph.split("[h];")[1].split("[t];")[0]
        # Burned-in captions: the tutorial is fitted and padded, never cropped.
        self.assertIn("force_original_aspect_ratio=decrease,pad=1080:1920", tutorial_chain)
        self.assertIn("force_original_aspect_ratio=increase,crop=1080:1920", hook_chain)
        # Speed on both parts, the tint on both, the zoom/shift on the composed frame.
        self.assertIn("setpts=PTS/1.0200", hook_chain)
        self.assertIn("setpts=PTS/1.0070", tutorial_chain)
        for chain in (hook_chain, tutorial_chain):
            self.assertIn("eq=saturation=", chain)
        self.assertRegex(graph, r"\[v4\]scale=[^;]*crop=1080:1920[^;]*\[v5\]")
        # The song starts later by starting the scene 3 frames (0.1s) in.
        self.assertIn("trim=start_frame=3", hook_chain)
        self.assertIn("tutorial 1.007x", recipe)

    def test_song_shift_moves_the_song_start_later(self):
        _r0, plain = self.render(song_shift=0.0)
        _r1, shifted = self.render(song_shift=0.1)
        start = lambda cmd: float(cmd[cmd.index("-ss") + 1])
        self.assertAlmostEqual(start(shifted) - start(plain), 0.1, places=3)

    # ---- a whole run: picks, history and per-format folders -------------------------------

    def run_main(self, *argv):
        made = []

        def fake_build(out, hook, tut, text, e, money, *rest):
            made.append(dict(zip(("look", "speed", "mark", "tutorial_speed", "song_shift"),
                                 rest[-5:])))
            pathlib.Path(out).write_bytes(b"video")
            return True, os.path.basename(hook), "recipe", ""
        with patch.object(sys, "argv", ["make_videos.py", *argv]), \
                patch.object(MV, "ensure_font", return_value="font.ttf"), \
                patch.object(MV, "ensure_renderer", return_value="renderer"), \
                patch.object(MV, "duration", return_value=5.0), \
                patch.object(MV, "clip_fps", return_value=60), \
                patch.object(MV, "build_one", side_effect=fake_build):
            MV.main()
        return made

    def test_run_draws_micro_changes_and_never_repeats_a_cover(self):
        stocked_library(scenes=("scene-01.mp4", "scene-02.mp4"))
        drawn = self.run_main("--make", "4", "--formats", "line")
        rows = [r for r in M.read_rows() if r["status"] == "ok"]
        self.assertEqual(len(rows), 4)
        covers = {(r["scene"], cover_match.line_signature(r["hook_line"], r["emoji"])) for r in rows}
        self.assertEqual(len(covers), 4)
        for row, picks in zip(rows, drawn):
            self.assertTrue(row["file"].startswith("line/"))
            self.assertTrue(os.path.isfile(os.path.join(paths.VIDEOS, row["file"])))
            self.assertIn(row["look"], MR.LOOKS)
            self.assertTrue(MR.valid_mark(row["frame_mark"]))
            self.assertNotEqual(row["hook_speed"], "1.00x")
            self.assertIn(row["wording_id"], ("1", "2"))
            self.assertTrue(MR.valid_speed(picks["tutorial_speed"], "tutorial"))
            self.assertNotEqual(picks["tutorial_speed"], 1.0)
            self.assertGreater(picks["song_shift"], 0)
        # Every unused cover is spent: the next request refuses with a reason.
        with self.assertRaises(SystemExit) as stop:
            self.run_main("--make", "1", "--formats", "line")
        self.assertNotEqual(stop.exception.code, 0)


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
