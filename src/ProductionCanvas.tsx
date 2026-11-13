import {productionReady} from './productionSource';
import {useEffect,useMemo,useRef,useState, type PointerEvent} from 'react';
import {Sparkles,Plus,Minus,Maximize2,RotateCcw,Unlink,GripVertical,Film,Music,MousePointer2,Hand,Expand,Minimize2,Image as ImageIcon} from 'lucide-react';
import {adoptedVideos} from './VideoVersions';
type Obj=Record<string,any>;
type Point={x:number;y:number};
type View=Point & {scale:number};
type Positions=Record<string,Point>;
type Node={id:string;kind:string;name:string;value:Obj;width:number;height:number;index?:number;start?:number;duration?:number};
type Edge={assetId:string;shotId:string};
type Props={project:Obj;busy:boolean;aiRunning:boolean;onAI:()=>void;onLayout:(nodes:Positions)=>void;onReference:(shot:string,asset:string,bound:boolean,previous?:string)=>void;onAssemble:()=>void;preview:(m:Obj)=>void;openAsset:(id:string)=>void;openShot:(id:string)=>void;openVideo:(id:string)=>void;addAudio:(m:Obj)=>void};
const url=(name:string)=>'/media/'+encodeURIComponent(name);
const kindName:Obj={character:'角色',scene:'场景',prop:'道具'};
const colors:Obj={character:'#b49bff',scene:'#78c9b3',prop:'#dfbd77'};

