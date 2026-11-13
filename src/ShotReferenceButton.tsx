import {lazy,Suspense,useState} from 'react';
import {BookOpen} from 'lucide-react';

const ShotReferenceLibrary=lazy(()=>import('./ShotReferenceLibrary'));

type Props={selectedIds?:string[];onSelect?:(ids:string[])=>void};

export function ShotReferenceButton({selectedIds=[],onSelect}:Props){
 const [open,setOpen]=useState(false);
 return <>
  <button onClick={()=>setOpen(true)}><BookOpen size={16}/>分镜示例{selectedIds.length>0&&` · 已选 ${selectedIds.length}`}</button>
  {open&&<Suspense fallback={<small role="status">正在加载分镜示例…</small>}>
   <ShotReferenceLibrary close={()=>setOpen(false)} selectedIds={selectedIds} onSelect={onSelect}/>
  </Suspense>}
 </>;
}
