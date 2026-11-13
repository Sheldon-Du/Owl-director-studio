"""Render fixed modules from the current, verified action timeline."""
from pathlib import Path

def rules():return (Path(__file__).resolve().parents[1]/'rules/storyboard-standard.md').read_text(encoding='utf-8')

def render(native,actions):
    lighting=native.get('调色和打光') or '；'.join(str(native.get(k) or '未单独指定') for k in ('色彩','光影','材质','氛围'))
    video=[];speech=[];sounds=[]
    if not any(a.get('sound_layers') for a in actions):
        legacy=native.get('原生提示词底稿') or (native.get('AIGC提示词') if not native.get('标准化提示词版本') else '')
        if legacy:
            from . import timing
            video.append('镜头视觉基准（旧格式保留）：'+timing.remove_estimates(legacy))
    for action in actions:
        label=f'{float(action["start"]):.2f}s–{float(action["end"]):.2f}s'
        video.append(label+'：'+action['description'])
        for key,title in (('dialogue','对白'),('voiceover','旁白')):
            if action.get(key):speech.append(label+' '+title+'：'+action[key])
        layers=action.get('sound_layers') or {}
        sound=[label+'：']
        for key,title,default in (('environment','底层环境声','未单独指定'),('music','配乐','无新增配乐'),('physical','实体机械/碰撞声','未单独指定'),('upper','上层动态声','无额外声源'),('transition','切换与人声衔接','依本段对白/旁白，连续声场')):
            sound.append(title+'：'+str(layers.get(key) or default))
        if not layers:sound.append('原有声音设计：'+str(native.get('音效') or native.get('音频描述') or '未单独指定'))
        sounds.append('\n'.join(sound))
    return '\n\n'.join(['【调色和打光】\n'+lighting,'【视频提示词】\n'+'\n'.join(video),'【对白/旁白】\n'+('\n'.join(speech) or '无明确台词或旁白'),'【音效】\n'+'\n'.join(sounds),'【视频制作禁令】\n无水印、无未经要求的字幕或画面文字、无未经要求的配乐；保留剧本必需的已有文字及已确认人声。动作自然实时，遵守项目明确禁令。'])

def apply(native):
    actions=native.get('动作预案',[])
    if not actions:return native
    native['原生提示词底稿']=native['AIGC提示词']
    native['标准化提示词版本']=1
    native['AIGC提示词']=native['AIGC适配提示词']=render(native,actions)
    return native
