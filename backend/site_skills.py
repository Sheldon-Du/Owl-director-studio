"""Instruction-only website skills. Imported code is never executed."""
import hashlib
import io
import json
import re
import stat
import shutil
import zipfile
from pathlib import Path, PurePosixPath
import yaml
import copy
from functools import lru_cache
from . import store

BUILTINS=Path(__file__).with_name('skills_builtin')
MAX_BYTES=2*1024*1024
TEXT_SUFFIXES={'.md','.txt','.json','.yaml','.yml'}


def root():
    path=store.DATA/'skills';path.mkdir(exist_ok=True)
    return path


def parse(text):
    text=text.lstrip('\ufeff').replace('\r\n','\n')
    match=re.match(r'^---\n(.*?)\n---(?:\n|$)([\s\S]*)',text,re.S)
    if not match:raise ValueError('技能需要 YAML 头部，包含 name 和 description')
    try:meta=yaml.safe_load(match[1])
    except yaml.YAMLError:raise ValueError('技能 YAML 头部格式错误')
    if not isinstance(meta,dict):raise ValueError('技能头部需要 name 和 description')
    extra=meta.get('metadata',{}) if isinstance(meta.get('metadata',{}),dict) else {}
    usage=meta.get('usage',extra.get('usage'))
    if usage is not None and usage not in ('writing','video','image','tools'):raise ValueError('usage 必须为 writing、video、image 或 tools')
    name=meta.get('name');description=meta.get('description')
    if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}',name) or name in {'con','prn','aux','nul',*[f'com{i}' for i in range(1,10)],*[f'lpt{i}' for i in range(1,10)]}:raise ValueError('技能名称需为64字符以内的小写字母、数字、连字符，不能使用系统保留名称')
    if not isinstance(description,str) or not description.strip() or len(description)>1600:raise ValueError('技能需要不超过1600字的 description')
    if not match[2].strip():raise ValueError('技能正文不能为空')
    required=meta.get('requires_tools',extra.get('requires_tools',[]))
    if not isinstance(required,list) or len(required)>40 or any(not isinstance(v,str) or len(v)>100 for v in required):raise ValueError('requires_tools 必须是工具名称列表')
    stages=meta.get('stages',extra.get('stages',[]));tasks=meta.get('tasks',extra.get('tasks',[]));conflicts=meta.get('conflicts_with',extra.get('conflicts_with',[]))
    if not isinstance(stages,list) or any(v not in ('script_plan','script','storyboard_outline','storyboard') for v in stages):raise ValueError('技能 stages 需为支持的创作阶段列表')
    if not isinstance(tasks,list) or any(v not in ('adapt','continue','expand','condense','restructure','perspective') for v in tasks):raise ValueError('技能 tasks 需为支持的剧本任务列表')
    if not isinstance(conflicts,list) or any(not isinstance(v,str) for v in conflicts):raise ValueError('conflicts_with 需为技能ID列表')
    return {'usage':usage,'id':name,'name':str(meta.get('display_name') or extra.get('display_name') or name)[:100],'description':description,'requires_tools':required,'dependencies_declared':'requires_tools' in meta or 'requires_tools' in extra,'instructions':match[2].strip(),'text':text,
            'origin':str(meta.get('origin',''))[:200],'category':str(meta.get('category','项目创作方法'))[:80],
            'source_skill':str(meta.get('source_skill',''))[:100],'source_sha256':str(meta.get('source_sha256',''))[:64],
            'execution_gaps':[str(v)[:120] for v in meta.get('execution_gaps',[])][:20],
            'trigger_words':[str(v)[:100] for v in meta.get('trigger_words',[])][:30],
            'stages':stages,'tasks':tasks,'version':str(meta.get('version',extra.get('version','1')))[:80],
            'automatic':bool(meta.get('automatic',extra.get('automatic',False))),'conflicts_with':conflicts}


def flags():
    path=root()/'enabled.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


@lru_cache(maxsize=512)
def _entry(path,mtime,size,builtin):
    entry=Path(path);data=parse(entry.read_text(encoding='utf-8-sig'))
    return {**data,'path':entry,'builtin':builtin}


