"""Assets, compatibility and reuse accounting for Hook Story.

Identities follow file contents, not filenames. The ledger owns all use counts; editing a
name or moving a supporting asset between shared folders cannot make its history disappear.
"""
from collections import Counter
import copy
import hashlib
import json
import math
import os
import tempfile

import formula as FM
import manifest as M
import paths
import tutorial_libraries as TL

POOLS = {'hooks': 'Hooks', 'intros': 'Introductions', 'reactions': 'Reactions',
         'bridges': 'Bridges', 'endings': 'End of video',
         'demos': 'Tutorials'}
BUILD_POOLS = tuple(POOLS)
ROLES = ('hook', 'demo', 'intro', 'reaction', 'bridge', 'ending')
# Keep historical identities and usage readable without offering the retired pools.
HISTORY_ROLES = ('hook', 'demo', 'intro', 'reaction', 'bridge', 'advice', 'closing', 'ending')
EXTS = ('.mp4', '.mov', '.m4v', '.webm', '.mkv')
_CACHE = {}
CATEGORIES = ('YouTube Shorts', 'Zillow')


def category(value):
    name = ' '.join(str(value or '').split())[:100]
    return {'youtube': 'YouTube Shorts', 'youtube shorts': 'YouTube Shorts',
            'brainrot videos': 'YouTube Shorts', 'brainrot': 'YouTube Shorts',
            'brain rot videos': 'YouTube Shorts', 'brain rot': 'YouTube Shorts',
            'shorts': 'YouTube Shorts', 'property': 'Zillow', 'zillow': 'Zillow'}.get(name.casefold(), name)


def asset_categories(item):
    s = item['settings']
    # An explicitly empty selection means no categories, never every category.
    values = s.get('use_cases') if item['pool'] == 'hooks' else None
    if values is None:
        values = [s.get('use_case', '')]
    return list({category(v).casefold(): category(v) for v in values if category(v)}.values())


def category_list(pools):
    names = {n.casefold(): n for n in CATEGORIES}
    for pool in ('hooks', 'demos'):
        for item in pools[pool]:
            for name in asset_categories(item):
                names.setdefault(name.casefold(), name)
    return list(names.values())


def folder(pool, library=None):
    if pool not in POOLS:
        raise ValueError('Unknown Hook Story folder.')
    if pool == 'demos' and (library is not None or TL.enabled()):
        return TL.folder(library or TL.library_for('reaction'))
    # Spoken openings are assigned to accounts; source stories are shared.
    if pool == 'intros':
        return os.path.join(paths.ASSETS, 'reaction', pool)
    return paths.asset('reaction/' + pool)


