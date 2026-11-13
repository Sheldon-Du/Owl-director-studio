"""Shared Seedance prompt contract and deterministic media-reference compilation."""
import copy, hashlib, json, re
from . import store

SECTIONS=('场景语境','活跃参考','场地映射','首帧与空间调度','格式模式','光学镜头','摄影机机位','动作时间轴','物理法则','灯光','音频','正向约束','输出设置')
LIMITS={'2.5':4500,'2.0':2300}
TAG=re.compile(r'<<<(image|video|audio)_(\d+)>>>')
CLOCK=re.compile(r'\d+(?:\.\d+)?\s*(?:s|秒)?\s*[–—~～-]\s*\d+(?:\.\d+)?\s*(?:s|秒)',re.I)
FIDELITY='保留核心人物关系、关键事实、因果、世界观和结局；允许删支线、调节奏、补充表演、空间调度及不改变事实的可见细节。不得新增重大情节、篡改对白事实、套用参考中的人物品牌事件。科普不编造引用和数据来源，未证实内容列pending_checks。'

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def rules():return (store.ROOT/'rules'/'seedance-authoring.md').read_text('utf-8')
def render(sections):return '\n\n'.join('【'+key+'】\n'+str(sections[key]).strip() for key in SECTIONS if str(sections.get(key,'')).strip())

def validate(sections,version='2.5',bindings=None):
    if not isinstance(sections,dict) or any(k not in SECTIONS or not isinstance(v,str) for k,v in sections.items()):raise ValueError('提示词段落格式无效')
    for key in ('首帧与空间调度','动作时间轴','灯光'):
        if not sections.get(key,'').strip():raise ValueError('缺少提示词段落：'+key)
    prompt=render(sections)
    if len(prompt)>LIMITS.get(version,4500):raise ValueError('Seedance '+version+' 提示词超出字符上限，请精简审美词，保留对白与控制信号')
    if CLOCK.search(prompt):raise ValueError('动作应写因果顺序，不得使用挂钟式秒段')
    allowed={b['tag'] for b in bindings or []}
    used={m.group(0) for m in TAG.finditer(prompt)}
    if used-allowed:raise ValueError('出现没有实际媒体的引用标签')
    if '<<<' in TAG.sub('',prompt) or '>>>' in TAG.sub('',prompt):raise ValueError('引用标签格式不正确')
    if '负向约束' in prompt:raise ValueError('不得添加独立负向约束块')
    if '无字幕' not in prompt:raise ValueError('提示词须内联无字幕')
    if re.search(r'(?:第\s*\d+\s*镜|场景编号|shot_id|asset_id)',prompt,re.I):raise ValueError('提示词不得泄漏内部镜号或标识')
    return prompt

def binding_hash(shot):return digest([shot.get('seedance_sections'),shot.get('seedance_references',[]),shot.get('seedance_model','2.5')])

def validate_speech(sections,lines):
    audio=sections.get('音频','');expected=[l['text'] for l in lines if l['kind']=='dialogue']
    for text in expected:
        if text not in audio:raise ValueError('音频段遗漏剧本原句对白')
    for line in lines:
        if line['kind']=='voiceover' and line['text'] in audio:raise ValueError('独立旁白不可重复在视频提示词中')
    for quoted in re.findall(r'[“「]([^”」]+)[”」]',audio):
        if quoted not in expected:raise ValueError('音频中出现原句清单之外的引号台词')
    if any(l['kind']=='voiceover' for l in lines) and '无音乐' not in render(sections):raise ValueError('独立旁白镜头须无音乐')

def bind(project,shot,rows,confirm=False):
    if not isinstance(rows,list) or len(rows)>24:raise ValueError('参考清单无效')
    pool={m['media']:m['kind'] for m in project.get('media',[])}
    for a in project.get('assets',[]):
        for r in a.get('references',[])+a.get('previews',[]):
            if r.get('media'):pool[r['media']]='image'
        if a.get('adopted'):pool[a['adopted']]='image'
        if a.get('voice',{}).get('reference_media'):pool[a['voice']['reference_media']]='audio'
    for s in project.get('shots',[]):
        for field in ('first_frame','adopted_keyframe','adopted_tailframe'):
            if s.get(field):pool[s[field]]='image'
        for field in ('frames','keyframes','tailframes','outputs'):
            for r in s.get(field,[]):
                if r.get('media'):pool[r['media']]='video' if field=='outputs' else 'image'
    counts={'image':0,'video':0,'audio':0};out=[];seen=set()
    for r in rows:
        name=r.get('media');kind=pool.get(name);anchor=str(r.get('anchor','')).strip()
        if kind not in counts or not store.media_path(name).is_file():raise ValueError('只能引用本项目存在的媒体')
        if name in seen:raise ValueError('同一媒体不能重复绑定')
        if not anchor:raise ValueError('请填写每项参考的身份/内容锚点')
        counts[kind]+=1;seen.add(name)
        out.append({'media':name,'kind':kind,'anchor':anchor,'tag':f'<<<{kind}_{counts[kind]}>>>'})
    sections=copy.deepcopy(shot.get('seedance_sections') or {'首帧与空间调度':shot.get('description',''),'动作时间轴':shot.get('prompt',''),'灯光':'沿用当前画面的光线方向','正向约束':'无字幕'})
    # Rebuild all tags from the current manifest, never retain stale numbering.
    for k in sections:sections[k]=TAG.sub('',sections[k]).strip()
    sections['活跃参考']='\n'.join(r['tag']+' '+r['anchor'] for r in out)
    prompt=validate(sections,shot.get('seedance_model','2.5'),out)
    if 'sound_script' in shot:validate_speech(sections,shot['sound_script'].get('lines',[]))
    if shot.get('prompt') and shot['prompt']!=prompt:shot.setdefault('seedance_history',[]).append({'prompt':shot['prompt'],'sections':shot.get('seedance_sections'),'created':__import__('time').time()})
    shot.update(seedance_sections=sections,seedance_references=out,prompt=prompt)
    shot.setdefault('native',{})['AIGC提示词']=prompt
    shot['seedance_reference_confirmation']=binding_hash(shot) if confirm else None
    return shot
