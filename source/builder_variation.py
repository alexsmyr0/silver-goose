"""Supporting-ingredient spread seeded from the ledger, with no application imports."""
from collections import Counter

import poolpick


def successful_rows(rows, formats):
    """Preserve campaign history order; removed and failed outputs spend no choice."""
    allowed = set(formats)
    return [row for row in rows if row.get('status') == 'ok'
            and (row.get('format') or '').strip() in allowed]


class LedgerSpread:
    """The existing batch/lifetime/recent picker, restored for each builder process.

    Owners supply physical ingredient identities, including a tutorial's library. Picks
    made during this run only affect memory; the next run reloads successful ledger rows.
    Thus a failed render or deleted output cannot leave a permanent counter behind.
    """

    def __init__(self, history):
        self.recent = list(history)
        self.life = Counter(self.recent)
        self.batch = Counter()

    def pick(self, options, key=None):
        if not options:
            return None
        return poolpick.pick(options, self.life, self.batch, self.recent, key=key)

    def record(self, identity):
        self.batch[identity] += 1
        self.recent.append(identity)
