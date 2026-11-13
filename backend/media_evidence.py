"""Build local timestamped video evidence. Does not perform semantic analysis."""
import hashlib,io,json,math,subprocess,time
from PIL import Image,ImageDraw
import imageio_ffmpeg
from . import store

def extract(project,media_id,count=12):
    from .agent import inspect
    if type(count) is not int or not 4<=count<=24:raise ValueError('关键帧数量应为4–24张')
    item=next((m for m in project.get('media',[]) if m['id']==media_id),None)
    if not item or item.get('kind')!='video':raise ValueError('请先上传并选择当前项目的视频')
    path=store.media_path(item['media']);info=inspect(project,media_id)
    timestamps=[round(info['duration']*i/count,3) for i in range(count)]
    stat=path.stat();signature=hashlib.sha256(json.dumps([item['media'],stat.st_size,stat.st_mtime_ns,timestamps]).encode()).hexdigest()
    cached=next((m for m in project['media'] if m.get('evidence_hash')==signature and store.media_path(m['media']).is_file()),None)
    if cached:return cached
    cols=4;rows=math.ceil(count/cols);cell=(320,210)
    sheet=Image.new('RGB',(cols*cell[0],rows*cell[1]),'#171b21');draw=ImageDraw.Draw(sheet)
    started=time.monotonic()
    for i,stamp in enumerate(timestamps):
        if time.monotonic()-started>55:raise ValueError('关键帧提取超过55秒，请减少帧数重试；未保存不完整拼图')
        result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-ss',str(stamp),'-i',str(path),'-frames:v','1','-vf','scale=320:180:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','png','pipe:1'],capture_output=True,timeout=15)
        if result.returncode or not result.stdout:raise ValueError('无法提取第'+str(i+1)+'张关键帧，请检查视频编码或减少帧数')
        with Image.open(io.BytesIO(result.stdout)) as image:
            x=(i%cols)*cell[0];y=(i//cols)*cell[1];sheet.paste(image.convert('RGB'),(x+(cell[0]-image.width)//2,y+(180-image.height)//2))
            draw.text((x+10,y+187),f'{i+1:02d}  {stamp:.3f}s',fill='white')
    name=store.uid()+'.jpg';sheet.save(store.media_path(name),quality=90)
    value={'id':store.uid(),'media':name,'kind':'image','name':'关键帧证据 · '+item.get('name',item['media']),'derived_evidence':True,'source_media_id':media_id,'evidence_hash':signature,'sample_times':timestamps,'sample_count':count,'content_analyzed':False,'created':time.time()}
    live=store.get_project(project['id'])
    if not any(m.get('id')==media_id and m.get('media')==item['media'] for m in live['media']):
        store.media_path(name).unlink(missing_ok=True);raise store.Conflict('提取期间源素材已移除，未回填')
    def apply(current):
        if not any(m.get('id')==media_id and m.get('media')==item['media'] for m in current['media']):raise store.Conflict('源素材已移除，未回填')
        current['media'].append(value)
    try:store.mutate(project['id'],apply)
    except Exception:store.media_path(name).unlink(missing_ok=True);raise
    return value

def install_routes(app):
    @app.post('/api/projects/{pid}/media-evidence')
    def create_evidence(pid:str,body:dict):
        p=store.get_project(pid)
        if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请保存后重试')
        evidence=extract(p,body.get('media_id'),body.get('count',12))
        return {'evidence':evidence,'project':store.get_project(pid)}
