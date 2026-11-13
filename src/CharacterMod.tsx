type Obj=Record<string,any>;
export function CharacterMod({asset,busy,job}:{asset:Obj;busy:boolean;job:(kind:string,target?:string,options?:Obj)=>void}){
  const mod=asset.character_mod;
  const ready=mod?.status==='ready'&&mod.source_media===asset.adopted;
  return <section className="character-mod-controls">
    <button disabled={busy||!asset.adopted} onClick={()=>job('character_mod',asset.id,{source_media:asset.adopted})}>{ready?'重新制作角色 mod':'制作角色 mod'}</button>
    {ready?<span className="pill">mod 已制作</span>:mod&&<small className="muted">采用图已更换，需重新制作 mod。</small>}
    <small className="muted">使用已采用图片生成八视图并放大，自动保存角色 mod。H3 分镜引用该角色时使用 mod 的视频参考模式。</small>
  </section>
}
