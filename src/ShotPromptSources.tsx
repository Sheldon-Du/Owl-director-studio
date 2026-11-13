import {performanceRead} from './performanceRead';
import {useEffect,useState} from 'react';
type Obj=Record<string,any>;
export function ShotPromptSources({project,shot,notify}:{project:Obj;shot:Obj;notify:(s:string)=>void}){
 const [value,setValue]=useState<Obj|null>(null),[error,setError]=useState('');
 useEffect(()=>{let live=true;setValue(null);setError('');performanceRead(`/api/projects/${project.id}/shots/${shot.id}/performance`).then(v=>{if(live)setValue(v)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[project.id,project.revision,shot.id]);
 const copy=(text:string)=>navigator.clipboard.writeText(text).then(()=>notify('已复制提示词')).catch(()=>notify('复制失败，请选中文字复制'));
 return <div className="shot-prompt-sources">{error&&<p className="speech-notice">{error}</p>}{[['creative_prompt','创作概览分镜提示词'],['finalized_prompt','三步定稿分镜提示词']].map(([key,label])=><details key={key}><summary>{label}</summary>{value?.[key]?<><pre className="seedance-shot-prompt">{value[key]}</pre><button onClick={()=>copy(value[key])}>复制{key==='creative_prompt'?'创作概览':'三步定稿'}提示词</button></>:<p className="muted">{!value&&!error?'正在读取…':key==='creative_prompt'?'尚无创作概览分镜提示词。':'三步定稿尚未完成或已失效，请到“配音与测时”完成定稿。'}</p>}</details>)}</div>;
}