def locations():
    result={}
    for base,builtin in ((BUILTINS,True),(root(),False)):
        for entry in sorted(base.glob('*/SKILL.md')):
            try:
                stat=entry.stat();data=copy.deepcopy(_entry(str(entry),stat.st_mtime_ns,stat.st_size,builtin))
                result[data['id']]=data
            except (ValueError,OSError):continue
    return result


def catalog(tool_names):
    from . import skill_usage
    enabled=flags();items=[]
    for value in locations().values():
        missing=[t for t in value['requires_tools'] if t not in tool_names]
        items.append({k:value[k] for k in ('id','name','description','requires_tools','builtin','dependencies_declared','stages','tasks','version','automatic','conflicts_with','origin','category','source_skill','source_sha256','execution_gaps','trigger_words')} | {
            'usage':skill_usage.usage(value),
            'enabled':enabled.get(value['id'],True),'missing_tools':missing,
            'status':'缺少执行工具' if missing else ('规则可用 · 完整流程待接入' if value['execution_gaps'] else '方法已接入 · 按实际能力执行') if value['origin'] else '可使用' if value['dependencies_declared'] else '需确认工具依赖',
            'instruction_only':True,
            'digest':hashlib.sha256(value['text'].encode()).hexdigest()})
    return items


def load(skill_id, tool_names):
    if not flags().get(skill_id,True):raise ValueError('该技能已停用')
    value=locations().get(skill_id)
    if not value:raise ValueError('技能不存在')
    refs={}
    folder=value['path'].parent.resolve()
    # Only linked local textual references; never scripts, URLs or absolute paths.
    for link in re.findall(r'\]\(([^)]+)\)',value['instructions']):
        relative=PurePosixPath(link.replace('\\','/'))
        if relative.is_absolute() or '..' in relative.parts or ':' in link or relative.parts[:1]!=('references',):continue
        target=(folder/Path(*relative.parts)).resolve()
        if target.is_relative_to(folder) and target.suffix.lower() in TEXT_SUFFIXES and target.is_file():
            content=target.read_text(encoding='utf-8-sig')
            limit=64000 if value.get('origin') and link=='references/original.md' else 16000
            refs[link]=content[:limit]+(f'\n[已截取，原文{len(content)}字；请用read_skill_reference从{limit}继续读取]' if len(content)>limit else '')
        if len(refs)>=5:break
    return {'id':value['id'],'instructions':value['instructions'][:32000],'references':refs,
            'execution_gaps':value['execution_gaps'],'source_sha256':value['source_sha256'],
            'missing_tools':[t for t in value['requires_tools'] if t not in tool_names]}


def reference(skill_id, name, offset=0):
    if not flags().get(skill_id,True):raise ValueError('该技能已停用')
    item=locations().get(skill_id)
    if not item:raise ValueError('技能不存在')
    path=PurePosixPath(str(name).replace('\\','/'))
    if path.is_absolute() or '..' in path.parts or ':' in str(name) or path.parts[:1]!=('references',):raise ValueError('仅可读取技能目录中的文本参考')
    folder=item['path'].parent.resolve();target=(folder/Path(*path.parts)).resolve()
    if not target.exists() and item.get('origin'):
        # Original documents retain their relative reference names; packaged snapshots live under source/.
        target=(folder/'references/source'/Path(*path.parts)).resolve()
    if not target.is_relative_to(folder) or not target.is_file() or target.suffix.lower() not in TEXT_SUFFIXES:raise ValueError('参考文件不存在或不是文本')
    if target.stat().st_size>MAX_BYTES:raise ValueError('参考文件超过2MB')
    if type(offset) is not int or offset<0:raise ValueError('分页起点应为非负整数')
    text=target.read_text(encoding='utf-8-sig');end=offset+12000
    return {'skill_id':skill_id,'name':str(path),'text':text[offset:end],'offset':offset,'total':len(text),'next_offset':end if end<len(text) else None,'digest':hashlib.sha256(text.encode()).hexdigest()}


def enable(skill_id, enabled):
    if skill_id not in locations():raise ValueError('技能不存在')
    with store.LOCK:
        values=flags();values[skill_id]=bool(enabled)
        tmp=root()/'enabled.tmp';tmp.write_text(json.dumps(values),encoding='utf-8');tmp.replace(root()/'enabled.json')


