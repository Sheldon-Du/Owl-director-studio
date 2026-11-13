import {useEffect,useRef,useState} from 'react';
import './agent-chat-layout.css';
import {ReferenceText} from './ReferenceText';
import {Sparkles,MessageSquare,X,Upload,BookOpen} from 'lucide-react';
type Row=Record<string,any>;
const names:Row={chatcut_status:'连接 ChatCut',chatcut_send:'发送到 ChatCut',chatcut_read:'读取剪辑工程',chatcut_edit:'执行剪辑',chatcut_export:'导出 ChatCut 成片',chatcut_progress:'查询导出进度',chatcut_collect:'回收剪辑成片',read_skill_reference:'读取技能参考',write_skill_document:'保存技能文档',read_skill_documents:'读取续做记录',plan_skill:'规划专项技能',adopt_skill_plan:'采用技能方案',agent_response:'回复格式检查',read_project:'读取项目',inspect_media:'检查素材',load_skill:'读取技能',install_skill:'安装技能',update_project:'修改项目',edit_shot:'编辑镜头',start_job:'提交制作任务',job_results:'制作结果',confirm_stage:'确认阶段',adopt_frame:'采用首帧',adopt_video:'采用视频',previous_tail:'沿用尾帧',accept_timing:'采用时长',set_media_brief:'记录素材依据',assemble_timeline:'组装时间线',cancel_job:'取消任务'};
async function api(path:string,body?:any){
 const response=await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers:body instanceof FormData?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)});
 const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail));return result;
}
type Props={project:Row;busy:boolean;save:()=>Promise<Row>;changed:(revision:number)=>void;notify:(s:string)=>void;cancel:(id:string)=>void};

export function AgentPanel({project,busy,save,changed,notify,cancel}:Props){
 const [data,setData]=useState<Row>({messages:[],runs:[],skills:[]}),[text,setText]=useState(''),[mode,setMode]=useState('execute'),[skill,setSkill]=useState(''),[sending,setSending]=useState(false),[manager,setManager]=useState(false),[expanded,setExpanded]=useState(false);
 const end=useRef<HTMLDivElement>(null),callbacks=useRef({changed,notify,revision:project.revision});
 callbacks.current={changed,notify,revision:project.revision};
 const active=data.runs.find((r:Row)=>['queued','running','cancelling'].includes(r.status));
 useEffect(()=>{
  let mounted=true,inflight=false;
  const load=async()=>{if(inflight)return;inflight=true;try{const value=await api(`/projects/${project.id}/agent`);if(mounted){setData(value);if(value.project_revision>callbacks.current.revision)callbacks.current.changed(value.project_revision);}}catch(e){if(mounted)callbacks.current.notify((e as Error).message)}finally{inflight=false}};
  load();const timer=setInterval(load,1500);return()=>{mounted=false;clearInterval(timer)};
 },[project.id]);
 useEffect(()=>{if(expanded)end.current?.scrollIntoView({block:'nearest',behavior:'smooth'})},[data.messages.length,expanded]);
 const submit=async()=>{
  const message=text.trim();if(!message||sending||active)return;setSending(true);
  try{const saved=await save();const result=await api(`/projects/${saved.id}/agent`,{revision:saved.revision,message,mode,skill_id:skill||undefined});setText('');setData(await api(`/projects/${saved.id}/agent`));notify('Agent 已接收，可在对话和任务队列查看进度');if(!result.id)throw new Error('未能创建Agent任务');}
  catch(e){notify((e as Error).message)}finally{setSending(false)};
 };
 return <>{!expanded&&<button className="agent-launcher" aria-label="展开导演 Agent" onClick={()=>setExpanded(true)}><MessageSquare size={18}/>导演 Agent</button>}{expanded&&<aside className="assistant-panel agent-panel agent-mobile-open" aria-label="导演 Agent 对话">
  <div className="assistant-title"><span className="assistant-avatar"><Sparkles size={18}/></span><div><strong>导演 Agent</strong><small>理解项目 · 调用制作工具</small></div><button className="icon agent-mobile-close" aria-label="收起Agent" title="收起导演 Agent" onClick={()=>setExpanded(false)}><X size={18}/></button></div>
  <div className="agent-controls" aria-label="Agent 对话工具栏"><button type="button" aria-label="Agent对话模式" title={mode==='execute'?'执行制作：按明确要求操作。点击切换为讨论建议':'讨论建议：不修改项目。点击切换为执行制作'} onClick={()=>setMode(mode==='execute'?'discuss':'execute')}><MessageSquare size={13}/>{mode==='execute'?'执行制作':'讨论建议'}</button><select className="agent-skill-choice" aria-label="Agent制作技能" title={skill?data.skills.find((s:Row)=>s.id===skill)?.name:'自动选择相关技能'} value={skill} onChange={e=>setSkill(e.target.value)}><option value="">技能：自动选择</option>{data.skills.filter((s:Row)=>s.enabled).map((s:Row)=><option key={s.id} value={s.id}>{s.name}</option>)}</select><button type="button" title="技能管理与安装" onClick={()=>setManager(true)}><BookOpen size={14}/>管理</button></div>
  <div className="assistant-body">
   {data.messages.length===0&&<div className="assistant-message"><p>可以询问剧本、分镜和任务问题，也可以直接要求执行单镜制作。</p><p>例如：“检查第3镜的参考图，再生成两张首帧。”固定音频或视频改编请先在项目素材导入文件，并提供歌词、时间标注或内容说明。</p></div>}
   {data.messages.map((m:Row,i:number)=>m.role==='tool'?<details className={'agent-tool '+(m.status==='failed'?'failed':'')} key={m.id||'old'+i}><summary>{names[m.tool]||m.tool} · {m.status==='failed'?'未执行成功':'返回结果'}</summary>{m.arguments&&<pre>{JSON.stringify(m.arguments,null,2)}</pre>}<pre>{m.content}</pre></details>:<div key={m.id||'old'+i} className={'chat-message '+m.role+(m.intermediate?' intermediate':'')}><ReferenceText text={m.content||''}/></div>)}
   {active&&<div className="agent-running" role="status"><Sparkles size={14}/><span>{active.message||'Agent正在工作…'}</span><button disabled={active.status==='cancelling'} onClick={()=>cancel(active.id)}>停止</button></div>}
   {data.memory&&<details className="agent-memory"><summary>本项目创作记忆</summary><p>{data.memory}</p></details>}<div ref={end}/>
  </div>
  <form className="chat-input" onSubmit={e=>{e.preventDefault();submit()}}><textarea aria-label="发给导演Agent" rows={3} placeholder="输入问题或制作要求，也可指定技能路径安装…" value={text} onChange={e=>setText(e.target.value)}/><div><span>{active?'正在执行，可停止后继续对话':'使用工作室已配置的文本 AI'}</span><button className="primary" disabled={busy||sending||!!active||!text.trim()}><Sparkles size={14}/>{sending?'提交中':'发送'}</button></div></form>
 </aside>}{manager&&<SkillManager notify={notify} close={()=>setManager(false)}/>}</>;
}