def inspect(path):
    import subprocess
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    if key in _CACHE:
        return dict(_CACHE[key])
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                        '-of', 'json', path], capture_output=True, text=True)
    try:
        d = json.loads(p.stdout)
        v = next(s for s in d['streams'] if s['codec_type'] == 'video')
        duration = float(v.get('duration') or d['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError()
    except (ValueError, KeyError, StopIteration):
        raise ValueError('This file has no readable video: ' + os.path.basename(path))
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    out = dict(id=h.hexdigest(), seconds=duration, width=int(v['width']), height=int(v['height']),
               audio=any(s['codec_type'] == 'audio' for s in d['streams']), bytes=st.st_size)
    _CACHE[key] = out
    return dict(out)


def store_path():
    return paths.data('reaction_assets.json')


def read_store():
    try:
        with open(store_path()) as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get('assets', {}), dict):
            raise ValueError()
        return d
    except FileNotFoundError:
        return {'assets': {}}
    except (ValueError, OSError):
        raise ValueError('The Hook Story asset settings could not be read. Restore that settings file before saving changes.')


def scope(pool):
    return 'openart'


def key(pool, identity):
    return '|'.join([scope(pool), pool, identity])


def defaults(pool, seconds):
    return dict(start=0.0, end=seconds, use_case='', join='contrast', enabled=True,
                use_cases=None, answer_start=None, ending_text='',
                assembly='finished',
                crop_top=0.0, crop_bottom=0.0, crop_left=0.0, crop_right=0.0,
                frame_scale=1.0, frame_x=.5, frame_y=.5,
                gain_db=0.0, background='keep' if pool == 'endings' else 'person', position='alternate' if pool == 'reactions' else 'center',
                width=.20 if pool == 'reactions' else .50,
                x=.72 if pool == 'reactions' else .25,
                y=.48 if pool == 'reactions' else .28,
                loop=False)


def assets():
    db = read_store().get('assets', {})
    out = {p: [] for p in POOLS}
    for pool in POOLS:
        library = TL.library_for('reaction') if pool == 'demos' else None
        root = folder(pool, library=library)
        for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            if name.startswith('.') or not name.lower().endswith(EXTS):
                continue
            path = os.path.join(root, name)
            try:
                info = inspect(path)
                settings = dict(defaults(pool, info['seconds']), **db.get(key(pool, info['id']), {}))
                settings['use_case'] = category(settings.get('use_case'))
                if isinstance(settings.get('use_cases'), list):
                    settings['use_cases'] = list({category(v).casefold(): category(v)
                                                 for v in settings['use_cases'] if category(v)}.values())
                out[pool].append(dict(info, name=name, pool=pool, settings=settings, path=path))
            except ValueError as e:
                out[pool].append(dict(name=name, pool=pool, error=str(e), seconds=0, settings={}, path=path))
            if pool == 'demos':
                out[pool][-1].update(library=library, product=TL.product_for(library, name) if TL.enabled() else '')
    mark_tutorials(out)
    return out


def mark_tutorials(pools):
    """Keep the complete editing inventory while marking safe build ingredients."""
    items = pools.get('demos', [])
    if not TL.enabled():
        for item in items:
            item['eligible'] = True
        return
    library = TL.library_for('reaction')
    eligible = set(TL.eligible_names('reaction', [item['name'] for item in items]))
    for item in items:
        item['eligible'] = item.get('library', library) == library and item['name'] in eligible


def build_usable(item):
    return usable(item) and (item.get('pool') != 'demos' or item.get('eligible', False) or not TL.enabled())


def finite(value, label, lo, hi):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + ' must be a number.')
    if not math.isfinite(n) or not lo <= n <= hi:
        raise ValueError('%s must be between %g and %g.' % (label, lo, hi))
    return n


def validate(pool, data, seconds):
    d = defaults(pool, seconds)
    d.update({k: v for k, v in data.items() if k in d})
    d['start'] = finite(d['start'], 'Start', 0, seconds)
    d['end'] = finite(d['end'], 'End', 0, seconds)
    if d['end'] - d['start'] < 2/30:
        raise ValueError('Keep at least two video frames between Start and End.')
    d['gain_db'] = finite(d['gain_db'], 'Volume', -60, 12)
    d['width'] = finite(d['width'], 'Presenter width', .08, 1.5)
    d['x'] = finite(d['x'], 'Horizontal position', -1, 1)
    d['y'] = finite(d['y'], 'Vertical position', -1, 1)
    for side in ('top', 'bottom', 'left', 'right'):
        d['crop_'+side] = finite(d['crop_'+side], 'Crop '+side, 0, .9)
    if d['crop_top']+d['crop_bottom'] > .9 or d['crop_left']+d['crop_right'] > .9:
        raise ValueError('Keep at least 10% of the picture after cropping.')
    d['frame_scale'] = finite(d['frame_scale'], 'Full-screen zoom', 1, 3)
    for k in ('frame_x','frame_y'):d[k] = finite(d[k], 'Framing position', 0, 1)
    if d['background'] not in ('person', 'green', 'keep', 'alpha'):
        raise ValueError('Choose a background option.')
    if d['position'] not in ('alternate', 'left', 'center', 'right', 'custom'):
        raise ValueError('Choose a presenter position.')
    if d['join'] not in ('contrast', 'answer', 'either'):
        raise ValueError('Choose how this clip joins the next part.')
    d['use_case'] = category(d['use_case'])
    if pool == 'hooks' and d['use_cases'] is not None:
        if not isinstance(d['use_cases'], list) or len(d['use_cases']) > 50:
            raise ValueError('Choose the tutorial categories this hook can introduce.')
        d['use_cases'] = list({category(v).casefold(): category(v)
                              for v in d['use_cases'] if category(v)}.values())
    d['ending_text'] = str(d['ending_text'] or '').strip()[:1500]
    if d['answer_start'] is not None and d['answer_start'] != '':
        d['answer_start'] = finite(d['answer_start'], 'Tutorial start', d['start'], d['end'])
        if d['end'] - d['answer_start'] < 2/30:
            raise ValueError('Keep at least two video frames after the tutorial start.')
    else:
        d['answer_start'] = None
    if d['assembly'] not in ('finished', 'pieces'):
        raise ValueError('Choose a finished video or a tutorial with separate ending clips.')
    if pool == 'demos' and d['assembly'] == 'pieces' and d['join'] != 'answer':
        raise ValueError('A tutorial with separate clips must start straight at the tutorial.')
    if pool == 'demos' and d['assembly'] == 'finished' and d['join'] == 'either' and (
            d['answer_start'] is None or d['answer_start'] - d['start'] < 1/30):
        raise ValueError('Mark where the tutorial starts after the bridge so question hooks can skip it.')
    d['enabled'] = bool(d['enabled'])
    d['loop'] = bool(d['loop'])
    return d


