import React,{useEffect,useState} from 'react';
import {SourcePages} from './SourcePreview';
type Obj=Record<string,any>;
async function api(path:string,body?:Obj){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const v=await r.json();if(!r.ok)throw Error(v.detail||'本地识别请求失败');return v}
export function LocalOCRSettings({locked,ready,notify}:{locked:boolean;ready:(v:boolean)=>void;notify:(v:string)=>void}){
 const [info,setInfo]=useState<Obj>({}),[cfg,setCfg]=useState<Obj>({gpu:0,dpi:200}),[working,setWorking]=useState(false);
 const refresh=async()=>{try{const v=await api('/api/local-ocr');setInfo(v);setCfg(v.settings);ready(v.ready)}catch(e){notify((e as Error).message)}};
 useEffect(()=>{void refresh()},[]);
 const save=async()=>{setWorking(true);try{const v=await api('/api/local-ocr/settings',cfg);setInfo(v);ready(v.ready);notify('本地识别设置已保存')}catch(e){notify((e as Error).message)}finally{setWorking(false)}};
 return <aside className="medical-card"><h4>百度 Unlimited-OCR · 本地识别</h4><p>{info.message||'正在检查本地识别环境'}</p><p className="muted">PDF 在本机显卡上逐页识别，保留页码和识别结果，支持失败续跑。识别内容仍需核对表格、数字、单位和否定词。</p><div className="medical-grid"><label>识别显卡<select disabled={locked} value={cfg.gpu} onChange={e=>setCfg(c=>({...c,gpu:Number(e.target.value)}))}><option value={0}>0 号显卡</option><option value={1}>1 号显卡</option></select></label><label>页面清晰度<select disabled={locked} value={cfg.dpi} onChange={e=>setCfg(c=>({...c,dpi:Number(e.target.value)}))}>{[150,200,300].map(v=><option key={v} value={v}>{v} DPI</option>)}</select></label></div><div className="row wrap"><button disabled={locked||working} onClick={save}>保存识别设置</button><button disabled={working} onClick={refresh}>刷新模型状态</button></div></aside>
}
export function SourceOCR({source,locked,ready,act,sourceBase}:{source:Obj;locked:boolean;ready:boolean;act:(path:string)=>void;sourceBase:string}){
 if(!source.media?.toLowerCase().endsWith('.pdf'))return null;
 const result=source.ocr_candidate;
 return <div className="medical-ocr"><p>{source.extraction==='unlimited-ocr-local'?'当前使用本地 OCR 文字。':'文字缺失、扫描件或提取顺序不佳时，可使用本地 OCR。'}识别结果先保存为候选，采用后更新资料文字。</p><button disabled={locked||!ready} onClick={()=>act(`/sources/${source.id}/ocr`)}>{result?'重新识别（复用已完成页）':'本地 OCR 识别全部页'}{source.page_count?` · ${source.page_count} 页`:''}</button>{result&&<div className="medical-card"><h5>本地识别候选 · {result.page_count} 页</h5><p>{result.current?'可预览并采用':'资料已变化，此结果仅供参考，请重新识别'}</p><details><summary>预览 OCR 全文 · {result.blocks.length} 个文本块</summary><SourcePages blocks={result.blocks} pages={result.pages} sourceBase={sourceBase}/></details>{result.warnings.map((w:string,i:number)=><p key={i}>{w}</p>)}<button disabled={locked||!result.current} onClick={()=>act(`/sources/${source.id}/ocr/adopt`)}>采用 OCR 文字并更新资料</button></div>}</div>
}
