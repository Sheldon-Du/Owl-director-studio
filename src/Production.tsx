import {productionReady} from './productionSource';
import {Sparkles} from 'lucide-react';
import {WorldPolicy} from './ScriptWorkflow';
import {ScriptTaskChoice} from './ScriptTask';
import {CreativeSkills} from './CreativeSkills';
import {AssetExploration} from './AssetExploration';

type Obj=Record<string,any>;
function SceneAssetNotes({project}:{project:Obj}){
 const omitted=project.asset_analysis?.omitted_scenes||[],archive=project.scene_asset_archive||[];
 return <>{omitted.length>0&&<details><summary>未建立独立资产的次要场景 · {omitted.length}</summary>{omitted.map((item:Obj,i:number)=><p key={i}><strong>{item.name}</strong>：{item.reason}{item.kept_existing?'（已有资料保留，可自行移除）':''}</p>)}</details>}{archive.length>0&&<details><summary>查看旧场景资料 · {archive.length} 条</summary><small className="muted">不同拍摄地点已分开，旧描述和图片保留在这里。新地点需按剧本单独提取外观。</small>{archive.map((entry:Obj,i:number)=><details key={i}><summary>{entry.asset.name}</summary><p>{entry.reason}</p><p>{entry.asset.description}</p><p>对应地点：{entry.replacement_ids.map((id:string)=>project.assets.find((a:Obj)=>a.id===id)?.name).filter(Boolean).join('、')||'未建立独立资产'}</p><div className="reference-list">{[...(entry.asset.references||[]),...(entry.asset.previews||[])].map((m:Obj,j:number)=><a key={j} href={'/media/'+encodeURIComponent(m.media)} target="_blank" rel="noreferrer"><img src={'/media/'+encodeURIComponent(m.media)} alt={entry.asset.name+' · 旧资料'}/></a>)}</div></details>)}</details>}</>;
}
export function AssetExtraction({project,busy,job,save,changed,notify}:{project:Obj;busy:boolean;job:(kind:string,target?:string,options?:Obj)=>void;save?:()=>Promise<Obj>;changed?:(p:Obj)=>void;notify?:(text:string)=>void}){
 const analysis=project.asset_analysis||{},running=['queued','running'].includes(analysis.status);
 const ready=!busy&&!running&&productionReady(project);
 return <section className="script-asset-stage"><strong>手动提取元素外观与性格</strong><p className="muted">有有效剧本使用剧本，否则从原始故事提取。先通读归集资料，元素较多时每组3个评估，最多2组同时处理；完成项逐个保存。再次提取复用缓存并补齐失败项，用户设定和图片保留。</p><div className="row wrap"><button className="primary" disabled={!ready} onClick={()=>job('script_assets')}><Sparkles size={15}/>{running?'正在提取…':analysis.status==='partial'||analysis.status==='cancelled'?'继续提取未完成元素':'提取元素外观与性格'}</button><details><summary>重新提取选项</summary><p className="muted">需要重新设计所有 AI 建议时，可跳过复用；手动设定仍保留。</p><button disabled={!ready} onClick={()=>job('script_assets',undefined,{force:true})}>全部重新提取</button></details></div>{analysis.message&&<p className="muted" aria-live="polite">{analysis.message}</p>}{analysis.total>0&&<><progress aria-label="元素提取进度" max={analysis.total} value={(analysis.completed||0)+(analysis.failed||0)}/><small>完成 {analysis.completed||0}/{analysis.total} · 复用 {analysis.reused||0} · 失败 {analysis.failed||0}</small></>}{analysis.failures?.length>0&&<details><summary>查看失败元素 · {analysis.failures.length}</summary>{analysis.failures.map((f:Obj,i:number)=><p key={i}>{f.name}：{f.error}</p>)}</details>}{save&&changed&&notify&&<AssetExploration project={project} busy={busy} job={job} save={save} changed={changed} notify={notify}/>}<SceneAssetNotes project={project}/>{!project.documents.script?.trim()&&<small className="muted">请先编写并保存剧本。</small>}</section>
}
export function StoryPolicy({project,edit}:{project:Obj;edit:(fn:(p:any)=>void)=>void}){
 const notes:Obj={faithful:'原文完整保留为正文；DirectorMaster 用于后续镜头与美术设计。',screenplay:'保留人物、情节顺序与结局，按 DirectorMaster 设定整理成分场、动作、对白和画外音，并记录原文对应段落。需要文本 AI。',creative:'AI 将故事作为参考素材，按 DirectorMaster 规则创意编排，并列出新增、删减与重排。需要文本 AI。'};
 return <div className="story-policy"><label>故事与剧本的处理方式<select value={project.story_policy||'faithful'} onChange={e=>edit(p=>{p.story_policy=e.target.value;p.script_task='auto';p.script_workflow='director';if(e.target.value!="creative"&&p.video_brief?.allow_world_change)p.video_brief.allow_world_change=false;p.script_confirmed=false;p.script_needs_rewrite=true;p.native_storyboard_current=false;p.confirmed=false})}><option value="faithful">1. 原文直用 · 保留故事原文</option><option value="screenplay">2. 忠于故事剧本化 · 按 DirectorMaster 设定编写</option><option value="creative">3. AI 编排为主 · 把输入作为参考素材</option></select></label><p className="muted">{notes[project.story_policy||'faithful']}选择后生成剧本应用。</p><ScriptTaskChoice project={project} edit={edit}/><WorldPolicy project={project} edit={edit}/><CreativeSkills project={project} edit={edit}/></div>
}
export {StoryboardProgress} from './Storyboard';
export {H3Panel} from './H3';

