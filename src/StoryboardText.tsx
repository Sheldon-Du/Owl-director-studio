import {useEffect,useState} from 'react';
type Obj=Record<string,any>;
export function StoryboardText({project}:{project:Obj}){
 const [text,setText]=useState(''),[open,setOpen]=useState(false),[error,setError]=useState('');
 useEffect(()=>{if(!open)return;let live=true;fetch(`/api/projects/${project.id}/storyboard/text`).then(async r=>{const v=await r.json();if(!r.ok)throw Error(v.detail||'文字稿读取失败');if(live){setText(v.text);setError('')}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[open,project.id,project.revision]);
 return <section style={{marginBottom:20}}><div className="row wrap"><button disabled={!project.shots.length} onClick={()=>setOpen(!open)}>{open?'收起分镜文字稿':'查看分镜文字稿'}</button>{project.shots.length>0&&<a className="button" href={`/api/projects/${project.id}/storyboard/text/download`} download="Owl-storyboard.txt">下载文字稿</a>}<small>逐镜列出画面、景别、视角、运镜、角色、场景、台词和音效。</small></div>{open&&<div className="note"><h3>完整分镜文字稿</h3><pre className="document">{error||text||'正在读取当前分镜…'}</pre></div>}</section>;
}