def save_asset(pool, name, data, library=None):
    if pool not in POOLS or os.path.basename(name) != name:
        raise ValueError('Choose a file in this format.')
    info = inspect(os.path.join(folder(pool, library=library), name))
    settings = validate(pool, data, info['seconds'])
    path = store_path()
    # Same locking convention as the ledger: concurrent saves preserve other assets.
    with M.locked(path):
        db = read_store()
        db.setdefault('assets', {})[key(pool, info['id'])] = settings
        _write_store(path, db)
    return settings


def _write_store(path, db):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.reaction-', dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(db, f, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)




def usable(item):
    return not item.get('error') and item['settings'].get('enabled', True)


def compatible(hook, demo):
    try:
        join_plan(hook, demo)
        return True
    except ValueError:
        return False


def join_plan(hook, demo):
    a, b = hook['settings'], demo['settings']
    topics = {c.casefold() for c in asset_categories(hook)}
    target = category(b.get('use_case'))
    if not target or target.casefold() not in topics:
        raise ValueError('Choose a demo in one of this hook\'s tutorial categories. '
                         'A direct answer must address the hook\'s question.')
    join = a['join'] if a['join'] != 'either' else ('answer' if b['join'] == 'answer' else 'contrast')
    if b.get('assembly', 'finished') == 'pieces':
        if b['join'] != 'answer':
            raise ValueError('A tutorial with separate clips must start straight at the tutorial.')
        return dict(kind=join, category=target, demo_start=b['start'],
                    skipped_bridge_seconds=0, separate_clips=True, needs_bridge=join=='contrast')
    if b['join'] not in (join, 'either'):
        raise ValueError('This hook needs a direct tutorial answer.' if join == 'answer' else
                         'This hook needs a demo with a contrast bridge.')
    start = b['start']
    if b['join'] == 'either':
        marker = b.get('answer_start')
        # Older "Either works" settings never proved that an embedded bridge was removed.
        if marker is None or not math.isfinite(marker) or marker-start < 1/30 or b['end']-marker < 2/30:
            raise ValueError('Mark the tutorial start after the bridge in the demo\'s details.')
        if join == 'answer':
            start = marker
    return dict(kind=join, category=target, demo_start=start,
                skipped_bridge_seconds=round(start-b['start'], 8))


def cut_id(item):
    return '%s:%d:%d' % (item['id'], math.floor(item['settings']['start']*30+.5), math.floor(item['settings']['end']*30+.5))


def pair_key(hook, demo):
    return cut_id(hook) + '|' + cut_id(demo)


def positions(reaction):
    p = reaction['settings']['position']
    return ['left', 'right'] if p == 'alternate' else [p]


