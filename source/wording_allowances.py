"""Campaign-wide wording allowances from successful builds, independent of accounts."""

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
        if row.get("enabled", "1") in ("0", "false"):
            count = max(count, number(row.get("retire_at"), limit))
        row[csvfile.USES_COL] = str(count)
    return rows, list(dict.fromkeys(fields + [csvfile.USES_COL]))


def live(rows, default=25):
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
