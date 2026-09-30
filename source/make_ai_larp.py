"""Build AI LARP split screens, followed by required full-screen tutorials."""


import argparse
import datetime
import json
import os
import uuid

import ai_larp as L
import manifest as M
import paths


def _row(recipe, note, index, output, batch):
    label = 'Split screen + tutorial' if recipe['subformat'] == 'tutorial' else 'Split screen'
    if recipe.get('captions'):
        label += ' + captions'
    tutorial = recipe.get('tutorial') or {}
    return M.blank_row(
        video_id='final_%04d' % index, file=os.path.basename(output), format=L.FORMAT,
        source=recipe['original']['name'], scene=os.path.splitext(recipe['original']['name'])[0],
        tutorial=tutorial.get('name', ''), tutorial_library=tutorial.get('library', ''),
        batch=batch,
        recipe='AI LARP | %s | %s + %s%s' % (
            label, recipe['original']['name'], recipe['ai']['name'],
            ' + ' + tutorial['name'] if tutorial else ''),
        reaction_recipe=json.dumps(dict(L.saved_recipe(recipe), render=note), sort_keys=True))


def build_batch(counts):
    import catalog as CP
    if ('openart' != 'openart' or '' == '__general__' or
            paths.product() != 'director' or
            L.FORMAT not in CP.formats(paths.product())):
        print('FAIL AI LARP is available only to enabled OpenArt Director content.', flush=True)
        return 1
    try:
        from storage_guard import require_space
        outdir = paths.output('ai_larp')
        require_space(outdir)
        recipes = []
        for subformat in L.SUBFORMATS:
            recipes.extend(L.select(subformat, counts.get(subformat, 0), planned=recipes))
        import ai_larp_music as MUSIC
        recipes = MUSIC.assign(recipes, M.read_rows())
    except (OSError, ValueError, RuntimeError) as error:
        print('FAIL ' + str(error)[-600:], flush=True)
        return 1
    os.makedirs(outdir, exist_ok=True)
    batch = datetime.datetime.now().strftime('%m%d-%H%M')
    made = 0
    for recipe in recipes:
        output = None
        temporary = os.path.join(outdir, '.ai-larp-' + uuid.uuid4().hex + '.mp4')
        rendered = False
        try:
            import ai_larp_render as R
            L.validate_current(recipe)
            index, output = M.claim_id(outdir)
            note = R.build_one(recipe, temporary)
            if not os.path.isfile(temporary) or not os.path.getsize(temporary):
                raise RuntimeError('AI LARP rendering produced no video.')
            rendered = True
            row = _row(recipe, note, index, output, batch)
            with M.locked():
                L.validate_current(recipe, M.read_rows())
                os.replace(temporary, output)
                try:
                    M.append_row(row)
                except BaseException:
                    os.replace(output, temporary)
                    raise
            made += 1
            print('ok final_%04d | %.2fs' % (index, note['duration']), flush=True)
        except (Exception, SystemExit) as error:
            print('FAIL ' + str(error)[-600:], flush=True)
        finally:
            if output:
                M.drop_claim(output)
            if os.path.exists(temporary):
                if rendered:
                    recovery = os.path.join(paths.WORK, 'ai-larp-recovery')
                    os.makedirs(recovery, exist_ok=True)
                    os.replace(temporary, os.path.join(recovery, os.path.basename(temporary)))
                else:
                    os.unlink(temporary)
    asked = sum(counts.values())
    print('made %d of %d requested (batch %s)' % (made, asked, batch), flush=True)
    return 0 if made == asked else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', type=int, default=0)
    parser.add_argument('--tutorial', type=int, default=0)
    args = parser.parse_args()
    if args.split < 0 or args.tutorial < 0 or not 1 <= args.split + args.tutorial <= 500:
        parser.error('Choose between 1 and 500 AI LARP videos.')
    return build_batch({'split': args.split, 'tutorial': args.tutorial})


if __name__ == '__main__':
    raise SystemExit(main())
