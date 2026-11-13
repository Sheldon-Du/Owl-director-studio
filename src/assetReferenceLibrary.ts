import {assetPreviewVersions} from './assetPreviewVersions';
type Obj=Record<string,any>;
export function assetReferenceLibrary(project:Obj){
 const choices=new Map<string,Obj>();
 for(const asset of project.assets||[]){
  const role=asset.kind==='character'?'identity':asset.kind==='scene'?'environment':'prop';
  for(const image of [...assetPreviewVersions(asset),...(asset.references||[]),...(asset.adopted?[{media:asset.adopted}]:[])]){
   if(image.media&&!choices.has(image.media))choices.set(image.media,{media:image.media,asset_id:asset.id,label:asset.name,category:asset.kind,role,adopted:asset.adopted===image.media});
  }
 }
 for(const image of project.media||[])if(image.kind==='image'&&image.media&&!choices.has(image.media))choices.set(image.media,{media:image.media,label:image.name||image.filename||image.media,category:'library',role:'style',adopted:false});
 return Array.from(choices.values());
}
