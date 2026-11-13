import {useEffect,useId,useRef,useState} from 'react';
import {X} from 'lucide-react';
import {CopyMark} from './StudioTools';
import examples from './shotReferenceAssets.json';
import './shot-references.css';

const categories=[
 {id:'lighting',label:'光影'},
 {id:'cameraMovement',label:'运镜'},
 {id:'composition',label:'构图'},
];
const groups=categories.map(category=>({
 ...category,
 examples:examples.filter(example=>example.category===category.id)
  .sort((a,b)=>a.nameZh.localeCompare(b.nameZh,'zh-CN')),
}));
const pageSize=24;

type Props={close:()=>void;selectedIds:string[];onSelect?:(ids:string[])=>void};

export default function ShotReferenceLibrary({close,selectedIds,onSelect}:Props){
 const [groupIndex,setGroupIndex]=useState(0);
 const [query,setQuery]=useState('');
 const [selectedId,setSelectedId]=useState('');
 const [limit,setLimit]=useState(pageSize);
 const dialog=useRef<HTMLDialogElement>(null);
 const titleId=useId();
 useEffect(()=>{dialog.current?.showModal()},[]);

 const keyword=query.trim().toLowerCase();
 const matches=groups[groupIndex].examples.filter(example=>
  [example.nameZh,example.nameEn,example.promptZh,example.promptEn].some(text=>text?.toLowerCase().includes(keyword))
 );
 const selected=matches.find(example=>example.id===selectedId)||matches[0];
 return <dialog ref={dialog} className="shot-reference-dialog" aria-labelledby={titleId} onClose={close}>
  <div className="modal-heading">
   <div><h2 id={titleId}>分镜示例</h2><small className="muted">来自 HRO Studio 的 RunningHub 示例库</small></div>
   <button className="icon" aria-label="关闭分镜示例" onClick={()=>dialog.current?.close()}><X size={18}/></button>
  </div>
  <nav className="mode-tabs" aria-label="分镜示例分类">
   {groups.map((group,index)=><button key={group.id} aria-pressed={index===groupIndex} className={index===groupIndex?'active':''}
    onClick={()=>{setGroupIndex(index);setQuery('');setSelectedId('');setLimit(pageSize)}}>
    {group.label} · {group.examples.length}{group.examples.some(example=>selectedIds.includes(example.id))&&' ✓'}
   </button>)}
  </nav>
  {onSelect&&<p className="muted">每类可选一个示例。保存项目后，重新生成本镜提示词即可使用这些参考。</p>}
  <label>搜索示例<input type="search" value={query} placeholder="搜索中英文名称或提示词"
   onChange={event=>{setQuery(event.target.value);setLimit(pageSize)}}/></label>
  <div className="shot-reference-layout">
   <div className="shot-reference-list">
    <div className="shot-reference-grid">
     {matches.slice(0,limit).map(example=><button key={example.id} aria-pressed={selected?.id===example.id} onClick={()=>setSelectedId(example.id)}>
      <img src={example.posterUrl||example.mediaUrl} alt="" loading="lazy"/>
      <span>{example.nameZh}{selectedIds.includes(example.id)?<small>已选</small>:example.mediaKind==='video'&&<small>视频</small>}</span>
     </button>)}
    </div>
    {!matches.length&&<p role="status" className="muted">没有匹配的示例。</p>}
    {matches.length>limit&&<button onClick={()=>setLimit(limit+pageSize)}>查看更多 · {limit} / {matches.length}</button>}
   </div>
   {selected&&<section className="shot-reference-detail" aria-label="示例详情">
    <h3>{selected.nameZh}</h3>
    {selected.mediaKind==='video'
     ?<video key={selected.id} src={selected.mediaUrl} poster={selected.posterUrl} controls playsInline preload="metadata" aria-label={selected.nameZh}/>
     :<img src={selected.mediaUrl} alt={selected.nameZh}/>}
    <div className="copy-surface">
     <CopyMark text={selected.promptZh}/>
     <textarea readOnly rows={5} aria-label="示例提示词" value={selected.promptZh}/>
    </div>
    {onSelect&&<label className="inline-check">
     <input type="checkbox" checked={selectedIds.includes(selected.id)} onChange={event=>{
      const sameCategory=new Set(groups[groupIndex].examples.map(example=>example.id));
      const next=selectedIds.filter(id=>!sameCategory.has(id));
      if(event.target.checked)next.push(selected.id);
      onSelect(next);
     }}/>
     用于本镜提示词生成
    </label>}
    <div className="row wrap">
     <a className="button" href={selected.mediaUrl} download>下载素材</a>
     <a href={selected.sourceUrl} target="_blank" rel="noreferrer">原始素材 ↗</a>
    </div>
   </section>}
  </div>
 </dialog>;
}
