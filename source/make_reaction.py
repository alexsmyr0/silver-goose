"""Hook Story: held-frame introduction, hook with silent reaction, finished demo.

Every join is counted in frames. Source audio only plays with its own segment; the small
reaction is always silent. Previews use the same renderer and never spend ledger uses.
"""
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
import time
import reaction_render_cache as FRC

import video_encode as VE
import encode as E
import manifest as M
import paths
import reaction as R
import reaction_music as RM
import reaction_captions as RC
from render_support import clip_frames

FPS = 30


def frames(seconds):
    return clip_frames(seconds, FPS)


def asset_path(asset):
    # A saved recipe remains tied to its original folder when format sharing changes.
    root = (R.folder('demos', library=asset.get('library') or 'reaction')
            if asset['pool'] == 'demos' else R.folder(asset['pool']))
    wanted = os.path.join(root, os.path.basename(asset['name']))
    candidates = [wanted] + [os.path.join(root,n) for n in sorted(os.listdir(root) if os.path.isdir(root) else [])
                            if not n.startswith('.') and n.lower().endswith(R.EXTS)]
    for path in dict.fromkeys(candidates):
        if os.path.isfile(path) and R.inspect(path)['id'] == asset['id']:
            return path
    raise ValueError('This ingredient changed or was removed: ' + asset['name'])


def normalise(asset, cache, w, h):
    from media_source import ensure_sdr
    src = ensure_sdr(asset_path(asset))
    s = asset['settings']
    nf = frames(s['end']-s['start'])
    alpha = s.get('background') == 'alpha'
    identity = json.dumps([asset['id'],s['start'],s['end'],s['gain_db'],w,h,alpha,'normal-v3-complete-audio'])
    ext = '.webm' if alpha else '.mp4'
    path = os.path.join(cache, hashlib.sha256(identity.encode()).hexdigest()+ext)
    if os.path.isfile(path) and os.path.getsize(path):
        return path, nf
    tmp = path+'.'+uuid.uuid4().hex+ext
    vf = ('trim=start=%.8f:end=%.8f,setpts=PTS-STARTPTS,fps=%d,'
          'scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,'
          'setsar=1,tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame=%d,settb=1/%d,setpts=N'
          % (s['start'],s['end'],FPS,w,h,w,h,nf,FPS))
    if alpha:
        vf = 'format=rgba,'+vf.replace('pad=%d:%d:(ow-iw)/2:(oh-ih)/2'%(w,h),
                                     'pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black@0'%(w,h))
    cmd = ['ffmpeg','-v','error','-y']
    # FFmpeg's native VP9 decoder discards WebM alpha. libvpx reads the alpha plane.
    if alpha and src.lower().endswith('.webm'):cmd += ['-c:v','libvpx-vp9']
    cmd += ['-i',src]
    if asset['audio']:
        af = ('atrim=start=%.8f:end=%.8f,asetpts=PTS-STARTPTS,volume=%.6f,apad,'
              'atrim=duration=%.8f,aformat=sample_rates=%d:channel_layouts=stereo'
              % (s['start'],s['end'],10**(s['gain_db']/20),nf/FPS,E.AUDIO_RATE))
        cmd += ['-map','0:v:0','-map','0:a:0','-af',af]
    else:
        cmd += ['-f','lavfi','-i','anullsrc=r=%d:cl=stereo'%E.AUDIO_RATE,'-map','0:v:0','-map','1:a:0']
    cmd += ['-vf',vf]
    cmd += (['-c:v','libvpx-vp9','-pix_fmt','yuva420p','-b:v','0','-crf','16',
             '-deadline','good','-cpu-used','5','-row-mt','1'] if alpha else
            ['-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p'])
    cmd += (['-c:a','libopus','-b:a','192k','-ar',str(E.AUDIO_RATE)] if alpha else E.audio_args())+['-t','%.8f'%(nf/FPS)]
    if not alpha:cmd += ['-movflags','+faststart']
    cmd += [tmp]
    try:
        E.run(cmd);os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return path,nf