def render_identity(recipe):
    # Labels and classification notes do not make another visual version. Apply the same
    # identity to old ledger recipes so adding category controls does not reset history.
    identity = {'position': recipe['position']}
    visual = ('start', 'end', 'gain_db', 'background', 'position', 'width', 'x', 'y', 'loop')
    for role in HISTORY_ROLES:
        item = recipe.get(role)
        if role in ('bridge', 'advice', 'closing', 'ending') and not item:
            continue  # Preserve identities of recipes made before separate tails existed.
        identity[role] = {'id': item['id'], 'audio': item['audio'],
                          'settings': {k: item['settings'][k] for k in visual}} if item else None
        if item:
            for k in ('crop_top', 'crop_bottom', 'crop_left', 'crop_right'):
                if item['settings'].get(k, 0):
                    identity[role]['settings'][k] = item['settings'][k]
            if role in ('demo','bridge','advice','closing','ending') and item['settings'].get('frame_scale',1) != 1:
                for k, default in [('frame_scale',1),('frame_x',.5),('frame_y',.5)]:
                    identity[role]['settings'][k] = item['settings'].get(k,default)
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def make_recipe(hook, demo, intro, reaction, position, bridge=None, ending=None):
    plan = join_plan(hook, demo)
    if plan.get('separate_clips'):
        validate_parts(plan, bridge, ending)
    elif any((bridge, ending)):
        raise ValueError('This finished tutorial already contains its bridge and closing.')
    recipe = {'version': 2, 'pair': pair_key(hook, demo), 'position': position, 'transition': plan}
    if plan.get('separate_clips'):recipe['version'] = 4
    for part, asset in [('hook', hook), ('demo', demo), ('intro', intro), ('reaction', reaction),
                        ('bridge', bridge), ('ending', ending)]:
        recipe[part] = (copy.deepcopy({k: asset[k] for k in ('id','name','pool','settings','seconds','audio')})
                        if asset else None)
    recipe['demo']['library'] = demo.get('library') or TL.library_for('reaction')
    recipe['demo']['settings']['start'] = plan['demo_start']
    recipe['id'] = render_identity(recipe)
    return recipe


def record_usage(recipe, usage):
    for role in HISTORY_ROLES:
        if recipe.get(role):
            usage[(role, recipe[role]['id'])] += 1
        elif role == 'intro':
            usage[('intro', 'none')] += 1
    intro = recipe['intro']['id'] if recipe.get('intro') else 'none'
    for role in ('hook', 'reaction', 'bridge'):
        if recipe.get(role):
            usage[('intro_'+role, intro, recipe[role]['id'])] += 1
    usage[('position', recipe.get('position'))] += 1


def opening_story_key(hook, intro):
    # A rename, new crop/trim, different tutorial or move to another account does not
    # turn the same opening and story into fresh footage with a new allowance.
    return (intro['id'] if intro else 'none', hook['id'])


def history(rows=None, campaign=False):
    pairs, ids, usage = Counter(), set(), Counter()
    rows = M.read_rows() if rows is None else rows
    for row in rows if campaign else M.all_rows(rows):
        if row.get('format') != 'reaction' or row.get('status') != 'ok':
            continue
        try:
            recipe = json.loads(row.get('reaction_recipe') or '{}')
            identity = render_identity(recipe)
            allowance = opening_story_key(recipe['hook'], recipe.get('intro'))
            saved_id = recipe['id']
            pairs[allowance] += 1
            ids.add(saved_id)
            ids.add(identity)
            record_usage(recipe, usage)
        except (ValueError, KeyError, TypeError):
            continue
    return pairs, ids, usage


def part_matches(asset, target_category):
    topic = category(asset['settings'].get('use_case'))
    return not topic or topic.casefold() == target_category.casefold()


