import React from 'react';

// OCR citation notation only; arbitrary source text remains escaped React text.
export function ReferenceText({text}:{text:string}){
 const result:React.ReactNode[]=[];let offset=0;
 const pattern=/\\\(\s*\^\s*\{\s*(\[[\d\s,，、–—−-]+\])\s*\}\s*\\\)/g;
 for(const match of text.matchAll(pattern)){
  const start=match.index!;
  if(start>offset)result.push(text.slice(offset,start));
  result.push(<sup className="ocr-reference" key={start} title="原文参考文献编号">{match[1]}</sup>);
  offset=start+match[0].length;
 }
 if(offset<text.length)result.push(text.slice(offset));
 return <>{result}</>;
}