def person_matte(src, cache):
    helper = E.ensure_exe('reaction_cutout.swift','.reaction_cutout')
    key = hashlib.sha256((src+'person-matte-v1').encode()).hexdigest()
    dest = os.path.join(cache,key+'.mkv')
    if os.path.isfile(dest) and os.path.getsize(dest):return dest
    tmp = dest+'.'+uuid.uuid4().hex+'.mkv'
    processes=[]
    with tempfile.TemporaryFile() as errors:
        try:
            a=subprocess.Popen(['ffmpeg','-v','error','-i',src,'-vf','scale=360:640',
                                '-an','-f','rawvideo','-pix_fmt','bgra','pipe:1'],stdout=subprocess.PIPE,stderr=errors)
            processes.append(a)
            b=subprocess.Popen([helper,'360','640'],stdin=a.stdout,stdout=subprocess.PIPE,stderr=errors)
            processes.append(b);a.stdout.close()
            c=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','gray',
                                '-video_size','360x640','-framerate',str(FPS),'-i','pipe:0',
                                '-an','-c:v','ffv1',tmp],stdin=b.stdout,stderr=errors)
            processes.append(c);b.stdout.close()
            codes=[p.wait() for p in reversed(processes)]
            if any(codes):
                errors.seek(0)
                raise RuntimeError('Could not remove the background. '+errors.read().decode(errors='replace')[-450:])
            os.replace(tmp,dest)
        finally:
            for p in processes:
                if p.poll() is None:p.terminate()
            if os.path.exists(tmp):os.unlink(tmp)
    return dest


def green_key(path):
    import numpy as np
    raw = subprocess.check_output(['ffmpeg','-v','error','-i',path,'-frames:v','1',
        '-vf','scale=90:160','-an','-f','rawvideo','-pix_fmt','rgb24','pipe:1'])
    a = np.frombuffer(raw, np.uint8).reshape(160,90,3).astype(int)
    red, green, blue = a[...,0], a[...,1], a[...,2]
    mask = (green > 60) & (green > red+25) & (green > blue+25)
    if mask.mean() < .05:
        raise ValueError('No green background found. Choose Remove background or Keep background.')
    color = tuple(int(v) for v in np.median(a[mask], axis=0))
    return '0x%02x%02x%02x' % color


def build_one(recipe, out, cache=None, w=E.W, h=E.H):
    cache = cache or os.path.join(paths.WORK, 'reaction-cache')
    with FRC.session(cache):
        return _build_one(recipe, out, cache, w, h)