def validate_parts(plan, bridge, ending):
    if bool(bridge) != bool(plan['needs_bridge']):
        raise ValueError('Choose a contrast bridge.' if plan['needs_bridge'] else
                         'A question goes straight to its tutorial without a bridge.')
    for role, asset, pool in [('bridge', bridge, 'bridges'), ('End of video', ending, 'endings')]:
        if role == 'bridge' and not plan['needs_bridge']:
            continue
        if not asset or asset['pool'] != pool or not usable(asset):
            raise ValueError('Choose an enabled '+role+' clip.')
        if not part_matches(asset, plan['category']):
            raise ValueError('Choose a '+role+' clip for '+plan['category']+'.')


def variants(hook, demo, intro, pools, usage, taken, limit):
    """Visit the best combinations first without materializing the full product.

    A library with 30 bridges and 25 combined ending takes can have hundreds of thousands of
    variants. Only enough unused variants to fill this opening/story allowance are needed.
    """
    plan = join_plan(hook, demo)
    reactions=[]
    hs=hook['settings']
    for r in pools['reactions']:
        s=r['settings']
        if s['end']-s['start']+.02 < hs['end']-hs['start'] and not s['loop']:continue
        reactions.extend((r,p) for p in positions(r))
    options = [('intro',[intro]), ('reaction',reactions)]
    if plan.get('separate_clips'):
        allowed=lambda p:[a for a in pools[p] if part_matches(a,plan['category'])]
        options += [('bridge',allowed('bridges') if plan['needs_bridge'] else [None]),
                    ('ending',allowed('endings'))]
    else:options += [('bridge',[None]),('ending',[None])]
    if any(not xs for _,xs in options):return []
    def cost(role, value):
        if role=='reaction':
            a,p=value
            return (usage[(role,a['id'])],0,
                    usage[('intro_reaction',intro['id'] if intro else 'none',a['id'])],usage[('position',p)])
        uses=usage[(role,value['id'] if value else 'none')]
        combination=usage[('intro_bridge',intro['id'] if intro else 'none',value['id'])] if role=='bridge' and value else 0
        return (uses if role in ('intro','bridge') else 0,
                uses if role == 'ending' else 0,combination,0)
    from reaction_assembly import ranked_product
    result=[]
    for picked in ranked_product(options,cost):
        reaction,position=picked.pop('reaction')
        recipe=make_recipe(hook,demo,picked.pop('intro'),reaction,position,**picked)
        if recipe['id'] not in taken:result.append(recipe)
        if len(result)>=limit:break
    return result


def choices(poolset, rows=None):
    mark_tutorials(poolset)
    pools = {p: [x for x in poolset.get(p, []) if build_usable(x)] for p in BUILD_POOLS}
    # Identical copies in the same pool are the same ingredient, even under a new name.
    pools = {p: list({x['id']: x for x in xs}.values()) for p,xs in pools.items()}
    used, taken, usage = history(rows, campaign=True)
    groups = []
    cap = int(FM.num('reaction_intro_story_repeats'))
    for h in pools['hooks']:
        for intro in pools['intros'] or [None]:
            key = opening_story_key(h,intro)
            remaining = max(0, cap-used[key])
            if not remaining:
                continue
            demos=[d for d in pools['demos'] if compatible(h,d)]
            available=[]
            for d in demos:
                available.extend(variants(h,d,intro,pools,usage,taken|{v['id'] for v in available},remaining-len(available)))
                if len(available)>=remaining:break
            if available:
                groups.append({'key':key, 'remaining': min(remaining,len(available)),
                               'hook':h, 'intro':intro, 'demos':demos, 'pools':pools})
    return groups, usage


