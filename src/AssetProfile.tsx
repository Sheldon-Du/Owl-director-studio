import React from 'react';
import {Sparkles} from 'lucide-react';
import schemaData from '../asset-feature-schema.json';
type Obj=Record<string,any>;
const schema:Obj=schemaData;
const sourceNames:Obj={explicit:'剧本明示',suggested:'设计建议',user:'用户设定',unknown:'剧本未指定'};
const legacyMap:Obj={age:'basic.age',gender:'basic.gender',appearance:'face.shape',hair:'hair.style_length',costume:'outfit.key_items',personality:'personality.traits',expression:'basic.demeanor_posture'};

function grouped(asset:Obj):Obj{
 const profile:Obj={version:2,groups:{},other_age_stages:asset.visual_profile?.other_age_stages||[]};
 for(const [group,spec] of Object.entries(schema[asset.kind]) as [string,Obj][]){
  profile.groups[group]={fields:{}};
  for(const key of Object.keys(spec.fields))profile.groups[group].fields[key]={value:'',source:'unknown',evidence:'',owner:asset.name,...asset.visual_profile?.groups?.[group]?.fields?.[key]};
 }
 if(asset.kind==='character'&&!asset.visual_profile?.groups){
  for(const [key,path] of Object.entries(legacyMap) as [string,string][]){
   const old=asset.visual_profile?.fields?.[key];
   const [group,field]=path.split('.');
   if(old)profile.groups[group].fields[field]={...old};
   else if(['age','gender','costume','personality'].includes(key)&&asset[key])profile.groups[group].fields[field]={value:asset[key],source:'user',evidence:'',owner:asset.name};
  }
  if(!asset.visual_profile&&asset.visual_description_source==='user')profile.groups.face.fields.shape={value:asset.description,source:'user',evidence:'',owner:asset.name};
  const hair=asset.visual_profile?.fields?.hair;
  if(hair?.value){
   for(const [pattern,color] of [[/黑发|黑色.{0,6}发|black/i,'黑色'],[/红发|红色.{0,6}发|red|ginger/i,'红色'],[/棕发|棕色.{0,6}发|brown/i,'棕色'],[/金发|金色.{0,6}发|blond/i,'金色'],[/白发|银发|silver|white/i,'银白色'],[/蓝发|蓝色.{0,6}发|blue/i,'蓝色']] as [RegExp,string][]){
    if(pattern.test(hair.value)){profile.groups.hair.fields.color={...hair,value:color};break;}
   }
  }
 }
 if(asset.visual_profile?.user_summary)profile.user_summary=asset.visual_profile.user_summary;
 return profile;
}

function values(profile:Obj,paths:string[]){
 return paths.map(path=>{const [g,k]=path.split('.');return profile.groups[g].fields[k]}).filter(i=>i.value&&i.source!=='unknown').map(i=>i.value).join('；');
}

function sync(asset:Obj){
 const profile=asset.visual_profile;
 asset.description=profile.user_summary||Object.entries(schema[asset.kind]).map(([g,s]:[string,any])=>{
  const entries=Object.entries(s.fields).filter(([k])=>g!=='personality'||k==='traits').filter(([k])=>profile.groups[g].fields[k].value&&profile.groups[g].fields[k].source!=='unknown').map(([k,label])=>label+'：'+profile.groups[g].fields[k].value);
  return entries.length?s.label+'（'+entries.join('；')+'）':'';
 }).filter(Boolean).join('；');
 if(asset.kind==='character'){
  const paths=Object.entries(schema.character).flatMap(([g,s]:[string,any])=>Object.keys(s.fields).map(k=>g+'.'+k));
  const selected:Obj={age:['basic.age'],gender:['basic.gender'],appearance:paths.filter(k=>k.startsWith('face.')||['basic.species_identity','basic.build','basic.skin'].includes(k)),hair:paths.filter(k=>k.startsWith('hair.')),costume:paths.filter(k=>k.startsWith('outfit.')||k.startsWith('accessories.')),personality:paths.filter(k=>k.startsWith('personality.')&&k!=='personality.values_motivation'),expression:['basic.demeanor_posture','face.gaze','face.lips_expression']};
  profile.fields={};
  for(const [key,items] of Object.entries(selected) as [string,string[]][]){
   let value=values(profile,items);
   if(key==='hair'&&profile.groups.hair.fields.color.value)value=profile.groups.hair.fields.color.value+'头发；'+value;
   profile.fields[key]=['age','gender'].includes(key)?{...profile.groups.basic.fields[key]}:{value,source:value?'suggested':'unknown',evidence:'',owner:asset.name};
  }
  for(const key of ['age','gender','costume','personality'])asset[key]=profile.fields[key].value;
 }
 asset.prompt='';asset.prompt_zh='';(asset.previews||[]).forEach((m:Obj)=>m.stale=true);
}