def _build_one(recipe, out, cache=None, w=E.W, h=E.H):
    if recipe.get('advice') or recipe.get('closing'):
        raise ValueError('This old recipe uses separate closing clips. Make a new combination with End of video.')
    cache=cache or os.path.join(paths.WORK,'reaction-cache')
    os.makedirs(cache,exist_ok=True)
    music = RM.settings(recipe['music'] if 'music' in recipe else R.read_store().get('music'))
    started = time.monotonic()
    normal={}
    prepared=set()
    for role in R.ROLES:
        if recipe.get(role):
            asset=recipe[role]
            if role=='reaction' and asset['settings'].get('background')=='alpha':
                normal[role] = FRC.foreground(asset, normal['hook'][1], cache, w, h,
                    source=asset_path, frames=frames)
                prepared.add(role)
                continue
            if role=='reaction':
                # Only normalize the portion visible over this hook. Long transparent
                # reaction takes should not fill the Air's cache for a short excerpt.
                s=dict(asset['settings'])
                s['end']=min(s['end'],s['start']+normal['hook'][1]/FPS)
                asset=dict(asset,settings=s)
            normal[role]=normalise(asset,cache,w,h)
    print('  timing: Hook Story preparation %.2fs' % (time.monotonic()-started), flush=True)
    caption_note = None
    if 'ending' in normal:
        started = time.monotonic()
        path, nf = normal['ending']
        caption_note, pngs = RC.prepare(path, cache, nf/FPS, recipe.get('captions'))
        normal['ending'] = (FRC.ending(path, nf, recipe['ending']['settings'],
                                     caption_note, pngs, cache, w, h), nf)
        print('  timing: Hook Story captions %.2fs' % (time.monotonic()-started), flush=True)
    cmd=['ffmpeg','-v','error','-y','-filter_complex_threads','4']
    index={};matte={};next_i=0
    for role,(path,nf) in normal.items():
        if role=='reaction' and recipe[role]['settings']['loop']:cmd+=['-stream_loop','-1']
        if recipe[role]['settings'].get('background')=='alpha' and path.lower().endswith('.webm'):cmd+=['-c:v','libvpx-vp9']
        cmd+=['-i',path];index[role]=next_i;next_i+=1
        if role in ('intro','reaction') and recipe[role]['settings']['background']=='person':
            mask=person_matte(path,cache)
            if role=='reaction' and recipe[role]['settings']['loop']:cmd+=['-stream_loop','-1']
            cmd+=['-i',mask];matte[role]=next_i;next_i+=1
    graph=[]
    hook_n=normal['hook'][1];demo_n=normal['demo'][1];intro_n=normal.get('intro',(None,0))[1]

    def foreground(role,length,position):
        i=index[role];s=recipe[role]['settings'];label=role+'fg'
        # WebM stores millisecond timestamps. Restore the exact frame clock before
        # overlay so shortest=1 cannot discard a rounded final frame.
        chain='[%d:v]trim=end_frame=%d,settb=1/%d,setpts=N,format=rgba'%(i,length,FPS)
        if s['background']=='green':
            color=green_key(normal[role][0])
            chain+=',format=yuva444p,chromakey=%s:0.10:0.06,format=rgba'%color
        if role in matte:
            graph.append(chain+'[%ssrc]'%role)
            graph.append('[%d:v]scale=%d:%d,trim=end_frame=%d,setpts=PTS-STARTPTS,format=gray[%smask]'%(matte[role],w,h,length,role))
            chain='[%ssrc][%smask]alphamerge'%(role,role)
        cw,ch,cx,cy,ow,oh = FRC.geometry(s,w,h)
        if role not in prepared:
            chain+=',crop=%d:%d:%d:%d,scale=%d:%d'%(cw,ch,cx,cy,ow,oh)
        graph.append(chain+'[%s]'%label)
        x = s['x']*w if position=='custom' else .05*w if position=='left' else w-ow-.05*w if position=='right' else (w-ow)/2
        y = s['y']*h
        return label,round(x),round(y)

    if intro_n:
        graph.append('[%d:v]split=2[hookstill][hookplay]'%index['hook'])
        graph.append('[hookstill]trim=end_frame=1,tpad=stop_mode=clone:stop_duration=%.8f,trim=end_frame=%d,settb=1/%d,setpts=N[held]'%(intro_n/FPS,intro_n,FPS))
        label,x,y=foreground('intro',intro_n,recipe['intro']['settings']['position'])
        graph.append('[held][%s]overlay=x=%d:y=%d:shortest=1:format=auto,format=yuv420p[iv]'%(label,x,y))
        hook_input='[hookplay]'
    else:hook_input='[%d:v]'%index['hook']
    label,x,y=foreground('reaction',hook_n,recipe['position'])
    graph.append(hook_input+'[%s]overlay=x=%d:y=%d:shortest=1:format=auto,format=yuv420p[hv]'%(label,x,y))
    video_audio=[];segments=[];cursor=0
    def segment(role, video):
        nonlocal cursor
        nf=normal[role][1]
        video_audio.extend([video,'[%d:a]'%index[role]])
        segments.append(dict(role=role,start_frame=cursor,frames=nf))
        cursor+=nf
    if intro_n:segment('intro','[iv]')
    segment('hook','[hv]')
    for role in ('bridge','demo','ending'):
        if role not in normal:continue
        s=recipe[role]['settings'];zoom=s.get('frame_scale',1)
        label='full'+role
        cw=max(2,int(w/zoom)//2*2);ch=max(2,int(h/zoom)//2*2)
        if role == 'ending':
            graph.append('[%d:v]null[%s]'%(index[role],label))
        else:
            graph.append('[%d:v]crop=%d:%d:%d:%d,scale=%d:%d,setsar=1,format=yuv420p[%s]'%(
                index[role],cw,ch,round((w-cw)*s.get('frame_x',.5)),
                round((h-ch)*s.get('frame_y',.5)),w,h,label))
        segment(role,'[%s]'%label)
    graph.append(''.join(video_audio)+'concat=n=%d:v=1:a=1[cv][ca]'%len(segments))
    graph.append('[cv]settb=1/%d,setpts=N,format=yuv420p[v]'%FPS)
    total=cursor/FPS
    if music and music['enabled']:
        cmd += ['-stream_loop','-1','-i',RM.file_path(music)]
        music_graph, music = RM.mix(music, input_index=next_i,
            hook_end=(intro_n+hook_n)/FPS, duration=total, rate=E.AUDIO_RATE)
        graph.append(music_graph)
    else:
        graph.append('[ca]aresample=%d[a]'%E.AUDIO_RATE)
    cmd+=['-filter_complex',';'.join(graph),'-map','[v]','-map','[a]',
          '-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p']
    cmd+=E.audio_args()+['-t','%.8f'%total,"-map_metadata", "-1",'-movflags','+faststart+use_metadata_tags',
          '-metadata','creation_time='+datetime.datetime.now(datetime.timezone.utc).isoformat(),out]
    VE.run(cmd, runner=E.run, label='Hook Story')
    if abs(E.duration(out)-total)>.12:
        raise RuntimeError('The output length did not match the selected clips.')
    return {'duration':total,'hook_frames':hook_n,'intro_frames':intro_n,'demo_frames':demo_n,
            'segments':segments, 'music':music, 'captions':caption_note}


def build_batch(count):
    import catalog as CP
    if 'reaction' not in CP.formats(paths.product()):
        print('FAIL Hook Story is not enabled for this content type.', flush=True)
        return 1
    recipes=R.select(count)
    outdir=paths.output('reaction');os.makedirs(outdir,exist_ok=True)
    batch=datetime.datetime.now().strftime('%m%d-%H%M')
    made=0
    for recipe in recipes:
        idx,out=M.claim_id(outdir)
        temp=os.path.join(outdir,'.reaction-'+uuid.uuid4().hex+'.mp4')
        try:
            note=build_one(recipe,temp)
            identity=R.inspect(temp)['id']
            recipe['output_sha256']=identity
            recipe.update(note)
            # Record only a completed encode. A ledger failure leaves the reservation empty
            # and the finished file in scratch for recovery, never silently in Ready.
            row=M.blank_row(video_id='final_%04d'%idx,file=os.path.basename(out),format='reaction',
                scene=os.path.splitext(recipe['hook']['name'])[0],tutorial=recipe['demo']['name'],
                tutorial_library=recipe['demo'].get('library') or 'reaction',
                source=recipe['hook']['name'],hook_len='%.3f'%(note['hook_frames']/FPS),
                cut_at='%.3f'%((note['hook_frames']+note['intro_frames'])/FPS),
                recipe='Hook Story | %s | %s | introduction: %s | reaction: %s, %s'%(
                    recipe['hook']['name'],recipe['demo']['name'],
                    recipe['intro']['name'] if recipe['intro'] else 'none',recipe['reaction']['name'],recipe['position']),
                reaction_recipe=json.dumps(recipe,sort_keys=True),batch=batch)
            if note.get('music') and note['music']['enabled']:
                row['song']=note['music']['name']
                row['music_at']='%.3f'%note['music']['video_start']
            row['reaction_intro']=recipe['intro']['name'] if recipe['intro'] else ''
            row['reaction_presenter']=recipe['reaction']['name']
            os.replace(temp,out)
            try:M.append_row(row)
            except BaseException:
                os.replace(out,temp)
                raise
            made+=1;print('ok final_%04d | %.2fs'%(idx,note['duration']),flush=True)
        except (Exception,SystemExit) as e:
            print('FAIL '+str(e)[-500:],flush=True)
            M.drop_claim(out)
        finally:
            # Preserve a completed but unrecorded encode for recovery outside Ready.
            if os.path.exists(temp):
                recovery=os.path.join(paths.WORK,'reaction-recovery');os.makedirs(recovery,exist_ok=True)
                os.replace(temp,os.path.join(recovery,os.path.basename(temp)))
    print('made %d of %d requested (batch %s)'%(made,count,batch),flush=True)
    return 0 if made==count else 1


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--make',type=int,default=1)
    ap.add_argument('--preview');a=ap.parse_args()
    if a.preview:
        with open(a.preview) as f:job=json.load(f)
        try:
            note=build_one(job['recipe'],job['out'])
            result={'ok':True,**note}
        except Exception as e:result={'ok':False,'msg':str(e)[-600:]}
        with open(job['out']+'.json','w') as f:json.dump(result,f)
        return 0 if result['ok'] else 1
    return build_batch(max(1,min(500,a.make)))


if __name__=='__main__':raise SystemExit(main())
