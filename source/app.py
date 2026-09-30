#!/usr/bin/env python3
"""Silver Goose's local Builder and Assets panel."""

from pathlib import Path
from urllib.parse import urlsplit
import fcntl, hashlib, json, os, secrets, subprocess, sys, threading, time, webbrowser
import stat
from flask import Flask, jsonify, render_template, request, send_file, abort
from werkzeug.serving import make_server
import assets as A, catalog, csvfile, formula, jobs, manifest as M, paths, production
import tutorial_libraries as TL, pairing
from install_config import atomic_write_json

CACHE = {}
CACHE_LOCK = threading.Lock()
THUMBNAILS = threading.Semaphore(2)


def invalidate():
    with CACHE_LOCK:
        CACHE.clear()


def create_app():
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=8 * 1024**3)
    token = secrets.token_urlsafe(32)
    library_id = hashlib.sha256(str(paths.LIBRARY).encode()).hexdigest()[:20]

    @app.before_request
    def local_only():
        if request.host.split(":")[0] not in ("127.0.0.1", "localhost"):
            abort(403)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not secrets.compare_digest(
                request.headers.get("X-Silver-Token", ""), token
            ):
                abort(403)
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                abort(403)

    @app.errorhandler(ValueError)
    @app.errorhandler(FileNotFoundError)
    def invalid(error):
        return jsonify(ok=False, error=str(error)), 400

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(
            ok=False, error="Upload is too large. Add fewer files at a time."
        ), 413

    @app.errorhandler(Exception)
    def unexpected(error):
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return jsonify(ok=False, error=error.description), error.code
        app.logger.exception("Request failed")
        return jsonify(
            ok=False, error=str(error) or "Request failed. Check Terminal."
        ), 500

    @app.get("/")
    def index():
        return render_template("index.html", token=token)

    @app.get("/api/health")
    def health():
        return jsonify(app="silver-goose", library=library_id)

    @app.get("/api/catalog")
    def catalog_route():
        return jsonify(
            products=catalog.PRODUCTS,
            formats=catalog.FORMATS,
            product_formats=catalog.PRODUCT_FORMATS,
            pools=A.POOLS,
            tables={k: dict(label=v[0], fields=v[1]) for k, v in A.TABLES.items()},
            libraries=list(TL.LIBRARIES),
        )

    @app.get("/api/state")
    def state_route():
        product = request.args.get("product", "director")
        with paths.use_product(product):
            stamp = (
                Path(paths.data("manifest.csv")).stat().st_mtime_ns
                if Path(paths.data("manifest.csv")).exists()
                else 0
            )
            with CACHE_LOCK:
                cached = CACHE.get(product)
            if not cached or cached[0] != stamp or time.monotonic() - cached[1] > 15:
                value = production.state()
                with CACHE_LOCK:
                    CACHE[product] = (stamp, time.monotonic(), value)
            else:
                value = cached[2]
            return jsonify(formats=value)

    @app.get("/api/job")
    def job_route():
        return jsonify(jobs.status())

    @app.post("/api/build")
    def build_route():
        data = request.get_json()
        job = jobs.start(data.get("product"), data.get("counts"))
        invalidate()
        return jsonify(ok=True, job=job)

    @app.get("/api/outputs")
    def outputs_route():
        fmt = request.args.get("format", "")
        product = request.args.get("product", "")
        if fmt and fmt not in catalog.FORMATS:
            raise ValueError("Unknown video format.")
        rows = []
        for row in reversed(M.read_rows()):
            if (
                row["status"] != "ok"
                or not row.get("file")
                or (fmt and row["format"] != fmt)
                or (product and row.get("product") != product)
            ):
                continue
            p = Path(paths.contained(paths.VIDEOS, row["file"]))
            try:
                info = p.stat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_size == 0:
                continue
            rows.append(
                {
                    k: row.get(k, "")
                    for k in (
                        "video_id",
                        "file",
                        "format",
                        "product",
                        "created_at",
                        "caption",
                    )
                }
                | {"available": True}
            )
        return jsonify(outputs=rows[:300])

    @app.get("/media/output/<path:name>")
    def output_media(name):
        if name not in {r.get("file") for r in M.read_rows() if r["status"] == "ok"}:
            abort(404)
        return send_file(paths.contained(paths.VIDEOS, name), conditional=True)

    @app.get("/media/thumbnail/<path:name>")
    def thumbnail(name):
        if name not in {r.get("file") for r in M.read_rows() if r["status"] == "ok"}:
            abort(404)
        source = Path(paths.contained(paths.VIDEOS, name))
        info = source.stat()
        key = hashlib.sha256(
            (name + str(info.st_size) + str(info.st_mtime_ns)).encode()
        ).hexdigest()
        dest = Path(paths.WORK) / "thumbnails" / (key + ".jpg")
        with THUMBNAILS, M.locked(str(dest)):
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-ss",
                        "0.5",
                        "-i",
                        str(source),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=360:-2",
                        "-q:v",
                        "3",
                        str(dest),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode:
                    dest.unlink(missing_ok=True)
                    raise ValueError("Could not preview this video.")
        return send_file(dest, conditional=True)

    @app.get("/media/asset/<key>/<path:name>")
    def asset_media(key, name):
        return send_file(A.file_path(key, name), conditional=True)

    @app.get("/api/assets/<key>")
    def asset_list(key):
        return jsonify(A.inventory(key, request.args.get("format")))

    @app.post("/api/assets/<key>/upload")
    def upload(key):
        with jobs.exclusive():
            new_names = (
                json.loads(request.form["names"]) if request.form.get("names") else None
            )
            added = A.upload(
                key,
                request.files.getlist("files"),
                request.form.get("product", ""),
                new_names,
            )
            invalidate()
            return jsonify(ok=True, added=added)

    @app.post("/api/assets/<key>/remove")
    def remove(key):
        with jobs.exclusive():
            trash = A.remove(key, request.get_json()["name"])
            invalidate()
            return jsonify(ok=True, trash=trash)

    @app.post("/api/assets/<key>/settings")
    def media_settings(key):
        data = request.get_json()
        with jobs.exclusive():
            value = A.save_settings(
                key, data["name"], data["settings"], data.get("format")
            )
            invalidate()
            return jsonify(ok=True, settings=value)

    @app.get("/api/text/<key>")
    def text_get(key):
        return jsonify(A.table(key))

    @app.post("/api/text/<key>")
    def text_save(key):
        with jobs.exclusive():
            A.save_table(key, request.get_json()["rows"])
            invalidate()
        return jsonify(ok=True)

    @app.get("/api/settings")
    def settings_get():
        return jsonify(
            formulas=[dict(s, value=formula.num(s["key"])) for s in formula.NUMBERS],
            formats={f: TL.library_for(f) for f in TL.DEFAULT_LIBRARIES},
            emoji=Path(paths.asset("emoji.txt")).read_text()
            if Path(paths.asset("emoji.txt")).exists()
            else "",
            vocabulary=Path(paths.data("caption_vocab.txt")).read_text()
            if Path(paths.data("caption_vocab.txt")).exists()
            else "",
        )

    @app.post("/api/settings")
    def settings_save():
        data = request.get_json()
        with jobs.exclusive():
            if "formulas" in data:
                ok, error = formula.save(data["formulas"])
                if not ok:
                    raise ValueError(error)
            if "formats" in data:
                TL.set_formats(data["formats"])
            for key, target in [
                ("emoji", paths.asset("emoji.txt")),
                ("vocabulary", paths.data("caption_vocab.txt")),
            ]:
                if key in data:
                    if not isinstance(data[key], str) or len(data[key]) > 100000:
                        raise ValueError("Invalid text.")
                    temp = Path(target + ".tmp")
                    temp.write_text(data[key])
                    os.replace(temp, target)
            invalidate()
        return jsonify(ok=True)

    @app.post("/api/tutorials/assign")
    def assign():
        data = request.get_json()
        with jobs.exclusive():
            TL.assign(data["library"], data["names"], data["product"])
            invalidate()
        return jsonify(ok=True)

    @app.get("/api/tutorials/pairing")
    def pairing_get():
        library = request.args["library"]
        name = request.args["name"]
        key = TL.pairing_key(library, name)
        import make_videos as MV

        return jsonify(
            choice=pairing.choice(key),
            logos=[p["key"] for p in MV.logo_pairs(paths.ASSETS)[0]],
            compare=csvfile.read(paths.data("compare_lines.csv"))[0],
            captions=csvfile.read(paths.data("captions.csv"))[0],
        )

    @app.post("/api/tutorials/pairing")
    def pairing_save():
        data = request.get_json()
        key = TL.pairing_key(data["library"], data["name"])
        with jobs.exclusive():
            for kind in ("logos", "compare"):
                if kind in data:
                    if data[kind] is not None and (
                        not isinstance(data[kind], list)
                        or not all(isinstance(x, str) for x in data[kind])
                    ):
                        raise ValueError("Invalid tutorial pairing.")
                    pairing.set_choice(key, kind, data[kind])
            invalidate()
        return jsonify(ok=True)

    @app.post("/api/open")
    def open_folder():
        data = request.get_json()
        if data.get("pool"):
            p = A.root(data["pool"])
        elif data.get("format"):
            p = paths.output(data["format"])
        elif data.get("where") == "trash":
            p = str(paths.LIBRARY / "trash")
        else:
            p = paths.VIDEOS
        Path(p).mkdir(parents=True, exist_ok=True)
        subprocess.run(["/usr/bin/open", p], check=True)
        return jsonify(ok=True)

    return app


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0, help="Local port (default: choose a free port)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    paths.prepare()
    lock = open(Path(paths.WORK) / "server.lock", "a+")
    record = Path(paths.WORK) / "server.json"
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        import urllib.request

        data = json.loads(record.read_text())
        url = data["url"]
        if not url.startswith("http://127.0.0.1:"):
            raise RuntimeError("Invalid local server address.")
        info = json.load(urllib.request.urlopen(url + "/api/health", timeout=4))
        expected = hashlib.sha256(str(paths.LIBRARY).encode()).hexdigest()[:20]
        if info.get("app") != "silver-goose" or info.get("library") != expected:
            raise RuntimeError("Another process holds this server address.")
        webbrowser.open(url)
        print("Silver Goose is already running: " + url)
        return
    app = create_app()
    # Port zero asks macOS for an unused port; explicit ports fail if occupied.
    server = make_server("127.0.0.1", args.port, app, threaded=True)
    url = "http://127.0.0.1:" + str(server.server_port)
    atomic_write_json(str(record), {"url": url, "pid": os.getpid()})
    if not args.no_browser:
        webbrowser.open(url)
    print(
        "Silver Goose: "
        + url
        + "\nLeave this Terminal open. Control-C stops the panel. Active builds finish separately.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lock.close()


if __name__ == "__main__":
    main()
