import {WorkTag} from './Workbench';
import './task-queue.css';
import {Clock, Folder, X} from 'lucide-react';
import {useEffect,useState} from 'react';

type Row=Record<string,any>;
type Props={tasks:Row[];projects:Row[];currentProjectId?:string;names:Row;onCancel:(id:string)=>void;onParallel:(id:string)=>void;startingParallel?:string;onCancelAll:()=>void;cancellingAll?:boolean;onOpen:(id:string)=>void};
const activeStates=new Set(['running','cancelling','queued']);
const stateNames:Row={queued:'排队中',running:'正在执行',cancelling:'正在取消',completed:'完成',cancelled:'已取消',failed:'失败'};
const comfyKinds=new Set(['preview','frame','generate','audio','character_card','h3_generate','h3_upscale','keyframe','tail','music_generate','asset_upscale','character_mod']);
const group=(t:Row)=>t.phase==='ai_prepare'?'ai':t.kind==='preview'?'comfy':t.queue_group|| (t.kind==='export'?'local':comfyKinds.has(t.kind)?'comfy':'ai');
const lane=(t:Row)=>t.queue_lane|| (t.kind==='agent'?'agent':t.phase==='ai_prepare'?'production':group(t)==='comfy'?'comfy':t.kind==='export'?'export':((t.kind==='h3'&&t.target)||t.kind==='stage3d_plan'||(['frame','schedule'].includes(t.kind)&&t.options?.single_shot))?'continuation':'production');
const groupNames:Row={ai:'AI 任务',comfy:'ComfyUI 任务',local:'本地导出'};
const stamp=(value:number)=>new Date(value*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
const elapsed=(start:number,end:number)=>{
 const seconds=Math.max(0,Math.floor(end-start)),hours=Math.floor(seconds/3600),minutes=Math.floor(seconds%3600/60);
 return (hours?hours+'小时 ':'')+(minutes?minutes+'分 ':'')+seconds%60+'秒';
};
const guidance=(t:Row)=>{
 if(t.kind==='storyboard_outline')return '回到分镜页；若有已保存草稿，点击“继续生成汇总”接着完善。需要重新规划时再舍弃草稿；汇总完成并确认后，生成具体分镜。'+(/超时|HTTP|连接|网络/.test(t.message||'')?'先检查文本 AI 连接设置。':'');
 if(/超时|HTTP|连接|网络/.test(t.message||''))return '检查 AI 或 ComfyUI 的连接设置，再回到对应页面重试；已完成的结果仍可查看。';
 const tips:Row={script:'回到剧本页，按完整错误中的原文依据调整后重试编写。',storyboard_outline:'回到分镜页；若有已保存草稿，点击“继续生成汇总”接着完善。需要重新规划时再舍弃草稿；汇总完成并确认后，生成具体分镜。',storyboard:'回到分镜页，查看已完成镜头；可单镜重试，或继续生成未完成镜头。',storyboard_timing:'打开对应镜头的编辑与时序，核对动作顺序和自然时长后重试。',script_assets:'回到资产页，查看提取进度后继续提取未完成元素。',asset_prompt:'查看该元素的外观档案与人工描述，再点击元素卡的生成提示词。',frame:'查看本镜提示词和绑定元素的参考图，再重试生成首帧。',h3:'回到 H3 页，查看该镜头的原生分镜后重新转写。',h3_generate:'检查本镜 H3 提示词、时长和 ComfyUI 连接，再重试生成视频。',h3_upscale:'检查已采用的视频版本及其种子号，再重试二采放大。'};
 return tips[t.kind]||'回到对应项目页面，根据完整错误说明调整后重试。';
};

export function TaskQueue({tasks,projects,currentProjectId,names,onCancel,onParallel,startingParallel='',onCancelAll,cancellingAll=false,onOpen}:Props){
 const [collapsedHistory,setCollapsedHistory]=useState<Record<string,boolean>>({});
 const [control,setControl]=useState<Row|null>(null),[controlBusy,setControlBusy]=useState(false),[controlError,setControlError]=useState(''),[filter,setFilter]=useState('all');
 const readControl=async()=>{const response=await fetch('/api/queue/control');const value=await response.json();if(!response.ok)throw Error(value.detail||'读取队列状态失败');return value};
 useEffect(()=>{let live=true;const load=()=>readControl().then(v=>{if(live){setControl(v);setControlError('')}}).catch(e=>{if(live)setControlError(e.message)});void load();const timer=setInterval(load,1500);return()=>{live=false;clearInterval(timer)}},[]);
 const toggle=async()=>{if(!control||controlBusy)return;setControlBusy(true);try{const response=await fetch('/api/queue/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused:!control.paused})});const value=await response.json();if(!response.ok)throw Error(value.detail||'更新队列状态失败');setControl(value);setControlError('')}catch(e){setControlError((e as Error).message)}finally{setControlBusy(false)}};
 const hasActive=tasks.some(t=>activeStates.has(t.status));
 const [now,setNow]=useState(()=>Date.now()/1000),[copied,setCopied]=useState('');
 useEffect(()=>{if(!hasActive)return;setNow(Date.now()/1000);const timer=window.setInterval(()=>setNow(Date.now()/1000),1000);return()=>window.clearInterval(timer)},[hasActive]);
 const running=tasks.filter(t=>t.status==='running'||t.status==='cancelling').sort((a,b)=>a.created-b.created);
 const queued=tasks.filter(t=>t.status==='queued').sort((a,b)=>group(a)==='comfy'&&group(b)==='comfy'?(a.queue_position||9999)-(b.queue_position||9999):(a.queued_at||a.created)-(b.queued_at||b.created));
 const recent=tasks.filter(t=>!activeStates.has(t.status)).sort((a,b)=>(b.finished||b.created)-(a.finished||a.created)).slice(0,30);
 const projectName=(t:Row)=>projects.find(p=>p.id===t.project_id)?.name||t.project_name||'其他项目';
 const renderTask=(t:Row)=>{
  const queue=queued.filter(q=>group(q)===group(t)),executing=running.filter(q=>group(q)===group(t)&&!['manual_parallel','auto_parallel'].includes(q.execution_mode));
  const active=activeStates.has(t.status),position=queue.findIndex(q=>q.id===t.id);
  const blocker=executing[0]||(position>0?queue[0]:null);
  const ahead=executing.length+Math.max(0,position);
  const count=t.progress,total=Number(count?.total||0),completed=Number(count?.completed||0);
  const comfy=t.comfy_progress,sampling=!!comfy&&/采样|重放|sampler/i.test(String(comfy.phase||'')+' '+String(comfy.node_type||''));
  const current=t.project_id===currentProjectId;
  const canOpen=projects.some(p=>p.id===t.project_id);
  const end=t.finished||now,details=t.generation_details||{};
  const stage=t.stage_message||t.message,waiting=t.status==='queued';
  const copyError=async()=>{try{await navigator.clipboard.writeText(String(t.message||''));setCopied(t.id)}catch{setCopied('')}};
  return <article className={'task '+t.status} data-engine={group(t)} key={t.id} data-task-id={t.id}>
   <div className="task-heading"><strong>{names[t.kind]||t.kind}</strong><WorkTag kind={t.phase==='ai_prepare'?'ai':t.kind==='export'||t.kind==='stage3d_render'?'local':comfyKinds.has(t.kind)?'ai_local':'ai'}/><small>{stateNames[t.status]||t.status}{t.status==='queued'&&group(t)==='comfy'?' · 第 '+(t.queue_position||position+1)+' 位':''}</small></div>
   <div className="task-project"><Folder size={13}/><span>{projectName(t)}</span>{current&&<small>当前项目</small>}</div>
   {t.target_label&&<div className="task-target">{t.target_label}</div>}
   <small className={'task-resource '+group(t)}>{t.phase==='ai_prepare'?'AI 准备 → ComfyUI':groupNames[group(t)]}</small>
   {t.execution_mode==='auto_parallel'&&<small className="task-engine">自动并发执行</small>}{t.execution_mode==='manual_parallel'&&<small className="task-engine">手动并发执行</small>}
   {t.engine_label&&<small className="task-engine">{t.engine_label}{t.image_model_label&&group(t)!=='comfy'?' · 图片规则：'+t.image_model_label:''}{Number(t.planned_seconds)>0?' · 计划 '+t.planned_seconds+'秒':''}</small>}
   {waiting?<><p className="task-wait">{control?.paused?'队列已暂停，等待点击开始。':group(t)==='ai'?'可点击并发执行，也可等待自动调度。':blocker?<>等待「{projectName(blocker)}」的{names[blocker.kind]||blocker.kind}{blocker.status==='cancelling'?'取消':'完成'}；前方 {ahead} 个任务。</>:'等待开始，轮到后自动执行。'}</p>{t.queue_batch&&<small className="queue-order-tag">同类连续执行 · {t.queue_batch}</small>}</>:<p className={t.status==='failed'?'task-error-summary':''}>{t.status==='running'?stage:(t.message||'').includes('请先完成三步定稿')?'当前镜头的声音、时序或画面尚未审定。到“镜头 → 编辑与时序”查看未确认项，再重试本帧。':t.message}</p>}
   <div className="task-times"><span>{waiting?'已排队 '+elapsed(t.queued_at||t.created,end):active&&t.started?'本次执行 '+elapsed(t.execution_started||t.started,end):'总耗时 '+elapsed(t.created,end)}</span>{!waiting&&active&&t.stage_started&&<span>本阶段 {elapsed(t.stage_started,end)}</span>}</div>
   {sampling&&active&&!waiting&&<div className="task-sampling-progress"><progress aria-label="采样进度" max={Number(comfy.total)>0?Number(comfy.total):100} value={Number(comfy.total)>0&&comfy.current!=null?Math.max(0,Math.min(Number(comfy.current),Number(comfy.total))):undefined}/></div>}
   {total>0&&<div className="task-progress"><progress max={total} value={completed} aria-label={t.kind==='storyboard_timing'?'时间修正进度':t.kind==='storyboard_outline'?'分镜汇总核对进度':t.kind==='storyboard'?'分镜生成进度':'元素提取进度'}/><small>{count.phase==='outline_visuals'?'旁白画面已保存':'已完成'} {completed}/{total} · 复用 {count.reused||0}{!['storyboard','storyboard_outline','storyboard_timing'].includes(t.kind)&&<> · 失败 {count.failed||0}</>}</small></div>}
   <details className="task-details"><summary>{t.status==='failed'?'完整错误与执行记录':'任务详情与执行记录'}</summary>
    {t.message&&<pre className="task-full-message">{t.message}</pre>}
    {t.status==='failed'&&<><p className="task-guidance">处理建议：{guidance(t)}</p><button onClick={copyError}>{copied===t.id?'已复制':'复制错误'}</button></>}
    <dl><dt>提交</dt><dd>{stamp(t.created)}</dd>{t.started&&<><dt>开始</dt><dd>{stamp(t.started)}</dd></>}{t.finished&&<><dt>结束</dt><dd>{stamp(t.finished)}</dd></>}{t.started&&t.finished&&<><dt>开始至结束</dt><dd>{elapsed(t.started,t.finished)}</dd></>}
     {details.seed!==undefined&&<><dt>种子号</dt><dd>{details.seed}</dd></>}{details.resolution&&<><dt>输出规格</dt><dd>{details.resolution}</dd></>}{details.upscale_factor&&<><dt>二采放大</dt><dd>{details.upscale_factor} 倍</dd></>}{details.temporal_chunks&&details.spatial_chunks&&<><dt>二采分块</dt><dd>时间 {details.temporal_chunks} × 画面 {details.spatial_chunks}</dd></>}{details.output_width&&details.output_height&&<><dt>输出尺寸</dt><dd>{details.output_width} × {details.output_height}</dd></>}{details.format&&<><dt>导出格式</dt><dd>{details.format}</dd></>}
     {t.prompt_id&&<><dt>ComfyUI ID</dt><dd>{t.prompt_id}</dd></>}<dt>任务 ID</dt><dd>{t.id}</dd>
    </dl>
    {!!t.stage_history?.length&&<ol className="task-stage-history">{t.stage_history.map((item:Row,i:number)=><li key={i}><time>{stamp(item.time)}</time><span>{item.message}</span></li>)}</ol>}
   </details>
   <div className="task-footer"><small><Clock size={11}/>{new Date(t.created*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} 提交</small><div>{canOpen&&!current&&<button onClick={()=>onOpen(t.project_id)}>查看项目</button>}{t.download&&<a href={t.download} download>下载结果</a>}{waiting&&t.parallel_eligible&&<button disabled={!t.can_parallel||control?.paused||startingParallel===t.id} title={t.parallel_blocker||'立即并发执行此AI任务'} onClick={()=>onParallel(t.id)} aria-label={'并发执行 '+projectName(t)+' 的'+(names[t.kind]||t.kind)}>{startingParallel===t.id?'正在启动…':'并发执行'}</button>}{active&&<button disabled={t.status==='cancelling'} onClick={()=>onCancel(t.id)} aria-label={'取消 '+projectName(t)+' 的'+(names[t.kind]||t.kind)}><X size={12}/>{t.status==='cancelling'?'正在取消…':'取消'}</button>}</div></div>
  </article>;
 };
 return <section className="task-list global-task-list" aria-label="全局创作任务">
  <div className="queue-heading"><strong>全局创作任务</strong><small>{running.length} 运行 · {queued.length} 排队</small></div>
  <div className="queue-actions"><small>跨全部项目 · 保留已完成结果</small><button disabled={!tasks.some(t=>t.status==='queued'||t.status==='running')||cancellingAll} onClick={onCancelAll} title="取消所有项目正在执行和排队的 AI、ComfyUI 与导出任务"><X size={12}/>{cancellingAll?'正在全部取消…':'全部取消'}</button></div>
  <div className="queue-controller"><small>{control?.draining?'完成当前任务后暂停':control?.paused?'已暂停':control?'正在调度':'读取队列状态…'}</small><button disabled={!control||controlBusy} onClick={toggle}>{controlBusy?'更新中…':control?.paused?'开始':'暂停'}</button></div>
  {controlError&&<p className="queue-control-error">{controlError}</p>}
  <nav className="queue-view-tabs" aria-label="任务显示筛选">{[['all','全部'],['running','运行'],['queued','排队'],['recent','最近记录']].map(([key,label])=><button key={key} className={filter===key?'active':''} onClick={()=>setFilter(key)}>{label}</button>)}</nav>
  {['ai','comfy','local'].filter(key=>key!=='local'||[...running,...queued,...(filter==='recent'?recent:[])].some(t=>group(t)===key)).map(key=>{
   const activeRunning=running.filter(t=>group(t)===key),activeQueued=queued.filter(t=>group(t)===key),history=recent.filter(t=>group(t)===key);const visible=filter==='recent'?history:[...(filter==='queued'?[]:activeRunning),...(filter==='running'?[]:activeQueued)];
   return <section className={'queue-resource-group '+key} aria-label={groupNames[key]} key={key}>{filter==='recent'?<button className="queue-resource-heading queue-history-toggle" aria-expanded={!collapsedHistory[key]} onClick={()=>setCollapsedHistory(previous=>({...previous,[key]:!previous[key]}))}><strong><span aria-hidden="true">{collapsedHistory[key]?'▸':'▾'}</span> {groupNames[key]}</strong><small>{history.length} 条最近记录</small></button>:<div className="queue-resource-heading"><strong>{groupNames[key]}</strong><small>{activeRunning.length} 运行 · {activeQueued.length} 排队</small></div>}
    {(filter!=='recent'||!collapsedHistory[key])&&visible.map(renderTask)}
    {(filter!=='recent'||!collapsedHistory[key])&&!visible.length&&<p className="queue-empty">{filter==='recent'?'暂无最近记录。':filter==='running'?'当前没有运行中的任务。':filter==='queued'?'当前没有排队任务。':key==='comfy'?'当前没有图片、视频或音频生成任务。':'当前没有 AI 任务。'}</p>}
   </section>;
  })}
 </section>;
}
