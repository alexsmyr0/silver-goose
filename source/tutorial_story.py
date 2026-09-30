"""Bottle spin ingredients, source identities and successful-build allowances.

The same physical opening/tutorial pair can use each ending once, up to the format's
repeat allowance. Only successful originals in the campaign ledger spend those uses.
"""
from collections import Counter, defaultdict
import copy
from fractions import Fraction
import hashlib
import json
import math
import os
import subprocess
import threading

import formula as FM
import manifest as M
import openart_repurpose as RP
import paths
import tutorial_libraries as TL
import tutorial_story_music as MUSIC

FORMAT = 'tutorial_story'
LABEL = 'Bottle spin'
POOLS = {'scenes': 'Starting scenes', 'tutorials': 'Tutorials', 'endings': 'Final talking clips',
         'music': 'Songs'}
ROLES = {'start': 'scenes', 'tutorial': 'tutorials', 'ending': 'endings'}
EXTS = TL.EXTENSIONS
SOUND_EXTS = ('.m4a', '.mp3', '.wav', '.aac')
FPS = 30
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def repeats():
    return max(1, int(FM.num('tutorial_story_repeats')))


def folder(pool, library=None):
    if pool not in POOLS:
        raise ValueError('Choose a Bottle spin asset folder.')
    if pool == 'tutorials':
        return TL.folder(library) if library else TL.folder_for(FORMAT)
    return paths.asset(FORMAT + '/' + pool)


def _stamp(path):
    st = os.stat(path)
    return (os.path.realpath(path), st.st_dev, st.st_ino, st.st_size,
            st.st_mtime_ns, st.st_ctime_ns)


def fingerprint(path):
    """Hash actual contents; metadata only caches unchanged files within this process."""
    stamp = _stamp(path)
    key = ('hash', stamp)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if _stamp(path) != stamp:
        raise ValueError('This video changed while it was being read: ' + os.path.basename(path))
    result = digest.hexdigest()
    with _CACHE_LOCK:
        if len(_CACHE) > 2048:
            _CACHE.clear()
        _CACHE[key] = result
    return result


def inspect(path):
    """Read source facts through the shared media inspector, without upload constraints.

    A short opening or a silent tutorial is a valid ingredient even when it is not a
    complete upload. Only readable picture, dimensions and duration are required here.
    """
    stamp = _stamp(path)
    key = ('info', stamp)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached:
        return dict(cached)
    import media_probe
    info = media_probe.inspect(path)
    video = info.get('video') or {}
    try:
        seconds = float(info['duration'] or video.get('duration'))
        width, height = int(video['width']), int(video['height'])
        if not math.isfinite(seconds) or seconds <= 0 or min(width, height) <= 0:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError('This file has no readable video: ' + os.path.basename(path))
    try:
        fps = float(Fraction(str(video.get('avg_frame_rate') or video.get('r_frame_rate') or '0')))
        if not math.isfinite(fps) or fps <= 0:
            fps = 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    result = dict(id=fingerprint(path), seconds=seconds, width=width, height=height,
                  fps=fps, audio=bool(info.get('audio')), bytes=stamp[3])
    if _stamp(path) != stamp:
        raise ValueError('This video changed while it was being read: ' + os.path.basename(path))
    with _CACHE_LOCK:
        _CACHE[key] = result
    return dict(result)


def _names(root, extensions=EXTS):
    try:
        names = os.listdir(root)
    except FileNotFoundError:
        return []
    return sorted(n for n in names if not n.startswith('.') and n.lower().endswith(extensions)
                  and os.path.isfile(os.path.join(root, n)))


def _safe_name(name):
    return (isinstance(name, str) and bool(name) and not name.startswith('.')
            and os.path.basename(name) == name and '/' not in name and '\\' not in name
            and name.lower().endswith(EXTS + SOUND_EXTS))


def inspect_music(path):
    stamp = _stamp(path)
    key = ('music', stamp)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached:
        return copy.deepcopy(cached)
    try:
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                                '-of', 'json', path], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        raise ValueError('Music inspection timed out: ' + os.path.basename(path)) from error
    if probe.returncode:
        raise ValueError('This file has no readable music: ' + os.path.basename(path))
    info = json.loads(probe.stdout)
    audio = next((s for s in info.get('streams', []) if s.get('codec_type') == 'audio'), {})
    seconds = float(info.get('format', {}).get('duration') or audio.get('duration') or 0)
    if not audio or not math.isfinite(seconds) or seconds < 2 / FPS:
        raise ValueError('This file has no readable music: ' + os.path.basename(path))
    result = dict(id=fingerprint(path), seconds=seconds, audio=True,
                  bytes=stamp[3], settings=dict(gain_db=-18.0))
    if _stamp(path) != stamp:
        raise ValueError('This song changed while it was being read: ' + os.path.basename(path))
    with _CACHE_LOCK:
        _CACHE[key] = result
    return copy.deepcopy(result)


