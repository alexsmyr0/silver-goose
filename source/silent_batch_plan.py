"""Pure allocation of requested silent formats against shared cover identities.

The caller supplies current eligible wordings and tutorial allowances. This module
owns only the joint allocation, with no paths, ledger access or rendering imports.
"""
from collections import deque


def allocate(edges, quotas, limits=None):
    """Return feasible ``(format, scene, tutorial, signature)`` selections.

    ``edges`` maps each format/scene/tutorial tuple to eligible cover signatures;
    ``quotas`` caps that tuple and ``limits`` caps each requested format. A cover
    signature may be used once on a scene across all formats and tutorials.
    Input ordering breaks ties, preserving the caller's preferred ingredients.
    """
    def count(value):
        if type(value) is not int or value < 0:
            raise ValueError('Build allowances must be nonnegative whole numbers.')
        return value

    source, sink = ('source',), ('sink',)
    graph, picks, formats, covers = {}, {}, {}, set()

    def connect(start, end, capacity):
        forward = [end, capacity, None]
        reverse = [start, 0, forward]
        forward[2] = reverse
        graph.setdefault(start, []).append(forward)
        graph.setdefault(end, []).append(reverse)
        return forward

    for key, signatures in edges.items():
        if not isinstance(key, tuple) or len(key) != 3:
            raise ValueError('Each build allowance needs a format, scene and tutorial.')
        fmt, scene, tutorial = key
        quota = count(quotas.get(key, 0))
        if not quota:
            continue
        formats[fmt] = formats.get(fmt, 0) + quota
        slot = ('slot', *key)
        connect(('format', fmt), slot, quota)
        ordered = sorted(signatures) if isinstance(signatures, (set, frozenset)) else signatures
        for signature in dict.fromkeys(ordered):
            cover = ('cover', scene, signature)
            picks[(*key, signature)] = connect(slot, cover, 1)
            if cover not in covers:
                covers.add(cover)
                connect(cover, sink, 1)
    for fmt, quota in formats.items():
        connect(source, ('format', fmt), quota if limits is None else count(limits.get(fmt, 0)))

    while True:
        parents = {source: None}
        waiting = deque([source])
        while waiting and sink not in parents:
            node = waiting.popleft()
            for edge in graph.get(node, ()):
                if edge[1] > 0 and edge[0] not in parents:
                    parents[edge[0]] = (node, edge)
                    waiting.append(edge[0])
        if sink not in parents:
            break
        # Every path ends with a one-use cover identity, so each augmentation
        # reserves exactly one video, including paths that reassign earlier picks.
        node = sink
        while node != source:
            previous, edge = parents[node]
            edge[1] -= 1
            edge[2][1] += 1
            node = previous
    return [key for key, edge in picks.items() if edge[2][1]]
