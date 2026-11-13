import {useEffect,useRef,useState} from 'react';
import {jsonApi as api} from './jsonApi';
import {ProfessionalOptions} from './SeedanceTabs';
type Obj=Record<string,any>;
const categories:Obj={style:'风格',lighting:'光影',rendering:'渲染方式'};
const libraries=[['即梦探索','https://jimeng.jianying.com/ai-tool/explore'],['Liblib 灵感','https://www.liblib.art/inspiration'],['Civitai 图片','https://civitai.com/images'],['ArtStation 美术','https://www.artstation.com/search'],['PromptHero 精选','https://prompthero.com/featured'],['Midlibrary 艺术风格','https://midlibrary.io/art-styles']];
const empty=()=>({references:[],final:{style:'',lighting:'',rendering:''}} as Obj);

function VisionSettings({notify}:{notify:(s:string)=>void}){
 const [cfg,setCfg]=useState<Obj>({}),[loaded,setLoaded]=useState(false),[busy,setBusy]=useState(false);
 const load=async()=>{try{setCfg(await api('/settings'));setLoaded(true)}catch(e){notify((e as Error).message)}};
 const save=async()=>{setBusy(true);try{const body:Obj={vision_provider:cfg.vision_provider||'auto',vision_url:cfg.vision_url||'',vision_model:cfg.vision_model||''};if(cfg.vision_key)body.vision_key=cfg.vision_key;const r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.detail||'保存失败');notify('图片理解设置已保存');await load()}catch(e){notify((e as Error).message)}finally{setBusy(false)}};
 return <details className="art-vision-settings" onToggle={e=>{if(e.currentTarget.open&&!loaded)load()}}><summary>图片理解接口 · 默认复用 Owl AI</summary><p className="muted">M3 等视觉模型可直接看图；MiniMax M2 使用独立图片理解。也可指定其他兼容视觉接口。仅在接口来源相同时复用文本 AI 密钥。</p><div className="parameter-grid"><label>接口类型<select value={cfg.vision_provider||'auto'} onChange={e=>setCfg({...cfg,vision_provider:e.target.value})}><option value="auto">自动 · 复用 Owl</option><option value="chat">兼容多模态聊天接口</option><option value="minimax">MiniMax Coding Plan 图片理解</option></select></label><label>专用接口地址（可选）<input value={cfg.vision_url||''} onChange={e=>setCfg({...cfg,vision_url:e.target.value})} placeholder="留空复用现有 AI 地址"/></label><label>视觉模型名称（可选）<input value={cfg.vision_model||''} onChange={e=>setCfg({...cfg,vision_model:e.target.value})} placeholder="留空复用现有模型"/></label><label>专用密钥（可选）<input type="password" value={cfg.vision_key||''} onChange={e=>setCfg({...cfg,vision_key:e.target.value})} placeholder={cfg.has_vision_key?'已有密钥，留空保留':'相同接口可复用现有密钥'}/></label></div><button disabled={busy||!loaded} onClick={save}>保存图片理解设置</button></details>;
}

