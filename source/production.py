"""Availability delegates to the same recipe owners used by the renderers."""

import os
import catalog, paths, manifest as M
import make_videos as MV
import make_farm as MF
import wording_allowances as WA
import tutorial_libraries as TL
from render_support import ensure_font


def capacity(fmt):
    catalog.require(fmt, paths.product())
    ensure_font(paths.ASSETS)
    if fmt in MV.FORMATS:
        pools = MV.pools_now()
        folder = paths.asset(MV.FORMAT_SOURCE[fmt])
        scenes = [
            p
            for p in MV.clips_in(folder)
            if not MV.hook_wrong_length(MV.duration(p), fmt)
        ]
        if not scenes:
            return 0, "Add " + (
                "short scenes (about 2 seconds)."
                if fmt == "card"
                else "opening scenes (at least 4.2 seconds)."
            )
        if not MV.usable_tutorials(fmt, pools=pools):
            return 0, "Assign a matching tutorial and its logo pair in Assets."
        if not MV.logo_pairs(paths.ASSETS)[0]:
            return 0, "Add a complete OpenArt/Shorts logo pair."
        if not os.path.isfile(paths.asset(MV.song_for(fmt))):
            return 0, "Add music for this format."
        if not MV.read_emoji(paths.asset("emoji.txt")):
            return 0, "Add emoji in Assets → Common."
        if not MV.csvfile.read(paths.data("money_cards.csv"))[0]:
            return 0, "Add money card amounts in Assets."
        rows = M.read_rows()
        uses = M.scene_uses(rows)
        tu = MV.tutorial_uses(rows)
        left = sum(
            MV.left_for(os.path.basename(n), fmt, uses, tu, pools=pools) for n in scenes
        )
        if fmt != "card":
            left = min(left, MV.wording_room(fmt, pools))
        return left, "" if left else "Add fresh scenes, tutorials or enabled wording."
    if fmt in MF.FARM_VARIANTS:
        root = MF.asset_root(fmt)
        scenes, _ = MF.scenes_in(paths.asset(root + "/scenes"))
        speaking, _ = MF.speaking_in(paths.asset(root + "/speaking"))
        tuts = MF.pool(
            TL.folder_for("farm")
            if fmt == "farm"
            else paths.asset(root + "/tutorials"),
            TL.EXTENSIONS,
        )
        if fmt == "farm":
            tuts = TL.eligible_names(fmt, tuts)
        songs = MF.pool(paths.asset(root + "/songs"), (".m4a", ".mp3", ".wav", ".aac"))
        words = MF.live_wordings(fmt=fmt)
        missing = [
            n
            for n, items in [
                ("starting scenes", scenes),
                ("complete speaking A/B pairs", speaking),
                ("tutorials for this content type", tuts),
                ("songs", songs),
                ("enabled wording", words),
            ]
            if not items
        ]
        if missing:
            return 0, "Add " + ", ".join(missing) + "."
        left = min(
            sum(
                MF.remaining_by_scene(
                    scenes, speaking, tuts, words, M.read_rows(), fmt
                ).values()
            ),
            WA.remaining(words, 40),
        )
        return (
            left,
            "" if left else "No unused combinations. Add fresh scenes or wording.",
        )
    if fmt == "reaction":
        import reaction as R

        state = R.state()
    elif fmt == "tutorial_story":
        import tutorial_story as TS

        state = TS.public_state()
    else:
        import ai_larp as L

        state = L.public_state()
    return int(state["left"]), state.get("reason", "")


def state():
    results = []
    for fmt in catalog.formats(paths.product()):
        try:
            left, reason = capacity(fmt)
        except (ValueError, OSError, RuntimeError) as error:
            left, reason = 0, str(error)
        results.append(
            dict(id=fmt, label=catalog.FORMATS[fmt], left=left, reason=reason)
        )
    return results


def commands(counts):
    """One subprocess per format: an unavailable format never discards another's results."""
    for fmt, count in counts.items():
        if not count:
            continue
        catalog.require(fmt, paths.product())
        if fmt in MV.FORMATS:
            args = ["make_videos.py", "--make", str(count), "--formats", fmt]
        elif fmt == "ai_larp":
            args = ["make_ai_larp.py", "--tutorial", str(count)]
        else:
            args = ["make_" + fmt + ".py", "--make", str(count)]
        yield fmt, args
