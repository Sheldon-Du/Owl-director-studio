"""Keep a character's visual identity separate from story events and other people."""
import copy
import hashlib
import json
import re
import unicodedata
from . import visual_schema as vs, script_source

FIELDS={'age':'年龄阶段','gender':'性别','appearance':'面容与体态','hair':'发色与发型','costume':'衣着与配饰','personality':'性格气质','expression':'常态神态与姿态'}
SOURCES={'explicit','suggested','user','unknown'}
HAIR={
    'red':r'红发|红色(?:的)?(?:头发|发色)|赤红.*发|red[- ]haired|(?:red|ginger|scarlet|auburn) hair',
    'black':r'黑发|黑色(?:的)?(?:头发|发色)|(?:自然)?黑色.{0,5}发|black[- ]haired|black hair',
    'blond':r'金发|金色.{0,5}发|blond(?:e)?[- ]haired|blond(?:e)? hair',
    'brown':r'棕发|棕色.{0,5}发|brown[- ]haired|brown hair',
    'white':r'白发|银发|(?:white|silver)[- ]haired|(?:white|silver) hair',
    'blue':r'蓝发|蓝色.{0,5}发|blue[- ]haired|blue hair',
}
for _color,_pattern in HAIR.items():
    _names={'red':'red|ginger|scarlet|auburn','black':'black','blond':'blond|blonde','brown':'brown','white':'white|silver','blue':'blue'}[_color]
    HAIR[_color]=_pattern+r'|\b(?:'+_names+r')(?:[- ](?:short|long|straight|curly|wavy|natural|dyed|shoulder-length|chin-length|silky|cropped|layered)){0,5}[- ]hair\b'
HAIR['red']+=r'|\bredhead\b'


def source_hash(project,asset):
    base=script_source.asset_hash(project,asset)
    return hashlib.sha256((base+':protagonist-head-to-shoes-v1').encode()).hexdigest() if asset.get('is_protagonist') else base


