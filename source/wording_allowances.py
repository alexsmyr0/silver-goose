"""Campaign-wide wording allowances from successful builds, independent of accounts.

Opening lines and tick-and-cross wordings have no reuse ceiling (Golden Goose, 4 Oct 2026,
ported 15 Nov 2026): the builder spreads them least-used first and its exact-cover plan stops
one scene carrying the same wording twice. A row switched off (`enabled` = 0) never builds.
Farm titles keep their per-row `retire_at` limit. Saved `retire_at` values on the unlimited
pools are kept in the file but no longer read.
"""

import os
import csvfile
import manifest as M
from cover_match import line_signature

POOLS = {
    "hook_lines.csv": ("line", 25),
    "compare_lines.csv": ("compare", 25),
    "farm_hooks.csv": ("farm", 40),
    "mcp_farm_hooks.csv": ("mcp_farm", 40),
}


def unlimited(path):
    """Silent-format wordings have no reuse ceiling; only the enabled switch removes one."""
    return os.path.basename(path) in ("hook_lines.csv", "compare_lines.csv")


def enabled(row):
    return str(row.get("enabled", "1")).strip().lower() not in ("0", "false")


def number(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read(path):
    rows, fields = csvfile.read(path)
    kind = POOLS.get(os.path.basename(path))
    if not kind:
        return rows, fields
    fmt, limit = kind
    history = [
        r for r in M.read_rows() if r.get("status") == "ok" and r.get("format") == fmt
    ]
    for row in rows:
        text = (
            "%s ❌ / %s ✅" % (row.get("bad", ""), row.get("good", ""))
            if fmt == "compare"
            else row.get("hook_text", "")
        )
        count = sum(
            1
            for r in history
            if (
                r.get("wording_id") == str(row.get("id"))
                if r.get("wording_id")
                else line_signature(r.get("hook_line"), r.get("emoji"))
                == line_signature(text)
            )
        )
        if not enabled(row) and not unlimited(path):
            count = max(count, number(row.get("retire_at"), limit))
        row[csvfile.USES_COL] = str(count)
    return rows, list(dict.fromkeys(fields + [csvfile.USES_COL]))


def live(rows, default=25, *, path=None):
    if path is not None and unlimited(path):
        return [r for r in rows if enabled(r)]
    return [
        r
        for r in rows
        if number(r.get(csvfile.USES_COL)) < number(r.get("retire_at"), default)
    ]


def remaining(rows, default=25):
    return sum(
        max(0, number(r.get("retire_at"), default) - number(r.get(csvfile.USES_COL)))
        for r in rows
    )
