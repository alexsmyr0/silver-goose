"""Exact silent-format combinations, independent of files, rendering and application state.

The allowance is an upper bound. A plan also needs an unused visible cover and a
tutorial that may carry it. Both availability and the builder use this owner.
"""
from collections import Counter
import os


class SilentBuildPlan:
    def __init__(self, *, rows, tutorials, logos, wordings, libraries, scene_key,
                 signature, row_library, per_tutorial, per_scene, money, looks,
                 blockers=None):
        self.tutorials = tutorials
        self.logos = logos
        self.wordings = wordings
        self.libraries = libraries
        self.scene_key = scene_key
        self.signature = signature
        self.row_library = row_library
        self.per_tutorial = per_tutorial
        self.per_scene = per_scene
        self.money = tuple(dict.fromkeys(money))
        self.looks = tuple(dict.fromkeys(looks))
        self.blockers = blockers or {}
        self.tutorial_uses = Counter()
        self.scene_uses = Counter()
        self.covers = set()
        self.recipes = set()
        for row in rows:
            self.record(row)

    def record(self, row):
        """Only successful ledger rows spend a combination; reposts spend no allowance."""
        if row.get('status') != 'ok':
            return
        scene = self.scene_key((row.get('scene') or '').strip())
        fmt = (row.get('format') or '').strip()
        if not row.get('repost_root'):
            self.scene_uses[scene, fmt] += 1
            if fmt in ('line', 'compare') and self.row_library(row) == self.libraries[fmt]:
                self.tutorial_uses[scene, fmt, (row.get('tutorial') or '').strip()] += 1
        if (row.get('hook_line') or '').strip():
            self.covers.add((scene, self.signature(row['hook_line'], row.get('emoji', ''))))
        if fmt == 'card':
            self.recipes.add((scene, self.row_library(row), os.path.basename(row.get('tutorial') or ''),
                              row.get('money') or '', row.get('logo_pair') or '',
                              row.get('look') or 'plain'))

    def _edges(self, scene, fmt):
        scene = self.scene_key(scene)
        edges, quotas = {}, {}
        for tutorial in self.tutorials.get(fmt, ()):
            if not self.logos.get((fmt, tutorial)):
                continue
            quota = max(0, self.per_tutorial - self.tutorial_uses[scene, fmt, tutorial])
            words = {}
            for row, signature in self.wordings.get((fmt, tutorial), ()):
                if signature and (scene, signature) not in self.covers:
                    words.setdefault(signature, []).append(row)
            if quota and words:
                edges[tutorial], quotas[tutorial] = words, quota
        return edges, quotas

    @staticmethod
    def _matching(edges, quotas, tutorial_order=None, word_order=None):
        """Maximum matching: a cover is unique while a tutorial has several slots.

        A minimum of two independent totals is insufficient: several tutorials can
        all be tied to the same one remaining cover. Augmenting paths preserve the
        scarce covers needed by more restricted tutorials.
        """
        owners = {}
        order = list(dict.fromkeys(tutorial_order or edges))
        order += [tutorial for tutorial in edges if tutorial not in order]
        def assign(slot, visited):
            tutorial = slot[0]
            signatures = list(edges[tutorial])
            if word_order:
                signatures.sort(key=lambda value: word_order(tutorial, edges[tutorial][value]))
            for signature in signatures:
                if signature in visited:
                    continue
                visited.add(signature)
                previous = owners.get(signature)
                if previous is None or assign(previous, visited):
                    owners[signature] = slot
                    return True
            return False
        for tutorial in order:
            if tutorial in edges:
                for index in range(quotas[tutorial]):
                    assign((tutorial, index), set())
        return [(slot[0], signature) for signature, slot in owners.items()]

    def wording_plan(self, scene, fmt, *, tutorial_order=None, word_order=None, formats=None):
        if self.blockers.get(fmt):
            return []
        if formats is not None and set(formats) - {fmt, 'card'}:
            all_edges, all_quotas = {}, {}
            for selected in [fmt] + [f for f in ('line','compare') if f != fmt and f in formats]:
                if self.blockers.get(selected):
                    continue
                edges, quotas = self._edges(scene, selected)
                all_edges.update({(selected,tutorial): words for tutorial,words in edges.items()})
                all_quotas.update({(selected,tutorial): quota for tutorial,quota in quotas.items()})
            order = [(fmt,tutorial) for tutorial in tutorial_order] if tutorial_order else None
            rank = (lambda key, rows: word_order(key[1], rows) if key[0] == fmt else (0,0)) if word_order else None
            matched = self._matching(all_edges,all_quotas,order,rank)
            return [dict(tutorial=tutorial,signature=signature,rows=all_edges[selected,tutorial][signature])
                    for (selected,tutorial),signature in matched if selected == fmt]
        edges, quotas = self._edges(scene, fmt)
        return [dict(tutorial=tutorial, signature=signature,
                     rows=edges[tutorial][signature])
                for tutorial, signature in self._matching(edges, quotas, tutorial_order, word_order)]

    def batch_wording_plan(self, scenes, limits):
        """A mixed request's allocation witness, including each format's requested ceiling."""
        from silent_batch_plan import allocate
        edges, quotas, wording_rows = {}, {}, {}
        for fmt in ('line','compare'):
            if not limits.get(fmt) or self.blockers.get(fmt):
                continue
            for name in scenes.get(fmt, ()):
                scene = self.scene_key(name)
                scene_edges, scene_quotas = self._edges(scene,fmt)
                for tutorial, words in scene_edges.items():
                    key = fmt,scene,tutorial
                    edges[key],quotas[key] = words,scene_quotas[tutorial]
                    wording_rows[key] = words
        return [dict(format=fmt,scene=scene,tutorial=tutorial,signature=signature,
                     rows=wording_rows[fmt,scene,tutorial][signature])
                for fmt,scene,tutorial,signature in allocate(edges,quotas,limits)]

    def has_shared_covers(self, scene, formats):
        if not {'line','compare'}.issubset(formats):
            return False
        signatures = []
        for fmt in ('line','compare'):
            edges,_ = self._edges(scene,fmt)
            signatures.append(set().union(*(set(words) for words in edges.values())) if edges else set())
        return bool(signatures[0] & signatures[1])

    def count_many(self, scene, formats):
        """Combined stock: line and compare cannot each spend the same visible cover."""
        edges, quotas = {}, {}
        formats = set(formats)
        for fmt in ('line', 'compare'):
            if fmt not in formats or self.blockers.get(fmt):
                continue
            fmt_edges, fmt_quotas = self._edges(scene, fmt)
            edges.update({(fmt, tutorial): words for tutorial, words in fmt_edges.items()})
            quotas.update({(fmt, tutorial): quota for tutorial, quota in fmt_quotas.items()})
        return len(self._matching(edges, quotas)) + (self.count(scene, 'card') if 'card' in formats else 0)

    def card_options(self, scene, *, tutorial=None, pair=None, money=None):
        """Actual visible recipe choices, used only when a card is about to render."""
        if self.blockers.get('card'):
            return []
        scene = self.scene_key(scene)
        if self.scene_uses[scene, 'card'] >= self.per_scene:
            return []
        options = []
        for tut in self.tutorials.get('card', ()):
            if tutorial is not None and tut != tutorial:
                continue
            for logo in self.logos.get(('card', tut), ()):
                if pair is not None and logo != pair:
                    continue
                for amount in self.money:
                    if money is not None and amount != money:
                        continue
                    for look in self.looks:
                        key = (scene, self.libraries['card'], tut, amount, logo, look)
                        if key not in self.recipes:
                            options.append(dict(tutorial=tut, pair=logo, money=amount, look=look))
        return options

    def count(self, scene, fmt):
        if self.blockers.get(fmt):
            return 0
        if fmt != 'card':
            return len(self.wording_plan(scene, fmt))
        scene = self.scene_key(scene)
        allowance = max(0, self.per_scene - self.scene_uses[scene, 'card'])
        if not allowance:
            return 0
        pairs = {(tut, pair) for tut in self.tutorials.get('card', ())
                 for pair in self.logos.get(('card', tut), ())}
        total = len(pairs) * len(self.money) * len(self.looks)
        spent = sum(sc == scene and library == self.libraries['card']
                    and (tut, pair) in pairs and amount in self.money and look in self.looks
                    for sc, library, tut, amount, pair, look in self.recipes)
        return min(allowance, max(0, total - spent))

    def reason(self, scene, fmt):
        if self.blockers.get(fmt):
            return self.blockers[fmt]
        if self.count(scene, fmt):
            return ''
        if fmt in ('line', 'compare'):
            scene = self.scene_key(scene)
            if not any(self.tutorial_uses[scene, fmt, tutorial] < self.per_tutorial
                       for tutorial in self.tutorials.get(fmt, ())):
                return 'Every eligible tutorial has used its allowance on this footage. Add a tutorial or starting scene.'
            return ('Every tick-and-cross wording has already been used on this footage. '
                    'Add a new wording or starting scene.'
                    if fmt == 'compare' else
                    'Every opening line has already been used on this footage. Add a new line or starting scene.')
        return 'No distinct card combinations remain for this footage. Add a starting scene or supporting assets.'