export function ArtWorkspace({project,catalog,edit,save,changed,notify,busy}:{project:Obj;catalog:Obj;edit:(fn:(p:Obj)=>void)=>void;save:()=>Promise<Obj>;changed:(p:Obj)=>void;notify:(s:string)=>void;busy:boolean}){
 const [draft,setDraft]=useState<Obj>(empty),[dirty,setDirty]=useState(false),[working,setWorking]=useState(false);
 const [prompt,setPrompt]=useState(''),[url,setUrl]=useState(''),[imageUrl,setImageUrl]=useState(''),[image,setImage]=useState(''),[file,setFile]=useState<File|null>(null),[preview,setPreview]=useState(''),[mode,setMode]=useState('style'),[inferred,setInferred]=useState('');
 const draftProject=useRef(project.id);
 const savedDraft=JSON.stringify(project.art_references?.draft||empty());
 useEffect(()=>{const switched=draftProject.current!==project.id;draftProject.current=project.id;if(switched||!dirty){setDraft(JSON.parse(savedDraft));setDirty(false)}},[project.id,savedDraft]);
 useEffect(()=>{setPrompt('');setUrl('');setImageUrl('');setImage('');setFile(null)},[project.id]);
 useEffect(()=>{if(!file){setPreview('');return}const path=URL.createObjectURL(file);setPreview(path);return()=>URL.revokeObjectURL(path)},[file]);
 const candidate=project.art_references?.image_candidate;
 useEffect(()=>setInferred(candidate?.inferred_prompt||''),[candidate?.id]);
 const update=(fn:(d:Obj)=>void)=>{const d=structuredClone(draft);fn(d);setDraft(d);setDirty(true)};
 const locked=busy||working;
 const commit=async(action:string,nextDraft?:Obj)=>{
  setWorking(true);
  try{
   let p=await save();
   if(dirty||nextDraft||action==='save-draft'){p=(await api(`/projects/${p.id}/visual/save-draft`,{revision:p.revision,draft:nextDraft||draft})).project;changed(p);setDraft(structuredClone(p.art_references?.draft||empty()));setDirty(false)}
   if(action==='save-draft'){notify(nextDraft?'参考已删除并保存；已应用风格需另行更新':'参考草稿已保存');return}
   const body:Obj={revision:p.revision};
   if(['import','analyze-image'].includes(action)){
    if(file){const form=new FormData();form.append('file',file);const response=await fetch('/api/upload',{method:'POST',body:form});const value=await response.json();if(!response.ok)throw Error(value.detail||'上传失败');body.uploaded_image=value.media;}
    Object.assign(body,{prompt,source_url:url,image,image_url:imageUrl,mode});
   }
   if(action==='adopt-image')Object.assign(body,{candidate_id:candidate?.id,inferred_prompt:inferred});
   const value=await api(`/projects/${p.id}/visual/${action}`,body);changed(value.project);setDraft(structuredClone(value.project.art_references?.draft||empty()));setDirty(false);
   if(action==='import'){setPrompt('');setImageUrl('');setImage('');setFile(null)}
   if(action==='analyze-image'){setImage(value.project.art_references.image_candidate.image);setFile(null);setImageUrl('')}
   const messages:Obj={import:'已保存原图与原始提示词，并提取三类美术参考',compose:'已整理最终风格草稿，请检查后应用',apply:'已应用美术版本，资产及下游成果需要更新','clear-applied':'已恢复默认美术，历史版本保留','save-draft':'参考草稿已保存','analyze-image':'已按真实图片生成推测候选，请核对后保存为参考','adopt-image':'图片分析结果已保存为参考，尚未正式应用'};
   notify(messages[action]||'已保存');
  }catch(e){notify((e as Error).message)}finally{setWorking(false)}
 };
 const readDetail=async()=>{setWorking(true);try{const value=await api('/visual/jimeng/detail',{url});setPrompt(value.prompt);setImageUrl(value.image_url);setImage('');setFile(null);notify('已读取公开原图与提示词，请核对后导入')}catch(e){notify((e as Error).message)}finally{setWorking(false)}};
 const selectedPreview=preview||(image?'/media/'+encodeURIComponent(image):imageUrl);
 return <>
  <section className="panel art-workspace">
   <div className="workspace-heading"><div><span className="workspace-kicker">VISUAL REFERENCES</span><h2>美术风格</h2><p>参考只改变视觉表达，角色身份与故事事实保持原样。</p></div><span className="workspace-chip">{project.art_references?.applied?'已应用版本 · '+project.art_references.applied.id.slice(0,8):'采用剧本与 Skill 默认美术'}</span></div>
   <div className="art-library-links" aria-label="美术参考库">{libraries.map(([name,link])=><a key={link} href={link} target="_blank" rel="noreferrer">{name} ↗</a>)}</div>
   <section className="art-import">
    <h3>添加图片参考</h3>
    <div className="art-entry-grid"><div>
     <label>上传参考图片<input type="file" accept="image/png,image/jpeg,image/webp" disabled={locked} onChange={e=>{setFile(e.target.files?.[0]||null);setImage('');setImageUrl('');setUrl('')}}/></label>
     <label>或选用素材库图片<select value={image} disabled={locked} onChange={e=>{setImage(e.target.value);setFile(null);setImageUrl('');setUrl('')}}><option value="">选择图片</option>{(project.media||[]).filter((m:Obj)=>m.kind==='image').map((m:Obj)=><option key={m.media} value={m.media}>{m.name||m.media}</option>)}</select></label>
     {selectedPreview&&<img className="art-import-preview" src={selectedPreview} alt="待分析参考图片" referrerPolicy="no-referrer"/>}
    </div><div><label>原始提示词 · 保留手动输入<textarea rows={5} aria-label="参考图原始提示词" value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="直接填写原始提示词即可提取，图片可选；没有提示词时，使用下方图片分析。"/></label><button disabled={locked||!prompt.trim()} onClick={()=>commit('import')}>从原始提示词提取并保存参考</button><p className="muted">填写提示词即可提取，图片可选。{locked?'当前项目正在处理任务，完成后可操作。':''}</p>
     <label>图片分析目标<select aria-label="图片分析目标" disabled={locked} value={mode} onChange={e=>setMode(e.target.value)}><option value="style">只推测美术风格 · 风格 / 光影 / 渲染</option><option value="full">反推完整生图提示词</option></select></label>
     <button className="primary" disabled={locked||!(file||image)} onClick={()=>commit('analyze-image')}>{working?'正在处理…':'AI 看图分析'}</button><p className="muted">通过已配置的图片理解 AI 分析。结果先作为候选，保存为参考后仍需单独正式应用。</p>
    </div></div>
    <details><summary>通过图片详情链接导入（可选）</summary><label>即梦图片详情链接<input aria-label="即梦图片详情链接" value={url} onChange={e=>setUrl(e.target.value)}/></label><button disabled={locked||!url.trim()} onClick={readDetail}>读取图片与提示词</button><label>原图链接<input value={imageUrl} onChange={e=>{setImageUrl(e.target.value);setImage('');setFile(null)}}/></label></details>
    <VisionSettings notify={notify}/>
   </section>
   {candidate&&<section className="art-analysis-candidate"><div className="section-title"><h3>图片分析候选 · {candidate.mode==='full'?'完整提示词反推':'美术风格推测'}</h3><span className="pill">AI 推测 · 待核对</span></div><p className="muted">这是根据图片推测的描述，不代表真实原始提示词或实际渲染引擎。</p><div className="art-reference-columns"><img className="art-reference-image" src={'/media/'+encodeURIComponent(candidate.image)} alt="分析原图"/>{Object.entries(categories).map(([k,label])=><div className={'art-category art-'+k} key={k}><strong>{String(label)}</strong><p>{candidate.terms[k]||'未观察到'}</p></div>)}</div>{candidate.mode==='full'&&<label>反推生图提示词 · 可修改<textarea rows={6} aria-label="反推生图提示词" value={inferred} onChange={e=>setInferred(e.target.value)}/><button onClick={()=>navigator.clipboard.writeText(inferred).then(()=>notify('已复制反推提示词')).catch(()=>notify('复制失败，请手动选取'))}>复制提示词</button></label>}{candidate.notes?.map((note:string,i:number)=><p className="muted" key={i}>{note}</p>)}<button disabled={locked} onClick={()=>commit('adopt-image')}>核对后保存为参考</button></section>}
   <p className="muted">每条参考从左到右：图片、风格、光影、渲染。兼容词汇可合并；同维度冲突时优先采用列表中第一条保留项。</p>
   <div className="art-reference-grid">{draft.references.map((r:Obj,i:number)=><article className="art-reference-card" key={r.id}>
    <div className="section-title"><h3>参考 {i+1}{r.source_kind==='image_inference'&&<small> · AI 推测</small>}</h3><div className="row"><button disabled={locked||i===0} onClick={()=>update(d=>{[d.references[i-1],d.references[i]]=[d.references[i],d.references[i-1]]})}>上移</button><button disabled={locked} aria-label={'删除参考 '+(i+1)} onClick={()=>{const next=structuredClone(draft);next.references=next.references.filter((v:Obj)=>v.id!==r.id);void commit('save-draft',next)}}>删除整条参考</button></div></div>
    <div className="art-reference-columns"><div className="art-reference-picture">{r.image?<img className="art-reference-image" src={'/media/'+encodeURIComponent(r.image)} alt={'参考 '+(i+1)}/>:<div className="art-reference-image muted" style={{display:'grid',placeItems:'center'}}>文字参考 · 未附图片</div>}</div>{Object.entries(categories).map(([key,label])=><label className={'art-category art-'+key} key={key}><span><input type="checkbox" checked={r.retained?.[key]!==false} disabled={locked} onChange={e=>update(d=>{d.references[i].retained??={};d.references[i].retained[key]=e.target.checked})}/>{String(label)}</span><textarea rows={5} disabled={locked} value={r.edited?.[key]||''} onChange={e=>update(d=>{d.references[i].edited[key]=e.target.value})}/></label>)}</div>
    <details><summary>原始依据与分析记录</summary>{r.source_url&&<a href={r.source_url} target="_blank" rel="noreferrer">查看来源 ↗</a>}<h4>{r.source_kind==='image_inference'?'AI 反推提示词':'原始提示词'}</h4><pre className="document">{r.source_kind==='image_inference'?r.inferred_prompt||'仅推测美术风格，未反推主体与场景':r.original_prompt}</pre>{r.analysis?.notes?.map((note:string,j:number)=><p key={j}>{note}</p>)}<h4>初次提取</h4>{Object.entries(categories).map(([k,label])=><p key={k}>{String(label)}：{r.extracted?.[k]||'未提取'}</p>)}</details>
   </article>)}</div>
   <div className="row wrap"><button disabled={locked||!dirty} onClick={()=>commit('save-draft')}>保存参考草稿</button><button disabled={locked||!draft.references.length} onClick={()=>commit('compose')}>按优先顺序整理最终风格</button>{dirty&&<span className="muted">草稿有未保存修改</span>}</div>
   <h3>最终美术风格 · 草稿</h3><div className="art-final-grid">{Object.entries(categories).map(([k,label])=><label className={'art-category art-'+k} key={k}>{String(label)}<textarea aria-label={'最终'+label} rows={5} value={draft.final[k]||''} onChange={e=>update(d=>{d.final[k]=e.target.value})}/></label>)}</div>
   {!!draft.conflicts?.length&&<details open><summary>冲突处理记录</summary>{draft.conflicts.map((v:string,i:number)=><p key={i}>{v}</p>)}</details>}
   <div className="row wrap"><button className="primary" disabled={locked||!Object.values(draft.final).some(Boolean)} onClick={()=>commit('apply')}>正式应用当前风格</button>{project.art_references?.applied&&<button disabled={locked} onClick={()=>commit('clear-applied')}>恢复默认美术</button>}</div>
   {project.art_references?.applied&&<details open><summary>当前已应用版本 · 生成仅参考这里</summary>{Object.entries(categories).map(([k,label])=><p key={k}><strong>{String(label)}：</strong>{project.art_references.applied.categories[k]||'沿用剧本'}</p>)}</details>}
   {!!project.art_references?.history?.length&&<details><summary>已应用版本历史</summary>{project.art_references.history.map((v:Obj)=><section key={v.id}><small>{v.id.slice(0,8)} · {new Date(v.created*1000).toLocaleString()}</small>{Object.entries(categories).map(([k,label])=><p key={k}>{String(label)}：{v.categories[k]}</p>)}</section>)}</details>}
  </section><ProfessionalOptions project={project} catalog={catalog} edit={edit} modules={['art']}/>
 </>;
}
