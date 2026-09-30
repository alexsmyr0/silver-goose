"""One local library. Importing this module never creates or migrates files.

Product is production metadata, not an account or a directory. Child renderers receive
SG_LIBRARY and SG_PRODUCT explicitly; request scope is restored after every operation.
"""

from contextlib import contextmanager
from pathlib import Path
import os
import threading

BASE = str(Path(__file__).resolve().parent)
LIBRARY = (
    Path(os.environ.get("SG_LIBRARY", Path(BASE).parent / "library"))
    .expanduser()
    .resolve()
)
ASSETS = str(LIBRARY / "assets" / "openart")
VIDEOS = str(LIBRARY / "videos" / "openart")
DATA = str(LIBRARY / "data" / "openart")
WORK = str(LIBRARY / "work")
CONFIG = str(LIBRARY / "settings.json")
_scope = threading.local()


def contained(root, name=""):
    base = Path(root).resolve()
    target = (base / name).resolve()
    if target != base and base not in target.parents:
        raise ValueError("Choose a file inside the Silver Goose library.")
    return str(target)


def asset(name, assets=None):
    return contained(assets or ASSETS, name)


def data(name):
    return contained(DATA, name)


def output(fmt):
    from catalog import FORMATS

    if fmt not in FORMATS:
        raise ValueError("Unknown video format.")
    return contained(VIDEOS, fmt)


def product():
    from catalog import PRODUCTS

    value = getattr(_scope, "product", os.environ.get("SG_PRODUCT", "director"))
    if value not in PRODUCTS:
        raise ValueError("Choose MCP, Chat or Director.")
    return value


@contextmanager
def use_product(value):
    from catalog import PRODUCTS

    if value not in PRODUCTS:
        raise ValueError("Choose MCP, Chat or Director.")
    before = getattr(_scope, "product", None)
    _scope.product = value
    try:
        yield
    finally:
        if before is None:
            del _scope.product
        else:
            _scope.product = before


def prepare():
    """Explicit first-run initialization; existing files are never replaced."""
    from catalog import FORMATS
    import shutil

    for root in (ASSETS, DATA, WORK, VIDEOS):
        Path(root).mkdir(parents=True, exist_ok=True)
    for fmt in FORMATS:
        Path(output(fmt)).mkdir(parents=True, exist_ok=True)
    for seed in (Path(BASE) / "data.example").iterdir():
        dest = Path(DATA) / seed.name
        if seed.is_file() and not dest.exists():
            shutil.copyfile(seed, dest)
