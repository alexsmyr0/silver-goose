"""Install this copy's Python dependencies once, then compile its local helpers."""

from pathlib import Path
import hashlib, importlib.metadata, subprocess, sys


def main():
    source = Path(__file__).resolve().parent
    requirements = source / "requirements.txt"
    stamp = Path(sys.prefix) / ".silver-requirements"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    missing = False
    for line in requirements.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        name, version = line.split("==")
        try:
            missing |= importlib.metadata.version(name) != version
        except importlib.metadata.PackageNotFoundError:
            missing = True
    if missing or not stamp.exists() or stamp.read_text() != digest:
        print("Preparing local Python packages…", flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-r",
                str(requirements),
            ],
            check=True,
        )
        stamp.write_text(digest)
    import render_support as RS

    print("Checking native video and caption tools…", flush=True)
    for name in ("render_hook", "transcribe", "to_sdr", "reaction_cutout"):
        RS.ensure_native(name)
    print("Checking Apple speech model…", flush=True)
    subprocess.run([str(source / ".transcribe"), "--prepare"], check=True)
    print("Ready.", flush=True)


if __name__ == "__main__":
    main()