def _within(root, name):
    path = os.path.join(root, name)
    if os.path.commonpath([os.path.realpath(root), os.path.realpath(path)]) != os.path.realpath(root):
        raise ValueError('This video points outside its asset folder: ' + name)
    return path


def assets():
    library = TL.library_for(FORMAT)
    music_settings = MUSIC.read()['tracks']
    pools = {}
    for pool in POOLS:
        root = folder(pool, library if pool == 'tutorials' else None)
        names = _names(root, SOUND_EXTS if pool == 'music' else EXTS)
        eligible = set(TL.eligible_names(FORMAT, names)) if pool == 'tutorials' else set(names)
        items = []
        for name in names:
            item = dict(name=name, pool=pool, kind=(('tutorial-library/' + library)
                        if pool == 'tutorials' else FORMAT + '/' + pool), eligible=name in eligible)
            if pool == 'tutorials':
                item.update(library=library, product=TL.product_for(library, name) if TL.enabled() else '')
            try:
                if pool == 'music':
                    item.update(inspect_music(_within(root, name)))
                    item['settings'] = MUSIC.validate(music_settings.get(item['id'], {}), item['seconds'])
                    items.append(item)
                    continue
                info = inspect(_within(root, name))
                item.update(info, settings=dict(start=0.0, end=info['seconds'], gain_db=0.0))
                if pool == 'endings' and not info['audio']:
                    item['error'] = 'This final talking clip has no audio to caption.'
            except (OSError, ValueError, RuntimeError) as error:
                item.update(error=str(error), seconds=0, bytes=0, settings={})
            items.append(item)
        pools[pool] = items
    return pools


def save_music(name, settings):
    if not _safe_name(name) or not name.lower().endswith(SOUND_EXTS):
        raise ValueError('Choose a song from Bottle spin Songs.')
    info = inspect_music(_within(folder('music'), name))
    return MUSIC.save(info['id'], settings, info['seconds'])


def usable(item):
    return bool(item and item.get('id') and not item.get('error')
                and item.get('seconds', 0) >= 2 / FPS and item.get('eligible', True)
                and (item.get('pool') != 'endings' or item.get('audio')))


def pair_key(start, tutorial):
    # Folder moves, renames, duplicate uploads and trims do not refresh physical footage.
    return (start['id'], tutorial['id'])


def _identity(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value))


def history(rows=None):
    """All accounts share physical footage history; repost allowances remain separate."""
    counts, endings, usage = Counter(), defaultdict(set), Counter()
    for row in M.read_rows() if rows is None else rows:
        if row.get('format') != FORMAT or row.get('status') != 'ok' or row.get('repost_root'):
            continue
        try:
            recipe = json.loads(row.get('reaction_recipe') or '{}')
            if any(not _identity(recipe[role]['id']) for role in ROLES):
                raise ValueError()
            if not isinstance(recipe.get('variation') or {}, dict):
                raise ValueError()
            pair = pair_key(recipe['start'], recipe['tutorial'])
            ending = recipe['ending']['id']
            counts[pair] += 1
            endings[pair].add(ending)
            _record_usage(recipe, usage)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError('The saved Bottle spin recipe for %s could not be read. '
                             'Restore it before building more videos.' %
                             (row.get('video_id') or 'a completed video')) from error
    return counts, endings, usage


def _record_usage(recipe, usage):
    pair = pair_key(recipe['start'], recipe['tutorial'])
    for role in ROLES:
        usage[(role, recipe[role]['id'])] += 1
    if recipe.get('music'):
        usage[('music', recipe['music']['id'])] += 1
    usage[('pair', pair)] += 1
    for kind in ('mark', 'look', 'speed'):
        value = (recipe.get('variation') or {}).get(kind)
        if value:
            usage[(kind, value)] += 1
            usage[('pair_' + kind, pair, value)] += 1


def _unique(items):
    selected = {}
    for item in items:
        if usable(item):
            selected.setdefault(item['id'], item)
    return list(selected.values())


def _groups(poolset, rows):
    pools = {pool: _unique(poolset.get(pool, [])) for pool in POOLS}
    counts, endings, usage = history(rows)
    limit = repeats()
    groups = []
    for start in pools['scenes']:
        for tutorial in pools['tutorials']:
            pair = pair_key(start, tutorial)
            options = [ending for ending in pools['endings'] if ending['id'] not in endings[pair]]
            left = min(max(0, limit - counts[pair]), len(options))
            if left:
                groups.append(dict(pair=pair, start=start, tutorial=tutorial, endings=options, left=left))
    return groups, pools, counts, usage


