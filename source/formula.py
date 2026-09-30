"""Production allowances shared by the builders and compact Build settings."""

import math
import csvfile
import paths

COLS = ["setting", "value", "note"]
NUMBERS = [
    {
        "key": "tutorial_story_repeats",
        "fmt": ("tutorial_story",),
        "default": 2,
        "lo": 1,
        "hi": 20,
        "whole": True,
        "label": "Videos per starting scene and tutorial",
        "note": "each version uses a different final talking clip and subtle repurposing",
    },
    {
        "key": "line_per_tutorial",
        "fmt": ("line", "compare"),
        "default": 3,
        "lo": 1,
        "hi": 20,
        "whole": True,
        "label": "Videos per hook scene, per tutorial",
        "note": "line and tick-and-cross share this number",
    },
    {
        "key": "per_clip",
        "fmt": ("card",),
        "default": 4,
        "lo": 1,
        "hi": 20,
        "whole": True,
        "label": "Videos per short scene",
        "note": "card only - it has no tutorial on screen to be new",
    },
    {
        "key": "reaction_intro_story_repeats",
        "fmt": ("reaction",),
        "default": 4,
        "lo": 1,
        "hi": 20,
        "whole": True,
        "label": "Videos per spoken opening and hook story",
        "note": "opening allowance = hook stories × this number; shared across tutorials; least-used "
        "clips first across build history",
    },
    {
        "key": "farm_repeats",
        "fmt": ("farm", "mcp_farm"),
        "default": 3,
        "lo": 1,
        "hi": 10,
        "whole": True,
        "label": "Videos per speaking pair and tutorial, per starting scene",
        "note": "the multiplier in starting scenes x speaking pairs x tutorials x repeats",
    },
]
BY_KEY = {n["key"]: n for n in NUMBERS}


def csv_path(path=None):
    return path or paths.data("formulas.csv")


def for_format(fmt):
    return [n for n in NUMBERS if fmt in n["fmt"]]


def _validate(spec, raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(spec["label"] + " must be a number.")
    if not math.isfinite(value) or not spec["lo"] <= value <= spec["hi"]:
        raise ValueError(
            "%s must be between %g and %g." % (spec["label"], spec["lo"], spec["hi"])
        )
    if spec["whole"] and value != int(value):
        raise ValueError(spec["label"] + " must be a whole number.")
    return int(value) if spec["whole"] else value


def num(key, path=None):
    if key not in BY_KEY:
        raise ValueError("Unknown build setting: " + key)
    spec = BY_KEY[key]
    rows, _ = csvfile.read(csv_path(path))
    found = [r for r in rows if r.get("setting") == key]
    if len(found) > 1:
        raise ValueError("Duplicate build setting: " + key)
    raw = found[0].get("value", "") if found else ""
    return spec["default"] if raw == "" else _validate(spec, raw)


def shown(key, path=None):
    return "%g" % num(key, path)


def save(values, path=None):
    if not isinstance(values, dict):
        return False, "Choose build settings."
    try:
        checked = {}
        for key, raw in values.items():
            if key not in BY_KEY:
                raise ValueError("Unknown build setting: " + key)
            checked[key] = (
                "" if raw in ("", None) else "%g" % _validate(BY_KEY[key], raw)
            )
        current, fields = csvfile.read(csv_path(path))
        by_key = {r["setting"]: r for r in current}
        for key, value in checked.items():
            by_key[key] = dict(
                by_key.get(key, {}), setting=key, value=value, note=BY_KEY[key]["note"]
            )
        csvfile.write(
            csv_path(path),
            list(by_key.values()),
            list(dict.fromkeys(COLS + fields)),
            False,
        )
        return True, "Saved."
    except (ValueError, OSError) as error:
        return False, str(error)


def rule(fmt, path=None):
    if fmt == "tutorial_story":
        return (
            "Each starting scene and tutorial makes up to %s versions with different endings."
            % shown("tutorial_story_repeats", path)
        )
    if fmt == "reaction":
        return (
            "Each spoken opening and story makes up to %s compatible versions."
            % shown("reaction_intro_story_repeats", path)
        )
    if fmt in ("line", "compare"):
        return "%s videos per scene and tutorial." % shown("line_per_tutorial", path)
    if fmt == "card":
        return "%s videos per short scene." % shown("per_clip", path)
    if fmt in ("farm", "mcp_farm"):
        return "%s versions per scene, speaking pair and tutorial." % shown(
            "farm_repeats", path
        )
    if fmt == "ai_larp":
        return "Four tutorial layouts per original and AI pair: normal/mirrored, plain/captioned."
    return ""
