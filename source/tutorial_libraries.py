"""Shared tutorial folders and campaign eligibility for OpenArt production.

Library IDs identify the existing physical folders permanently. Assigning a format to
a library never moves media or rewrites the identity of a previously built video.
"""
import hashlib
import json
import os
import stat
import tempfile
import threading

import paths


FILENAME = 'tutorial_libraries.json'
LIBRARIES = (
    {'id': 'regular', 'label': 'Regular tutorials', 'kind': 'tutorials'},
    {'id': 'farm', 'label': 'Content farm tutorials', 'kind': 'farm/tutorials'},
    {'id': 'reaction', 'label': 'Hook Story tutorials', 'kind': 'reaction/demos'},
    {'id': 'tutorial_story', 'label': 'Bottle spin tutorials', 'kind': 'tutorial_story/tutorials'},
    {'id': 'ai_larp', 'label': 'AI LARP tutorials', 'kind': 'ai_larp/tutorials'},
)
DEFAULT_LIBRARIES = {'line': 'regular', 'card': 'regular', 'compare': 'regular',
                     'farm': 'farm', 'reaction': 'reaction', 'tutorial_story': 'tutorial_story',
                     'ai_larp': 'ai_larp'}
# Rows without a saved library predate Bottle spin's dedicated folder. Changing the
# production default must not retarget their tutorial references or reuse history.
LEGACY_LIBRARIES = dict(DEFAULT_LIBRARIES, tutorial_story='regular')
FORMAT_LABELS = {'line': 'Line, then card', 'card': 'Card only', 'compare': 'Tick and cross',
                 'farm': 'Content farm', 'reaction': 'Hook Story', 'tutorial_story': 'Bottle spin',
                 'ai_larp': 'AI LARP'}
PRODUCTS = ('mcp', 'chat', 'director')
EXTENSIONS = ('.mp4', '.mov', '.m4v', '.webm', '.mkv')
_FINGERPRINTS = {}
_CACHE_LOCK = threading.Lock()


def enabled():
    return 'openart' == 'openart'


def store_path():
    return paths.data(FILENAME)


def _library(library):
    item = next((item for item in LIBRARIES if item['id'] == library), None)
    if item is None:
        raise ValueError('Choose a tutorial folder.')
    return item


def _name(name):
    if (not isinstance(name, str) or not name or name.startswith('.')
            or os.path.basename(name) != name or '/' in name or '\\' in name
            or not name.lower().endswith(EXTENSIONS)):
        raise ValueError('Choose a video in this tutorial folder.')
    return name


def _product(product):
    if not isinstance(product, str) or product not in ('',) + PRODUCTS:
        raise ValueError('Choose MCP, Chat, Director or Unassigned.')
    return product


def read_store():
    """Missing means unconfigured; an unreadable or malformed store never means empty."""
    try:
        with open(store_path(), encoding='utf-8') as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return {'version': 1, 'formats': {}, 'tutorials': {}}
    except (OSError, ValueError) as error:
        raise ValueError('The tutorial folder settings could not be read. Restore that settings file before continuing.') from error
    try:
        if not isinstance(data, dict) or data.get('version', 1) != 1:
            raise ValueError()
        mappings = data.get('formats', {})
        tutorials = data.get('tutorials', {})
        if not isinstance(mappings, dict) or not isinstance(tutorials, dict):
            raise ValueError()
        for fmt, library in mappings.items():
            if fmt not in DEFAULT_LIBRARIES:
                raise ValueError()
            _library(library)
        for library, entries in tutorials.items():
            _library(library)
            if not isinstance(entries, dict):
                raise ValueError()
            for name, entry in entries.items():
                _name(name)
                if not isinstance(entry, dict):
                    raise ValueError()
                _product(entry.get('product'))
                digest = entry.get('sha256')
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(c not in '0123456789abcdef' for c in digest)):
                    raise ValueError()
    except (TypeError, ValueError) as error:
        raise ValueError('The tutorial folder settings are invalid. Restore that settings file before continuing.') from error
    return data


def _write_store(data):
    target = store_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.tutorial-libraries-', dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def library_for(fmt, assets=None):
    if fmt not in DEFAULT_LIBRARIES:
        raise ValueError('This format does not use a tutorial folder.')
    data = read_store() if enabled() and _live_assets(assets) else {}
    return data.get('formats', {}).get(fmt, DEFAULT_LIBRARIES[fmt])


def folder(library, assets=None):
    return paths.asset(_library(library)['kind'], assets)


def folder_for(fmt, assets=None):
    # Explicit scratch inputs keep their historical layout and never use personal mappings.
    return folder(library_for(fmt, assets), assets)


def _live_assets(assets):
    return assets is None or os.path.realpath(assets) == os.path.realpath(paths.ASSETS)


def current_product(account=None):
    return paths.product()


def _file(library, name, assets=None):
    root = folder(library, assets)
    path = os.path.join(root, _name(name))
    if os.path.commonpath((os.path.realpath(root), os.path.realpath(path))) != os.path.realpath(root):
        raise ValueError('Tutorial files must stay inside their folder.')
    return path