export function ProductionCanvas({project,busy,aiRunning,onAI,onLayout,onReference,onAssemble,preview,openAsset,openShot,openVideo,addAudio}:Props){
 const viewport=useRef<HTMLDivElement>(null),drag=useRef<Obj|null>(null),positionsRef=useRef<Positions>({}),viewRef=useRef<View>({x:20,y:20,scale:.72}),pickedRef=useRef<string[]>([]),nodesRef=useRef<Node[]>([]),spaceRef=useRef(false),hovered=useRef(false),suppressClick=useRef(false);
 const [positions,setPositions]=useState<Positions>({}),[view,setView]=useState({x:20,y:20,scale:.72}),[draft,setDraft]=useState<Obj|null>(null),draftRef=useRef<Obj|null>(null),[selected,setSelected]=useState<Edge|null>(null);
 const [tool,setTool]=useState<'select'|'hand'>('select'),[picked,setPicked]=useState<string[]>([]),[marquee,setMarquee]=useState<Obj|null>(null),[gesturing,setGesturing]=useState(false),[spaceDown,setSpaceDown]=useState(false),[expanded,setExpanded]=useState(false);
 const rows=useMemo(()=>{const result:Obj[]=[],seen=new Set<string>();let clock=0;
  for(const o of project.storyboard_generation?.outlines||[]){const s=project.shots.find((s:Obj)=>s.generation_outline_id===o.id),d=Number(s?.duration||o.natural_seconds||0);result.push({id:s?.id||o.id,index:o.index,description:s?.description||o.focus,shot:s,asset_ids:s?.asset_ids||project.canvas_bindings?.[o.id]?.asset_ids||[],manual_asset_ids:s?.manual_asset_ids||project.canvas_bindings?.[o.id]?.manual_asset_ids||[],start:clock,duration:d});clock+=d;if(s)seen.add(s.id)}
  for(const s of project.shots)if(!seen.has(s.id)){result.push({id:s.id,index:s.generation_index||result.length+1,description:s.description,shot:s,asset_ids:s.asset_ids||[],manual_asset_ids:s.manual_asset_ids||[],start:clock,duration:Number(s.duration)});clock+=Number(s.duration)}return result;
 },[project]);
 const nodes=useMemo(()=>[...project.assets.map((a:Obj)=>({id:'asset:'+a.id,kind:'asset',name:a.name,value:a,width:210,height:228})),...rows.map((r:Obj)=>({id:'shot:'+r.id,kind:'shot',name:'第 '+r.index+' 镜',value:r,width:270,height:266,index:r.index,start:r.start,duration:r.duration})),...project.media.filter((m:Obj)=>m.kind==='audio').map((m:Obj)=>({id:'audio:'+m.media,kind:'audio',name:m.name||'音频 '+m.media.slice(0,10),value:m,width:270,height:188}))] as Node[],[project,rows]);
 nodesRef.current=nodes;
 const keys=nodes.map(n=>n.id).join('|');
 const defaults=()=>{const map:Positions={};let a=0,s=0,m=0;for(const n of nodes){map[n.id]=n.kind==='shot'?{x:70+(s++)*320,y:65}:n.kind==='asset'?{x:70+(a++)*250,y:415}:{x:70+(m++)*310,y:735}}return map};
 useEffect(()=>{if(drag.current?.kind==='node')return;const next={...defaults(),...(project.canvas_layout?.lane_version===2?project.canvas_layout?.nodes||{}:{})};positionsRef.current=next;setPositions(next);setSelected(null);const valid=pickedRef.current.filter(id=>nodes.some(n=>n.id===id));pickedRef.current=valid;setPicked(valid)},[project.id,project.canvas_layout?.updated,keys]);
 useEffect(()=>{pickedRef.current=[];setPicked([]);drag.current=null;draftRef.current=null;setDraft(null);setMarquee(null);setSelected(null);setGesturing(false);viewRef.current={x:20,y:20,scale:.72};setView(viewRef.current)},[project.id]);
 const point=(id:string)=>positions[id]||{x:0,y:0};
 const setDraftState=(next:Obj|null)=>{draftRef.current=next;setDraft(next)};
 const pick=(ids:string[])=>{pickedRef.current=ids;setPicked(ids)};
 const updateView=(next:View|((value:View)=>View))=>{const result=typeof next==='function'?next(viewRef.current):next;viewRef.current=result;setView(result)};
 const updatePositions=(next:Positions)=>{positionsRef.current=next;setPositions(next)};
 const clamp=(p:Point)=>({x:Math.max(-10000,Math.min(100000,p.x)),y:Math.max(-10000,Math.min(100000,p.y))});
 const editable=(target:Element|null)=>!!target?.closest('input,textarea,select,[contenteditable="true"]');
 const interactive=(target:Element|null)=>!!target?.closest('button,a,input,textarea,select,video,audio,[contenteditable="true"],.canvas-overlay-controls,.canvas-link-state,[data-edge]');
 const bounds=()=>nodes.reduce((b,n)=>{const p=positionsRef.current[n.id]||{x:0,y:0};return {left:Math.min(b.left,p.x),top:Math.min(b.top,p.y),right:Math.max(b.right,p.x+n.width),bottom:Math.max(b.bottom,p.y+n.height)}},{left:Infinity,top:Infinity,right:-Infinity,bottom:-Infinity});
 const fit=()=>{if(!viewport.current||!nodes.length)return;const b=bounds(),scale=Math.min(1.05,Math.max(.15,Math.min((viewport.current.clientWidth-120)/(b.right-b.left),(viewport.current.clientHeight-110)/(b.bottom-b.top))));updateView({scale,x:75-b.left*scale,y:45-b.top*scale})};
 const zoomAt=(factor:number,cx:number,cy:number)=>updateView(v=>{const scale=Math.max(.15,Math.min(2,v.scale*factor));return {scale,x:cx-(cx-v.x)*scale/v.scale,y:cy-(cy-v.y)*scale/v.scale}});
 const zoom=(factor:number)=>zoomAt(factor,(viewport.current?.clientWidth||900)/2,(viewport.current?.clientHeight||560)/2);
 const world=(x:number,y:number)=>{const box=viewport.current!.getBoundingClientRect(),v=viewRef.current;return {x:(x-box.left-v.x)/v.scale,y:(y-box.top-v.y)/v.scale}};
 const capture=(e:PointerEvent)=>{e.preventDefault();e.stopPropagation();document.getSelection()?.removeAllRanges();viewport.current?.focus({preventScroll:true});viewport.current?.setPointerCapture(e.pointerId);setGesturing(true)};
 const cancelGesture=()=>{const d=drag.current;if(d?.kind==='node')updatePositions({...positionsRef.current,...d.origins});drag.current=null;setMarquee(null);setGesturing(false);setDraftState(null)};
 const startPan=(e:PointerEvent)=>{capture(e);suppressClick.current=true;setDraftState(null);drag.current={kind:'pan',x:e.clientX,y:e.clientY,origin:{...viewRef.current},moved:false}};
 const beginNode=(id:string,e:PointerEvent)=>{if(busy||e.button!==0)return;capture(e);setSelected(null);setDraftState(null);
  const ids=pickedRef.current.includes(id)?pickedRef.current:(e.shiftKey||e.ctrlKey||e.metaKey)?[...pickedRef.current,id]:[id];pick(ids);
  drag.current={kind:'node',x:e.clientX,y:e.clientY,scale:viewRef.current.scale,origins:Object.fromEntries(ids.map(key=>[key,{...positionsRef.current[key]}])),moved:false};
 };
 const panCapture=(e:PointerEvent)=>{const target=e.target instanceof Element?e.target:null;if(editable(target)||target?.closest('.canvas-overlay-controls,.canvas-link-state,.canvas-port,[data-edge]'))return;
  if(e.button===1||e.button===0&&(spaceRef.current||tool==='hand'&&(!interactive(target)||!!target?.closest('.canvas-node-grip'))))startPan(e);
 };
 const pointerDown=(e:PointerEvent)=>{if(e.button!==0||drag.current||draftRef.current)return;const target=e.target instanceof Element?e.target:null;if(interactive(target))return;
  const id=target?.closest('[data-node-id]')?.getAttribute('data-node-id');if(id){beginNode(id,e);return}
  if(tool==='hand'){startPan(e);return}capture(e);setSelected(null);const base=e.shiftKey||e.ctrlKey||e.metaKey?[...pickedRef.current]:[];pick(base);drag.current={kind:'select',x:e.clientX,y:e.clientY,start:world(e.clientX,e.clientY),base,moved:false};
 };
 const move=(e:PointerEvent)=>{if(draftRef.current){const current=draftRef.current;setDraftState({...current,end:world(e.clientX,e.clientY),moved:current.moved||!!current.pointerStart&&Math.hypot(e.clientX-current.pointerStart.x,e.clientY-current.pointerStart.y)>4});return}const d=drag.current;if(!d)return;e.preventDefault();
  if(Math.hypot(e.clientX-d.x,e.clientY-d.y)>3){d.moved=true;suppressClick.current=true}
  if(d.kind==='pan')updateView(v=>({...v,x:d.origin.x+e.clientX-d.x,y:d.origin.y+e.clientY-d.y}));
  else if(d.kind==='node'){if(!d.moved)return;const next={...positionsRef.current};for(const [id,p] of Object.entries(d.origins) as [string,Point][])next[id]=clamp({x:p.x+(e.clientX-d.x)/d.scale,y:p.y+(e.clientY-d.y)/d.scale});updatePositions(next)}
  else if(d.moved){const end=world(e.clientX,e.clientY),box={x:Math.min(d.start.x,end.x),y:Math.min(d.start.y,end.y),width:Math.abs(end.x-d.start.x),height:Math.abs(end.y-d.start.y)};setMarquee(box);
   pick([...new Set([...d.base,...nodesRef.current.filter(n=>{const p=positionsRef.current[n.id];return p&&p.x<box.x+box.width&&p.x+n.width>box.x&&p.y<box.y+box.height&&p.y+n.height>box.y}).map(n=>n.id)])]);
  }
 };
 const finish=(e:PointerEvent)=>{const d=drag.current;if(draftRef.current){const current=draftRef.current,destination=document.elementFromPoint(e.clientX,e.clientY)?.closest('[data-shot-target]')?.getAttribute('data-shot-target');if(destination&&destination!==current.previous){onReference(destination,current.assetId,true,current.previous);setDraftState(null);setSelected(null)}else if(!current.moved&&!current.previous)setDraftState({...current,sticky:true});else setDraftState(null)}
  else if(d?.kind==='node'&&d.moved)onLayout(positionsRef.current);drag.current=null;setMarquee(null);setGesturing(false);if(viewport.current?.hasPointerCapture(e.pointerId))viewport.current.releasePointerCapture(e.pointerId);setTimeout(()=>{suppressClick.current=false},0);
 };
 const beginLink=(assetId:string,e:PointerEvent,previous?:string)=>{if(busy||e.button!==0)return;capture(e);drag.current=null;setMarquee(null);setDraftState({assetId,previous,end:world(e.clientX,e.clientY),pointerStart:{x:e.clientX,y:e.clientY},moved:false})};
 const attach=(identity:string)=>{if(draftRef.current){onReference(identity,draftRef.current.assetId,true,draftRef.current.previous);setDraftState(null)}};
 const nudge=(ids:string[],x:number,y:number)=>{if(busy)return;const next={...positionsRef.current};for(const id of ids)if(next[id])next[id]=clamp({x:next[id].x+x,y:next[id].y+y});updatePositions(next);onLayout(next)};
 useEffect(()=>{document.documentElement.classList.toggle('canvas-gesturing',gesturing);return()=>document.documentElement.classList.remove('canvas-gesturing')},[gesturing]);
 useEffect(()=>{const element=viewport.current;if(!element)return;
  const wheel=(e:WheelEvent)=>{if(editable(e.target instanceof Element?e.target:null))return;e.preventDefault();if(drag.current||draftRef.current)return;const box=element.getBoundingClientRect();if(e.shiftKey)updateView(v=>({...v,x:v.x-e.deltaY-e.deltaX}));else zoomAt(Math.exp(-Math.max(-150,Math.min(150,e.deltaY))*.002),e.clientX-box.left,e.clientY-box.top)};
  const down=(e:KeyboardEvent)=>{const target=e.target instanceof Element?e.target:null;if(e.code==='Space'&&(hovered.current||element.contains(document.activeElement))&&!editable(target)&&!target?.closest('button:not(.canvas-node-grip),a,video,audio')){e.preventDefault();spaceRef.current=true;setSpaceDown(true)}};
  const up=(e:KeyboardEvent)=>{if(e.code==='Space'){spaceRef.current=false;setSpaceDown(false)}};
  const blur=()=>{spaceRef.current=false;setSpaceDown(false);cancelGesture()};
  element.addEventListener('wheel',wheel,{passive:false});window.addEventListener('keydown',down);window.addEventListener('keyup',up);window.addEventListener('blur',blur);
  return()=>{element.removeEventListener('wheel',wheel);window.removeEventListener('keydown',down);window.removeEventListener('keyup',up);window.removeEventListener('blur',blur)};
 },[]);
 const edges:Edge[]=rows.flatMap((r:Obj)=>r.asset_ids.filter((id:string)=>project.assets.some((a:Obj)=>a.id===id)).map((assetId:string)=>({assetId,shotId:r.id})));
 const path=(left:Point,right:Point)=>`M ${left.x} ${left.y} C ${left.x+Math.max(80,Math.abs(right.x-left.x)*.4)} ${left.y}, ${right.x-80} ${right.y}, ${right.x} ${right.y}`;
 const extent=nodes.reduce((box,n)=>({right:Math.max(box.right,point(n.id).x+n.width+100),bottom:Math.max(box.bottom,point(n.id).y+n.height+100)}),{right:1400,bottom:800});
 const total=rows.reduce((n:number,r:Obj)=>n+r.duration,0);
 const audioClips=project.timeline.filter((c:Obj)=>c.kind==='audio');
 const disconnect=()=>{if(selected){onReference(selected.shotId,selected.assetId,false);setSelected(null)}};
 return <section className="production-canvas" aria-label="制作关系画布">
  <div className="canvas-heading"><div><h2>制作关系画布</h2></div><div className="row wrap"><button disabled={busy||!project.shots.length} onClick={onAssemble}>按采用视频组装时间线</button></div></div>
  <p hidden className="canvas-help">拖动卡片移动节点，空白处框选；空格＋拖动或中键平移，滚轮缩放。Shift 可加选多个节点并一起移动。拖动圆点建立参考，布局与连接自动保存。</p>
  <div className={'canvas-shell'+(expanded?' is-expanded':'')}>
  <div ref={viewport} className={'canvas-viewport '+tool+(spaceDown?' space-pan':'')+(gesturing?' is-gesturing':'')} role="region" aria-label="可拖动制作节点" tabIndex={0}
   onPointerEnter={()=>{hovered.current=true}} onPointerLeave={()=>{hovered.current=false}}
   onPointerDownCapture={panCapture} onPointerDown={pointerDown} onPointerMove={move} onPointerUp={finish}
   onPointerCancel={cancelGesture} onLostPointerCapture={()=>{if(drag.current)cancelGesture()}}
   onDragStartCapture={e=>e.preventDefault()} onAuxClick={e=>{if(e.button===1)e.preventDefault()}}
   onClickCapture={e=>{if(suppressClick.current&&e.detail>0){e.preventDefault();e.stopPropagation();suppressClick.current=false}}}
   onKeyDown={e=>{if(editable(e.target instanceof Element?e.target:null))return;
    if(e.key==='Escape'){cancelGesture();setSelected(null);pick([]);setExpanded(false)}
    if(e.key==='Delete'&&selected&&!busy){e.preventDefault();disconnect()}
    const delta:Obj={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};
    if(delta[e.key]&&pickedRef.current.length&&!(e.target instanceof Element&&e.target.closest('button,video,audio'))){e.preventDefault();nudge(pickedRef.current,...delta[e.key] as [number,number])}
   }}>
   <div className="canvas-floating-tools canvas-overlay-controls" role="toolbar" aria-label="画布工具">
    <button aria-label="选择与框选" title="选择与框选 · 拖动卡片移动节点" aria-pressed={tool==='select'} onClick={()=>{cancelGesture();setTool('select')}}><MousePointer2 size={18}/></button>
    <button aria-label="抓手平移" title="抓手平移 · 空格或中键也可平移" aria-pressed={tool==='hand'} onClick={()=>{cancelGesture();setTool('hand')}}><Hand size={18}/></button>
    <span/>
    <button aria-label="适应画布" title="显示全部节点" onClick={fit}><Maximize2 size={17}/></button>
    <button aria-label="自动排布" title="自动排布节点并保存" disabled={busy} onClick={()=>{const next=defaults();updatePositions(next);onLayout(next)}}><RotateCcw size={17}/></button>
    <button aria-label="解除所选关联" title="解除所选参考连线 · Delete" disabled={busy||!selected} onClick={disconnect}><Unlink size={17}/></button>
   </div>
   <div className="canvas-floating-legend"><span><i style={{background:colors.character}}/>角色</span><span><i style={{background:colors.scene}}/>场景</span><span><i style={{background:colors.prop}}/>道具</span><span><i style={{background:'#80aaff'}}/>镜头顺序</span></div>
   <div className="canvas-navigation canvas-overlay-controls" role="toolbar" aria-label="画布缩放">
    <button aria-label="缩小画布" onClick={()=>zoom(1/1.2)}><Minus size={16}/></button><small aria-label="当前画布缩放">{Math.round(view.scale*100)}%</small><button aria-label="放大画布" onClick={()=>zoom(1.2)}><Plus size={16}/></button><span/>
    <button aria-label={expanded?'退出大画布':'展开大画布'} title={expanded?'退出大画布 · Esc':'展开大画布'} onClick={()=>setExpanded(!expanded)}>{expanded?<Minimize2 size={16}/>:<Expand size={16}/>}</button>
   </div>
   <div className="canvas-selection-info" role="status">{picked.length?'已选 '+picked.length+' 个节点 · 拖动任一选中节点可一起移动':selected?'已选参考连线 · 拖动末端换接镜头，Delete 解除关联':tool==='hand'||spaceDown?'抓手平移 · 拖动画布查看其他节点':'选择模式 · 拖动节点，空白处框选'}</div>
   {marquee&&<div className="canvas-marquee" aria-label="节点框选区域" style={{left:marquee.x*view.scale+view.x,top:marquee.y*view.scale+view.y,width:marquee.width*view.scale,height:marquee.height*view.scale}}/>}
  {draft&&<div className="canvas-link-state" role="status">连接中：拖到镜头左侧圆点，或点击圆点完成连接。<button onClick={()=>setDraftState(null)}>取消连线</button></div>}
   {nodes.length===0&&<div className="canvas-empty">先提取资产或生成分镜汇总，画布会自动出现节点。</div>}
   <div className="canvas-world" style={{transform:`translate(${view.x}px,${view.y}px) scale(${view.scale})`}}>
    <svg className="canvas-lines" width={extent.right} height={extent.bottom} aria-label="资产参考与时间顺序连线"><defs><marker id="canvas-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#80aaff"/></marker></defs>
     {edges.map(edge=>{const left={x:point('asset:'+edge.assetId).x+210,y:point('asset:'+edge.assetId).y+114},right={x:point('shot:'+edge.shotId).x,y:point('shot:'+edge.shotId).y+120},active=selected?.assetId===edge.assetId&&selected?.shotId===edge.shotId,asset=project.assets.find((a:Obj)=>a.id===edge.assetId);return <g key={edge.assetId+':'+edge.shotId} data-edge="reference" className="canvas-edge" tabIndex={0} role="button" aria-label={asset.name+' → 第 '+rows.find((r:Obj)=>r.id===edge.shotId)?.index+' 镜参考连线'} onPointerDown={e=>{e.preventDefault();e.stopPropagation();viewport.current?.focus({preventScroll:true})}} onClick={()=>{pick([]);setSelected(edge)}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick([]);setSelected(edge)}}}><title>{asset.name} → 第 {rows.find((r:Obj)=>r.id===edge.shotId)?.index} 镜；点击选择连线</title><path d={path(left,right)} fill="none" stroke="transparent" strokeWidth={18} pointerEvents="stroke"/><path d={path(left,right)} fill="none" stroke={colors[asset.kind]||'#aaa'} strokeWidth={active?4:2} opacity={active?1:.65} pointerEvents="none"/>{active&&<circle cx={right.x-12} cy={right.y} r={9} fill={colors[asset.kind]} stroke="#fff" onPointerDown={e=>beginLink(edge.assetId,e,edge.shotId)}/>}</g>})}
     {rows.slice(1).map((r:Obj,i:number)=>{const prior=rows[i],left={x:point('shot:'+prior.id).x+270,y:point('shot:'+prior.id).y+50},right={x:point('shot:'+r.id).x,y:point('shot:'+r.id).y+50};return <g key={'time:'+r.id}><path d={path(left,right)} fill="none" stroke="#80aaff" strokeWidth={3} markerEnd="url(#canvas-arrow)"/><text x={(left.x+right.x)/2} y={(left.y+right.y)/2-10} fill="#9bb8ec" textAnchor="middle" fontSize="12">{r.start.toFixed(1)}s</text></g>})}
     {audioClips.filter((c:Obj)=>nodes.some(n=>n.id==='audio:'+c.media)).map((c:Obj,i:number)=>{const a=point('audio:'+c.media);return rows.filter((r:Obj)=>Math.min(r.start+r.duration,Number(c.start||0)+Number(c.duration))-Math.max(r.start,Number(c.start||0))>0).map((r:Obj)=>{const right={x:point('shot:'+r.id).x+135,y:point('shot:'+r.id).y+266};return <path key={'audio:'+i+':'+r.id} d={path({x:a.x+135,y:a.y},right)} fill="none" stroke="#df9db9" strokeDasharray="6 5" strokeWidth={1.5} opacity={.6}/>})})}
     {draft&&<path d={path({x:point('asset:'+draft.assetId).x+210,y:point('asset:'+draft.assetId).y+114},draft.end||{x:point('asset:'+draft.assetId).x+260,y:point('asset:'+draft.assetId).y+114})} fill="none" stroke="#e1d2ff" strokeWidth={3} strokeDasharray="6 4"/>}
    </svg>
    {nodes.map(n=>{const pos=point(n.id),v=n.value,shown=n.kind==='shot'?(adoptedVideos(v.shot||{}).at(-1)||(v.shot?.outputs||[]).filter((m:Obj)=>m.kind==='video').at(-1)):null;return <article key={n.id} aria-label={n.name+' · 制作节点'} data-selected={picked.includes(n.id)} className={'canvas-node '+n.kind+(n.kind==='asset'?' '+v.kind:'')+(picked.includes(n.id)?' is-selected':'')} style={{left:pos.x,top:pos.y,width:n.width,height:n.height}} data-node-id={n.id}>
     <button className="canvas-node-grip" aria-label={'移动 '+n.name} disabled={busy} onPointerDown={e=>beginNode(n.id,e)} onKeyDown={e=>{const delta:Obj={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]};if(delta[e.key]){e.preventDefault();e.stopPropagation();const ids=pickedRef.current.includes(n.id)?pickedRef.current:[n.id];pick(ids);nudge(ids,...delta[e.key] as [number,number])}}}><GripVertical size={14}/><strong>{n.name}</strong><small>{n.kind==='asset'?kindName[v.kind]:n.kind==='audio'?'音频':v.shot?'分镜':'占位'}</small></button>
     {n.kind!=='audio'&&['top','right','bottom','left'].map(side=><button key={side} className={'canvas-port port-'+side} data-shot-target={n.kind==='shot'?v.id:undefined} aria-label={n.name+' '+side+' 连接点'} disabled={busy} onPointerDown={e=>n.kind==='asset'?beginLink(v.id,e):e.stopPropagation()} onClick={()=>n.kind==='shot'?attach(v.id):setDraftState({assetId:v.id})}/>)}
     {n.kind==='asset'?<><div className="canvas-node-media">{v.adopted?<button onClick={()=>preview({media:v.adopted,kind:'image'})}><img draggable={false} src={url(v.adopted)} alt={v.name+' · 已采用画面'}/></button>:<span><ImageIcon size={22}/>尚未采用画面</span>}</div><small>{v.adopted?'已采用元素画面':'图片生成后在元素中选择采用'}</small><button onClick={()=>openAsset(v.id)}>打开资产元素</button><button className="canvas-port output" style={{background:colors[v.kind]}} aria-label={'连接资产 '+v.name} disabled={busy} onPointerDown={e=>beginLink(v.id,e)} onClick={e=>{if(e.detail===0)setDraftState({assetId:v.id})}}/></>:n.kind==='shot'?<><button data-shot-target={v.id} className="canvas-port input" aria-label={'连接到第 '+v.index+' 镜'} disabled={busy} onPointerDown={e=>e.stopPropagation()} onClick={()=>attach(v.id)}/><small>{v.start.toFixed(1)}–{(v.start+v.duration).toFixed(1)} 秒 · {v.duration} 秒</small><div className="canvas-node-media">{shown?<video draggable={false} controls preload="metadata" src={url(shown.media)}/>:v.shot?.first_frame?<button onClick={()=>preview({media:v.shot.first_frame,kind:'image'})}><img draggable={false} src={url(v.shot.first_frame)} alt={'第 '+v.index+' 镜首帧'}/></button>:<span><Film size={22}/>{v.shot?'视频待生成':'分镜待生成'}</span>}</div><p>{v.description}</p><small>{shown?(adoptedVideos(v.shot).length?'已采用视频':'最新视频 · 待采用')+' · 种子 '+(shown.seed??'未记录'):v.asset_ids.length+' 个参考元素'}</small><div className="row"><button onClick={()=>openShot(v.id)}>{v.shot?'提示词 / 时序':'前往生成'}</button>{shown&&<button onClick={()=>openVideo(v.id)}>视频版本</button>}</div></>:<><div className="canvas-audio"><Music size={18}/><audio controls preload="metadata" src={url(v.media)}/></div><small>{audioClips.some((c:Obj)=>c.media===v.media)?'已加入音频轨':'未加入剪辑'}</small><button onClick={()=>addAudio(v)}>加入音频轨</button><button onClick={()=>preview(v)}>播放 / 查看</button></>}
    </article>})}
   </div>
  </div>
  </div>
  <div className="canvas-time-strip"><div className="row"><strong>镜头时间顺序</strong><small>{rows.length} 镜 · {total.toFixed(1)} 秒 · 蓝线按此顺序连接</small></div><div className="canvas-time-shots">{rows.map((r:Obj)=><button key={r.id} style={{flex:Math.max(r.duration,1)}} onClick={()=>openShot(r.id)}><strong>第 {r.index} 镜</strong><small>{r.start.toFixed(1)}–{(r.start+r.duration).toFixed(1)} 秒</small><span>{r.shot&&adoptedVideos(r.shot).length?'已采用视频':r.shot?.outputs?.length?'视频待采用':'占位'}</span></button>)}</div>{audioClips.map((c:Obj)=><div className="canvas-audio-track" key={c.id}><button style={{marginLeft:Math.max(0,Math.min(95,Number(c.start||0)/Math.max(total,1)*100))+'%',width:Math.max(5,Math.min(100,Number(c.duration)/Math.max(total,1)*100))+'%'}} onClick={()=>preview(c)}><Music size={13}/>{project.media.find((m:Obj)=>m.media===c.media)?.name||'音频'} · {Number(c.start||0).toFixed(1)}–{(Number(c.start||0)+Number(c.duration)).toFixed(1)} 秒</button></div>)}</div>
 </section>;
}
