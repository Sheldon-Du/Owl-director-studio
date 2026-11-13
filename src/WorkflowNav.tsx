import {productionReady} from './productionSource';
import {ArrowLeft,ArrowRight} from 'lucide-react';
type Obj=Record<string,any>;
const creation=[['brief','创作设定'],['skills','案例与模板'],['production','美术风格'],['documents','创作概览'],['shots','分镜']];
const making=[['assets','资产元素'],['voice','声音与时序'],['frames','首帧／关键帧／尾帧'],['h3','H3 视频'],['soundtrack','配乐'],['timeline','剪辑与导出'],['media','素材库']];
export function WorkflowActions({project,tab,info,select}:{project:Obj;tab:string;info:Obj;select:(id:string)=>void}){
 const all=[...creation,...making],index=all.findIndex(([id])=>id===tab),previous=index>0?all[index-1]:null;
 const links:Record<string,string[]>={brief:['skills','选择案例与模板'],skills:['production','选择美术风格'],documents:['shots','制作分镜'],promo:['shots','生成分镜与三帧描述'],production:['documents','进入创作概览'],shots:['assets','制作资产与角色'],assets:['voice','声音与时序'],frames:['overview','预演并审核节奏'],voice:['frames','制作首帧／关键帧／尾帧'],keyframes:['overview','预演并审核节奏'],h3:['soundtrack','剪辑前制作配乐'],soundtrack:['timeline','剪辑与导出'],timeline:['media','查看素材库']};
 const next=links[tab];
 const ready=tab==='documents'?productionReady(project):tab==='promo'?!!project.story_promo?.adopted&&!info.promo_stale:true;
 return <footer className="workflow-actions"><div>{previous&&<button onClick={()=>select(previous[0])}><ArrowLeft size={15}/>{previous[1]}</button>}</div><div className="row wrap">{['documents','promo','production','shots'].includes(tab)&&<button onClick={()=>select('assets')}>从当前来源提取资产</button>}{next&&<button className="primary" disabled={!ready} title={!ready?'请先完成并确认当前阶段':''} onClick={()=>select(next[0])}>{next[1]}<ArrowRight size={15}/></button>}</div></footer>;
}