def _stamp(path):
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Choose a video file in this tutorial folder.')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _fingerprint(path):
    """Cache by file identity and modification facts, never by its reusable name alone."""
    path = os.path.realpath(path)
    before = _stamp(path)
    with _CACHE_LOCK:
        cached = _FINGERPRINTS.get(path)
        if cached and cached[0] == before:
            return cached[1]
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if _stamp(path) != before:
        raise ValueError('A tutorial is still changing. Wait for its copy to finish and try again.')
    value = digest.hexdigest()
    with _CACHE_LOCK:
        _FINGERPRINTS[path] = (before, value)
    return value


def _product_for(library, name, data):
    _library(library)
    _name(name)
    entry = data.get('tutorials', {}).get(library, {}).get(name)
    if not entry or not entry.get('product'):
        return ''
    try:
        digest = _fingerprint(_file(library, name))
    except FileNotFoundError:
        return ''
    return entry['product'] if digest == entry['sha256'] else ''


def product_for(library, name):
    return _product_for(library, name, read_store()) if enabled() else ''


def eligible_names(fmt, names, assets=None, account=None):
    """Preserve caller ordering; only this content type's explicitly tagged tutorials build."""
    names = list(names)
    if not enabled() or not _live_assets(assets):
        return names
    data = read_store()
    product = current_product(account)
    if product not in PRODUCTS:
        return []
    library = data.get('formats', {}).get(fmt, DEFAULT_LIBRARIES.get(fmt))
    _library(library)
    return [name for name in names if _product_for(library, name, data) == product]


def pairing_key(library, name):
    _library(library)
    _name(name)
    return name if library == 'regular' else library + '/' + name


def row_library(row):
    saved = (row.get('tutorial_library') or '').strip()
    if saved:
        _library(saved)
        return saved
    return LEGACY_LIBRARIES.get((row.get('format') or '').strip(), '')


def set_formats(assignments):
    if not enabled():
        raise ValueError('Tutorial folders are available for OpenArt content.')
    if not isinstance(assignments, dict) or not assignments:
        raise ValueError('Choose the formats that use each tutorial folder.')
    import catalog as CP
    import manifest as M
    allowed = tuple(CP.FORMATS)
    for fmt, library in assignments.items():
        if fmt not in DEFAULT_LIBRARIES or fmt not in allowed:
            raise ValueError('Choose an enabled format that uses tutorials.')
        _library(library)
    with M.locked(store_path()):
        data = read_store()
        data.setdefault('formats', {}).update(assignments)
        _write_store(data)
    return data


def assign(library, names, product):
    if not enabled():
        raise ValueError('Tutorial folders are available for OpenArt content.')
    _library(library)
    _product(product)
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError('Select at least one tutorial.')
    names = list(dict.fromkeys(_name(name) for name in names))
    import manifest as M
    with M.locked(store_path()):
        data = read_store()
        # Validate every selected file before changing any assignment.
        entries = {}
        for name in names:
            try:
                digest = _fingerprint(_file(library, name))
            except FileNotFoundError as error:
                raise ValueError(name + ' is no longer in this tutorial folder. Reload and try again.') from error
            entries[name] = {'product': product, 'sha256': digest}
        target = data.setdefault('tutorials', {}).setdefault(library, {})
        for name, entry in entries.items():
            if product:
                target[name] = dict(target.get(name, {}), **entry)
            else:
                target.pop(name, None)
        _write_store(data)
    return data


def forget(library, name):
    """Forget active eligibility on deletion without editing production history."""
    _library(library)
    _name(name)
    if not enabled():
        return False
    import manifest as M
    with M.locked(store_path()):
        data = read_store()
        entries = data.get('tutorials', {}).get(library, {})
        if name not in entries:
            return False
        del entries[name]
        _write_store(data)
    return True


def describe():
    import catalog as CP
    if not enabled():
        raise ValueError('Tutorial folders are available for OpenArt content.')
    data = read_store()
    formats = [fmt for fmt in CP.FORMATS if fmt in DEFAULT_LIBRARIES]
    mappings = dict(DEFAULT_LIBRARIES, **data.get('formats', {}))
    libraries = []
    for library in LIBRARIES:
        root = folder(library['id'])
        try:
            names = sorted(os.listdir(root))
        except FileNotFoundError:
            names = []
        tutorials = []
        for name in names:
            if name.startswith('.') or not name.lower().endswith(EXTENSIONS):
                continue
            path = _file(library['id'], name)
            info = os.stat(path)
            if not stat.S_ISREG(info.st_mode):
                continue
            tutorials.append({'name': name, 'product': _product_for(library['id'], name, data),
                              'bytes': info.st_size, 'kind': 'tutorial-library/' + library['id']})
        libraries.append(dict(library, formats=[fmt for fmt in formats if mappings[fmt] == library['id']],
                              tutorials=tutorials))
    return {'ok': True, 'libraries': libraries,
            'formats': [{'key': fmt, 'label': FORMAT_LABELS[fmt]} for fmt in formats],
            'products': [{'key': k, 'label': v} for k, v in CP.PRODUCTS.items()], 'account_product': current_product()}
