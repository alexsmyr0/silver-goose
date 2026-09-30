"""Build starting scene, captioned tutorial and automatically captioned talking ending."""


import argparse
import datetime
import json
import os
import uuid

import manifest as M
import paths
import tutorial_story as TS


def build_one(recipe, out, cache=None, w=1080, h=1920):
    # Import the media stack only for a render, never for capacity or asset requests.
    import tutorial_story_render
    return tutorial_story_render.build_one(recipe, out, cache=cache, w=w, h=h)


def _row(recipe, note, index, output, batch):
    variation = recipe['variation']
    return M.blank_row(
        video_id='final_%04d' % index, file=os.path.basename(output), format=TS.FORMAT,
        source=recipe['start']['name'], scene=os.path.splitext(recipe['start']['name'])[0],
        tutorial=recipe['tutorial']['name'], tutorial_library=recipe['tutorial']['library'],
        speaking=recipe['ending']['name'], batch=batch,
        song=(recipe.get('music') or {}).get('name', ''),
        hook_len='%.3f' % (note['start_frames'] / TS.FPS),
        cut_at='%.3f' % (note['start_frames'] / TS.FPS),
        frame_mark=variation['mark'], look=variation['look'], head_speed=variation['speed'],
        recipe='Bottle spin | %s | %s | ending: %s' % (
            recipe['start']['name'], recipe['tutorial']['name'], recipe['ending']['name']),
        reaction_recipe=json.dumps(recipe, sort_keys=True))


def build_batch(count):
    import catalog as CP
    if ('' == '__general__'
            or TS.FORMAT not in CP.formats(paths.product())):
        print('FAIL Bottle spin is not enabled for this content type.', flush=True)
        return 1
    try:
        from storage_guard import require_space
        outdir = paths.output('tutorial_story')
        require_space(outdir)
        recipes = TS.select(count)
        if not recipes:
            print('FAIL ' + TS.capacity()['reason'], flush=True)
            return 1
    except (OSError, ValueError, RuntimeError) as error:
        print('FAIL ' + str(error)[-600:], flush=True)
        return 1
    os.makedirs(outdir, exist_ok=True)
    batch = datetime.datetime.now().strftime('%m%d-%H%M')
    made = 0
    for recipe in recipes:
        output = None
        temporary = os.path.join(outdir, '.tutorial-story-' + uuid.uuid4().hex + '.mp4')
        completed = False
        try:
            TS.validate_current(recipe)
            index, output = M.claim_id(outdir)
            note = build_one(recipe, temporary)
            if not os.path.isfile(temporary) or not os.path.getsize(temporary):
                raise RuntimeError('The Bottle spin render did not produce a video.')
            completed = True
            recipe.update(note)
            recipe['output_sha256'] = TS.fingerprint(temporary)
            row = _row(recipe, note, index, output, batch)
            # Rendering can overlap a second process. Recheck the shared ledger under its
            # existing lock, so only the first successful use of this ending can publish.
            with M.locked():
                TS.validate_current(recipe, M.read_rows())
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
                if completed:
                    # Preserve a completed render that could not be recorded, outside Ready.
                    recovery = os.path.join(paths.WORK, 'tutorial-story-recovery')
                    os.makedirs(recovery, exist_ok=True)
                    os.replace(temporary, os.path.join(recovery, os.path.basename(temporary)))
                else:
                    os.unlink(temporary)
    print('made %d of %d requested (batch %s)' % (made, count, batch), flush=True)
    return 0 if made == count else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--make', type=int, default=1, help='Number of videos to build')
    args = parser.parse_args()
    if not 1 <= args.make <= 500:
        parser.error('Choose between 1 and 500 videos.')
    return build_batch(args.make)


if __name__ == '__main__':
    raise SystemExit(main())
