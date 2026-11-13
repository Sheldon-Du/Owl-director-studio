"""An English-only prose editing boundary; timing and dialogue stay in code."""
import copy,re,collections

PROTECTED=re.compile(r'<d>.*?</d>|<(?:Subject|Picture|Video|Audio) \d+>|\(S\d+(?:,S\d+)*\)|"[^"\n]*[\u3400-\u9fff][^"\n]*"|\d+(?:\.\d+)?',re.S)
REFERENCE=re.compile(r'<(?:Subject|Picture|Video|Audio) \d+>')
SPOKEN=re.compile(r'<d>\[([^]]+)\]\s*(.*?)</d>',re.S)

def canonical_visual(step,value):
    """Remove only exact, already-approved dialogue repetitions, reject new words."""
    out=copy.deepcopy(value)
    for clip,written in zip(step['clips'],out.get('shots',[])):
        approved={str(row['text']).strip() for row in clip.get('speech_timeline',[])}
        approved.update(str(row.get('dialogue','')).strip() for row in clip['actions'] if row.get('dialogue'))
        def clean(text):
            for match in SPOKEN.finditer(text):
                if match[2].strip() not in approved:raise ValueError('H3转写包含未审定或改写的对白，拒绝新增台词')
            return SPOKEN.sub('',text).strip()
        written['description']=clean(str(written.get('description','')))
        for source,action in zip(clip['actions'],written.get('actions',[])):
            if not step.get('audio_binding'):
                allowed=str(source.get('dialogue','')).strip()
                for match in SPOKEN.finditer(str(action.get('text',''))):
                    if match[2].strip()!=allowed:raise ValueError('H3转写把对白放入了错误的动作段')
            action['text']=clean(str(action.get('text','')))
    return out

def paths(value):
    result=[]
    for key in ('subject_definitions','summary','retention_analysis','overall_soundscape','non_diegetic_music'):
        if isinstance(value.get(key),str):result.append((key,))
    for i,shot in enumerate(value['shots']):
        result.append(('shots',i,'description'))
        result.extend(('shots',i,'actions',j,'text') for j,_ in enumerate(shot['actions']))
    return result

def at(value,path):
    for key in path:value=value[key]
    return value

def contract(value,full_count):
    fields=[];private={};total=sum(len(at(value,path)) for path in paths(value))
    fixed=max(0,full_count-total)
    for i,path in enumerate(paths(value)):
        text=at(value,path);tokens={};reverse={}
        def mask(match):
            literal=match[0]
            if REFERENCE.fullmatch(literal):return literal
            if literal not in reverse:
                token=f'__LOCK_{i}_{len(tokens)}__';tokens[token]=literal;reverse[literal]=token
            return reverse[literal]
        masked=PROTECTED.sub(mask,text);identity=f'f{i}'
        original_counts=collections.Counter(re.findall(r'__LOCK_\d+_\d+__',masked))
        literal_counts={token:count for token,count in original_counts.items() if tokens[token].startswith('<d>') or tokens[token].startswith('"')}
        required_refs=sorted(set(REFERENCE.findall(text)))
        minimum=sum(len(literal)*literal_counts.get(token,1)+1 for token,literal in tokens.items())+sum(len(label)+1 for label in required_refs)+40
        fields.append({'id':identity,'text':masked,'minimum_characters':minimum})
        private[identity]={'path':path,'tokens':tokens,'original':masked,'literal_counts':literal_counts,'references':required_refs,'weight':max(1,len(PROTECTED.sub('',text))),'minimum':minimum}
    # References identify assets, not immutable prose tokens. Allow valid labels
    # to replace names while retaining every reference already in the field.
    all_refs=set(REFERENCE.findall(str(value.get('subject_definitions',''))))
    all_refs.update(label for item in private.values() for label in item['references'])
    for field in fields:
        item=private[field['id']];path=item['path']
        allowed=set(REFERENCE.findall(str(value['shots'][path[1]]))) if path[0]=='shots' else all_refs
        item['allowed_references']=sorted(allowed)
        field['allowed_references']=item['allowed_references']
    mandatory=sum(r['minimum_characters'] for r in fields)
    if fixed+mandatory>5900:raise ValueError('固定时间、对白及必需引用已占满H3字符空间，请拆分分组；不会删除动作或对白')
    spare=max(0,5600-fixed-mandatory);weight=sum(v['weight'] for v in private.values())
    for field in fields:
        source=private[field['id']];quota=source['minimum']+int(spare*source['weight']/max(1,weight));source['quota']=quota
        prose=max(0,quota-source['minimum']+40)
        source_path=source['path']
        role='action_change' if 'actions' in source_path else 'shot_setup' if source_path[0]=='shots' else source_path[0]
        field.update(required_references=source['references'],role=role,target_characters=quota,maximum_expanded_characters=quota,maximum_unlocked_prose_characters=prose,target_prose_words=max(3,int(prose/7)),instruction='State only what CHANGES in this action; inherit stable identity, positions, lighting and posture from shot setup. A hold can be described in 3-8 words.' if role=='action_change' else 'Establish shared context once, using short clauses or reference mappings. Avoid narrating actions in setup or metadata.')
    return {'reference_identity_guide':next((item['original'] for item in private.values() if item['path']==('subject_definitions',)), ''),'fields':fields,'maximum_final_characters':6000,'preferred_final_characters':5600,'fixed_program_characters':fixed,'rule':'Hard field limits apply after restoring tokens. Repeated reference/number tokens may be merged within their field; retain every distinct token at least once. Quoted visible text and dialogue tokens retain exact original counts. Rewrite concise English clauses, do not merely substitute adjectives.'},private

