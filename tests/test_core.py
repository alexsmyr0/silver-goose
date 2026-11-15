"""Safe tests: import production only after selecting a disposable library."""

import io, os, pathlib, re, shutil, subprocess, sys, tempfile, threading, unittest
from unittest.mock import patch

TEST_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="silver-core-"))
os.environ["SG_LIBRARY"] = str(TEST_ROOT / "library")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "source"))
import assets as A, catalog, csvfile, jobs, manifest as M, paths, tutorial_libraries as TL, wording_allowances as WA
from app import create_app, invalidate
from werkzeug.datastructures import FileStorage


class Core(unittest.TestCase):
    def test_shared_tutorial_folder_keeps_format_settings_separate(self):
        import reaction as R

        TL.set_formats({"farm": "regular", "reaction": "regular"})
        folder = pathlib.Path(TL.folder("regular"))
        folder.mkdir(parents=True)
        (folder / "take.mp4").write_bytes(b"test media")
        info = dict(id="a" * 64, seconds=8)
        with patch.object(R, "inspect", return_value=info):
            A.save_settings(
                "tutorial_regular",
                "take.mp4",
                {"join": "answer", "use_case": "Zillow"},
                context="reaction",
            )
        before = R.read_store()
        A.save_settings("tutorial_regular", "take.mp4", {"gain_db": -5}, context="farm")
        self.assertEqual(R.read_store(), before)
        rows, _ = csvfile.read(paths.data("farm_levels.csv"))
        self.assertEqual(rows[0]["clip"], "regular/take.mp4")
        self.assertEqual(float(rows[0]["gain_db"]), -5)

    def test_failed_export_leaves_finished_folder(self):
        number, target = M.claim_id(paths.output("farm"))
        pathlib.Path(target).write_bytes(b"incomplete export")
        M.record_result(
            M.blank_row(video_id="final_%04d" % number, format="farm", status="FAIL"),
            target,
        )
        self.assertFalse(pathlib.Path(target).exists())
        self.assertEqual(
            len(list((pathlib.Path(paths.WORK) / "failed-renders").glob("*.mp4"))), 1
        )
        self.assertEqual(M.read_rows()[0]["status"], "FAIL")

    def test_unrecorded_export_is_recoverable(self):
        number, target = M.claim_id(paths.output("farm"))
        pathlib.Path(target).write_bytes(b"completed export")
        with patch.object(M, "append_row", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                M.record_result(
                    M.blank_row(
                        video_id="final_%04d" % number, format="farm", file=target
                    ),
                    target,
                )
        self.assertFalse(pathlib.Path(target).exists())
        recovered = list(
            (pathlib.Path(paths.WORK) / "unrecorded-renders").glob("*.mp4")
        )
        self.assertEqual(recovered[0].read_bytes(), b"completed export")
        self.assertEqual(M.read_rows(), [])

    def setUp(self):
        shutil.rmtree(paths.LIBRARY, ignore_errors=True)
        paths.prepare()
        invalidate()

    def tearDown(self):
        self.assertNotIn("dashboard", sys.modules)

    def test_scope_restores_and_threads_are_independent(self):
        with paths.use_product("chat"):
            with paths.use_product("mcp"):
                self.assertEqual(paths.product(), "mcp")
            result = []
            t = threading.Thread(target=lambda: result.append(paths.product()))
            t.start()
            t.join()
            self.assertEqual(result, ["director"])
            self.assertEqual(paths.product(), "chat")
        self.assertEqual(paths.product(), "director")

    def test_paths_refuse_traversal_and_symlinks(self):
        for name in ("../../../outside", "/etc/passwd"):
            with self.assertRaises(ValueError):
                paths.asset(name)
        pathlib.Path(paths.asset("outside")).symlink_to(TEST_ROOT)
        with self.assertRaises(ValueError):
            paths.asset("outside/private")

    def test_no_account_output_folders(self):
        for fmt in catalog.FORMATS:
            self.assertEqual(
                pathlib.Path(paths.output(fmt)).parent, pathlib.Path(paths.VIDEOS)
            )
        with self.assertRaises(ValueError):
            catalog.require("line", "director")

    def test_video_ids_are_shared_and_not_refunded(self):
        one, p1 = M.claim_id(paths.output("farm"))
        two, p2 = M.claim_id(paths.output("line"))
        self.assertEqual((one, two), (1, 2))
        pathlib.Path(p1).unlink()
        pathlib.Path(p2).unlink()
        self.assertEqual(M.claim_id(paths.output("farm"))[0], 3)

    def test_parallel_id_reservation(self):
        code = 'import manifest as M,paths; n,p=M.claim_id(paths.output("farm")); M.append_row(M.blank_row(video_id="final_%04d"%n,file=p,format="farm"))'
        env = dict(os.environ, PYTHONPATH=paths.BASE)
        ps = [
            subprocess.Popen(
                [sys.executable, "-c", code],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(8)
        ]
        for p in ps:
            _, err = p.communicate(timeout=20)
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(len({r["video_id"] for r in M.read_rows()}), 8)

    def test_bad_history_and_sequence_block_writes(self):
        pathlib.Path(paths.data("manifest.csv")).write_text("bad\nvalue\n")
        with self.assertRaises(ValueError):
            M.claim_id(paths.output("farm"))
        pathlib.Path(paths.data("manifest.csv")).unlink()
        pathlib.Path(paths.data("next_video_id.json")).write_text("{bad")
        with self.assertRaises(ValueError):
            M.claim_id(paths.output("farm"))

    def test_only_successful_builds_spend_allowances(self):
        csvfile.write(
            paths.data("farm_hooks.csv"),
            [dict(id="1", hook_text="Example", retire_at="3")],
            ["id", "hook_text", "retire_at"],
            False,
        )
        for n, status in [(1, "ok"), (2, "FAIL")]:
            with paths.use_product("chat" if n == 1 else "director"):
                M.append_row(
                    M.blank_row(
                        video_id=f"final_{n:04}",
                        format="farm",
                        wording_id="1",
                        status=status,
                        scene="take.mp4",
                    )
                )
        rows, _ = WA.read(paths.data("farm_hooks.csv"))
        self.assertEqual(rows[0]["your_uses"], "1")
        self.assertEqual(M.uses_of(M.scene_uses(), "take.mp4", "farm"), 1)
        self.assertEqual(WA.remaining(rows, 40), 2)

    def test_text_edit_preserves_metadata_and_validates_atomically(self):
        p = paths.data("farm_hooks.csv")
        csvfile.write(
            p,
            [dict(id="stable", hook_text="Before", custom="keep", retire_at="40")],
            ["id", "hook_text", "custom", "retire_at"],
            False,
        )
        A.save_table(
            "farm_hooks",
            [dict(id="stable", hook_text="After", retire_at=30, enabled="0")],
        )
        row = csvfile.read(p)[0][0]
        self.assertEqual(row["custom"], "keep")
        self.assertEqual(WA.remaining(WA.read(p)[0], 40), 0)
        before = pathlib.Path(p).read_bytes()
        with self.assertRaises(ValueError):
            A.save_table("farm_hooks", [dict(hook_text="", retire_at="NaN")])
        self.assertEqual(pathlib.Path(p).read_bytes(), before)

    def test_tutorial_identity_and_product(self):
        root = pathlib.Path(TL.folder("regular"))
        root.mkdir(parents=True)
        p = root / "take.mp4"
        p.write_bytes(b"original")
        TL.assign("regular", ["take.mp4"], "mcp")
        with paths.use_product("mcp"):
            self.assertEqual(TL.eligible_names("line", ["take.mp4"]), ["take.mp4"])
        with paths.use_product("director"):
            self.assertEqual(TL.eligible_names("line", ["take.mp4"]), [])
        p.write_bytes(b"replaced")
        self.assertEqual(TL.product_for("regular", "take.mp4"), "")

    def test_upload_batch_failure_rolls_back_every_file(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, format="PNG")
        blob = buf.getvalue()
        files = [
            FileStorage(io.BytesIO(blob), filename="openart-1.png"),
            FileStorage(io.BytesIO(b"broken"), filename="shorts-1.png"),
        ]
        with self.assertRaises(Exception):
            A.upload("logos", files)
        self.assertEqual(A.names("logos"), [])
        self.assertEqual(list(pathlib.Path(A.root("logos")).iterdir()), [])

    def test_upload_collision_keeps_existing(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, format="PNG")
        blob = buf.getvalue()
        A.upload("logos", [FileStorage(io.BytesIO(blob), filename="openart-1.png")])
        with self.assertRaises(ValueError):
            A.upload("logos", [FileStorage(io.BytesIO(b"x"), filename="openart-1.png")])
        self.assertEqual(
            pathlib.Path(A.file_path("logos", "openart-1.png")).read_bytes(), blob
        )

    def test_assets_move_to_trash_without_erasing_history(self):
        p = pathlib.Path(A.root("hooks"))
        p.mkdir(parents=True)
        (p / "take.mp4").write_bytes(b"x")
        dest = A.remove("hooks", "take.mp4")
        self.assertEqual((paths.LIBRARY / dest / "take.mp4").read_bytes(), b"x")
        self.assertFalse((p / "take.mp4").exists())

    def test_gate_blocks_second_process(self):
        code = "import jobs; print(jobs.is_busy())"
        with jobs.exclusive():
            output = subprocess.check_output(
                [sys.executable, "-c", code],
                env=dict(os.environ, PYTHONPATH=paths.BASE),
                text=True,
            )
            self.assertEqual(output.strip(), "True")
        self.assertFalse(jobs.is_busy())

    def test_http_security_and_missing_routes(self):
        app = create_app()
        client = app.test_client()
        html = client.get("/").text
        token = re.search('name="silver-token" content="([^"]+)"', html).group(1)
        self.assertEqual(client.get("/api/catalog").status_code, 200)
        self.assertEqual(client.get("/api/accounts").status_code, 404)
        self.assertEqual(
            client.get("/api/health", headers={"Host": "evil.example"}).status_code, 403
        )
        self.assertEqual(client.post("/api/build", json={}).status_code, 403)
        self.assertEqual(
            client.post(
                "/api/settings",
                json={},
                headers={"X-Silver-Token": token, "Origin": "https://evil.example"},
            ).status_code,
            403,
        )
        with jobs.exclusive():
            r = client.post(
                "/api/settings",
                json={"emoji": "test"},
                headers={"X-Silver-Token": token},
            )
            self.assertEqual(r.status_code, 400)
            self.assertIn("running", r.json["error"])

    def test_invalid_build_requests_do_not_start_workers(self):
        for counts in (
            {"line": -1},
            {"line": True},
            {"line": 1.5},
            {"line": 501},
            {"line": 0},
        ):
            with self.assertRaises(ValueError):
                jobs.start("mcp", counts)
        self.assertFalse((jobs.root() / "latest.json").exists())

    def test_wrong_product_never_builds(self):
        with self.assertRaises(ValueError):
            jobs.start("chat", {"line": 1})

    def test_new_app_has_exactly_two_tabs(self):
        body = create_app().test_client().get("/").text
        self.assertEqual(re.findall('data-tab="([^"]+)"', body), ["builder", "assets"])

    def test_outputs_hide_moved_files_without_changing_history(self):
        clip = pathlib.Path(paths.output("line")) / "final_0001.mp4"
        clip.write_bytes(b"finished video")
        row = dict(video_id="final_0001", file="line/final_0001.mp4",
                   format="line", product="mcp", status="ok")
        # Missing records must not consume the visible list's 300-item limit.
        M.write_rows([row] + [dict(row, video_id=f"missing_{i}",
                                 file=f"line/missing_{i}.mp4") for i in range(301)])
        history = pathlib.Path(paths.data("manifest.csv")).read_bytes()
        client = create_app().test_client()
        self.assertEqual(len(client.get("/api/outputs").json["outputs"]), 1)
        moved = paths.LIBRARY / clip.name
        clip.rename(moved)
        self.assertEqual(client.get("/api/outputs").json["outputs"], [])
        self.assertEqual(client.get("/api/outputs?format=line").json["outputs"], [])
        moved.rename(clip)
        self.assertEqual(len(client.get("/api/outputs").json["outputs"]), 1)
        clip.write_bytes(b"")
        self.assertEqual(client.get("/api/outputs").json["outputs"], [])
        self.assertEqual(pathlib.Path(paths.data("manifest.csv")).read_bytes(), history)

    def test_corrupt_formula_is_visible(self):
        import formula

        pathlib.Path(paths.data("formulas.csv")).write_bytes(
            b"setting,value\nkey,1,extra\n"
        )
        with self.assertRaises(ValueError):
            formula.num("farm_repeats")
        self.assertFalse(formula.save({"farm_repeats": "nan"})[0])


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