def install(files):
    if len(files)>80 or sum(len(v) for v in files.values())>MAX_BYTES:raise ValueError('技能包超过80个文件或2MB')
    entries=[p for p in files if PurePosixPath(p).name=='SKILL.md']
    if len(entries)!=1:raise ValueError('请导入只包含一个 SKILL.md 的技能包')
    source=PurePosixPath(entries[0]);prefix=source.parent
    try:data=parse(files[str(source)].decode('utf-8-sig'))
    except UnicodeDecodeError:raise ValueError('SKILL.md 需要 UTF-8 编码')
    if not data.get('usage'):raise ValueError('新增技能必须声明 usage：writing（剧本）、video（视频提示词）、image（图片资产）；tools 不在创作界面展示')
    if data['id'] in locations():raise ValueError('同名技能已经存在，请修改技能 name 后再导入')
    accepted={'SKILL.md':data['text'].encode('utf-8')};ignored=[]
    for name,content in files.items():
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or ':' in name:raise ValueError('技能包含非法文件路径')
        try:relative=path.relative_to(prefix)
        except ValueError:ignored.append(name);continue
        if relative==PurePosixPath('SKILL.md'):continue
        if relative.parts[:1]==('references',) and relative.suffix.lower() in TEXT_SUFFIXES:
            try:content.decode('utf-8-sig')
            except UnicodeDecodeError:raise ValueError('技能参考文件需要 UTF-8 编码')
            accepted[str(relative)]=content
        else:ignored.append(name)
    with store.LOCK:
        destination=root()/data['id']
        if data['id'] in locations() or destination.exists():raise ValueError('同名技能已经存在')
        staging=root()/('.install-'+store.uid());staging.mkdir()
        try:
            for name,content in accepted.items():
                target=staging/Path(*PurePosixPath(name).parts);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
            staging.rename(destination)
        except Exception:
            checked=staging.resolve()
            if checked.is_relative_to(root().resolve()) and checked.name.startswith('.install-') and checked.is_dir():shutil.rmtree(checked)
            raise ValueError('技能文件写入失败，未安装；请检查文件名与目录权限')
    return {'id':data['id'],'name':data['name'],'ignored_files':ignored,'message':'已安装到导演工坊。脚本和非文本附件不执行。'}


def upload(filename, content):
    if len(content)>MAX_BYTES:raise ValueError('技能文件不能超过2MB')
    if str(filename).lower().endswith('.md'):return install({'SKILL.md':content})
    if not str(filename).lower().endswith('.zip'):raise ValueError('请上传 SKILL.md 或 ZIP 技能包')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as bundle:
            entries=[v for v in bundle.infolist() if not v.is_dir()]
            if len(entries)>80 or sum(v.file_size for v in entries)>MAX_BYTES:raise ValueError('技能解压后超过80个文件或2MB')
            files={}
            for entry in entries:
                mode=entry.external_attr>>16
                if stat.S_ISLNK(mode):raise ValueError('技能包不能包含符号链接')
                name=entry.filename.replace('\\','/')
                path=PurePosixPath(name)
                if path.is_absolute() or '..' in path.parts or ':' in name:raise ValueError('技能包含非法文件路径')
                name=path.as_posix()
                if name.casefold() in {k.casefold() for k in files}:raise ValueError('技能包包含重复路径')
                files[name]=bundle.read(entry)
            return install(files)
    except zipfile.BadZipFile:raise ValueError('ZIP 技能包无效')


def import_path(source):
    path=Path(source).expanduser()
    if not path.is_absolute():raise ValueError('请输入本机技能目录的完整路径')
    if path.is_symlink():raise ValueError('技能路径不能是符号链接')
    if path.is_file():
        if path.stat().st_size>MAX_BYTES:raise ValueError('技能文件不能超过2MB')
        return upload(path.name,path.read_bytes())
    if not path.is_dir() or not (path/'SKILL.md').is_file():raise ValueError('该目录没有 SKILL.md')
    files={};size=0;folder=path.resolve()
    for entry in path.rglob('*'):
        if entry.is_symlink() or not entry.resolve().is_relative_to(folder):raise ValueError('技能目录包含外部链接')
        if not entry.is_file():continue
        size+=entry.stat().st_size
        if size>MAX_BYTES or len(files)>=80:raise ValueError('技能目录超过80个文件或2MB；请只保留技能说明与参考文本')
        files[entry.relative_to(path).as_posix()]=entry.read_bytes()
    return install(files)
