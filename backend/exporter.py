import json
import subprocess
import zipfile
import re
from pathlib import Path
import imageio_ffmpeg
from . import store, timing, director, h3, script_workflows


def run(args):
    result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',*args],capture_output=True,timeout=1800)
    if result.returncode:
        raise ValueError(result.stderr.decode('utf-8',errors='replace')[-2000:])


def has_audio(source):
    result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-i',str(source)],capture_output=True,timeout=30)
    return bool(re.search(r'Stream.*Audio:',result.stderr.decode('utf-8',errors='replace')))


def h3_delivery(media,duration,preserve_generated=False):
    reader=imageio_ffmpeg.read_frames(str(store.media_path(media)))
    metadata=next(reader);reader.close()
    source_seconds=metadata['duration']
    if preserve_generated:
        return media,{'raw_duration':source_seconds,'observed_duration':source_seconds,'planned_duration':duration,'delivery_duration':source_seconds,'timing_adjustment':'preserve_generated_audio_video'}
    # 30s is the node limit: its nearest temporal grid is 719 instead of 720
    # frames. One final-frame hold handles this single-frame quantization only.
    if source_seconds+1/24+0.01<duration:raise ValueError('H3 输出短于计划时长，请重新生成；不会拉慢动作补足')
    name=store.uid()+'.mp4'
    run(['-i',str(store.media_path(media)),'-t',str(duration),'-map','0:v','-map','0:a?','-vf',f'tpad=stop_mode=clone:stop_duration={1/24}','-af','apad','-c:v','libx264','-crf','16','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(store.media_path(name))])
    return name,{'source_media':media,'raw_duration':source_seconds,'delivery_duration':duration,'timing_adjustment':'normal_speed_trim_or_one_frame_rounding'}


def export_prompts(project):
    if not project.get('shots'):
        raise ValueError('项目还没有分镜')
    director.validate_project_shots(project)
    lines=[]
    for i,shot in enumerate(project['shots']):
        lines.append(f"## 镜头 {i+1}\n\n"+timing.render(shot))
    name=store.uid()+'.md'
    store.media_path(name).write_text('# '+project['name']+'\n\n'+'\n\n'.join(lines),encoding='utf-8')
    return name


def export_h3(project,shot_id=None):
    package=h3.package(project,shot_id)
    if not package:raise ValueError('请先转写 H3 提示词')
    if not h3.is_current(project,package,shot_id):raise ValueError('H3 提示词已过期，请重新转写')
    h3.groups(h3.scope(project,shot_id))
    name=store.uid()+'.md'
    store.media_path(name).write_text(h3.markdown(package),encoding='utf-8')
    return name


def archive(project):
    name=store.uid()+'.zip'
    with zipfile.ZipFile(store.media_path(name),'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('project.json',json.dumps(project,ensure_ascii=False,indent=2))
        if script_workflows.enabled(project):
            z.writestr('Final_Video_Spec.md',script_workflows.markdown(project))
            plan=project.get('documents',{}).get('script_workflow_plan')
            if plan and plan.get('source_hash')==script_workflows.plan_hash(project,project['documents'].get('script','')):z.writestr('Script_Workflow_Plan.json',json.dumps(plan,ensure_ascii=False,indent=2))
        media=set(m['media'] for m in project.get('media',[]))
        media.update(s['media'] for s in project.get('medical_director',{}).get('sources',[]))
        for result in project.get('media',[]):
            if result.get('source_media'):media.add(result['source_media'])
            snapshot=result.get('workflow_snapshot')
            if snapshot:
                media.add(snapshot)
                path=store.media_path(snapshot)
                if path.exists():
                    bound=json.loads(path.read_text(encoding='utf-8'))
                    media.update(r['media'] for r in bound.get('references',[]))
        for asset in project.get('assets',[]):
            media.update(r['media'] for r in asset.get('references',[]))
            media.update(r['media'] for r in asset.get('previews',[]))
        media.update(c['media'] for c in project.get('timeline',[]))
        for item in sorted(media):
            path=store.media_path(item)
            if path.exists():
                z.write(path,'media/'+path.name)
    return name


def edl(project):
    def tc(seconds):
        frames=round(seconds*24)
        return f'{frames//86400:02}:{frames//1440%60:02}:{frames//24%60:02}:{frames%24:02}'
    lines=['TITLE: '+project['name'],'FCM: NON-DROP FRAME']
    cursor=0
    for i,clip in enumerate(c for c in project.get('timeline',[]) if c['kind']!='audio'):
        end=cursor+clip['duration']
        lines += [f'{i+1:03} AX       V     C        {tc(clip.get("in",0))} {tc(clip.get("in",0)+clip["duration"])} {tc(cursor)} {tc(end)}',f'* FROM CLIP NAME: {clip["media"]}']
        cursor=end
    name=store.uid()+'.edl'
    store.media_path(name).write_text('\n'.join(lines),encoding='utf-8')
    return name


def movie(project,task_id):
    clips=project.get('timeline',[])
    visuals=[c for c in clips if c['kind'] in ('video','image')]
    if not visuals:
        raise ValueError('请先向时间线加入视频或图片')
    work=store.DATA/'renders'/task_id
    work.mkdir(parents=True,exist_ok=True)
    portrait=project.get('parameters',{}).get('画幅比例','').startswith('9:16')
    width,height=(720,1280) if portrait else (1280,720)
    durations=[]
    parts=[]
    for i,clip in enumerate(visuals):
        duration=timing.number(clip['duration'])
        if duration<=0 or duration>600:
            raise ValueError('片段时长必须在0–600秒内')
        source=store.media_path(clip['media'])
        args=['-loop','1'] if clip['kind']=='image' else ['-ss',str(clip.get('in',0))]
        out=work/f'{i}.mp4'
        # Padding repeats the final frame; playback rate is never changed.
        inputs=[*args,'-i',str(source)]
        audio_stream='0:a'
        if clip['kind']=='image' or not has_audio(source):
            inputs += ['-f','lavfi','-i','anullsrc=channel_layout=stereo:sample_rate=48000']
            audio_stream='1:a'
        run([*inputs,'-t',str(duration),'-map','0:v','-map',audio_stream,'-af',f'apad,volume={float(clip.get("volume",1))}','-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=24,tpad=stop_mode=clone:stop_duration={duration}','-c:v','libx264','-c:a','aac','-ar','48000','-ac','2','-pix_fmt','yuv420p',str(out)])
        parts.append(out);durations.append(duration)
    listing=work/'concat.txt'
    listing.write_text('\n'.join("file '"+str(p).replace('\\','/').replace("'","'\\''")+"'" for p in parts),encoding='utf-8')
    joined=work/'joined.mp4'
    run(['-f','concat','-safe','0','-i',str(listing),'-c','copy',str(joined)])
    total=sum(durations)
    args=['-i',str(joined)]
    filters=[]; labels=['[base]']
    audio=[c for c in clips if c['kind']=='audio']
    if audio:
        filters.append('[0:a]anull[base]')
    for i,clip in enumerate(audio):
        args += ['-ss',str(clip.get('in',0)),'-i',str(store.media_path(clip['media']))]
        label=f'a{i}'
        filters.append(f'[{i+1}:a]atrim=duration={float(clip["duration"])},asetpts=PTS-STARTPTS,volume={float(clip.get("volume",1))},adelay={round(float(clip.get("start",0))*1000)}:all=1[{label}]')
        labels.append('['+label+']')
    if audio:
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0,apad[audio]')
        args += ['-filter_complex',';'.join(filters),'-map','0:v','-map','[audio]','-c:a','aac']
    else:
        args += ['-map','0:v','-map','0:a','-c:a','aac']
    captions=project.get('captions',[])
    if captions:
        srt=work/'captions.srt'
        def stamp(n):
            ms=round(float(n)*1000)
            return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
        srt.write_text('\n\n'.join(f'{i+1}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(captions)),encoding='utf-8')
        args += ['-vf',"subtitles='"+str(srt).replace('\\','/').replace(':','\\:').replace("'","\\'")+"'"]
    name=store.uid()+'.mp4'
    run([*args,'-t',str(total),'-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(store.media_path(name))])
    return name


def animatic(project,task_id):
    import copy
    draft=copy.deepcopy(project);draft['timeline']=[];cursor=0
    for shot in draft.get('shots',[]):
        duration=float(shot['duration']);image=shot.get('first_frame') or shot.get('adopted_keyframe') or shot.get('adopted_tailframe')
        if not image or not store.media_path(image).is_file():
            from PIL import Image,ImageDraw
            name='animatic-placeholder-'+shot['id']+'.png';image=name
            canvas=Image.new('RGB',(1280,720),'#20252e');draw=ImageDraw.Draw(canvas);draw.text((48,330),'SHOT '+str(len(draft['timeline'])+1)+' - NO ADOPTED FRAME',fill='white');canvas.save(store.media_path(name))
        draft['timeline'].append({'id':store.uid(),'media':image,'kind':'image','duration':duration,'in':0,'volume':1})
        audio=shot.get('speech_track',{}).get('media')
        if audio and store.media_path(audio).is_file():draft['timeline'].append({'id':store.uid(),'media':audio,'kind':'audio','start':cursor,'in':0,'duration':duration,'volume':1})
        cursor+=duration
    draft['captions']=[]
    if not draft['timeline']:raise ValueError('请先建立分镜')
    return movie(draft,task_id)
