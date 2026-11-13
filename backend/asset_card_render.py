"""Render editable 5S asset cards directly, without an AI rewriting pass."""
from . import seedance_integration as seedance
from . import image_composition

def uses_card(asset):return isinstance(asset.get('card'),dict) and bool(asset['card'])

def prompt(asset,text_only=False):
    card=image_composition.card_for_render(asset,seedance.card(asset.get('card')))
    refs=[] if text_only else asset.get('references',[])
    prefix=''
    if refs and asset.get('model')=='qwen-image-2.1':
        if len(refs)==1:prefix='参考图像用于'+str(refs[0].get('role','身份与外观'))+'。'+str(refs[0].get('note',''))+'\n\n'
        else:prefix='参考图说明：\n'+'\n'.join(f"<image{i+1}> 用于{row.get('role','身份与外观')}：{row.get('note','')}" for i,row in enumerate(refs))+'\n\n'
    text=prefix+seedance.card_text(card)
    notes=str(asset.get('prompt_notes','')).strip()
    if notes:text+='\n\n人工补充与修改：'+notes
    return text

def dimensions(asset):
    from . import qwen_prompts
    settings=dict(asset)
    if not settings.get('wh_ratio') and not settings.get('ratio_follow'):
        settings['wh_ratio']={'character':'2:3','scene':'16:9','prop':'1:1'}.get(asset.get('kind'),'1:1')
    return qwen_prompts.dimensions(settings)