def capacity(rows=None, poolset=None):
    raw = assets() if poolset is None else poolset
    rows = list(M.read_rows() if rows is None else rows)
    groups, eligible, counts, usage = _groups(raw, rows)
    inventory = copy.deepcopy(raw)
    limit = repeats()
    left = sum(g['left'] for g in groups)
    scene_left = Counter()
    for group in groups:
        scene_left[group['start']['id']] += group['left']
    for role, pool in ROLES.items():
        for item in inventory.get(pool, []):
            identity = item.get('id')
            item['uses'] = usage[(role, identity)]
            if pool == 'scenes':
                item.update(cap=len(eligible['tutorials']) * limit,
                            cap_left=sum(max(0, limit - counts[(identity, tutorial['id'])])
                                         for tutorial in eligible['tutorials']), left=scene_left[identity])
    reason = ''
    for pool in POOLS:
        if pool == 'music' and not raw.get(pool):
            continue
        if not eligible[pool]:
            left = 0
            if pool == 'tutorials' and raw.get(pool) and any(not x.get('eligible', True) for x in raw[pool]):
                if TL.enabled() and not TL.current_product():
                    reason = 'Choose MCP, Chat or Director for this content type in Settings, then assign the tutorial to the same campaign under Manage tutorials.'
                else:
                    reason = 'Assign a tutorial to this content type\'s campaign under Manage tutorials.'
            elif raw.get(pool) and any(x.get('error') for x in raw[pool]):
                reason = 'Check the unreadable ' + POOLS[pool].lower() + ' under Assets.'
            else:
                reason = 'Add ' + POOLS[pool].lower() + ' under Assets.'
            break
    if not reason and not left:
        reason = 'No unused combinations left. Add a starting scene, tutorial or a different final talking clip.'
    library = TL.library_for(FORMAT)
    return dict(ok=True, left=left, buildable=left, reason=reason,
                sum='%d starting scenes x %d tutorials x %d; %d videos available' %
                    (len(eligible['scenes']), len(eligible['tutorials']), limit, left),
                scenes=inventory.get('scenes', []), tutorials=inventory.get('tutorials', []),
                endings=inventory.get('endings', []), pools=inventory, tutorials_library=library,
                music=inventory.get('music', []),
                counts={pool: len(items) for pool, items in eligible.items()}, pair_limit=limit,
                context=['openart', ''])


def public_state(rows=None, poolset=None):
    # No resolved filesystem paths, mutable owner data or private records reach the browser.
    try:
        result = capacity(rows, poolset)
    except (OSError, ValueError, RuntimeError) as error:
        # A broken folder or recipe must remain an explicit unavailable state without
        # taking the other formats' status cards down with this format.
        return dict(ok=False, left=0, buildable=0, reason=str(error), sum='Needs attention',
                    scenes=[], tutorials=[], endings=[], music=[], pools={p: [] for p in POOLS},
                    tutorials_library='', counts={p: 0 for p in POOLS},
                    context=['openart', ''])
    # Keep spent scenes available for preview and future allowance/tutorial changes.
    for items in result['pools'].values():
        for item in items:
            item.pop('path', None)
    return result


def safe_speeds(*items):
    permitted = set(RP.SPEEDS)
    for item in items:
        permitted.intersection_update(RP.speeds_for(item.get('fps'), FPS))
    return sorted(permitted) or [1.0]


def _variation(start, tutorial, ending, usage):
    pair = pair_key(start, tutorial)
    seed = '|'.join(pair + (ending['id'],))
    choices = {'mark': RP.marks(), 'look': list(RP.LOOK_NAMES),
               'speed': [RP.speed_key(s) for s in safe_speeds(start, tutorial, ending)]}
    def score(kind, value):
        return (usage[('pair_' + kind, pair, value)], usage[(kind, value)],
                hashlib.sha256((seed + kind + value).encode()).hexdigest())
    selected = {kind: min(values, key=lambda v: score(kind, v)) for kind, values in choices.items()}
    if selected == dict(mark=RP.NORMAL_MARK, look='natural', speed=RP.speed_key(1.0)):
        selected['look'] = min([v for v in choices['look'] if v != 'natural'],
                               key=lambda v: score('look', v))
    return selected