export function SkillManager({notify,close}:{notify:(s:string)=>void;close:()=>void}){
 const [query,setQuery]=useState('');
 const [data,setData]=useState<Row>({items:[],tools:[],limitations:[]}),[path,setPath]=useState(''),[busy,setBusy]=useState(false),[note,setNote]=useState('');
 const reload=async()=>setData(await api('/skills'));
 useEffect(()=>{reload().catch(e=>notify(e.message))},[]);
 const act=async(work:()=>Promise<any>)=>{setBusy(true);try{const result=await work();await reload();setNote(result.name?'已安装：'+result.name+(result.ignored_files?.length?'；已忽略脚本或非文本附件 '+result.ignored_files.length+' 个':''):'技能状态已更新');}catch(e){setNote((e as Error).message)}finally{setBusy(false)}};
 return <div className="modal-backdrop" onClick={close}><section className="modal skill-manager" onClick={e=>e.stopPropagation()}><div className="modal-heading"><h2>导演工坊技能</h2><button className="icon" onClick={close} aria-label="关闭技能管理"><X/></button></div><p className="muted">技能定义制作方法，调用网站已有工具。导入 SKILL.md 或 ZIP 后即可在 Agent 对话选择；也可让 Agent 安装你明确指定的本机路径。</p>
  <div className="row wrap"><label className="button"><Upload size={15}/>导入 SKILL.md / ZIP<input hidden type="file" accept=".md,.zip" disabled={busy} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)act(async()=>{const body=new FormData();body.append('file',file);return api('/skills/import',body)})}}/></label></div>
  <label>本机技能目录或文件<input aria-label="本机技能路径" value={path} onChange={e=>setPath(e.target.value)} placeholder="例如 D:\2video\codex\my-skill"/></label><button disabled={busy||!path.trim()} onClick={()=>act(()=>api('/skills/import-local',{path:path.trim()}))}>从本机路径安装</button>{note&&<p className="note" role="status">{note}</p>}
  <label>查找技能<input aria-label="技能管理搜索" value={query} onChange={e=>setQuery(e.target.value)} placeholder="名称、类型或关键词"/></label><small>{data.items.length} 个技能</small><div className="skill-list">{data.items.filter((s:Row)=>[s.name,s.description,s.category,s.id].join(' ').toLowerCase().includes(query.toLowerCase())).map((s:Row)=><article key={s.id}><div className="row"><strong>{s.name}</strong><span className="pill">{s.builtin?'内置':'已导入'}</span><span className="pill">{s.status}</span></div><p>{s.description}</p><small>{s.origin||'本站技能'} · {s.category}</small>{s.execution_gaps?.length>0&&<p className="trait-warning">完整流程需接入：{s.execution_gaps.join('、')}。专项规则和项目规划可用，不能据此声称已实现外部工具能力。</p>}{s.missing_tools.length>0&&<p className="trait-warning">缺少工具：{s.missing_tools.join('、')}。可提供方法说明，需接入这些工具后才能完整执行。</p>}{!s.dependencies_declared&&<small>该技能未声明 requires_tools，使用时需核对正文中的工具是否已接入。</small>}<label className="checkbox"><input type="checkbox" checked={s.enabled} disabled={busy} onChange={e=>act(()=>api(`/skills/${s.id}/enable`,{enabled:e.target.checked}))}/>启用</label></article>)}</div>
  <details><summary>现有工具与能力范围</summary>{data.limitations.map((s:string)=><p className="muted" key={s}>{s}</p>)}{data.tools.map((t:Row)=><p className="muted" key={t.name}><strong>{t.name}</strong>：{t.description}</p>)}</details>
 </section></div>;
}