def over_budget(response,private):
    result=[]
    for row in response.get('edits',[]):
        if row.get('id') not in private:continue
        source=private[row['id']];text=row.get('text','')
        for token,literal in source['tokens'].items():text=text.replace(token,literal)
        if len(text)>source['quota']:result.append({'id':row['id'],'actual_characters':len(text),'maximum_characters':source['quota']})
    return result


def lock_errors(response,private):
    result=[]
    for row in response.get('edits',[]) if isinstance(response,dict) else []:
        identity=row.get('id')
        if identity not in private or not isinstance(row.get('text'),str):continue
        source=private[identity];actual=collections.Counter(re.findall(r'__LOCK_\d+_\d+__',row['text']));expected=set(source['tokens'])
        original_refs=set(source.get('references',[]));actual_refs=set(REFERENCE.findall(row['text']))
        missing=sorted(expected-set(actual))+sorted(original_refs-actual_refs);extra=sorted(set(actual)-expected)+sorted(actual_refs-set(source.get('allowed_references',original_refs)))
        counts={token:{'expected':count,'actual':actual[token]} for token,count in source.get('literal_counts',{}).items() if actual[token]!=count}
        if missing or extra or counts:result.append({'id':identity,'path':'.'.join(map(str,source['path'])),'missing':missing,'unknown':extra,'wrong_counts':counts})
    return result

def apply(value,response,private):
    rows=response.get('edits') if isinstance(response,dict) else None
    if not isinstance(rows,list) or len(rows)!=len(private):raise ValueError('精简结果必须逐项保留全部字段，不能删除动作或镜头')
    out=copy.deepcopy(value);seen=set()
    for row in rows:
        identity=row.get('id');text=row.get('text')
        if identity not in private or identity in seen or not isinstance(text,str) or not text.strip():raise ValueError('精简字段编号缺失、重复或正文为空')
        seen.add(identity);source=private[identity];expected=collections.Counter(source['tokens'].keys())
        actual=collections.Counter(re.findall(r'__LOCK_\d+_\d+__',text))
        reference_set=set(REFERENCE.findall(text));required_refs=set(source.get('references',[]))
        if set(actual)!=set(expected) or (not required_refs.issubset(reference_set) or not reference_set.issubset(set(source.get('allowed_references',required_refs)))) or any(actual[token]!=count for token,count in source.get('literal_counts',{}).items()):
            detail=lock_errors({'edits':[row]},private)[0]
            raise ValueError('精简字段'+identity+'（'+detail['path']+'）固定标记不一致：缺少 '+','.join(detail['missing'])+'；未知 '+','.join(detail['unknown'])+'；重复次数异常 '+','.join(detail['wrong_counts'])+'。拒绝采用')
        for token,original in source['tokens'].items():text=text.replace(token,original)
        parent=out
        for key in source['path'][:-1]:parent=parent[key]
        parent[source['path'][-1]]=text.strip()
    return out

def language_errors(value):
    from . import h3
    errors=[]
    for path in paths(value):
        try:h3.english(at(value,path),allow_shot_labels=True)
        except ValueError as error:
            if '需为英文' not in str(error):raise
            errors.append('.'.join(map(str,path)))
    return errors

SYSTEM='''You are a film-direction compression editor. Rewrite long prose into terse, production-ready English shot instructions. This is SUBSTANTIAL COMPRESSION, not a synonym swap or translation. Return exactly JSON {"edits":[{"id":"supplied id","text":"concise English direction"}]} for every supplied field.
References stay readable as <Subject N>, <Picture N>, <Video N>, <Audio N>; consult reference_identity_guide for meaning. Keep every required_references label in its original field. Additional labels may only come from that field's allowed_references; these can replace character names. Never add an asset outside this list. Never substitute a chair with a candlestick or move an identity label to a different object.
NON-NEGOTIABLE: preserve every shot and action field, the essential action/change and cause, speaker identity, scripted event, interaction, continuity and every distinct __LOCK_ token in its original field. Fixed timing and exact dialogue are already written by code, never add them. Quoted-text/dialogue lock tokens keep their original occurrence counts. Other repeated lock tokens may be consolidated.
REMOVE REDUNDANCY ACROSS FIELDS: stable face/clothes/material belong in subject_definitions once; stable framing, positions and lighting belong in the shot_setup once. Action fields only state changes. Repeated holds do not need a new portrait, lighting or camera paragraph: unchanged context persists automatically. Retain a meaningful change of camera, gaze, gesture, posture, object state or sound. Omit repeated explanations, connective narration, decorative adjectives and statements that nothing else changes. Keep narrative meaning, not every original descriptive phrase. No new events, facts or substitutions.
TARGET: use target_prose_words as the main drafting guide. Count unlocked English words, not placeholder strings. Strive for target_characters after code restores placeholders; final prompt must fit 6000 characters. Use semicolons and short verbs. Copying the input is a failed response.
EXAMPLE: input 'Wei Bai holds the bent clasped-hand salute with his torso aimed toward Wei Qiannian, lips closed and gaze settled on the seated father. Wei Qiannian remains seated with lowered eyes and right fingertips lightly resting on the chair arm. The camera and candlelit composition remain stable, with no obvious response from either man.' A shot setup establishes the salute, seats, camera and lighting. Its subsequent HOLD action becomes 'Wei Bai holds his bow; Wei Qiannian remains still.' If fingers, gaze or camera actually change in an action, state that change explicitly instead of dropping it.
All output prose is ENGLISH. Do not expand or interpret __LOCK_ tokens, add dialogue, add timestamps, write Chinese narration, commentary or Markdown.'''
