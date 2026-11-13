export async function jsonApi(path:string,body?:Record<string,any>){
 const response=await fetch('/api'+path,{
  method:body?'POST':'GET',
  headers:{'Content-Type':'application/json'},
  body:body?JSON.stringify(body):undefined,
 });
 const value=await response.json();
 if(!response.ok)throw Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail));
 return value;
}
