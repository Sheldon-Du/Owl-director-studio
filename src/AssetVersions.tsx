import {Check,Trash2} from 'lucide-react';
import {assetPreviewVersions} from './assetPreviewVersions';
export {assetPreviewVersions} from './assetPreviewVersions';
type Obj=Record<string,any>;
const media=(name:string)=>'/media/'+encodeURIComponent(name);

export function AssetVersions({asset:a,editAsset,onPreview,newId}:{asset:Obj;editAsset:(id:string,fn:(a:Obj)=>void)=>void;onPreview:(m:Obj)=>void;newId:()=>string}){
 const versions=assetPreviewVersions(a);
 if(!versions.length)return null;
 return <><div className="reference-title generated-title"><strong>元素图片 <span>{versions.length}</span></strong><small>每次生成均追加到这里</small></div><div className="versions asset-versions">{versions.map((m:Obj,i:number)=><div key={m.id} className={a.adopted===m.media?'adopted':''}>
  <img src={media(m.media)} onClick={()=>onPreview(m)}/>
  <small>{m.upscaled?'二次放大 · '+(m.upscale_model||'图片模型'):m.upscaled?'二次放大 · '+(m.upscale_model||'图片模型'):m.character_card?(m.layout_normalized?'等格角色卡':'四宫格原图'):'版本 '+(i+1)}{m.stale?' · 旧设定':''}{m.layout_error?' · 排版未完成':''}</small>
  <button onClick={()=>editAsset(a.id,x=>{x.adopted=m.media})}>{a.adopted===m.media?<><Check size={13}/>已采用</>:'采用'}</button>
  <button disabled={a.references.some((r:Obj)=>r.media===m.media)} onClick={()=>editAsset(a.id,x=>{x.references.push({id:newId(),media:m.media,role:x.kind==='character'?'identity':x.kind==='scene'?'environment':'prop',note:''})})}>{a.references.some((r:Obj)=>r.media===m.media)?'已加入参考':'加入参考'}</button>
  {(m.alternative||m.source_media)&&<button onClick={()=>onPreview(m.alternative||{media:m.source_media,kind:'image'})}>{m.alternative?.layout_normalized?'查看等格图':'查看原图'}</button>}
  {m.alternative&&<button onClick={()=>editAsset(a.id,x=>{x.adopted=m.alternative.media})}>{m.alternative.layout_normalized?'采用等格图':'采用原图'}</button>}
  <button className="remove-image" title="从当前元素移除这次生成的图片" onClick={()=>editAsset(a.id,x=>{x.previews=x.previews.filter((item:Obj)=>!m.version_ids.includes(item.id));if(m.version_media.includes(x.adopted))x.adopted=null})}><Trash2 size={12}/>移除</button>
 </div>)}</div></>;
}
