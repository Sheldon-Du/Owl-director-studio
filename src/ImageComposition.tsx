type Obj=Record<string,any>;
export function ImageComposition({asset,editAsset,busy}:{asset:Obj;editAsset:(id:string,fn:(a:Obj)=>void)=>void;busy:boolean}){
  if(asset.kind==='character')return <details className="asset-generation-settings"><summary>输出构图 · 四宫格角色卡</summary><small className="muted">首次直接生成竖版四宫格：左上正脸近景，右上90°侧脸近景，左下无五官正面全身，右下180°背面全身。统一灰背景、柔和光照、原画风和服装，不添加文字。无需先采用单张角色图。</small></details>;
  const config=asset.image_composition||{};
  const mode=config.mode||'auto';
  const defaults:Obj={character:'单人正面全身',scene:'单张场景全景',prop:'单件道具'};
  function change(key:string,value:string){editAsset(asset.id,a=>{a.image_composition={...(a.image_composition||{}),[key]:value}})}
  return <details className="asset-generation-settings image-composition"><summary>输出构图 · {mode==='free'?'沿用描述':mode==='character_portrait'?'单人肖像':mode==='character_full'?'单人全身':mode==='scene_single'?'单张场景':mode==='prop_single'?'单件道具':defaults[asset.kind]||'单张画面'}</summary>
    <label>画面形式<select aria-label={asset.name+' · 输出构图'} disabled={busy} value={mode} onChange={e=>change('mode',e.target.value)}>
      <option value="auto">按资产类型 · {defaults[asset.kind]||'单张画面'}（默认）</option>
      {asset.kind==='character'&&<><option value="character_full">单人正面全身 · 角色基准图</option><option value="character_portrait">单人正面肖像 · 面部基准图</option></>}
      {asset.kind==='scene'&&<option value="scene_single">单张完整场景</option>}
      {asset.kind==='prop'&&<option value="prop_single">单件完整道具</option>}
      <option value="free">沿用描述 · 允许组合与多视角</option>
    </select></label>
    {mode!=='free'&&asset.kind!=='scene'&&<label>背景<select aria-label={asset.name+' · 输出背景'} disabled={busy} value={config.background||'white'} onChange={e=>change('background',e.target.value)}><option value="white">纯白背景</option><option value="original">沿用 5S 背景</option></select></label>}
    <label>构图补充<textarea aria-label={asset.name+' · 构图补充'} disabled={busy} rows={2} value={config.notes||''} placeholder="例如：改为三分之四侧身，双手自然下垂；完整露出鞋子。" onChange={e=>change('notes',e.target.value)}/></label>
    <label>画面文字原文 · 每行一条<textarea aria-label={asset.name+' · 画面文字原文'} disabled={busy} rows={2} value={asset.image_text?.content||''} placeholder="例如：药铺（保留原语言与标点，不填写则不新增文字）" onChange={e=>editAsset(asset.id,a=>{a.image_text={...(a.image_text||{}),content:e.target.value}})}/></label>
    <label>文字位置与字样<input aria-label={asset.name+' · 文字位置与字样'} disabled={busy} value={asset.image_text?.placement||''} placeholder="例如：店铺门楣的木匾上，黑色楷体" onChange={e=>editAsset(asset.id,a=>{a.image_text={...(a.image_text||{}),placement:e.target.value}})}/></label>
    <small className="muted">画面文字按 Image2.1 规则自动用英文双引号标注原文，并描述位置和字样；不会把 5S 字段标题印进图片。</small>
    <small className="muted">{mode==='free'?'使用原描述中的构图安排。': '自动约束为单张连续画面，禁止拼贴、宫格和重复主体；5S 原文保留，生成时替换任务目标、镜头构图及所选背景。'} 构图补充优先于默认姿态和机位。设置用于单张资产预览，专用四宫格角色卡继续使用其布局。</small>
  </details>
}
