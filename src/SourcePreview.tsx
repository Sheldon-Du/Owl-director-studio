import React,{useState} from 'react';
import {ReferenceText} from './ReferenceText';
type Obj=Record<string,any>;

// Build React elements from an inert template. Never insert OCR HTML into the
// live document or copy links, styles, event handlers, images or executable tags.
function tableView(markup:string,key:number){
 const template=document.createElement('template');template.innerHTML=markup;
 const allowed=new Set(['table','thead','tbody','tfoot','tr','td','th','caption','strong','b','em','i','sub','sup','br']);
 function node(n:Node,k:number,depth=0):React.ReactNode{
  if(n.nodeType===Node.TEXT_NODE)return <ReferenceText key={k} text={n.textContent||''}/>;
  if(n.nodeType!==Node.ELEMENT_NODE||depth>60)return null;
  const el=n as Element,tag=el.tagName.toLowerCase();
  if(['script','style','iframe','object','embed','img','svg','math','template'].includes(tag))return null;
  const children=Array.from(el.childNodes).map((c,i)=>node(c,i,depth+1));
  if(!allowed.has(tag))return <React.Fragment key={k}>{children}</React.Fragment>;
  const props:Obj={key:k};
  if(tag==='td'||tag==='th')for(const [attr,prop] of [['colspan','colSpan'],['rowspan','rowSpan']]){
   const v=el.getAttribute(attr)||'';if(/^\d{1,2}$/.test(v)&&Number(v)>0)props[prop]=Number(v);
  }
  return React.createElement(tag,props,tag==='br'?undefined:children);
 }
 return <div className="medical-table-scroll" role="region" aria-label="OCR 表格，可横向滚动" tabIndex={0} key={key}>{Array.from(template.content.childNodes).map((n,i)=>node(n,i))}</div>;
}

export function ReadableSource({text}:{text:string}){
 const parts:React.ReactNode[]=[];let offset=0;
 for(const match of text.matchAll(/<table\b[^>]*>[\s\S]*?<\/table\s*>/gi)){
  const start=match.index!;
  if(start>offset)parts.push(<div className="medical-readable-text" key={'text'+offset}><ReferenceText text={text.slice(offset,start)}/></div>);
  parts.push(tableView(match[0],start));offset=start+match[0].length;
 }
 if(offset<text.length)parts.push(<div className="medical-readable-text" key={'text'+offset}><ReferenceText text={text.slice(offset)}/></div>);
 return <div className="medical-readable-source">{parts}</div>;
}

function pageBody(raw:string){
 let image=false;const lines:string[]=[];
 for(const line of raw.split('\n')){
  const s=line.trim();
  const match=s.match(/^<\|ref\|>(.*?)<\|\/ref\|><\|det\|>.*?<\|\/det\|>(.*)$/)||s.match(/^<\|det\|>([\w-]+).*?<\|\/det\|>(.*)$/);
  if(match){image=match[1].trim()==='image';if(!image)lines.push('',match[2]);}
  else if(!image)lines.push(line);
 }
 return lines.join('\n').replaceAll('<｜end▁of▁sentence｜>','').trim();
}

function OriginalPage({base,page}:{base:string;page:number}){
 const [open,setOpen]=useState(false),[failed,setFailed]=useState(false);
 const url=`${base}/pages/${page}/preview`;
 return <details className="medical-page-image" onToggle={e=>setOpen(e.currentTarget.open)}><summary>查看本页原图（含插图、流程图与表格）</summary>{open&&<><p className="muted">原 PDF 页面图片，可与下方识别文字对照。点击图片可打开大图。</p>{failed?<p>图片暂时无法显示，请点击“查看原文件”核对。</p>:<a href={url} target="_blank" rel="noreferrer"><img src={url} alt={`物理第 ${page} 页原图，含本页图表`} loading="lazy" onError={()=>setFailed(true)}/></a>}</>}</details>;
}
export function SourcePages({blocks,pages,sourceBase}:{blocks:Obj[];pages?:Obj[];sourceBase?:string}){
 // Use whole-page OCR output so a long table split across source blocks is
 // reconstructed without losing a closing tag or a row at the boundary.
 const views=pages?.length?pages.map(p=>({page:p.page,text:pageBody(p.raw||'')})):
  Array.from(new Set(blocks.map(b=>b.page))).map(page=>({page,text:blocks.filter(b=>b.page===page).map(b=>b.text).join('\n')}));
 return <>{views.map((p,i)=><section className="medical-source-page" key={i}><h5>{p.page?`物理第 ${p.page} 页`:'原文资料'}</h5>{sourceBase&&p.page&&<OriginalPage base={sourceBase} page={p.page}/>}<ReadableSource text={p.text}/><details><summary>查看原始识别文字与表格标记</summary><pre className="medical-source">{p.text}</pre></details></section>)}</>;
}
