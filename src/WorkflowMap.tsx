import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {ArrowUpRight,Check,ChevronDown,ChevronUp,FolderOpen,LoaderCircle} from 'lucide-react';
import {WorkTag} from './Workbench';
import {stageJobs} from './projectProgress';

type Obj=Record<string,any>;
type Props={project:Obj;tasks:Obj[];tab:string;select:(tab:string)=>void;openVideo:(id:string)=>void};
const stateText:Record<string,string>={adopted:'已完成',partial:'部分完成',empty:'待开始',review:'待人工审核',stale:'待更新',working:'执行中'};

const jobTabs:Record<string,string>={script:'documents',style:'production',video:'h3',review:'shots',edit:'timeline',delivery:'timeline'};

export function FlowProgress({project,tasks,tab,select,openVideo}:Props){
 const [state,setState]=useState<Obj>({}),[expanded,setExpanded]=useState(false);
 const [geometry,setGeometry]=useState({width:0,height:0,paths:[] as string[]});
 const diagram=useRef<HTMLDivElement>(null),marker=useId().replace(/:/g,'');
 const active=tasks.filter(t=>t.project_id===project.id&&['queued','running','cancelling'].includes(t.status));
 const taskVersion=tasks.filter(t=>t.project_id===project.id).map(t=>`${t.id}:${t.status}:${t.finished||0}`).join('|');
 useEffect(()=>{const controller=new AbortController();setState({});fetch(`/api/projects/${project.id}/workbench`,{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error('制作进展读取失败');return r.json()}).then(setState).catch(e=>{if(e.name!=='AbortError')setState({error:e.message})});return()=>controller.abort()},[project.id,project.revision,taskVersion]);
 const nodes:Obj[]=(state.workflow_nodes||[]).map((node:Obj)=>{
  const jobs=node.id==='video'?['h3','h3_generate','h3_upscale','generate']:node.id==='voice'?['audio','performance_plan','schedule']:['review','animatic','delivery'].includes(node.id)?[]:(stageJobs[jobTabs[node.id]||node.id]||[]);
  return {...node,state:active.some(t=>jobs.includes(t.kind))?'working':node.state};
 });
 useLayoutEffect(()=>{
  const el=diagram.current;if(!el)return;let frame=0;
  const measure=()=>{const bounds=el.getBoundingClientRect(),cards=Array.from(el.querySelectorAll<HTMLButtonElement>('.production-node'));
   const pairs=cards.slice(1).map((card,i)=>[cards[i],card]);
   const paths=pairs.map(([prior,card])=>{const a=prior.getBoundingClientRect(),b=card.getBoundingClientRect();const x1=a.right-bounds.left+2,y1=a.top-bounds.top+a.height/2,x2=b.left-bounds.left-4,y2=b.top-bounds.top+b.height/2;
    if(a.top< b.bottom&&a.bottom>b.top||prior.closest('.production-lane')===card.closest('.production-lane'))return `M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2},${y2}`;
    if(Math.abs(y2-y1)<3)return `M${x1},${y1} L${x2},${y2}`;
    const right=bounds.width-7,left=b.left-bounds.left-14,middle=(a.bottom+b.top)/2-bounds.top;
    return `M${x1},${y1} L${right-5},${y1} Q${right},${y1} ${right},${y1+5} L${right},${middle-5} Q${right},${middle} ${right-5},${middle} L${left+5},${middle} Q${left},${middle} ${left},${middle+5} L${left},${y2-5} Q${left},${y2} ${left+5},${y2} L${x2},${y2}`;
   });setGeometry({width:bounds.width,height:bounds.height,paths});};
  const schedule=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(measure)};const observer=new ResizeObserver(schedule);observer.observe(el);el.querySelectorAll('.production-node').forEach(n=>observer.observe(n));schedule();
  return()=>{cancelAnimationFrame(frame);observer.disconnect()};
 },[state.workflow_nodes,expanded]);
 const open=(node:Obj)=>{if(node.id==='review'){const shot=(project.shots||[]).find((s:Obj)=>(s.outputs||[]).length);if(shot){openVideo(shot.id);return}}select(node.tab)};
 return <section className="production-flow" aria-label="项目工作流程">
  <div className="production-flow-heading"><div className="row wrap"><strong>制作进展</strong><span className="flow-count">{state.shot_count==null?'读取进展…':`${state.adopted_shots||0}/${state.shot_count} 镜已采用视频`}</span>{active.length>0&&<span className="flow-running-count"><LoaderCircle size={12}/>{active.length} 项执行中</span>}</div><div className="row"><button className="flow-library" onClick={()=>select('media')} title="素材库是全流程共用的资源，不作为顺序步骤"><FolderOpen size={14}/>素材库</button><button aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?'收起说明':'流程说明'}{expanded?<ChevronUp size={14}/>:<ChevronDown size={14}/>}</button></div></div>
  {state.error&&<p role="alert">{state.error}，请刷新页面重试。</p>}
  <div><div className="production-flow-scroll" tabIndex={0} aria-label="制作流程图，按箭头顺序操作，窄屏可横向滚动">
   <div className="production-diagram single-row" ref={diagram}>
    <svg className="production-connectors" width={geometry.width} height={geometry.height} aria-hidden="true"><defs><marker id={marker} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="currentColor"/></marker></defs>{geometry.paths.map((d,i)=><path key={i} d={d} markerEnd={`url(#${marker})`}/>)}</svg>
    {nodes.map(node=>{const index=nodes.indexOf(node)+1,selected=node.tab===tab&&!['review','delivery'].includes(node.id);return <button key={node.id} data-node={node.id} data-work={node.work} className={`production-node state-${node.state}${selected?' is-selected':''}`} aria-current={selected?'step':undefined} title={`${node.label} · ${stateText[node.state]}。${node.hint}`} onClick={()=>open(node)}><span className="production-node-top"><span className="production-node-number">{node.state==='adopted'?<Check size={12}/>:node.state==='working'?<LoaderCircle size={12}/>:String(index).padStart(2,'0')}</span><span className="production-node-role">{node.work==='human'?'人工':node.work==='local'?'本地':node.work==='ai_local'?'AI · 本地':'AI'}</span>{node.optional&&<em>可选</em>}</span><strong>{node.label}</strong><small>{node.optional&&node.state==='empty'?'按需选择':stateText[node.state]}{node.total>1?` · ${node.count}/${node.total}`:''}</small>{expanded&&<span className="production-node-hint">{node.hint}</span>}</button>})}
   </div>
  </div>
  <p className="flow-sequence-note" title="资产图片与角色音色可以并行准备；声音、时序、画面按顺序审定；采用首帧后制作关键帧和尾帧，最后审核动态预演。">镜头制作：资产与音色可并行 → 审定声音／时序／画面 → 首帧 → 关键帧与尾帧 → 预演审核</p><div className="production-flow-footer"><div className="row wrap"><WorkTag kind="ai"/><WorkTag kind="human"/><WorkTag kind="local"/><span className="flow-footnote">按箭头顺序推进 · 可选步骤可跳过 · 点击节点进入</span></div><span className="flow-scroll-hint">左右滑动查看完整流程 <ArrowUpRight size={12}/></span></div>
  {expanded&&<div className="production-flow-notes"><p>顺序表示推荐制作路径，可随时返回修改。AI · 本地表示该步骤涉及 AI 和本地处理；例如 H3 生成调用服务端模型，本地负责素材准备与工作流执行。</p><p>“已完成”只表示当前节点有对应成果或审核记录，不等于所有上游已经通过，也不等于最终视频已导出。</p>{(state.impact||[]).length>0&&<details><summary>最近修改影响 · {state.impact.length} 项</summary>{state.impact.map((item:Obj,i:number)=><p key={i}>{item.shot_id?`分镜 ${(project.shots||[]).findIndex((s:Obj)=>s.id===item.shot_id)+1}`:'镜头顺序'} · {item.changed.join('、')} → {item.downstream.join('、')}待更新</p>)}</details>}</div>}
 </div></section>;
}