def design_hash(asset):
    keys=('description','age','gender','costume','personality','visual_profile','narrative_context')
    return hashlib.sha256(json.dumps({k:asset.get(k) for k in keys},sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def narrative_description(text):
    return bool(re.search(r'画外|叙述者|开场|结尾|被诊断|接受.{0,8}治疗|遭.{0,8}要挟|偷拍视频|兜风喝酒|童年.{0,8}(?:独等|等待)|剧情|情节|故事经历',str(text)))


def has_five_s(asset):
    """Only complete cards qualify for structured image-prompt preparation."""
    from .seedance_integration import FIELDS
    card=asset.get('card')
    return isinstance(card,dict) and all(isinstance(card.get(key),str) and card[key].strip() for key in FIELDS)


def requires_profile_extraction(asset):
    # A 5S card contains goal/constraints and may describe different story states.
    # The image writer isolates one appearance; the generated prompt is validated
    # separately. Legacy prose still requires the original extraction step.
    return asset.get('kind')=='character' and not has_five_s(asset) and narrative_description(asset.get('description',''))


def describe(fields):
    return '；'.join(FIELDS[k]+'：'+v['value'].strip() for k in FIELDS if (v:=fields.get(k,{})).get('value','').strip() and v.get('source')!='unknown')


def manual(asset):
    fields={k:{'value':str(asset.get(k,'')),'source':'user' if asset.get(k) else 'unknown','evidence':'','owner':asset['name']} for k in FIELDS}
    fields['appearance']={'value':asset.get('description',''),'source':'user' if asset.get('description') else 'unknown','evidence':'','owner':asset['name']}
    return {'version':1,'fields':fields,'other_age_stages':[]}


def evidence_quote(story,evidence):
    """Return the actual source span; tolerate quotation/whitespace formatting only."""
    if not evidence:return ''
    if evidence in story:return evidence
    quote=evidence.strip('“”‘’「」『』\"\'').strip()
    if quote and quote in story:return quote
    needle=''.join(unicodedata.normalize('NFKC',c) for c in quote if not c.isspace())
    if not needle:return ''
    chars=[];positions=[]
    for index,char in enumerate(story):
        if char.isspace():continue
        normalized=unicodedata.normalize('NFKC',char)
        chars.extend(normalized);positions.extend([index]*len(normalized))
    offset=''.join(chars).find(needle)
    return story[positions[offset]:positions[offset+len(needle)-1]+1] if offset>=0 else ''


def preserve_user_fields(profile,asset):
    """Overlay hand-edited identity before validating new AI suggestions."""
    if not isinstance(profile,dict):return profile
    proposed=copy.deepcopy(profile)
    stored=asset.get('visual_profile') or {}
    if proposed.get('groups'):
        prior=vs.from_legacy('character',stored,asset['name'])
        if not stored and asset.get('visual_description_source')=='user' and not narrative_description(asset.get('description','')):
            prior=vs.from_legacy('character',manual(asset),asset['name'])
        for path,item in vs.flatten('character',proposed).items():
            if item.get('source')=='user':
                group,key=path.split('.');proposed['groups'][group]['fields'][key]['source']='suggested'
        for path,item in vs.flatten('character',prior).items():
            if item.get('source')=='user':
                group,key=path.split('.');proposed['groups'][group]['fields'][key]={**copy.deepcopy(item),'owner':asset['name']}
        if not stored:
            for key,path in {'age':'basic.age','gender':'basic.gender','costume':'outfit.key_items','personality':'personality.traits'}.items():
                if asset.get(key) and asset[key]!='不限':
                    group,field=path.split('.');proposed['groups'][group]['fields'][field]={'value':str(asset[key]),'source':'user','evidence':'','owner':asset['name']}
        return proposed
    if not isinstance(proposed.get('fields'),dict):return proposed
    previous=stored.get('fields',{})
    for item in proposed['fields'].values():
        if isinstance(item,dict) and item.get('source')=='user':item['source']='suggested'
    if not previous and asset.get('visual_description_source')=='user' and not narrative_description(asset.get('description','')):
        previous=manual(asset)['fields']
    for key,item in previous.items():
        if key in FIELDS and item.get('source')=='user':proposed['fields'][key]={**copy.deepcopy(item),'owner':asset['name']}
    if not asset.get('visual_profile'):
        for key in ('age','gender','costume','personality'):
            if asset.get(key) and asset[key]!='不限':proposed['fields'][key]={'value':str(asset[key]),'source':'user','evidence':'','owner':asset['name']}
    return proposed


def normalize(profile,project,asset,other_assets=()):
    if not isinstance(profile,dict) or not (isinstance(profile.get('fields'),dict) or isinstance(profile.get('groups'),dict)):raise ValueError('角色造型档案缺少结构化字段')
    grouped=isinstance(profile.get('groups'),dict)
    entries=vs.flatten('character',profile) if grouped else profile['fields']
    field_labels=vs.labels('character') if grouped else FIELDS
    fields={};story=script_source.asset_text(project,False);name=asset['name']
    foreign=[a['name'] for a in other_assets if a.get('kind')=='character' and a['name']!=name]
    for path in field_labels:
        key=path
        if grouped:
            key='age' if path=='basic.age' else 'gender' if path=='basic.gender' else 'personality' if path.startswith('personality.') or path=='basic.demeanor_posture' else 'expression' if path=='face.gaze' else 'hair' if path.startswith('hair.') else 'costume' if path.startswith(('outfit.','accessories.')) else 'appearance'
        item=entries.get(path,{})
        if not isinstance(item,dict):raise ValueError('角色造型字段必须标明来源：'+key)
        value=str(item.get('value','')).strip();source=item.get('source','unknown');evidence=str(item.get('evidence','')).strip();owner=item.get('owner',name);source_note=str(item.get('source_note','')).strip()
        if value.casefold() in ('unknown','未指定','未知','不详','unspecified','null','none','n/a'):value='';source='unknown';evidence=''
        if source not in SOURCES:raise ValueError('角色造型来源无效：'+key)
        if value and owner!=name:raise ValueError('其他人物的特征不能归给 '+name+'：'+key)
        if value and source=='unknown':value=''
        if grouped and path.startswith('marks.') and source=='suggested':source='unknown';value=''
        if source=='explicit' and value:
            evidence=evidence_quote(story,evidence)
            if not evidence:
                if key in ('personality','expression'):
                    # Inferred temperament/expression is valid design input,
                    # but an unverified quote must never look like a story fact.
                    source='suggested';source_note='原句引用未核实，暂按设计建议保留。'
                else:raise ValueError('角色造型的原文依据不存在：'+field_labels[path])
            if key in ('appearance','hair','costume','expression') and any(n in evidence for n in foreign):
                # A whole paragraph may introduce other actors before describing
                # this actor. Retain only an independently owned source sentence.
                sentences=re.split(r'(?<=[。！？；\n])',evidence)
                own=[q.strip() for q in sentences if name in q and not any(n in q for n in foreign) and q.strip()]
                phrases=[q.strip() for q in re.split(r'[，,、；;。\n]+',value) if q.strip()]
                owned_quote=next((q for q in own if phrases and all(v in q for v in phrases)),'')
                if owned_quote:
                    evidence=owned_quote
                else:
                    value='';source='unknown';evidence='';source_note='原引用涉及其他人物，外貌归属待核实；未采用该字段。'
        if narrative_description(value):raise ValueError('剧情经历或叙述方式不能作为角色造型：'+key)
        if key=='age' and re.search(r'童年|小时候',value) and re.search(r'高中|1[6-9]岁',value):raise ValueError('童年与高中年龄不能混在一张角色设定图中')
        if key=='hair' and value:
            # Detect the reported ownership failure even if an AI mislabeled
            # its source as a design suggestion. A foreign person's distinctive
            # hair color cannot silently become this person's visual identity.
            hair_value=value+(' hair' if re.search('[A-Za-z]',value) else '头发') if path=='hair.color' else value
            for color,pattern in HAIR.items():
                if not re.search(pattern,hair_value,re.I):continue
                if source=='user':continue
                other_has=any(re.search(pattern,a.get('name','')+' '+a.get('description',''),re.I) for a in other_assets if a.get('kind')=='character' and a.get('name')!=name)
                own_evidence=source=='explicit' and name in evidence and not any(n in evidence for n in foreign)
                if color not in ('black','brown') and other_has and not own_evidence:raise ValueError('发色可能来自另一角色；请为 '+name+' 使用独立的发型建议或仅属于本人的原文依据')
        fields[path]={'value':value,'source':source,'evidence':evidence if source=='explicit' else '','owner':name}
        if source=='suggested' and source_note:fields[path]['source_note']=source_note
        if source=='unknown' and source_note:fields[path]['source_note']=source_note
    if not any(v['value'] for v in fields.values()):raise ValueError('角色造型档案为空')
    others=profile.get('other_age_stages',[])
    if grouped:return vs.unflatten('character',fields,name,others if isinstance(others,list) else [])
    return {'version':1,'fields':fields,'other_age_stages':others if isinstance(others,list) else []}


def extract(project,asset,other_assets=None,script_text=None):
    from . import ai,asset_profiles
    others=other_assets if other_assets is not None else project.get('assets',[])
    system='''你是角色造型设计员，只输出JSON，不能用人物的故事梗概替代外貌设定。
输出 {visual_profile:{version:2,groups:{分组key:{fields:{字段key:{value,source,evidence,owner}}}},other_age_stages:[{label,age,note}]},narrative_context:string}。按feature_schema填写全部分组和子字段，不用一段总描述替代。
六类视觉特征：基础特征、面部特征、发型与发色、服饰与装束、配饰与随身物品、特殊标志。另独立填写性格与行为倾向：稳定性格、社交方式、情绪反应、行为习惯、价值观与动机；最后一项不进入外貌描述。特殊标志原文未指定时保持unknown、空值；不要默认添加伤疤、纹身、义肢、角或翅膀。
每个字段只属于 target_name，owner 必须等于 target_name。原文明确特征 source=explicit，evidence逐字引用该角色自己的短句；不能引用混有别人的外貌句。未写的脸型、发色、发型、衣着只能给独立、克制、符合年龄地域时代的造型建议，source=suggested，evidence为空；无法判断则 unknown，value为空。保留字段来源为user的已有设定。
原文仅指完成后的script剧本字段；导演建议不是剧情事实。old_description、current_visual_profile和previous可能包含AI设计建议，不能把其中的文字当作故事原句引用。标志性随身物品只记录原文明示常随的物件或用户指定物件；一次性拿起或放下的剧情道具单独归道具元素，不作为身份卡的固定配饰。
性格或常态神态若由事件、动作、对白推断，应标suggested；只有原文直接描述该性格/神态并能逐字引用时才标explicit。概括、解释、改写的句子不能作为原文引用。
禁止把另一人物的发色/服装/性别/年龄转移过来。比如“小禾与红发男孩兜风”只说明男孩红发，不能给小禾红发。校服只在原文明说角色穿着的年龄阶段采用；学生身份不等于校服是唯一衣着。不要把其他年龄阶段衣着一起叠穿。只选择主体当前年龄阶段，童年等另记other_age_stages。
appearance只写脸部和体态；hair只写自己的发型与发色；costume只写衣服、鞋与配饰；personality写稳定性格、社交气质；expression写可见的常态神态、中性姿态。经历、疾病、被害情况、对白、画外音归narrative_context，绝不转成视觉装饰、表情夸张或情节画面。造型采用普通完整衣着，非情节化、非性感化的身份设定。'''
    if asset.get('is_protagonist'):system+='\n主角需要从头到脚建立可复用造型：头发、面部、颈肩、躯干、手臂手部、上衣、下装、腿部、袜子和鞋履。缺失信息仅作符合剧本时代年龄的克制建议，标suggested，不能假冒原文。角色资产展示要求纯白背景板、完整全身含鞋，不把白背景写成角色肤色或服装。'
    payload={'is_protagonist':bool(asset.get('is_protagonist')),'target_name':asset['name'],'feature_schema':vs.SCHEMA['character'],'script':script_source.asset_text(project) if script_text is None else script_text,'user_visual_profile':asset_profiles.user_profile(asset),'other_characters':[{'name':a['name']} for a in others if a.get('kind')=='character' and a['name']!=asset['name']]}
    result=asset_profiles.request_profile(system,payload)
    try:profile=normalize(preserve_user_fields(result.get('visual_profile'),asset),project,asset,others)
    except ValueError as error:
        result=ai.ask(system+'\n上次校验失败，请逐项检查所有explicit字段：evidence必须是script中的逐字子串，不在script中的概括或造型建议改为suggested并清空引用。不要将别人的特征改标suggested后继续沿用。',json.dumps({**payload,'validation_error':str(error),'previous':result},ensure_ascii=False))
        profile=normalize(preserve_user_fields(result.get('visual_profile'),asset),project,asset,others)
    return update_fields(asset,profile,str(result.get('narrative_context') or asset.get('narrative_context') or asset.get('description','')),source_hash(project,asset))


def update_fields(asset,profile,context='',fingerprint=None):
    values={'visual_profile':profile,'description':vs.describe('character',profile) if profile.get('groups') else describe(profile['fields']),'narrative_context':context,'profile_source_hash':fingerprint,'profile_source_type':'script' if fingerprint else None,'profile_stale':False}
    for key in ('age','gender','costume','personality'):
        values[key]=profile['fields'][key]['value']
    return values


def prepare(project,asset):
    if asset['kind']!='character':return {}
    profile=asset.get('visual_profile')
    if profile and not asset.get('profile_stale') and asset.get('profile_source_type')=='script' and asset.get('profile_source_hash')==source_hash(project,asset):
        profile=normalize(profile,project,asset,project.get('assets',[]))
        return update_fields(asset,profile,asset.get('narrative_context',''),source_hash(project,asset))
    from . import ai
    if asset.get('visual_description_source')=='user' and not narrative_description(asset.get('description','')):return update_fields(asset,manual(asset),asset.get('narrative_context',''),source_hash(project,asset))
    if ai.store.settings().get('ai_url'):return extract(project,asset)
    if narrative_description(asset.get('description','')):raise ValueError('角色描述包含剧情经历。请配置文本AI重新提取造型，或手动填写该角色自己的外貌、衣着与性格')
    return update_fields(asset,manual(asset),'',source_hash(project,asset))


def image_subject(asset):
    # No story, narrative context, previous prompts, other age stages or media
    # history can enter a character's image-writing input.
    result={k:copy.deepcopy(asset[k]) for k in ('name','kind','description','age','gender','costume','model','references','is_protagonist') if k in asset}
    profile=asset.get('visual_profile') or {}
    if profile.get('groups'):
        visual_profile=copy.deepcopy(profile)
        visual_profile['groups']['personality']=copy.deepcopy(vs.blank('character',asset['name'])['groups']['personality'])
        # Dynamic behavior such as "recognizes family, becomes remorseful" is
        # performance context, not a fixed appearance in an identity image.
        result['description']=vs.describe('character',visual_profile)
        result.pop('personality',None)
        result['visual_features']=vs.image_features('character',visual_profile)
        result['visual_features'].pop('personality',None)
    elif asset.get('personality'):result['personality']=asset['personality']
    return result


def personality_notes(asset):
    """Full behavior archive for performance planning, separate from image facts."""
    profile=asset.get('visual_profile') or {}
    if profile.get('groups'):
        return {k:copy.deepcopy(v) for k,v in profile.get('groups',{}).get('personality',{}).get('fields',{}).items() if v.get('value') and v.get('source')!='unknown'}
    return {'traits':copy.deepcopy(profile.get('fields',{}).get('personality',{}))} if profile.get('fields',{}).get('personality',{}).get('value') else {}


def validate_image(parts,asset):
    text=parts['主体']+'\n'+parts['锁定·不改变'].split('CONSTRAINTS')[0]
    profile=asset.get('visual_profile',{}).get('fields',{})
    identity=' '.join(v.get('value','') for k,v in profile.items() if k in ('hair','appearance')) or asset.get('description','')
    notes=str(asset.get('prompt_notes','')).strip()
    for color,pattern in HAIR.items():
        positive=any(not re.search(r'\b(?:no|not|never|avoid)\b|禁止|不得|不要|不能',text[max(0,m.start()-25):m.start()],re.I) for m in re.finditer(pattern,text,re.I))
        note_matches=list(re.finditer(pattern,notes,re.I))
        note_allows=any(not re.search(r'\b(?:no|not|never|avoid)\b|禁止|不得|不要|不能',notes[max(0,m.start()-25):m.start()],re.I) for m in note_matches)
        if positive and note_matches and not note_allows:raise ValueError('图片提示词违背人工描述的发色限制：'+color)
        if positive and not note_allows and not re.search(pattern,identity,re.I):raise ValueError('图片提示词添加了角色造型中没有的发色：'+color)
    clauses=re.split(r'[。；;\n]+',text)
    positive=[]
    for clause in clauses:
        # "不表现剧情/画外叙述" is a restriction, not depicted story content.
        cleaned=re.sub(r'(?:(?:不得|不要|不能|不应|不)(?:包含|表现|呈现|描绘|展示|涉及|添加|出现|加入|含有|带有|使用|描写)|禁止|无)[^，,。；;\n]{0,32}(?:画外(?:音|叙述)?|叙述者|剧情|情节|故事经历)[^，,。；;\n]*','',clause)
        positive.append(cleaned)
    if narrative_description('。'.join(positive)):raise ValueError('角色设定图混入了剧情或叙述方式')
