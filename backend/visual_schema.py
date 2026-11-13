"""Shared asset field definitions and local adapters for earlier identity profiles."""
import copy
import json
import re
from pathlib import Path

SCHEMA=json.loads((Path(__file__).resolve().parents[1]/'asset-feature-schema.json').read_text(encoding='utf-8'))


def labels(kind):
    return {group+'.'+key:label for group,spec in SCHEMA[kind].items() for key,label in spec['fields'].items()}


def blank(kind,name):
    return {'version':2,'groups':{g:{'fields':{k:{'value':'','source':'unknown','evidence':'','owner':name} for k in spec['fields']}} for g,spec in SCHEMA[kind].items()},'other_age_stages':[]}


def flatten(kind,profile):
    groups=profile.get('groups',{})
    if not isinstance(groups,dict):raise ValueError('外观分组格式无效')
    result={}
    for group,spec in SCHEMA[kind].items():
        block=groups.get(group,{})
        if not isinstance(block,dict) or not isinstance(block.get('fields',{}),dict):raise ValueError('外观字段格式无效：'+spec['label'])
        for key in spec['fields']:result[group+'.'+key]=copy.deepcopy(block.get('fields',{}).get(key,{}))
    return result


def unflatten(kind,fields,name,others=()):
    p=blank(kind,name)
    for path,item in fields.items():
        group,key=path.split('.',1)
        p['groups'][group]['fields'][key]=copy.deepcopy(item)
    p['other_age_stages']=copy.deepcopy(list(others))
    if kind=='character':p['fields']=legacy_fields(p,name)
    return p


def from_legacy(kind,profile,name):
    if profile.get('groups'):return copy.deepcopy(profile)
    p=blank(kind,name)
    if kind!='character':return p
    old=profile.get('fields',{})
    mapping={'age':'basic.age','gender':'basic.gender','appearance':'face.shape','hair':'hair.style_length','costume':'outfit.key_items','personality':'personality.traits','expression':'basic.demeanor_posture'}
    for key,path in mapping.items():
        if key not in old:continue
        group,field=path.split('.')
        p['groups'][group]['fields'][field]=copy.deepcopy(old[key])
    hair=old.get('hair',{})
    for pattern,color in [(r'黑发|黑色.{0,6}发|black','黑色'),(r'红发|红色.{0,6}发|red|ginger','红色'),(r'棕发|棕色.{0,6}发|brown','棕色'),(r'金发|金色.{0,6}发|blond','金色'),(r'白发|银发|silver|white','银白色'),(r'蓝发|蓝色.{0,6}发|blue','蓝色')]:
        if re.search(pattern,hair.get('value',''),re.I):
            p['groups']['hair']['fields']['color']={**copy.deepcopy(hair),'value':color};break
    p['other_age_stages']=copy.deepcopy(profile.get('other_age_stages',[]))
    p['fields']=legacy_fields(p,name)
    return p


def combined(profile,paths,name):
    items=[]
    for path in paths:
        group,key=path.split('.')
        item=profile['groups'][group]['fields'][key]
        if item.get('value') and item.get('source')!='unknown':items.append((path,item))
    values=[]
    for path,item in items:
        value=item['value']
        if path=='hair.color':value+=' hair' if re.search('[A-Za-z]',value) else '头发'
        values.append(value)
    return {'value':'；'.join(values),'source':'suggested' if items else 'unknown','evidence':'','owner':name}


def legacy_fields(profile,name):
    paths=labels('character')
    p=profile['groups']
    return {'age':copy.deepcopy(p['basic']['fields']['age']),'gender':copy.deepcopy(p['basic']['fields']['gender']),
            'appearance':combined(profile,[k for k in paths if k.startswith('face.') or k in ('basic.species_identity','basic.build','basic.skin')],name),
            'hair':combined(profile,[k for k in paths if k.startswith('hair.')],name),
            'costume':combined(profile,[k for k in paths if k.startswith(('outfit.','accessories.'))],name),
            'personality':combined(profile,[k for k in paths if k.startswith('personality.') and k!='personality.values_motivation'],name),
            'expression':combined(profile,['basic.demeanor_posture','face.gaze','face.lips_expression'],name)}


def describe(kind,profile):
    sections=[]
    for group,spec in SCHEMA[kind].items():
        # Motivations remain in the independent personality archive; the image
        # identity contains only visual features and restrained temperament.
        values=[]
        for key,label in spec['fields'].items():
            if group=='personality' and key!='traits':continue
            item=profile['groups'][group]['fields'][key]
            if item.get('value') and item.get('source')!='unknown':values.append(label+'：'+item['value'])
        if values:sections.append(spec['label']+'（'+'；'.join(values)+'）')
    return '；'.join(sections)


def image_features(kind,profile):
    return {g:{k:v['value'] for k,v in group['fields'].items() if v.get('value') and v.get('source')!='unknown' and (g!='personality' or k=='traits')} for g,group in profile.get('groups',{}).items() if g in SCHEMA[kind]}