export function AssetProfile({asset,busy,scriptReady,editAsset,job}:{asset:Obj;busy:boolean;scriptReady:boolean;editAsset:(id:string,fn:(a:Obj)=>void)=>void;job:(kind:string,target?:string)=>void}){
 const [enrichmentReady,setEnrichmentReady]=React.useState(false);
 React.useEffect(()=>{let live=true;const check=()=>fetch('/api/session').then(r=>r.json()).then(v=>{if(live)setEnrichmentReady((v.features||[]).includes('asset_enrich_prompt'))}).catch(()=>{});check();const interval=setInterval(check,10000);return()=>{live=false;clearInterval(interval)}},[]);
 const profile=grouped(asset),character=asset.kind==='character';
 const change=(group:string,key:string,value:string)=>editAsset(asset.id,a=>{
  a.visual_profile=grouped(a);delete a.visual_profile.user_summary;
  a.visual_profile.groups[group].fields[key]={value,source:'user',evidence:'',owner:a.name};sync(a);
 });
 const legacySummary=!asset.visual_profile&&asset.description||profile.user_summary;
 return <section className="character-profile">
  <div className="row wrap"><strong>{character?'角色外观与性格档案':asset.kind==='scene'?'场景外观档案':'道具外观档案'}</strong><button disabled={busy||!scriptReady||!enrichmentReady||!!asset.variant} onClick={()=>job('asset_enrich',asset.id)}><Sparkles size={14}/>AI 补充描述</button>{!enrichmentReady&&<small className="muted">等待服务加载描述与提示词联合生成功能；运行中的任务保留。</small>}</div>
  <small className="muted">上方统一提取剧本元素；本按钮一次补全描述并按所选图片模型生成提示词，共用剧本上下文。已有特征保留，完成后可直接生成预览。{character?'性格指导神态与表演，经历另存剧情备注。':''}</small>
  {!scriptReady&&<small className="muted">请先完成剧本，再补充描述；也可手动填写外观。</small>}
  {asset.source_cache?.excerpt&&<details><summary>查看本元素的剧本资料缓存</summary><small className="muted">归集本元素描写后综合评估，剧情依据另存。</small>{asset.source_cache.observations?.length>0?<pre className="document">{asset.source_cache.observations.join('\n')}</pre>:<small className="muted">尚无可逐字核实的明确特征。</small>}<details><summary>相关段落与上下文</summary><pre className="document">{asset.source_cache.excerpt}</pre></details></details>}
  {asset.visual_profile&&(asset.profile_stale||asset.profile_source_type!=='script')&&<p className="muted">现有档案尚未按当前剧本更新，请在上方统一提取核对。</p>}
  {legacySummary&&<details className="feature-group"><summary>已有描述 · 手动保留</summary><textarea aria-label="已有外观描述" rows={4} value={legacySummary} onChange={e=>editAsset(asset.id,a=>{if(character){delete a.visual_profile}else{a.visual_profile=grouped(a);a.visual_profile.user_summary=e.target.value}a.description=e.target.value;a.visual_description_source='user';a.prompt='';a.prompt_zh='';(a.previews||[]).forEach((m:Obj)=>m.stale=true)})}/><small>编辑下方分类字段后，将采用分类外观描述。</small></details>}
  {Object.entries(schema[asset.kind]).map(([group,spec]:[string,any],index)=>{
   const filled=Object.values(profile.groups[group].fields).filter((v:any)=>v.value&&v.source!=='unknown').length;
   const preview=values(profile,Object.keys(spec.fields).map(k=>group+'.'+k));
   return <details className={'feature-group '+(group==='personality'?'personality-group':'')} key={group}>
    <summary><span>{group==='personality'?'性格与行为倾向':`${index+1}. ${spec.label}`}</span><small>{filled}/{Object.keys(spec.fields).length} 项</small></summary>
    {preview&&<p className="feature-preview">{preview}</p>}
    {group==='personality'&&<small>稳定性格、社交方式、情绪反应、习惯和动机；图片仅采用克制的气质表达。</small>}
    <div className="character-fields">{Object.entries(spec.fields).map(([key,title])=>{
     const item=profile.groups[group].fields[key];
     return <label key={key}>{String(title)} <span className={'trait-source '+item.source}>{item.source==='explicit'&&asset.profile_source_type!=='script'?'旧依据 · 待剧本核对':sourceNames[item.source]||'剧本未指定'}</span><textarea aria-label={spec.label+' · '+title} rows={2} value={item.value||''} placeholder="未指定；可补充并保存为用户设定" onChange={e=>change(group,key,e.target.value)}/>{item.evidence&&<small>{asset.profile_source_type==='script'?'剧本依据':'旧档案依据，待核对'}：{item.evidence}</small>}{item.source_note&&<small>{item.source_note}</small>}</label>
    })}</div>
   </details>
  })}
  {asset.description&&<details><summary>合并外观描述 · 用于图片提示词</summary><p className="feature-preview">{asset.description}</p></details>}
  {profile.other_age_stages?.length>0&&<details><summary>其他年龄阶段 · 单独设定</summary>{profile.other_age_stages.map((s:Obj,i:number)=><p key={i}>{s.label} · {s.age} · {s.note}</p>)}</details>}
  {asset.narrative_context&&<details><summary>剧情与叙述备注 · 不用于元素出图</summary><textarea aria-label="剧情与叙述备注" rows={4} value={asset.narrative_context} onChange={e=>editAsset(asset.id,a=>a.narrative_context=e.target.value)}/></details>}
 </section>
}
