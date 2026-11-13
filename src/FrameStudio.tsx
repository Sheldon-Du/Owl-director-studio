import React from 'react';
import {FramePromptEditor} from './FramePromptEditor';
type Obj=Record<string,any>;
export function FrameStudio({project,shot,busy,job,change,children,fixedMode,whiteLayout=false}:{project:Obj;shot:Obj;busy:boolean;job:(kind:string,target:string,options:Obj)=>void;change:(mode:string,plan:Obj)=>void;children:(mode:string)=>React.ReactNode;fixedMode?:string;openStage?:()=>void;whiteLayout?:boolean}){
 const [mode,setMode]=React.useState(fixedMode||'frame'),[tab,setTab]=React.useState('images'),[intent,setIntent]=React.useState('');
 React.useEffect(()=>{if(fixedMode)setMode(fixedMode)},[fixedMode]);
 const plan=shot.image_plans?.[mode]||{},ids:string[]=plan.selected_asset_ids??plan.asset_ids??shot.asset_ids??[];
 const label=mode==='frame'?'首帧':mode==='tail'?'尾帧':'关键帧';
 const update=(value:Obj)=>change(mode,{...plan,...value});
 return <section className="frame-studio-simple">{!fixedMode&&<div className="mode-tabs">{[['frame','首帧'],['keyframe','关键帧'],['tail','尾帧']].map(([v,n])=><button key={v} className={mode===v?'active':''} onClick={()=>setMode(v)}>{n}</button>)}</div>}
 <nav className="mode-tabs" aria-label="帧制作内容">{[['images','候选与采用'],['prompt','提示词'],['layout','构图参考']].map(([v,n])=><button key={v} className={tab===v?'active':''} onClick={()=>setTab(v)}>{n}</button>)}</nav>
 <div className={'frame-editor-grid'+(tab==='images'?' with-candidates':'')}>
 {tab==='images'&&<div className="frame-candidates-pane">{children(mode)}</div>}
 <div className="frame-settings-pane">
 <label>修改意见<textarea aria-label={label+'修改意见'} rows={2} value={intent} onChange={e=>setIntent(e.target.value)} placeholder="希望如何调整构图、比例、站位或动作？"/></label>
 <div className="frame-primary-actions"><button disabled={busy||!ids.length} onClick={()=>job('frame_plan',shot.id,{mode,description:intent,propose_assets:true,auto_bind_adopted:true,render_layout:false,rebuild_card:!!intent.trim(),layout_svg:whiteLayout,selected_asset_ids:ids})}>{plan.prompt?'AI 按意见修改':'准备提示词'}</button><button className="primary" disabled={busy||!plan.prompt||plan.stale||plan.selection_stale||!plan.references?.length} onClick={()=>job(mode,shot.id,{single_shot:true,use_image_plan:true})}>生成{label}候选</button></div>
 {tab==='prompt'&&<><details><summary>本帧可见资产 · {ids.length}</summary><div className="row wrap">{project.assets.map((a:Obj)=><label className="checkbox" key={a.id}><input type="checkbox" checked={ids.includes(a.id)} onChange={e=>update({selected_asset_ids:e.target.checked?[...new Set([...ids,a.id])]:ids.filter(id=>id!==a.id),selection_stale:true})}/>{a.name}</label>)}</div></details>{plan.selection_stale&&<p role="status">资产选择已变化，请重新准备提示词。</p>}{plan.prompt?<FramePromptEditor prompt={plan.prompt} onChange={value=>update({prompt:value,prompt_zh:value})}/>:<p className="muted">点击“准备提示词”后可查看和编辑。</p>}<details><summary>已自动绑定的参考</summary><div className="frame-reference-strip">{(plan.references||[]).map((r:Obj)=><figure key={r.media}><img src={'/media/'+encodeURIComponent(r.media)} alt="资产参考"/><figcaption>{project.assets.find((a:Obj)=>a.id===r.asset_id)?.name||'构图参考'}</figcaption></figure>)}</div>{(plan.missing_adopted_assets||[]).map((a:Obj)=><p role="alert" key={a.asset_id}>{a.name}：{a.reason}</p>)}</details></>}
 {tab==='layout'&&<><p className="muted">关键帧／尾帧自动参考已采用首帧；相邻镜头参考上一镜空间，景别按本镜执行。</p><button disabled={busy} onClick={()=>job('frame_layout',shot.id,{mode,description:intent})}>{plan.composition_reference?'更新白模布局':'绘制白模布局'}</button>{plan.composition_reference&&<><img className="frame-white-layout-image" src={'/media/'+encodeURIComponent(plan.composition_reference)} alt={label+'构图参考'}/><button onClick={()=>update({composition_reference:''})}>停用白模参考</button></>}</>}
 </div></div></section>;
}