def make_recipe(start, tutorial, ending, usage=None, music=None):
    if not all(usable(x) for x in (start, tutorial, ending)):
        raise ValueError('Choose a readable starting scene, eligible tutorial and final talking clip.')
    recipe = dict(version=1, format=FORMAT, campaign='openart', account='')
    for role, item in [('start', start), ('tutorial', tutorial), ('ending', ending)]:
        recipe[role] = copy.deepcopy({k: item[k] for k in
                                     ('id', 'name', 'pool', 'seconds', 'fps', 'audio', 'settings')})
        if role == 'tutorial':
            recipe[role]['library'] = item.get('library') or TL.library_for(FORMAT)
    recipe['variation'] = _variation(start, tutorial, ending, usage or Counter())
    if music is not None:
        if not usable(music):
            raise ValueError('Choose a readable song under Bottle spin Songs.')
        recipe['music'] = copy.deepcopy({k: music[k] for k in
                                        ('id', 'name', 'pool', 'seconds', 'settings')})
    recipe['id'] = hashlib.sha256(json.dumps(
        {k: recipe[k] for k in (*ROLES, 'variation', 'music') if k in recipe}, sort_keys=True).encode()).hexdigest()
    return recipe


def select(count, rows=None, poolset=None):
    pools = assets() if poolset is None else poolset
    rows = list(M.read_rows() if rows is None else rows)
    groups, _, _, usage = _groups(pools, rows)
    songs = _unique(pools.get('music', []))
    if pools.get('music') and not songs:
        raise ValueError('Add a readable song under Bottle spin Songs.')
    selected = []
    for _ in range(max(0, int(count))):
        candidates = [g for g in groups if g['left']]
        if not candidates:
            break
        group = min(candidates, key=lambda g: (usage[('start', g['start']['id'])],
                    usage[('pair', g['pair'])], usage[('tutorial', g['tutorial']['id'])], g['pair']))
        ending = min(group['endings'], key=lambda x: (usage[('ending', x['id'])], x['id']))
        music = min(songs, key=lambda x: (usage[('music', x['id'])], x['id'])) if songs else None
        recipe = make_recipe(group['start'], group['tutorial'], ending, usage, music)
        selected.append(recipe)
        group['left'] -= 1
        group['endings'] = [x for x in group['endings'] if x['id'] != ending['id']]
        _record_usage(recipe, usage)
    return selected


choose = select


def asset_path(asset):
    """Replay the original library and hash, tolerating a rename inside that folder."""
    if not isinstance(asset, dict) or asset.get('pool') not in POOLS or not _safe_name(asset.get('name')):
        raise ValueError('This saved Bottle spin ingredient is invalid.')
    if not _identity(asset.get('id')):
        raise ValueError('This saved Bottle spin ingredient has no valid source identity.')
    if asset['pool'] == 'tutorials' and not asset.get('library'):
        raise ValueError('This saved tutorial has no original folder identity.')
    root = folder(asset['pool'], asset.get('library'))
    names = [asset['name']] + _names(root, SOUND_EXTS if asset['pool'] == 'music' else EXTS)
    for name in dict.fromkeys(names):
        path = _within(root, name)
        if os.path.isfile(path) and fingerprint(path) == asset['id']:
            return path
    raise ValueError('This ingredient changed or was removed: ' + asset['name'])


def validate_current(recipe, rows=None):
    """Recheck sources, current tutorial eligibility and allowance before publication."""
    if recipe.get('format') != FORMAT or recipe.get('campaign') != 'openart' or recipe.get('account') != '':
        raise ValueError('This Bottle spin recipe belongs to a different account.')
    resolved = {}
    for role, pool in ROLES.items():
        asset = recipe.get(role) or {}
        if asset.get('pool') != pool:
            raise ValueError('This Bottle spin recipe has the wrong ingredient order.')
        resolved[role] = asset_path(asset)
    if recipe.get('music'):
        if recipe['music'].get('pool') != 'music':
            raise ValueError('This Bottle spin recipe has an invalid song.')
        resolved['music'] = asset_path(recipe['music'])
    tutorial = recipe['tutorial']
    if tutorial['library'] != TL.library_for(FORMAT):
        raise ValueError('The tutorial folder changed while this video was building. Build a new combination.')
    if os.path.basename(resolved['tutorial']) not in TL.eligible_names(FORMAT, [os.path.basename(resolved['tutorial'])]):
        raise ValueError('This tutorial is no longer assigned to this content type\'s campaign.')
    counts, endings, _ = history(rows)
    pair = pair_key(recipe['start'], tutorial)
    if counts[pair] >= repeats() or recipe['ending']['id'] in endings[pair]:
        raise ValueError('This starting scene and tutorial have already used this combination. Build a new combination.')
    return resolved
