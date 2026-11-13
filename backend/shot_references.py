"""Resolve a shot's selected example IDs to trusted visual guidance."""
import json
from functools import lru_cache

from . import store

CATEGORIES = {'lighting': '光影', 'cameraMovement': '运镜', 'composition': '构图'}
RULE = ('使用本镜勾选示例的光影、运镜和构图技法，将适用部分写进生成结果。'
        '只迁移技法，保留定稿时序、角色身份、剧情、对白、首尾状态及已有媒体约束。')
STILL_RULE = RULE + '静帧只取该时间点的机位和构图，不写镜头运动过程。'


@lru_cache(maxsize=1)
def catalogue():
    path = store.ROOT / 'src' / 'shotReferenceAssets.json'
    return {row['id']: row for row in json.loads(path.read_text(encoding='utf-8-sig'))}


def guidance(shot):
    ids = shot.get('shot_reference_ids')
    if not isinstance(ids, list) or not ids:
        return {}
    rows = catalogue()
    selected = {}
    for example_id in ids:
        row = rows.get(example_id) if isinstance(example_id, str) else None
        if row and row['category'] in CATEGORIES:
            selected[CATEGORIES[row['category']]] = row['promptZh']
    return selected
