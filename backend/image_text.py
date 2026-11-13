"""Literal in-image text and its placement, using Image2.1's quotation rules."""
import json,re

RULE='Image2.1 in-image text: every specified readable string is enclosed in ASCII double quotes, copied character for character in its original script, punctuation and spacing. Describe its placement, lettering style, colour and the surface carrying it. Keep it legible. Do not translate, paraphrase or invent additional text; description headings are not lettering in the image.'

def normalize(text):
    text=re.sub(r'[“「『]([^”」』\n]*)[”」』]',lambda m:json.dumps(m[1],ensure_ascii=False),text)
    # Common literal signage directives in existing Chinese 5S cards.
    pattern=r'((?:牌匾|招牌|标牌|路牌|标签|屏幕|海报)(?:上)?(?:写着|写有|印着|印有|刻着|题写|标有|显示文字|内容为|文字为)\s*[:：]?\s*)([^，。；;\n]+)'
    def quote(m):
        value=m[2].strip()
        if value.startswith('"'):return m[0]
        return m[1]+json.dumps(value,ensure_ascii=False)
    return re.sub(pattern,quote,text)

def apply(asset,text):
    value=asset.get('image_text') or {}
    if not isinstance(value,dict):value={}
    lines=[s for s in str(value.get('content','')).splitlines() if s.strip()]
    text=normalize(text)
    if lines:
        location=str(value.get('placement','')).strip()
        description='The specified text '+('at '+location+' ' if location else 'on the text-bearing surface in the image ')+'reads '+', '.join(json.dumps(s,ensure_ascii=False) for s in lines)+'. '
        description+='Its lettering style, colour and material match the specified setting, with clear readable characters.'
        description+=' These explicitly specified strings take precedence over generic restrictions on text.'
        text+='\n\n'+description
    return text+'\n\n'+RULE
