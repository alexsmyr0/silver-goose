"""Tutorial-to-logo and comparison-wording choices, shared by availability and builds.

None allows every current ingredient. An empty list intentionally allows none.
Missing ingredients stay recorded so restoring a file restores the chosen pairing.
"""
import json
import os
import paths
from install_config import atomic_write_json

FILENAME = 'tutorial_pairing.json'
KINDS = ('logos', 'compare')
NEEDS_ONE = ('logos',)

def path():
    return paths.data(FILENAME)


def load():
    """A missing store is unconfigured; corruption is an actionable error."""
    try:
        with open(path(), encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(raw, dict):
        raise ValueError('Tutorial pairing settings are invalid. Restore tutorial_pairing.json.')
    tuts = raw.get("tutorials")
    if not isinstance(tuts, dict):
        raise ValueError('Tutorial pairing settings are invalid. Restore tutorial_pairing.json.')
    out = {}
    for name, choice in tuts.items():
        if not isinstance(name, str) or not isinstance(choice, dict):
            raise ValueError('A tutorial pairing is invalid. Restore tutorial_pairing.json.')
        row = {}
        for kind in KINDS:
            v = choice.get(kind)
            # A list is a choice; anything else - including a missing key - is "everything".
            row[kind] = [str(x) for x in v] if isinstance(v, list) else None
        out[str(name)] = row
    return out


def save(store):
    atomic_write_json(path(), {'version': 1, 'tutorials': store})


def set_choice(tutorial, kind, chosen):
    """Tie one tutorial to `chosen`, or to everything when `chosen` is None. Returns the store.

    `chosen` is filtered to nothing here on purpose - what is a real logo pair or a real
    compare id is the CALLER's question, and the panel answers it before saving so it can say
    *which* name it did not recognise rather than dropping it in silence.
    """
    if kind not in KINDS:
        raise ValueError("not something a tutorial can be tied to: %r" % (kind,))
    store = load()
    row = store.setdefault(tutorial, {k: None for k in KINDS})
    for k in KINDS:
        row.setdefault(k, None)
    row[kind] = None if chosen is None else sorted({str(x) for x in chosen})
    save(store)
    return store


def forget(tutorial):
    """Drop a tutorial's ties when the file itself goes.

    THE SAME REASON `dashboard.forget_tags` EXISTS. Names are systematic - `naming.py` derives
    the next one from what is on disk - so deleting `tutorial-03.mp4` frees that name, and the
    next tutorial to arrive would land on it and silently inherit the deleted one's choices.
    A tutorial wearing somebody else's ties is a video with the wrong logo on it.
    """
    store = load()
    if store.pop(tutorial, None) is None:
        return False
    save(store)
    return True


def choice(tutorial, store=None):
    """One tutorial's raw stored choice, `{"logos": [...] or None, "compare": [...] or None}`."""
    st = load() if store is None else store
    row = st.get(tutorial) or {}
    return {k: row.get(k) for k in KINDS}


def allowed(tutorial, kind, available, store=None):
    """What this tutorial may use of `available`, IN `available`'S OWN ORDER.

    `available` is the live pool - the logo pair keys in the folder now, or the compare ids in
    the CSV now. Order is kept so the caller's own sorting (least-used-first, and so on) is
    untouched, and so two calls a second apart cannot hand back the same set in two orders.

    A stored name that is not in `available` simply does not appear; see the note at the top
    about why it is not deleted from the file.
    """
    want = choice(tutorial, store).get(kind)
    if want is None:
        return list(available)
    keep = {str(x) for x in want}
    return [a for a in available if str(a) in keep]


def logos_for(tutorial, pair_keys, store=None):
    """The logo pairs this tutorial may be built with. Empty means it may be built with NONE,
    which means it cannot be built at all - see the note at the top of the file."""
    return allowed(tutorial, "logos", pair_keys, store)


def compare_for(tutorial, compare_ids, store=None):
    """The tick-and-cross pairs this tutorial may carry. Empty means it does not make
    tick-and-cross videos, which is a choice he is allowed to make."""
    return allowed(tutorial, "compare", compare_ids, store)


def stale(tutorial, kind, available, store=None):
    """Is this tutorial tied to things that have all since gone?

    THE ONE QUESTION THAT SEPARATES A DELIBERATE "NONE" FROM A BROKEN TIE, and both look
    identical from `allowed()` - an empty list either way. It matters at posting time: he
    really can say a tutorial gets no first comment, and he really can delete the last caption
    a tutorial was tied to, and those two want opposite things done about them.

    Tied to nothing at all (`null`) is not stale - it allows everything.
    """
    want = choice(tutorial, store).get(kind)
    return bool(want) and not allowed(tutorial, kind, available, store)


def usable_tutorials(fmt, tutorials, pair_keys, compare_ids, store=None):
    """The tutorials `fmt` can ACTUALLY build with right now.

    THIS IS THE FUNCTION THE ALLOWANCE IS COUNTED OFF, and that is the whole point of it. The
    line and tick-and-cross formats are worth `LINE_PER_TUTORIAL` videos per scene PER TUTORIAL
    (6 Sep 2026), so a tutorial that cannot be used must not be counted - otherwise Builder
    offers a number the worker then refuses, which is the exact shape of the "it says 12
    left but it should say 96" report that produced the per-tutorial rule in the first place.

    Two tests, in this order:
      * it has a logo pair. Every format needs one, tick-and-cross included - it draws none but
        `build_one` still writes all four overlay images.
      * for `compare` only, it has a tick-and-cross pair.

    RETIREMENT IS NOT ONE OF THE TESTS, and every caller passes EVERY row of
    compare_lines.csv - the builder included, which narrows to the live ones only when it
    actually picks a wording. A worn-out wording is a thing to replace; it is not a reason for
    the number on the Builder tab to move under him, and it must not make the panel and the
    builder count to two different totals. A tie he has REMOVED is a different matter, and that
    is what this counts.

    AN EMPTY POOL IS NOT A PAIRING PROBLEM AND MUST NOT BE REPORTED AS ONE. With no logo pair
    on disk at all, every tutorial would fail the first test and every format would read "no
    tutorials yet" - sending him off to film a tutorial when what is missing is a logo. The
    tool already has a sentence for an empty pool, in `check_assets` and in `why_stuck`, and it
    names the right thing. So each test only applies while its pool has something in it.
    """
    st = load() if store is None else store
    check_logos, check_compare = bool(pair_keys), bool(compare_ids)
    out = []
    for t in tutorials:
        name = os.path.basename(t)
        if check_logos and not logos_for(name, pair_keys, st):
            continue
        if fmt == "compare" and check_compare and not compare_for(name, compare_ids, st):
            continue
        out.append(t)
    return out


def tied_to_nothing(kind, available, tutorials, store=None):
    """Which of `available` NO tutorial may use - so the panel can say so.

    A logo pair or a wording that is tied to nothing can never reach a video, and there is
    nothing on disk to show it: the file sits in the folder looking like it counts. That is the
    same fault `group_logos`' "Not being used" list exists for, one level up. It happens
    honestly - he ties a tutorial to two of three pairs, then adds a fourth pair, and the
    fourth is on no tutorial's list.

    Every tutorial with no choice at all allows everything, so this is empty until he has tied
    down every tutorial, which is right.
    """
    st = load() if store is None else store
    reach = set()
    for t in tutorials:
        reach.update(str(x) for x in allowed(os.path.basename(t), kind, available, st))
    return [a for a in available if str(a) not in reach]
