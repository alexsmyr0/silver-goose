"""Choosing which asset a video gets, and counting what has been spent.

Three counters, in order: **least-used in this run, then least-used ever, then not used
lately, ties at random.** Every one of them was added because the tool got it wrong without
it, and the third is the one people delete because it looks redundant. It is not - see
`pick()`.

Counts are COUNTED OFF THE LEDGER, never kept in a counter file. That is the rule the whole
project follows and it was learned the hard way: a running counter has to be decremented by
every path that gets rid of a video, every miss is silent and permanent, and it can only ever
drift one way. Two counter files had already drifted before this rule existed.

Lifted out of make_pump.py on 29 Aug 2026 unchanged, so a second format spreads its pools the
same way rather than growing a second, subtly different picker.
"""
import random

import csvfile


def _stale(tied, recent, width, key):
    """Whichever of `tied` has not been used in the last `width` videos - unless that is none
    of them, in which case they all stand.

    A guard that can empty the list is a guard that can hang the pick, so it never can. Same
    shape as the one `daily.py` puts on a repeated hook line: refuse the repeat while refusing
    still leaves a choice, and take the best of a bad lot when it does not.
    """
    if len(tied) < 2 or not recent:
        return tied
    blocked = set(recent[-max(1, width):])
    return [o for o in tied if key(o) not in blocked] or tied


def pick(options, life, batch, recent=(), key=None):
    """Least-used IN THIS RUN, then least-used EVER, then NOT USED LATELY, ties at random.

    The first two counters keep the totals level. The third is what keeps consecutive videos
    apart - and without it, the totals being level is itself the problem. Once a pool is
    balanced every option ties, the tie-break is a coin toss, and a coin toss re-picks what
    the last video just used about one time in `len(options)`.

    That is not theoretical. Measured on the real pools, building one video at a time, which
    is how the panel is actually used: each of the four screenshot pools came back to back on
    12% of consecutive videos and the talking head on 6.5%. The first two pump videos ever
    built shared three of their five screenshots, for exactly this reason - and pump.md calls
    the same face twice the most visible repeat available.

    The per-run counter alone does not fix it, and the run that found this had one. It only
    sees the videos beside it, so it goes blank between runs and says nothing at all about the
    one built a minute ago; and even inside one long run every pool empties and refills, so
    the last video of a round and the first of the next are picked from the same full set.

    The window is HALF the pool, so it scales without a table: one of three screenshots steps
    aside and two remain, five of the ten Orangie stills step aside. Randomness is kept among
    whatever is left rather than sorting strictly by age, and that is deliberate - a strict
    rotation makes four same-sized pools cycle in lockstep, and then the whole SET of
    screenshots repeats every third video instead of one of them repeating occasionally.

    `key` maps an option to the name the counters and the history use: the file pools count by
    basename and are picked by full path, the text pools are their own key.
    """
    k = key or (lambda o: o)
    best = min((batch.get(k(o), 0), life.get(k(o), 0)) for o in options)
    tied = [o for o in options if (batch.get(k(o), 0), life.get(k(o), 0)) == best]
    return random.choice(_stale(tied, recent, len(options) // 2, k))


def weighted_pick(weighted, life, batch, recent=()):
    """Same three counters as `pick`, and the WEIGHTS only break the final tie.

    `weighted` is `(value, weight)` pairs. On pump's emoji the crying face and the skull go
    into the bag once against the other two's twice, so over a run they come up half as often
    - but a weight never overrides a use count, which is what keeps the totals level.
    """
    best = min((batch.get(e, 0), life.get(e, 0)) for e, _ in weighted)
    tied = _stale([e for e, _ in weighted if (batch.get(e, 0), life.get(e, 0)) == best],
                  recent, len(weighted) // 2, lambda e: e)
    w = dict(weighted)
    return random.choice([e for e in tied for _ in range(w[e])])


def count_uses(rows, fmt, counted, history_csv=None):
    """How many videos each asset is in, for one format.

    `rows` is the ledger, `fmt` the `format` column's value, and `counted` a list of
    `(pool_name, ledger_column)` pairs - one list per format, so counting a use, remembering
    the order things were used in and checking a combination can never drift apart.

    COUNTED OFF THE `ok` ROWS. Deleting a video frees its talking head that instant, by any
    route, with nothing to remember - which is what makes it impossible to lock an asset by
    moving files about by hand.

    `history_csv` is for uses that legitimately PREDATE the ledger - the two pump videos Alex
    cut by hand in CapCut are real and are not rows, and `farm_hooks.csv` row 1 carries 2 from
    Steven's own pre-tool reels. **Nothing ever writes to it**: adding increments as well
    would double-count every video built since.
    """
    out = {}
    if history_csv:
        for r in csvfile.read(history_csv)[0]:
            out.setdefault((r.get("pool") or "").strip(), {})[(r.get("name") or "").strip()] = \
                int(float(r.get("uses") or 0))
    for r in rows:
        if r.get("status") != "ok" or (r.get("format") or "").strip() != fmt:
            continue
        for pname, col in counted:
            v = (r.get(col) or "").strip()
            if v:
                d = out.setdefault(pname, {})
                d[v] = d.get(v, 0) + 1
    return out