def state(rows=None, poolset=None):
    pools = assets() if poolset is None else poolset
    rows = list(M.read_rows() if rows is None else rows)
    groups, usage = choices(pools, rows)
    left = sum(g['remaining'] for g in groups)
    reason = ''
    for p in ('hooks','demos','reactions'):
        if not any(build_usable(x) for x in pools[p]):
            reason = ('Assign tutorials to the selected content type under Assets → Tutorial libraries.'
                      if p == 'demos' and TL.enabled() and pools[p] else
                      'Add ' + POOLS[p].lower() + ' under Assets.')
            break
    if not reason and not left and any(build_usable(d) and d['settings'].get('assembly') == 'pieces' for d in pools['demos']) and not any(usable(e) for e in pools.get('endings', [])):
        reason = 'Add a combined posting-advice and call-to-action clip under Assets → End of video.'
    if not reason and not left:
        reason = ('No unused compatible combinations. Check opening/story allowances, matching tutorials, reaction length and enabled bridge and End of video clips in Assets.')
    account_usage=history(rows)[2]
    opening_usage=history(rows,campaign=True)[0]
    story_ids={h['id'] for h in pools['hooks'] if usable(h)}
    opening_limit=int(FM.num('reaction_intro_story_repeats'))
    for p, items in pools.items():
        for item in items:
            role = {'hooks':'hook','demos':'demo','intros':'intro','reactions':'reaction',
                    'bridges':'bridge','endings':'ending'}.get(p)
            item['uses'] = account_usage[(role, item.get('id'))] if role else 0
            item['variety_uses'] = usage[(role, item.get('id'))] if role else 0
            if p=='intros':
                item['allowance']=len(story_ids)*opening_limit
                # Remaining reuse is independent of whether other ingredients can build now.
                item['uses_left']=sum(max(0,opening_limit-opening_usage[(item['id'],story)])
                                      for story in story_ids) if item.get('id') else None
                item['left']=sum(g['remaining'] for g in groups if g['intro'] and g['intro']['id']==item['id'])
    joins = [dict(hook=h['name'], demo=d['name'], **join_plan(h, d))
             for h in pools['hooks'] for d in pools['demos']
             if usable(h) and build_usable(d) and compatible(h, d)]
    return {'left': left, 'reason': reason, 'pools': pools, 'intro_story_limit': int(FM.num('reaction_intro_story_repeats')),
            'joins': joins, 'context': ['openart', ''],
            'categories': category_list(pools),
            'tutorial_library': TL.library_for('reaction'),
            'tutorial_product': TL.current_product() if TL.enabled() else '',
            'how': FM.rule('reaction'), 'sum': '%d opening/story pairing%s with unused versions' % (len(groups), '' if len(groups)==1 else 's')}


def variety_score(recipe, pools, usage):
    """Ingredient variety precedes story/demo balancing, with history across all accounts.

    An absent bridge on a question is neutral, not a zero-use clip that unfairly beats
    every contrast recipe after its first bridge. The same applies to finished tutorials.
    """
    def uses(role):
        asset=recipe.get(role)
        if asset:return usage[(role,asset['id'])]
        pool={'intro':'intros','bridge':'bridges','ending':'endings'}[role]
        values=[usage[(role,a['id'])] for a in pools.get(pool,[])]
        return min(values,default=0)
    intro=recipe['intro']['id'] if recipe.get('intro') else 'none'
    combinations=sum(usage[('intro_'+role,intro,recipe[role]['id'])]
                     for role in ('hook','reaction','bridge') if recipe.get(role))
    return (sum(uses(role) for role in ('intro','reaction','bridge')),
            uses('ending'),combinations,
            usage[('hook',recipe['hook']['id'])],usage[('demo',recipe['demo']['id'])],
            usage[('position',recipe['position'])])


def select(count, poolset=None, rows=None):
    pools = assets() if poolset is None else poolset
    rows = list(M.read_rows() if rows is None else rows)
    groups, usage = choices(pools, rows)
    taken = history(rows, campaign=True)[1]
    made = []
    while len(made) < count:
        candidates=[]
        for g in groups:
            if not g['remaining']:continue
            available=[]
            for demo in g['demos']:
                available.extend(variants(g['hook'],demo,g['intro'],g['pools'],usage,taken,1))
            if available:
                recipe=min(available,key=lambda r:variety_score(r,g['pools'],usage))
                candidates.append((variety_score(recipe,g['pools'],usage),g,recipe))
            else:g['remaining']=0
        if not candidates:break
        _,g,recipe=min(candidates,key=lambda x:x[0])
        taken.add(recipe['id']);g['remaining'] -= 1
        record_usage(recipe,usage)
        made.append(recipe)
    return made
