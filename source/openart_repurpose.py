"""OpenArt's subtle variations, approved 8 September 2026.

Only the line/card/compare and farm builders import this profile. Pump keeps repurpose's
existing settings. The filter construction and frame-rate safety rule remain shared.
New look names preserve the meaning of old recipes while the picker uses only gentle looks.
"""
import repurpose as _base
from repurpose import (mark_key as mark_key, parse_mark as parse_mark,
                       mark_vf as mark_vf, speed_key as speed_key, speed_of as speed_of)

NORMAL_MARK = mark_key(1.0, 0, 0)
MARK_STATES = _base.MARK_STATES + 1
SPEEDS = (0.95, 0.97, 1.00, 1.03, 1.05)

# saturation, gamma, contrast, hue. No hue rotation; small changes around neutral.
_GENTLE_LOOKS = {
    "natural":     (1.00, 1.00, 1.00, 0),
    "soft":        (0.98, 1.01, 0.99, 0),
    "crisp":       (1.00, 1.00, 1.02, 0),
    "gentle_lift": (1.00, 1.02, 1.00, 0),
    "gentle_deep": (0.99, 0.98, 1.01, 0),
    "gentle_rich": (1.02, 1.01, 1.00, 0),
}
LOOKS = {**_base.LOOKS, **_GENTLE_LOOKS}
LOOK_NAMES = list(_GENTLE_LOOKS)


def marks():
    # Normal scale can only be centred. Adding 1.0 to the old Cartesian grid would
    # also offer unsafe shifts without the extra image needed to cover the edges.
    return [NORMAL_MARK] + _base.marks()


def look_vf(name):
    return _base.look_vf(name, looks=LOOKS)


def tail_vf(mark, look, w, h):
    return _base.tail_vf(mark, look, w, h, looks=LOOKS)


def speeds_for(src_fps, out_fps):
    return _base.speeds_for(src_fps, out_fps, speeds=SPEEDS)
