"""Keep an asset's output layout separate from its identity and 5S archive."""
import copy

DEFAULTS={'character':'character_full','scene':'scene_single','prop':'prop_single'}
SHOTS={
    'character_full':'One single person, shown exactly once in one continuous image. A single front-facing full-body view, head to soles entirely visible, feet inside the frame, centered standing pose, hands naturally at the sides, readable facial features. 单人正面全身，完整露出头顶和鞋底，双手自然垂放。',
    'character_portrait':'One single person, shown exactly once in one continuous image. A single front-facing head-and-shoulders portrait, complete hairstyle visible, clearly readable facial features. 单人正面肩上肖像，发型完整、脸部清晰。',
    'scene_single':'One continuous wide panoramic establishing image of the complete environment from one coherent camera viewpoint. Use a wide-angle, slightly elevated viewpoint where suitable to reveal as much useful spatial information as possible: the foreground, middle ground and background, full architectural boundaries, entrances and exits, circulation routes, major objects and their relative positions. Keep the main structures readable with clear depth and minimal occlusion; avoid cropped close-ups, exaggerated fisheye distortion and invented off-screen structures. 单张广角全景，必要时适度抬高机位，尽量完整展示前中后景、空间边界、出入口、通道及主要物体的位置关系。',
    'prop_single':'One single complete object, shown exactly once from one readable three-quarter view. Keep the entire object inside the frame and show its material and construction clearly. 单件完整道具，单一三分之四视角，材质和结构清晰。',
}
PROHIBITIONS='Single continuous image only. No collage, panels, split screen, contact sheet, character sheet, multiple views, inset close-ups, duplicate subjects or overlapping portraits. Add no captions or labels beyond the exact text explicitly specified in the asset description. 仅一张连续画面，禁止拼贴、宫格、分屏、多视角、局部插图和重复主体；只保留明确指定的画面文字，不额外添加标题或标签。'

def settings(asset):
    config=asset.get('image_composition') or {}
    if not isinstance(config,dict):config={}
    mode=config.get('mode','auto')
    if mode=='auto':mode=DEFAULTS.get(asset.get('kind'),'scene_single')
    if mode not in (*SHOTS,'free'):raise ValueError('未知图片构图设置')
    return mode,str(config.get('notes','')).strip(),config.get('background','white')

def rules(asset):
    mode,notes,background=settings(asset)
    if mode=='free':return notes
    text='OUTPUT COMPOSITION — use this layout for the final image; the asset description supplies identity, appearance and materials.\n'+SHOTS[mode]
    if mode in ('character_full','character_portrait','prop_single') and background=='white':
        text+='\nPure white seamless background. 纯白无缝背景。'
    text+='\n'+PROHIBITIONS
    if notes:text+='\nUser composition adjustments (take precedence over the default pose/view/background above): '+notes
    return text

def card_for_render(asset,card):
    result=copy.deepcopy(card)
    mode,notes,background=settings(asset)
    if mode!='free':
        # Do not feed a sheet's camera/layout directions into an identity image.
        # The original editable card remains untouched.
        result['goal']='制作一张独立的资产基准图。'
        result['shot']=SHOTS[mode]+ ('\n'+notes if notes else '')
        if mode in ('character_full','character_portrait','prop_single') and background=='white':
            result['setting']='纯白无缝背景，无其他人物、道具插图或环境拼贴。'
    return result

def constrain(asset,text):
    rule=rules(asset)
    if not rule:return text
    return rule+'\n\nASSET APPEARANCE / 资产外观：\n'+text+'\n\nFINAL OUTPUT COMPOSITION:\n'+rule
