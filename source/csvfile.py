"""Small configuration tables. Corrupt data must never become an empty fallback."""

import csv
import io
import os
import tempfile
from ledger_lock import locked

USES_COL = "your_uses"


def read(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as stream:
            body = stream.read()
    except FileNotFoundError:
        return [], []
    if "\x00" in body:
        raise ValueError("Corrupt table: " + os.path.basename(path))
    reader = csv.DictReader(io.StringIO(body), strict=True)
    rows = list(reader)
    fields = list(reader.fieldnames or [])
    if body and (
        not fields or len(set(fields)) != len(fields) or any(not f for f in fields)
    ):
        raise ValueError("Invalid table headings: " + os.path.basename(path))
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Invalid table row: " + os.path.basename(path))
    return rows, fields


def write(path, rows, fields, had_rows=True):
    if had_rows and not rows:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locked(path):
        fd, temporary = tempfile.mkstemp(prefix=".table-", dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return True
