type Obj=Record<string,any>;
const pending=new Map<string,Promise<Obj>>();
export function performanceRead(url:string):Promise<Obj>{
 const existing=pending.get(url);if(existing)return existing;
 const request=fetch(url).then(async response=>{const value=await response.json();if(!response.ok)throw Error(value.detail||'读取编排失败');return value}).finally(()=>pending.delete(url));
 pending.set(url,request);return request;
}
