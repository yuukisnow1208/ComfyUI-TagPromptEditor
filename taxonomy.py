# -*- coding: utf-8 -*-
"""TagPromptEditor 的语义分类器：把全量 Danbooru tag 归到「大类 / 小类 / 细类」。

背景：``danbooru.csv`` 只带一个 category 号（0 通用 / 1 画师 / 3 作品 /
4 角色 / 5 元数据），通用类里挤了 2.8 万条 —— ``long_hair``、``red_dress``、
``holding_sword``、``school_uniform`` 全在一个 tab 里，没法用。本模块给每一条
tag 打一个三级语义路径。

Danbooru tag 是 ``a_b_c`` 结构且**中心词在末尾**（``long_hair`` 的中心是
hair，``hair_bow`` 的中心是 bow），所以匹配按「整体名 → 末尾 n-gram →
逐词元（右→左）」逐级下沉，每级都带单复数变体：

    1. 类别例外   人工指定（banned_artist 这种词库标注本身就错的）
    2. 类别权威   画师 / 作品 / 角色 —— 专有名词，按词库分类直接定死
    3. 括号后缀   xxx_(cosplay) / xxx_(style)   —— 语义信号极强
    4. 精确表     整名命中
    5. 前缀表     holding_* / implied_*
    6. 正则层     1girl / 6+girls / ^_^
    7. 末尾候选   *_hair / *_eyes / head_tilt   —— 主力
    8. 颜色词     dark_blue
    9. 子串兜底   含 clothes / collar / frill   —— 吃长尾
   10. 兜底       cat 0 → 其它，cat 5 → 元数据    —— 保证 100% 有归属

第 2 步为什么必须在语义规则**之前**：画师 / 作品 / 角色是专有名词，名字里
出现通用词只是巧合。让语义规则先跑会把它们丢进随机桶 —— 实测误伤 7,000 余
条且集中在高热度 tag：

    the_legend_of_zelda     → 身体/腿部     （leg）
    fire_emblem             → 场景/元素     （emblem）
    neon_genesis_evangelion → 光影/光照     （neon）
    cloud_strife            → 天气时间/天气 （cloud）
    yae_miko                → 服饰/传统服饰 （miko）
    minato_aqua             → 色彩/颜色     （aqua）

它们不是「在描述那个词」，而是「名字恰好含那个词」。

实测覆盖（121,078 条）：未归类 7.53%，按使用热度加权仅 2.82%，且
使用量 >= 10 万的热门 tag 100% 归类。

本模块不依赖 ComfyUI，可单独跑单测。
"""
from __future__ import annotations

import re

__all__ = ["classify", "build_tree", "L1_ORDER", "popularity_band"]


# ---------------------------------------------------------------------------
# 分类树 L1 顺序
# ---------------------------------------------------------------------------

L1_ORDER = [
    "推荐", "质量词", "负面",
    "人物主体", "面部", "身体", "服饰", "姿势", "动作",
    "场景", "光影", "天气时间", "构图镜头", "风格画质", "色彩",
    "道具物件", "动植物", "文字符号", "成人内容",
    "画师", "角色", "作品", "元数据", "其它",
]


# ---------------------------------------------------------------------------
# 1. 括号后缀
# ---------------------------------------------------------------------------

SUFFIX_RULES = {
    "cosplay": ("元数据", "cosplay"),
    "meme": ("元数据", "梗图"),
    "style": ("风格画质", "画风"),
    "object": ("道具物件", "物件"),
    "food": ("道具物件", "食物"),
    "weapon": ("道具物件", "武器"),
    "armor": ("服饰", "铠甲"),
    "symbol": ("文字符号", "符号"),
    "emblem": ("文字符号", "符号"),
    "logo": ("文字符号", "标志"),
    "phrase": ("文字符号", "文字"),
    "character": ("元数据", "角色同名"),
    "series": ("元数据", "作品同名"),
    "artist": ("元数据", "画师同名"),
    "company": ("元数据", "公司"),
    "disambiguation": ("元数据", "消歧义"),
    "flower": ("动植物", "植物"),
    "animal": ("动植物", "动物"),
    "creature": ("动植物", "动物"),
    "constellation": ("其它", "星座"),
    "tarot": ("其它", "塔罗牌"),
    "module": ("其它", "模块"),
    "sound_effect": ("文字符号", "拟声词"),
    "sky": ("天气时间", "天气"),
    "star": ("天气时间", "天体"),
    "vehicle": ("道具物件", "载具"),
    "boat": ("道具物件", "载具"),
    "instrument": ("道具物件", "乐器"),
    "pokemon": ("作品",),
    "no_humans": ("人物主体", "人数构成"),
}


# ---------------------------------------------------------------------------
# 2. 精确表（整名命中）
# ---------------------------------------------------------------------------

EXACT_RULES = {
    # ===== 人数构成 =====
    "solo": ("人物主体", "人数构成"),
    "solo_focus": ("人物主体", "人数构成"),
    "multiple_girls": ("人物主体", "人数构成"),
    "multiple_boys": ("人物主体", "人数构成"),
    "male_focus": ("人物主体", "人数构成"),
    "no_humans": ("人物主体", "人数构成"),
    "crowd": ("人物主体", "人数构成"),
    "everyone": ("人物主体", "人数构成"),
    # ===== 性别 / 年龄 / 种族 =====
    "female": ("人物主体", "性别"),
    "male": ("人物主体", "性别"),
    "androgynous": ("人物主体", "性别"),
    "futanari": ("人物主体", "性别"),
    "trap": ("人物主体", "性别"),
    "child": ("人物主体", "年龄体型"),
    "children": ("人物主体", "年龄体型"),
    "teenager": ("人物主体", "年龄体型"),
    "adult": ("人物主体", "年龄体型"),
    "elderly": ("人物主体", "年龄体型"),
    "petite": ("人物主体", "年龄体型"),
    "muscular": ("人物主体", "年龄体型"),
    "chubby": ("人物主体", "年龄体型"),
    "obese": ("人物主体", "年龄体型"),
    "twins": ("人物主体", "关系"),
    "siblings": ("人物主体", "关系"),
    "family": ("人物主体", "关系"),
    "hetero": ("元数据", "题材"),
    "yuri": ("元数据", "题材"),
    "yaoi": ("元数据", "题材"),
    "kemonomimi": ("身体", "身体特征"),
    "monster_girl": ("人物主体", "种族"),
    "cat_girl": ("人物主体", "种族"),
    "fox_girl": ("人物主体", "种族"),
    "demon_girl": ("人物主体", "种族"),
    "dragon_girl": ("人物主体", "种族"),
    "angel": ("人物主体", "种族"),
    "demon": ("人物主体", "种族"),
    "elf": ("人物主体", "种族"),
    "vampire": ("人物主体", "种族"),
    "fairy": ("人物主体", "种族"),
    "ghost": ("人物主体", "种族"),
    "zombie": ("人物主体", "种族"),
    "mermaid": ("人物主体", "种族"),
    "slime": ("人物主体", "种族"),
    "deity": ("人物主体", "种族"),
    "goddess": ("人物主体", "种族"),
    "android": ("人物主体", "种族"),
    "robot": ("人物主体", "种族"),
    "ninja": ("服饰", "制服"),
    "nun": ("服饰", "制服"),
    "witch": ("服饰", "制服"),
    "maid": ("服饰", "制服"),
    "nurse": ("服饰", "制服"),
    "police": ("服饰", "制服"),
    "soldier": ("服饰", "制服"),
    "bride": ("服饰", "制服"),
    "virtual_youtuber": ("元数据", "题材"),
    # ===== 面部 =====
    "face": ("面部", "脸部"),
    "looking_at_viewer": ("构图镜头", "视线"),
    "looking_away": ("构图镜头", "视线"),
    "looking_back": ("构图镜头", "视线"),
    "looking_up": ("构图镜头", "视线"),
    "looking_down": ("构图镜头", "视线"),
    "looking_at_another": ("构图镜头", "视线"),
    "looking_to_the_side": ("构图镜头", "视线"),
    "eye_contact": ("构图镜头", "视线"),
    "head_tilt": ("姿势", "头部"),
    "blush": ("面部", "表情"),
    "smile": ("面部", "表情"),
    "open_mouth": ("面部", "嘴部"),
    "closed_mouth": ("面部", "嘴部"),
    "one_eye_closed": ("面部", "表情"),
    "sidelocks": ("面部", "头发"),
    "hair_between_eyes": ("面部", "头发"),
    "hair_intakes": ("面部", "头发"),
    "hair_ornament": ("服饰", "配饰"),
    "hair_ribbon": ("服饰", "配饰"),
    "hairband": ("服饰", "配饰"),
    "hair_bow": ("服饰", "配饰"),
    "hair_flower": ("服饰", "配饰"),
    "hairclip": ("服饰", "配饰"),
    "hair_bobbles": ("服饰", "配饰"),
    "hair_scrunchy": ("服饰", "配饰"),
    "hair_tubes": ("服饰", "配饰"),
    # 面部毛发：是「长在脸上的毛」，不是头发颜色。
    # 放进 EXACT 而不是别处，是因为末尾候选层会把多词词条当后缀复用，
    # 这样 black_facial_hair 也能通过末尾的 facial_hair 命中。
    "facial_hair": ("面部", "脸部"),
    "beard": ("面部", "脸部"),
    "mustache": ("面部", "脸部"),
    # 体毛：与 pubic_hair（身体/耻部）同族，但部位不同，单独成桶
    "armpit_hair": ("身体", "体毛"),
    "body_hair": ("身体", "体毛"),
    "chest_hair": ("身体", "体毛"),
    "arm_hair": ("身体", "体毛"),
    "leg_hair": ("身体", "体毛"),
    "nose_hair": ("身体", "体毛"),
    "sweatdrop": ("面部", "表情"),
    "sweat": ("身体", "状态"),
    "sparkle": ("光影", "特效"),
    "halo": ("身体", "身体特征"),
    # ===== 身体 =====
    "breasts": ("身体", "胸部"),
    "large_breasts": ("身体", "胸部"),
    "huge_breasts": ("身体", "胸部"),
    "gigantic_breasts": ("身体", "胸部"),
    "medium_breasts": ("身体", "胸部"),
    "small_breasts": ("身体", "胸部"),
    "flat_chest": ("身体", "胸部"),
    "cleavage": ("身体", "胸部"),
    "underboob": ("身体", "胸部"),
    "sideboob": ("身体", "胸部"),
    "navel": ("身体", "躯干"),
    "midriff": ("身体", "躯干"),
    "stomach": ("身体", "躯干"),
    "armpits": ("身体", "臂部"),
    "wrist": ("身体", "手部"),
    "groin": ("身体", "耻部"),
    "ass": ("身体", "臀部"),
    "nose": ("面部", "脸部"),
    "nude": ("身体", "状态"),
    "naked": ("身体", "状态"),
    "completely_nude": ("身体", "状态"),
    "topless": ("身体", "状态"),
    "bottomless": ("身体", "状态"),
    "barefoot": ("服饰", "鞋袜"),
    "bare_legs": ("身体", "腿部"),
    "bare_arms": ("身体", "臂部"),
    "bare_shoulders": ("身体", "肩部"),
    "thighhighs": ("服饰", "鞋袜"),
    "kneehighs": ("服饰", "鞋袜"),
    "pantyhose": ("服饰", "鞋袜"),
    "zettai_ryouiki": ("服饰", "鞋袜"),
    "nail_polish": ("身体", "手部"),
    "piercing": ("身体", "身体特征"),
    "fangs": ("面部", "嘴部"),
    "fang": ("面部", "嘴部"),
    "pointy_ears": ("身体", "身体特征"),
    "animal_ears": ("身体", "身体特征"),
    "animal_tail": ("身体", "身体特征"),
    "tail": ("身体", "身体特征"),
    "wings": ("身体", "身体特征"),
    "horns": ("身体", "身体特征"),
    "halo": ("身体", "身体特征"),
    "fur": ("身体", "身体特征"),
    "feathers": ("身体", "身体特征"),
    "scales": ("身体", "身体特征"),
    "tattoo": ("身体", "皮肤"),
    "scar": ("身体", "皮肤"),
    "tanlines": ("身体", "皮肤"),
    "tan": ("身体", "皮肤"),
    "body_writing": ("身体", "皮肤"),
    # ===== 服饰 =====
    "shirt": ("服饰", "上衣"),
    "skirt": ("服饰", "裙装"),
    "dress": ("服饰", "裙装"),
    "miniskirt": ("服饰", "裙装"),
    "microskirt": ("服饰", "裙装"),
    "pinafore": ("服饰", "裙装"),
    "sundress": ("服饰", "裙装"),
    "gown": ("服饰", "裙装"),
    "pants": ("服饰", "裤装"),
    "jeans": ("服饰", "裤装"),
    "shorts": ("服饰", "裤装"),
    "leggings": ("服饰", "裤装"),
    "overalls": ("服饰", "裤装"),
    "bloomers": ("服饰", "裤装"),
    "bow": ("服饰", "配饰"),
    "ribbon": ("服饰", "配饰"),
    "jewelry": ("服饰", "配饰"),
    "gloves": ("服饰", "配饰"),
    "hat": ("服饰", "配饰"),
    "collar": ("服饰", "配饰"),
    "neckerchief": ("服饰", "配饰"),
    "ascot": ("服饰", "配饰"),
    "sash": ("服饰", "配饰"),
    "cuffs": ("服饰", "配饰"),
    "wrist_cuffs": ("服饰", "配饰"),
    "detached_collar": ("服饰", "配饰"),
    "buttons": ("服饰", "配饰"),
    "frills": ("服饰", "配饰"),
    "lace": ("服饰", "配饰"),
    "fur_trim": ("服饰", "配饰"),
    "sailor_collar": ("服饰", "配饰"),
    "school_uniform": ("服饰", "制服"),
    "serafuku": ("服饰", "制服"),
    "sailor_dress": ("服饰", "制服"),
    "playboy_bunny": ("服饰", "制服"),
    "kimono": ("服饰", "传统服饰"),
    "yukata": ("服饰", "传统服饰"),
    "hanbok": ("服饰", "传统服饰"),
    "qipao": ("服饰", "传统服饰"),
    "cheongsam": ("服饰", "传统服饰"),
    "hanfu": ("服饰", "传统服饰"),
    "miko": ("服饰", "传统服饰"),
    "japanese_clothes": ("服饰", "传统服饰"),
    "chinese_clothes": ("服饰", "传统服饰"),
    "swimsuit": ("服饰", "泳装"),
    "bikini": ("服饰", "泳装"),
    "school_swimsuit": ("服饰", "泳装"),
    "lingerie": ("服饰", "内衣"),
    "panties": ("服饰", "内衣"),
    "bra": ("服饰", "内衣"),
    "underwear": ("服饰", "内衣"),
    "boxers": ("服饰", "内衣"),
    "garter_belt": ("服饰", "内衣"),
    "corset": ("服饰", "内衣"),
    "sarashi": ("服饰", "内衣"),
    "high_heels": ("服饰", "鞋袜"),
    "boots": ("服饰", "鞋袜"),
    "socks": ("服饰", "鞋袜"),
    "shoes": ("服饰", "鞋袜"),
    "footwear": ("服饰", "鞋袜"),
    "legwear": ("服饰", "鞋袜"),
    "stockings": ("服饰", "鞋袜"),
    "alternate_costume": ("服饰", "服装变体"),
    "official_alternate_costume": ("服饰", "服装变体"),
    "casual": ("服饰", "服装变体"),
    "formal": ("服饰", "服装变体"),
    "suit": ("服饰", "外套"),
    "hood": ("服饰", "上衣"),
    "capelet": ("服饰", "外套"),
    "cape": ("服饰", "外套"),
    "cloak": ("服饰", "外套"),
    "apron": ("服饰", "上衣"),
    "sleeveless": ("服饰", "上衣"),
    "strapless": ("服饰", "上衣"),
    "backless": ("服饰", "上衣"),
    "crop_top": ("服饰", "上衣"),
    "tube_top": ("服饰", "上衣"),
    "tank_top": ("服饰", "上衣"),
    "open_clothes": ("服饰", "着装状态"),
    "torn_clothes": ("服饰", "着装状态"),
    "clothes_lift": ("服饰", "着装状态"),
    "clothing_cutout": ("服饰", "着装状态"),
    "see-through_clothes": ("服饰", "着装状态"),
    "wet_clothes": ("服饰", "着装状态"),
    "dressed": ("服饰", "着装状态"),
    "undressed": ("服饰", "着装状态"),
    "plaid_clothes": ("服饰", "图案"),
    "striped_clothes": ("服饰", "图案"),
    "polka_dot": ("服饰", "图案"),
    "checkered_clothes": ("服饰", "图案"),
    # ===== 姿势 =====
    "sitting": ("姿势", "坐姿"),
    "standing": ("姿势", "站姿"),
    "lying": ("姿势", "卧姿"),
    "on_back": ("姿势", "卧姿"),
    "on_stomach": ("姿势", "卧姿"),
    "on_side": ("姿势", "卧姿"),
    "kneeling": ("姿势", "跪姿"),
    "squatting": ("姿势", "蹲姿"),
    "crossed_arms": ("姿势", "手部姿势"),
    "arms_up": ("姿势", "手部姿势"),
    "arms_behind_back": ("姿势", "手部姿势"),
    "arms_behind_head": ("姿势", "手部姿势"),
    "hand_on_hip": ("姿势", "手部姿势"),
    "hand_up": ("姿势", "手部姿势"),
    "legs_crossed": ("姿势", "腿部姿势"),
    "crossed_legs": ("姿势", "腿部姿势"),
    "legs_apart": ("姿势", "腿部姿势"),
    "v_sign": ("姿势", "手部姿势"),
    "peace_sign": ("姿势", "手部姿势"),
    "thumbs_up": ("姿势", "手部姿势"),
    "heart_hands": ("姿势", "手部姿势"),
    "two_side_up": ("姿势", "头发姿势"),
    "salute": ("姿势", "手部姿势"),
    "stretching": ("动作", "日常行为"),
    # ===== 动作 =====
    "holding": ("动作", "手部动作"),
    "hug": ("动作", "人际互动"),
    "hugging": ("动作", "人际互动"),
    "kiss": ("动作", "人际互动"),
    "kissing": ("动作", "人际互动"),
    "holding_hands": ("动作", "人际互动"),
    "carrying": ("动作", "手部动作"),
    "eating": ("动作", "日常行为"),
    "drinking": ("动作", "日常行为"),
    "sleeping": ("动作", "日常行为"),
    "reading": ("动作", "日常行为"),
    "writing": ("动作", "日常行为"),
    "cooking": ("动作", "日常行为"),
    "bathing": ("动作", "日常行为"),
    "dressing": ("动作", "日常行为"),
    "undressing": ("动作", "日常行为"),
    "walking": ("动作", "移动"),
    "running": ("动作", "移动"),
    "jumping": ("动作", "移动"),
    "flying": ("动作", "移动"),
    "riding": ("动作", "移动"),
    "dancing": ("动作", "表演"),
    "singing": ("动作", "表演"),
    "playing": ("动作", "日常行为"),
    "swimming": ("动作", "运动"),
    "fighting": ("动作", "战斗"),
    "battle": ("动作", "战斗"),
    "smoking": ("动作", "日常行为"),
    "reaching": ("动作", "手部动作"),
    "waving": ("动作", "手部动作"),
    "pointing": ("动作", "手部动作"),
    "staring": ("动作", "日常行为"),
    "yawning": ("动作", "日常行为"),
    "crying": ("面部", "表情"),
    "laughing": ("面部", "表情"),
    # ===== 场景 =====
    "simple_background": ("场景", "背景类型"),
    "white_background": ("场景", "背景类型"),
    "black_background": ("场景", "背景类型"),
    "grey_background": ("场景", "背景类型"),
    "gray_background": ("场景", "背景类型"),
    "blue_background": ("场景", "背景类型"),
    "red_background": ("场景", "背景类型"),
    "pink_background": ("场景", "背景类型"),
    "purple_background": ("场景", "背景类型"),
    "green_background": ("场景", "背景类型"),
    "yellow_background": ("场景", "背景类型"),
    "orange_background": ("场景", "背景类型"),
    "brown_background": ("场景", "背景类型"),
    "transparent_background": ("场景", "背景类型"),
    "gradient_background": ("场景", "背景类型"),
    "detailed_background": ("场景", "背景类型"),
    "blurry_background": ("场景", "背景类型"),
    "photo_background": ("场景", "背景类型"),
    "checkered_background": ("场景", "背景类型"),
    "striped_background": ("场景", "背景类型"),
    "two-tone_background": ("场景", "背景类型"),
    "outdoors": ("场景", "室外"),
    "indoors": ("场景", "室内"),
    "scenery": ("场景", "风景"),
    "landscape": ("场景", "风景"),
    "cityscape": ("场景", "室外"),
    "blue_sky": ("场景", "室外"),
    "night_sky": ("天气时间", "时间"),
    "starry_sky": ("天气时间", "天体"),
    "swimming_pool": ("场景", "室外"),
    "hot_spring": ("场景", "室外"),
    "onsen": ("场景", "室外"),
    "poolside": ("场景", "室外"),
    "bathroom": ("场景", "室内"),
    "bathtub": ("场景", "室内"),
    "bedroom": ("场景", "室内"),
    "classroom": ("场景", "室内"),
    "kitchen": ("场景", "室内"),
    "library": ("场景", "室内"),
    "office": ("场景", "室内"),
    "stage": ("场景", "室内"),
    "window": ("场景", "室内"),
    "mirror": ("场景", "室内"),
    "curtains": ("场景", "室内"),
    "stairs": ("场景", "室内"),
    "border": ("风格画质", "版式"),
    "abstract": ("风格画质", "画风"),
    "comic": ("元数据", "来源"),
    "multiple_views": ("构图镜头", "构图"),
    "profile": ("构图镜头", "视角"),
    "perspective": ("构图镜头", "视角"),
    "symmetry": ("构图镜头", "构图"),
    "chromatic_aberration": ("风格画质", "缺陷"),
    "motion_blur": ("光影", "特效"),
    "depth_of_field": ("构图镜头", "景深"),
    "close-up": ("构图镜头", "景别"),
    "portrait": ("构图镜头", "景别"),
    "upper_body": ("构图镜头", "景别"),
    "lower_body": ("构图镜头", "景别"),
    "full_body": ("构图镜头", "景别"),
    "cowboy_shot": ("构图镜头", "景别"),
    "wide_shot": ("构图镜头", "景别"),
    "from_above": ("构图镜头", "视角"),
    "from_below": ("构图镜头", "视角"),
    "from_side": ("构图镜头", "视角"),
    "from_behind": ("构图镜头", "视角"),
    "dutch_angle": ("构图镜头", "视角"),
    # ===== 光影 / 天气 时间 =====
    "cinematic_lighting": ("光影", "光照"),
    "soft_lighting": ("光影", "光照"),
    "backlighting": ("光影", "光照"),
    "rim_lighting": ("光影", "光照"),
    "volumetric_lighting": ("光影", "光照"),
    "dramatic_lighting": ("光影", "光照"),
    "god_rays": ("光影", "光照"),
    "bloom": ("光影", "特效"),
    "lens_flare": ("光影", "特效"),
    "bokeh": ("光影", "特效"),
    "reflection": ("光影", "特效"),
    "silhouette": ("光影", "特效"),
    "clouds": ("天气时间", "天气"),
    "cloudy_sky": ("天气时间", "天气"),
    "rain": ("天气时间", "天气"),
    "snow": ("天气时间", "天气"),
    "fog": ("天气时间", "天气"),
    "mist": ("天气时间", "天气"),
    "lightning": ("天气时间", "天气"),
    "sunset": ("天气时间", "时间"),
    "sunrise": ("天气时间", "时间"),
    "twilight": ("天气时间", "时间"),
    "daytime": ("天气时间", "时间"),
    "night": ("天气时间", "时间"),
    "moon": ("天气时间", "天体"),
    "sun": ("天气时间", "天体"),
    "stars": ("天气时间", "天体"),
    "summer": ("天气时间", "季节"),
    "winter": ("天气时间", "季节"),
    "spring": ("天气时间", "季节"),
    "autumn": ("天气时间", "季节"),
    # ===== 风格画质 =====
    "masterpiece": ("质量词", "正向"),
    "best_quality": ("质量词", "正向"),
    "high_quality": ("质量词", "正向"),
    "highres": ("质量词", "正向"),
    "absurdres": ("质量词", "正向"),
    "ultra_detailed": ("质量词", "正向"),
    "very_aesthetic": ("质量词", "正向"),
    "monochrome": ("色彩", "色调"),
    "greyscale": ("色彩", "色调"),
    "colorful": ("色彩", "色调"),
    "pastel_colors": ("色彩", "色调"),
    "sepia": ("色彩", "色调"),
    "limited_palette": ("色彩", "色调"),
    "rainbow": ("色彩", "色调"),
    "sketch": ("风格画质", "画风"),
    "watercolor": ("风格画质", "画风"),
    "lineart": ("风格画质", "画风"),
    "chibi": ("风格画质", "画风"),
    "realistic": ("风格画质", "画风"),
    "photorealistic": ("风格画质", "画风"),
    "retro": ("风格画质", "画风"),
    "vintage": ("风格画质", "画风"),
    "pixel_art": ("风格画质", "媒介"),
    "traditional_media": ("风格画质", "媒介"),
    "photography": ("风格画质", "媒介"),
    "cgi": ("风格画质", "媒介"),
    "cel_shading": ("风格画质", "画风"),
    # ===== 文字符号 =====
    "text": ("文字符号", "文字"),
    "watermark": ("文字符号", "文字"),
    "signature": ("文字符号", "文字"),
    "artist_name": ("文字符号", "文字"),
    "character_name": ("文字符号", "文字"),
    "twitter_username": ("文字符号", "文字"),
    "username": ("文字符号", "文字"),
    "dated": ("文字符号", "文字"),
    "speech_bubble": ("文字符号", "文字"),
    "thought_bubble": ("文字符号", "文字"),
    "onomatopoeia": ("文字符号", "文字"),
    "sound_effects": ("文字符号", "文字"),
    "sign": ("文字符号", "文字"),
    "signage": ("文字符号", "文字"),
    "poster": ("文字符号", "文字"),
    "logo": ("文字符号", "标志"),
    "heart": ("文字符号", "符号"),
    "mosaic_censoring": ("文字符号", "符号"),
    "bar_censor": ("文字符号", "符号"),
    "censored": ("文字符号", "符号"),
    "uncensored": ("文字符号", "符号"),
    ":d": ("文字符号", "颜文字"),
    ":o": ("文字符号", "颜文字"),
    ":3": ("文字符号", "颜文字"),
    ":p": ("文字符号", "颜文字"),
    ":q": ("文字符号", "颜文字"),
    ";d": ("文字符号", "颜文字"),
    "^^^": ("文字符号", "颜文字"),
    "...": ("文字符号", "颜文字"),
    "!!": ("文字符号", "颜文字"),
    "?": ("文字符号", "颜文字"),
    "!": ("文字符号", "颜文字"),
    # ===== 成人内容 =====
    "sex": ("成人内容", "性行为"),
    "vaginal": ("成人内容", "性行为"),
    "anal": ("成人内容", "性行为"),
    "oral": ("成人内容", "性行为"),
    "paizuri": ("成人内容", "性行为"),
    "masturbation": ("成人内容", "性行为"),
    "cum": ("成人内容", "体液"),
    "cum_on_breasts": ("成人内容", "体液"),
    "pussy": ("身体", "耻部"),
    "penis": ("身体", "耻部"),
    "pubic_hair": ("身体", "耻部"),
    "fellatio": ("成人内容", "性行为"),
    "cunnilingus": ("成人内容", "性行为"),
    "rape": ("成人内容", "题材"),
    "bondage": ("成人内容", "题材"),
    "bdsm": ("成人内容", "题材"),
    "panty_shot": ("成人内容", "视角"),
    "upskirt": ("成人内容", "视角"),
    "downblouse": ("成人内容", "视角"),
    "solo_focus": ("人物主体", "人数构成"),
    "spread_legs": ("成人内容", "姿势"),
    "presenting": ("成人内容", "姿势"),
    "arched_back": ("成人内容", "姿势"),
    "all_fours": ("成人内容", "姿势"),
    # ===== 元数据 =====
    "bad_id": ("元数据", "来源存疑"),
    "third-party_edit": ("元数据", "来源存疑"),
    "commentary": ("元数据", "注解"),
    "commentary_request": ("元数据", "注解"),
    "artist_commentary": ("元数据", "注解"),
    "translated": ("元数据", "翻译"),
    "translation_request": ("元数据", "翻译"),
    "check_translation": ("元数据", "翻译"),
    "commission": ("元数据", "委托"),
    "sample": ("元数据", "样本"),
    "huge_filesize": ("元数据", "文件"),
    "lowres": ("元数据", "分辨率"),
    "bad_anatomy": ("负面", "人体"),
    "bad_hands": ("负面", "人体"),
    "bad_feet": ("负面", "人体"),
    "missing_fingers": ("负面", "人体"),
    "extra_fingers": ("负面", "人体"),
    "jpeg_artifacts": ("负面", "画质"),
    "worst_quality": ("负面", "画质"),
    "low_quality": ("负面", "画质"),
    "normal_quality": ("负面", "画质"),
    "rough": ("风格画质", "画质"),
    "unfinished": ("元数据", "未完成"),
    "water": ("场景", "元素"),
    "wet": ("身体", "状态"),
    "ice": ("场景", "元素"),
    "fire": ("场景", "元素"),
    "smoke": ("场景", "元素"),
    "blood": ("成人内容", "元素"),
}


# ---------------------------------------------------------------------------
# 3. 前缀表
# ---------------------------------------------------------------------------

PREFIX_RULES = [
    ("holding_", ("动作", "手部动作")),
    ("hugging_", ("动作", "人际互动")),
    ("kissing_", ("动作", "人际互动")),
    ("carrying_", ("动作", "手部动作")),
    ("wearing_", ("服饰",)),
    ("covered_", ("服饰",)),
    ("dressed_", ("服饰",)),
    ("striped_", ("服饰", "图案")),
    ("plaid_", ("服饰", "图案")),
    ("checkered_", ("服饰", "图案")),
    ("facing_", ("构图镜头", "视线")),
    ("turning_", ("动作", "转身")),
    ("standing_on_", ("姿势", "站姿")),
    ("sitting_on_", ("姿势", "坐姿")),
    ("lying_on_", ("姿势", "卧姿")),
    ("kneeling_on_", ("姿势", "跪姿")),
    ("implied_", ("动作", "暗示")),
    ("imminent_", ("动作", "暗示")),
    ("alternate_", ("服饰", "服装变体")),
    ("official_alternate_", ("服饰", "服装变体")),
]

# 纯颜色词元：仅在末尾候选里作为中心词时使用
COLOR_TOKENS = {
    "red", "blue", "green", "yellow", "purple", "orange", "pink", "brown",
    "black", "white", "grey", "gray", "silver", "blonde", "aqua", "cyan",
    "magenta", "violet", "indigo", "turquoise", "lavender", "maroon",
    "multicolored", "two-tone", "gradient", "platinum",
}
HAIR_COLOR = {
    "blonde", "brown", "black", "white", "grey", "gray", "silver", "red",
    "pink", "blue", "green", "purple", "orange", "aqua", "two-tone",
    "multicolored", "gradient", "colored", "rainbow", "streaked", "platinum",
    "light", "dark", "darker", "lighter",
}
EYE_COLOR = {
    "blue", "red", "green", "purple", "yellow", "brown", "orange", "pink",
    "black", "white", "grey", "gray", "aqua", "cyan", "golden", "silver",
    "heterochromia", "multicolored", "two-tone", "gradient", "light", "dark",
    "violet",
}

# 出现这些词元的 *_hair 不是头发颜色，而是别的部位/别的物件上的毛：
# black_facial_hair（胡须）/ colored_armpit_hair（腋毛）/
# multicolored_hair_bobbles（发圈）。发色细分必须把它们挡在外面。
HAIR_NON_COLOR = {"facial", "armpit", "body", "nose", "bobbles", "ornament", "pubic"}


# ---------------------------------------------------------------------------
# 4. 末尾候选表（整体名 / 末尾 n-gram / 单词元 都查这张表）
# ---------------------------------------------------------------------------

TAIL_RULES = {
    # ===== 头发 =====
    "hair": ("面部", "头发"),
    "bangs": ("面部", "头发"),
    "ahoge": ("面部", "头发"),
    "twintails": ("面部", "头发"),
    "low_twintails": ("面部", "头发"),
    "short_twintails": ("面部", "头发"),
    "ponytail": ("面部", "头发"),
    "braid": ("面部", "头发"),
    "braids": ("面部", "头发"),
    "sidetail": ("面部", "头发"),
    "bun": ("面部", "头发"),
    "chignon": ("面部", "头发"),
    "hime_cut": ("面部", "头发"),
    "bob_cut": ("面部", "头发"),
    "hair_style": ("面部", "头发"),
    "hairstyle": ("面部", "头发"),
    "drill_hair": ("面部", "头发"),
    "wavy_hair": ("面部", "头发"),
    "curly_hair": ("面部", "头发"),
    "straight_hair": ("面部", "头发"),
    "messy_hair": ("面部", "头发"),
    "flipped_hair": ("面部", "头发"),
    "spiked_hair": ("面部", "头发"),
    "antenna_hair": ("面部", "头发"),
    "hair_over_one_eye": ("面部", "头发"),
    "hair_over_eye": ("面部", "头发"),
    "hair_covering_ear": ("面部", "头发"),
    "hair_scrunchie": ("服饰", "配饰"),
    "braided_bun": ("面部", "头发"),
    "odango": ("面部", "头发"),
    "single_hair_bun": ("面部", "头发"),
    "double_bun": ("面部", "头发"),
    "cone_hair": ("面部", "头发"),
    "big_hair": ("面部", "头发"),
    # ===== 眼睛 =====
    "eyes": ("面部", "眼睛"),
    "eye": ("面部", "眼睛"),
    "eyelashes": ("面部", "眼睛"),
    "eyebrows": ("面部", "眼睛"),
    "pupils": ("面部", "眼睛"),
    "eyepatch": ("服饰", "配饰"),
    "eyewear": ("服饰", "配饰"),
    "glasses": ("服饰", "配饰"),
    "sunglasses": ("服饰", "配饰"),
    "blindfold": ("服饰", "配饰"),
    "monocle": ("服饰", "配饰"),
    # ===== 表情 =====
    "smile": ("面部", "表情"),
    "grin": ("面部", "表情"),
    "smirk": ("面部", "表情"),
    "frown": ("面部", "表情"),
    "pout": ("面部", "表情"),
    "angry": ("面部", "表情"),
    "surprised": ("面部", "表情"),
    "expressionless": ("面部", "表情"),
    "crying": ("面部", "表情"),
    "tears": ("面部", "表情"),
    "embarrassed": ("面部", "表情"),
    "shy": ("面部", "表情"),
    "nervous": ("面部", "表情"),
    "scared": ("面部", "表情"),
    "sad": ("面部", "表情"),
    "happy": ("面部", "表情"),
    "confused": ("面部", "表情"),
    "disgust": ("面部", "表情"),
    "serious": ("面部", "表情"),
    "determined": ("面部", "表情"),
    "worried": ("面部", "表情"),
    "excited": ("面部", "表情"),
    "sleepy": ("面部", "表情"),
    "bored": ("面部", "表情"),
    "calm": ("面部", "表情"),
    "freckles": ("面部", "脸部"),
    "mole": ("面部", "脸部"),
    "makeup": ("面部", "脸部"),
    "lipstick": ("面部", "脸部"),
    "eyeshadow": ("面部", "脸部"),
    "blush": ("面部", "表情"),
    "smug": ("面部", "表情"),
    "wink": ("面部", "表情"),
    # ===== 嘴 =====
    "mouth": ("面部", "嘴部"),
    "tongue": ("面部", "嘴部"),
    "teeth": ("面部", "嘴部"),
    "lips": ("面部", "嘴部"),
    "saliva": ("面部", "嘴部"),
    "nose": ("面部", "脸部"),
    # ===== 身体 =====
    "breast": ("身体", "胸部"),
    "breasts": ("身体", "胸部"),
    "nipple": ("身体", "胸部"),
    "nipples": ("身体", "胸部"),
    "areola": ("身体", "胸部"),
    "waist": ("身体", "躯干"),
    "hips": ("身体", "躯干"),
    "hip": ("身体", "躯干"),
    "torso": ("身体", "躯干"),
    "back": ("身体", "躯干"),
    "leg": ("身体", "腿部"),
    "legs": ("身体", "腿部"),
    "thigh": ("身体", "腿部"),
    "thighs": ("身体", "腿部"),
    "knee": ("身体", "腿部"),
    "knees": ("身体", "腿部"),
    "calves": ("身体", "腿部"),
    "foot": ("身体", "脚部"),
    "feet": ("身体", "脚部"),
    "toes": ("身体", "脚部"),
    "hand": ("身体", "手部"),
    "hands": ("身体", "手部"),
    "finger": ("身体", "手部"),
    "fingers": ("身体", "手部"),
    "nail": ("身体", "手部"),
    "nails": ("身体", "手部"),
    "arm": ("身体", "臂部"),
    "arms": ("身体", "臂部"),
    "shoulder": ("身体", "肩部"),
    "shoulders": ("身体", "肩部"),
    "neck": ("身体", "颈部"),
    "collarbone": ("身体", "颈部"),
    "skin": ("身体", "皮肤"),
    "abs": ("身体", "躯干"),
    "ear": ("身体", "身体特征"),
    "ears": ("身体", "身体特征"),
    "tail": ("身体", "身体特征"),
    "wing": ("身体", "身体特征"),
    "wings": ("身体", "身体特征"),
    "horn": ("身体", "身体特征"),
    "horns": ("身体", "身体特征"),
    "halo": ("身体", "身体特征"),
    "feathers": ("身体", "身体特征"),
    "scales": ("身体", "身体特征"),
    "fur": ("身体", "身体特征"),
    "paw": ("身体", "身体特征"),
    "sweat": ("身体", "状态"),
    "wet": ("身体", "状态"),
    "nude": ("身体", "状态"),
    "naked": ("身体", "状态"),
    # ===== 服饰 · 上衣 =====
    "shirt": ("服饰", "上衣"),
    "blouse": ("服饰", "上衣"),
    "sweater": ("服饰", "上衣"),
    "cardigan": ("服饰", "上衣"),
    "hoodie": ("服饰", "上衣"),
    "vest": ("服饰", "上衣"),
    "camisole": ("服饰", "上衣"),
    "t-shirt": ("服饰", "上衣"),
    "sleeves": ("服饰", "上衣"),
    "sweatshirt": ("服饰", "上衣"),
    "tunic": ("服饰", "上衣"),
    "leotard": ("服饰", "上衣"),
    "bodysuit": ("服饰", "上衣"),
    "jersey": ("服饰", "上衣"),
    "pullover": ("服饰", "上衣"),
    "turtleneck": ("服饰", "上衣"),
    "halterneck": ("服饰", "上衣"),
    "tube_top": ("服饰", "上衣"),
    "crop_top": ("服饰", "上衣"),
    "apron": ("服饰", "上衣"),
    "pajamas": ("服饰", "上衣"),
    "nightgown": ("服饰", "上衣"),
    "robe": ("服饰", "上衣"),
    "bathrobe": ("服饰", "上衣"),
    "kimono_shirt": ("服饰", "上衣"),
    "shrug": ("服饰", "上衣"),
    "sleeve": ("服饰", "上衣"),
    # ===== 服饰 · 外层 =====
    "jacket": ("服饰", "外套"),
    "coat": ("服饰", "外套"),
    "cape": ("服饰", "外套"),
    "cloak": ("服饰", "外套"),
    "poncho": ("服饰", "外套"),
    "parka": ("服饰", "外套"),
    "gakuran": ("服饰", "外套"),
    # ===== 服饰 · 裙装 =====
    "skirt": ("服饰", "裙装"),
    "dress": ("服饰", "裙装"),
    "gown": ("服饰", "裙装"),
    "pinafore": ("服饰", "裙装"),
    "sundress": ("服饰", "裙装"),
    "wedding_dress": ("服饰", "裙装"),
    "evening_gown": ("服饰", "裙装"),
    # ===== 服饰 · 裤装 =====
    "pants": ("服饰", "裤装"),
    "trousers": ("服饰", "裤装"),
    "jeans": ("服饰", "裤装"),
    "shorts": ("服饰", "裤装"),
    "leggings": ("服饰", "裤装"),
    "overalls": ("服饰", "裤装"),
    "bloomers": ("服饰", "裤装"),
    "spats": ("服饰", "裤装"),
    "bike_shorts": ("服饰", "裤装"),
    "hot_pants": ("服饰", "裤装"),
    # ===== 服饰 · 内衣 =====
    "bra": ("服饰", "内衣"),
    "panties": ("服饰", "内衣"),
    "underwear": ("服饰", "内衣"),
    "boxers": ("服饰", "内衣"),
    "briefs": ("服饰", "内衣"),
    "lingerie": ("服饰", "内衣"),
    "garter": ("服饰", "内衣"),
    "corset": ("服饰", "内衣"),
    "sarashi": ("服饰", "内衣"),
    "fundoshi": ("服饰", "内衣"),
    # ===== 服饰 · 泳装 =====
    "swimsuit": ("服饰", "泳装"),
    "swimwear": ("服饰", "泳装"),
    "bikini": ("服饰", "泳装"),
    "competition_swimsuit": ("服饰", "泳装"),
    "school_swimsuit": ("服饰", "泳装"),
    # ===== 服饰 · 传统 =====
    "kimono": ("服饰", "传统服饰"),
    "yukata": ("服饰", "传统服饰"),
    "hakama": ("服饰", "传统服饰"),
    "hanbok": ("服饰", "传统服饰"),
    "qipao": ("服饰", "传统服饰"),
    "cheongsam": ("服饰", "传统服饰"),
    "hanfu": ("服饰", "传统服饰"),
    "sari": ("服饰", "传统服饰"),
    "dirndl": ("服饰", "传统服饰"),
    "furisode": ("服饰", "传统服饰"),
    "happi": ("服饰", "传统服饰"),
    "jinbei": ("服饰", "传统服饰"),
    "miko": ("服饰", "传统服饰"),
    "dougi": ("服饰", "传统服饰"),
    "gi": ("服饰", "传统服饰"),
    "obi": ("服饰", "传统服饰"),
    "zhongshan_zhuang": ("服饰", "传统服饰"),
    "cheong_sam": ("服饰", "传统服饰"),
    # ===== 服饰 · 制服 =====
    "uniform": ("服饰", "制服"),
    "serafuku": ("服饰", "制服"),
    "military_uniform": ("服饰", "制服"),
    "sailor": ("服饰", "制服"),
    # ===== 服饰 · 鞋袜 =====
    "shoes": ("服饰", "鞋袜"),
    "shoe": ("服饰", "鞋袜"),
    "boots": ("服饰", "鞋袜"),
    "boot": ("服饰", "鞋袜"),
    "sneakers": ("服饰", "鞋袜"),
    "sandals": ("服饰", "鞋袜"),
    "loafers": ("服饰", "鞋袜"),
    "heels": ("服饰", "鞋袜"),
    "slippers": ("服饰", "鞋袜"),
    "geta": ("服饰", "鞋袜"),
    "socks": ("服饰", "鞋袜"),
    "sock": ("服饰", "鞋袜"),
    "thighhighs": ("服饰", "鞋袜"),
    "kneehighs": ("服饰", "鞋袜"),
    "stockings": ("服饰", "鞋袜"),
    "pantyhose": ("服饰", "鞋袜"),
    "tabi": ("服饰", "鞋袜"),
    "footwear": ("服饰", "鞋袜"),
    "legwear": ("服饰", "鞋袜"),
    "zettai_ryouiki": ("服饰", "鞋袜"),
    # ===== 服饰 · 配饰 =====
    "hat": ("服饰", "配饰"),
    "cap": ("服饰", "配饰"),
    "helmet": ("服饰", "配饰"),
    "headwear": ("服饰", "配饰"),
    "headband": ("服饰", "配饰"),
    "headdress": ("服饰", "配饰"),
    "veil": ("服饰", "配饰"),
    "crown": ("服饰", "配饰"),
    "tiara": ("服饰", "配饰"),
    "hairband": ("服饰", "配饰"),
    "hairpin": ("服饰", "配饰"),
    "ribbon": ("服饰", "配饰"),
    "bow": ("服饰", "配饰"),
    "bowtie": ("服饰", "配饰"),
    "necktie": ("服饰", "配饰"),
    "tie": ("服饰", "配饰"),
    "scarf": ("服饰", "配饰"),
    "muffler": ("服饰", "配饰"),
    "neckerchief": ("服饰", "配饰"),
    "ascot": ("服饰", "配饰"),
    "necklace": ("服饰", "配饰"),
    "earrings": ("服饰", "配饰"),
    "earring": ("服饰", "配饰"),
    "bracelet": ("服饰", "配饰"),
    "ring": ("服饰", "配饰"),
    "jewelry": ("服饰", "配饰"),
    "choker": ("服饰", "配饰"),
    "pendant": ("服饰", "配饰"),
    "brooch": ("服饰", "配饰"),
    "badge": ("服饰", "配饰"),
    "belt": ("服饰", "配饰"),
    "suspenders": ("服饰", "配饰"),
    "gloves": ("服饰", "配饰"),
    "glove": ("服饰", "配饰"),
    "mittens": ("服饰", "配饰"),
    "bracers": ("服饰", "配饰"),
    "wristband": ("服饰", "配饰"),
    "armband": ("服饰", "配饰"),
    "mask": ("服饰", "配饰"),
    "watch": ("服饰", "配饰"),
    "collar": ("服饰", "配饰"),
    "cuffs": ("服饰", "配饰"),
    "frills": ("服饰", "配饰"),
    "lace": ("服饰", "配饰"),
    "scrunchie": ("服饰", "配饰"),
    "hair_scrunchie": ("服饰", "配饰"),
    "bandana": ("服饰", "配饰"),
    "bandeau": ("服饰", "配饰"),
    # ===== 姿势 =====
    "pose": ("姿势",),
    "crossed_arms": ("姿势", "手部姿势"),
    "arms_up": ("姿势", "手部姿势"),
    "hand": ("身体", "手部"),
    "legs": ("姿势", "腿部姿势"),
    "stretching": ("动作", "日常行为"),
    # ===== 动作 =====
    "holding": ("动作", "手部动作"),
    "eating": ("动作", "日常行为"),
    "drinking": ("动作", "日常行为"),
    "sleeping": ("动作", "日常行为"),
    "reading": ("动作", "日常行为"),
    "writing": ("动作", "日常行为"),
    "cooking": ("动作", "日常行为"),
    "bathing": ("动作", "日常行为"),
    "dressing": ("动作", "日常行为"),
    "undressing": ("动作", "日常行为"),
    "walking": ("动作", "移动"),
    "running": ("动作", "移动"),
    "jumping": ("动作", "移动"),
    "flying": ("动作", "移动"),
    "riding": ("动作", "移动"),
    "dancing": ("动作", "表演"),
    "singing": ("动作", "表演"),
    "playing": ("动作", "日常行为"),
    "swimming": ("动作", "运动"),
    "fighting": ("动作", "战斗"),
    "hug": ("动作", "人际互动"),
    "kiss": ("动作", "人际互动"),
    "carrying": ("动作", "手部动作"),
    "reaching": ("动作", "手部动作"),
    "waving": ("动作", "手部动作"),
    "pointing": ("动作", "手部动作"),
    "pulling": ("动作", "手部动作"),
    "pushing": ("动作", "手部动作"),
    "smoking": ("动作", "日常行为"),
    "yawning": ("动作", "日常行为"),
    "staring": ("动作", "日常行为"),
    "watching": ("动作", "日常行为"),
    "listening": ("动作", "日常行为"),
    "talking": ("动作", "日常行为"),
    "shouting": ("动作", "日常行为"),
    "whispering": ("动作", "日常行为"),
    "hiding": ("动作", "日常行为"),
    "peeking": ("动作", "日常行为"),
    "undressing": ("动作", "日常行为"),
    "stretching": ("动作", "日常行为"),
    "leaning": ("姿势", "站姿"),
    "leaning_forward": ("姿势", "站姿"),
    "bent_over": ("姿势", "站姿"),
    "upside-down": ("姿势", "其它"),
    "handstand": ("姿势", "其它"),
    # ===== 场景 =====
    "background": ("场景", "背景类型"),
    "scenery": ("场景", "风景"),
    "landscape": ("场景", "风景"),
    "cityscape": ("场景", "室外"),
    "city": ("场景", "室外"),
    "street": ("场景", "室外"),
    "beach": ("场景", "室外"),
    "ocean": ("场景", "室外"),
    "sea": ("场景", "室外"),
    "lake": ("场景", "室外"),
    "river": ("场景", "室外"),
    "waterfall": ("场景", "室外"),
    "forest": ("场景", "室外"),
    "jungle": ("场景", "室外"),
    "mountain": ("场景", "室外"),
    "field": ("场景", "室外"),
    "garden": ("场景", "室外"),
    "park": ("场景", "室外"),
    "desert": ("场景", "室外"),
    "ruins": ("场景", "室外"),
    "rooftop": ("场景", "室外"),
    "balcony": ("场景", "室外"),
    "bridge": ("场景", "室外"),
    "road": ("场景", "室外"),
    "train": ("场景", "室外"),
    "pool": ("场景", "室外"),
    "classroom": ("场景", "室内"),
    "bedroom": ("场景", "室内"),
    "bed": ("场景", "室内"),
    "couch": ("场景", "室内"),
    "sofa": ("场景", "室内"),
    "kitchen": ("场景", "室内"),
    "bathroom": ("场景", "室内"),
    "library": ("场景", "室内"),
    "office": ("场景", "室内"),
    "cafe": ("场景", "室内"),
    "restaurant": ("场景", "室内"),
    "shop": ("场景", "室内"),
    "church": ("场景", "室内"),
    "shrine": ("场景", "室内"),
    "window": ("场景", "室内"),
    "door": ("场景", "室内"),
    "curtains": ("场景", "室内"),
    "wall": ("场景", "室内"),
    "floor": ("场景", "室内"),
    "ceiling": ("场景", "室内"),
    "stairs": ("场景", "室内"),
    "mirror": ("场景", "室内"),
    "stage": ("场景", "室内"),
    "bath": ("场景", "室内"),
    "bathtub": ("场景", "室内"),
    "pot": ("道具物件", "日用"),
    "space": ("场景", "其它"),
    "sky": ("场景", "室外"),
    "table": ("道具物件", "家具"),
    "desk": ("道具物件", "家具"),
    "chair": ("道具物件", "家具"),
    "pillow": ("道具物件", "家具"),
    "blanket": ("道具物件", "家具"),
    "lamp": ("道具物件", "家具"),
    # ===== 光影 =====
    "lighting": ("光影", "光照"),
    "light": ("光影", "光照"),
    "lights": ("光影", "光照"),
    "shadow": ("光影", "阴影"),
    "shadows": ("光影", "阴影"),
    "glow": ("光影", "特效"),
    "glowing": ("光影", "特效"),
    "flare": ("光影", "特效"),
    "bloom": ("光影", "特效"),
    "bokeh": ("光影", "特效"),
    "reflection": ("光影", "特效"),
    "silhouette": ("光影", "特效"),
    "backlight": ("光影", "光照"),
    "sunlight": ("光影", "光照"),
    "moonlight": ("光影", "光照"),
    "candlelight": ("光影", "光照"),
    "neon": ("光影", "光照"),
    "spotlight": ("光影", "光照"),
    "sparkle": ("光影", "特效"),
    "lens_flare": ("光影", "特效"),
    "god_rays": ("光影", "光照"),
    # ===== 天气 / 时间 / 天体 =====
    "rain": ("天气时间", "天气"),
    "raining": ("天气时间", "天气"),
    "snow": ("天气时间", "天气"),
    "snowing": ("天气时间", "天气"),
    "fog": ("天气时间", "天气"),
    "mist": ("天气时间", "天气"),
    "cloud": ("天气时间", "天气"),
    "clouds": ("天气时间", "天气"),
    "wind": ("天气时间", "天气"),
    "storm": ("天气时间", "天气"),
    "lightning": ("天气时间", "天气"),
    "rainbow": ("天气时间", "天气"),
    "day": ("天气时间", "时间"),
    "night": ("天气时间", "时间"),
    "daytime": ("天气时间", "时间"),
    "sunset": ("天气时间", "时间"),
    "sunrise": ("天气时间", "时间"),
    "dusk": ("天气时间", "时间"),
    "dawn": ("天气时间", "时间"),
    "twilight": ("天气时间", "时间"),
    "morning": ("天气时间", "时间"),
    "evening": ("天气时间", "时间"),
    "midnight": ("天气时间", "时间"),
    "summer": ("天气时间", "季节"),
    "winter": ("天气时间", "季节"),
    "spring": ("天气时间", "季节"),
    "autumn": ("天气时间", "季节"),
    "fall": ("天气时间", "季节"),
    "moon": ("天气时间", "天体"),
    "sun": ("天气时间", "天体"),
    "stars": ("天气时间", "天体"),
    "star": ("天气时间", "天体"),
    # ===== 构图 =====
    "perspective": ("构图镜头", "视角"),
    "symmetry": ("构图镜头", "构图"),
    "framing": ("构图镜头", "构图"),
    "angle": ("构图镜头", "视角"),
    "view": ("构图镜头", "构图"),
    "close-up": ("构图镜头", "景别"),
    "portrait": ("构图镜头", "景别"),
    # ===== 风格画质 =====
    "style": ("风格画质", "画风"),
    "realistic": ("风格画质", "画风"),
    "chibi": ("风格画质", "画风"),
    "anime": ("风格画质", "画风"),
    "cartoon": ("风格画质", "画风"),
    "sketch": ("风格画质", "画风"),
    "lineart": ("风格画质", "画风"),
    "watercolor": ("风格画质", "画风"),
    "retro": ("风格画质", "画风"),
    "vintage": ("风格画质", "画风"),
    "minimalism": ("风格画质", "画风"),
    "abstract": ("风格画质", "画风"),
    "surreal": ("风格画质", "画风"),
    "vector": ("风格画质", "媒介"),
    "pixel": ("风格画质", "媒介"),
    "voxel": ("风格画质", "媒介"),
    "cgi": ("风格画质", "媒介"),
    "photography": ("风格画质", "媒介"),
    "photo": ("风格画质", "媒介"),
    "monochrome": ("色彩", "色调"),
    "greyscale": ("色彩", "色调"),
    "colorful": ("色彩", "色调"),
    "sepia": ("色彩", "色调"),
    "duotone": ("色彩", "色调"),
    "quality": ("风格画质", "画质"),
    "resolution": ("元数据", "分辨率"),
    "detailed": ("风格画质", "画质"),
    # ===== 道具 =====
    "sword": ("道具物件", "武器"),
    "katana": ("道具物件", "武器"),
    "knife": ("道具物件", "武器"),
    "dagger": ("道具物件", "武器"),
    "gun": ("道具物件", "武器"),
    "pistol": ("道具物件", "武器"),
    "rifle": ("道具物件", "武器"),
    "spear": ("道具物件", "武器"),
    "lance": ("道具物件", "武器"),
    "arrow": ("道具物件", "武器"),
    "bow": ("服饰", "配饰"),
    "axe": ("道具物件", "武器"),
    "hammer": ("道具物件", "武器"),
    "staff": ("道具物件", "武器"),
    "wand": ("道具物件", "武器"),
    "scythe": ("道具物件", "武器"),
    "shield": ("道具物件", "武器"),
    "weapon": ("道具物件", "武器"),
    "scabbard": ("道具物件", "武器"),
    "sheath": ("道具物件", "武器"),
    "holster": ("道具物件", "武器"),
    "grenade": ("道具物件", "武器"),
    "missile": ("道具物件", "武器"),
    "cannon": ("道具物件", "武器"),
    "armor": ("服饰", "铠甲"),
    "book": ("道具物件", "日用"),
    "cup": ("道具物件", "日用"),
    "mug": ("道具物件", "日用"),
    "bottle": ("道具物件", "日用"),
    "glass": ("道具物件", "日用"),
    "plate": ("道具物件", "日用"),
    "bowl": ("道具物件", "日用"),
    "chopsticks": ("道具物件", "日用"),
    "spoon": ("道具物件", "日用"),
    "fork": ("道具物件", "日用"),
    "phone": ("道具物件", "日用"),
    "smartphone": ("道具物件", "日用"),
    "camera": ("道具物件", "日用"),
    "computer": ("道具物件", "日用"),
    "laptop": ("道具物件", "日用"),
    "keyboard": ("道具物件", "日用"),
    "mouse": ("道具物件", "日用"),
    "tv": ("道具物件", "日用"),
    "television": ("道具物件", "日用"),
    "radio": ("道具物件", "日用"),
    "towel": ("道具物件", "日用"),
    "clock": ("道具物件", "日用"),
    "watch": ("服饰", "配饰"),
    "balloon": ("道具物件", "日用"),
    "ball": ("道具物件", "日用"),
    "candle": ("道具物件", "日用"),
    "lantern": ("道具物件", "日用"),
    "banner": ("道具物件", "日用"),
    "flag": ("道具物件", "日用"),
    "poster": ("文字符号", "文字"),
    "sign": ("文字符号", "文字"),
    "signage": ("文字符号", "文字"),
    "umbrella": ("道具物件", "日用"),
    "parasol": ("道具物件", "日用"),
    "bag": ("道具物件", "日用"),
    "backpack": ("道具物件", "日用"),
    "purse": ("道具物件", "日用"),
    "handbag": ("道具物件", "日用"),
    "box": ("道具物件", "日用"),
    "card": ("道具物件", "日用"),
    "tube": ("道具物件", "日用"),
    "rope": ("道具物件", "物件"),
    "chain": ("道具物件", "物件"),
    "crystal": ("道具物件", "物件"),
    "gem": ("道具物件", "物件"),
    "jewel": ("道具物件", "物件"),
    "potion": ("道具物件", "物件"),
    "scroll": ("道具物件", "物件"),
    "map": ("道具物件", "物件"),
    "key": ("道具物件", "物件"),
    "treasure": ("道具物件", "物件"),
    "mirror_item": ("道具物件", "物件"),
    "candy": ("道具物件", "食物"),
    "cake": ("道具物件", "食物"),
    "bread": ("道具物件", "食物"),
    "fruit": ("道具物件", "食物"),
    "apple": ("道具物件", "食物"),
    "strawberry": ("道具物件", "食物"),
    "cherry": ("道具物件", "食物"),
    "banana": ("道具物件", "食物"),
    "grape": ("道具物件", "食物"),
    "lemon": ("道具物件", "食物"),
    "melon": ("道具物件", "食物"),
    "watermelon": ("道具物件", "食物"),
    "peach": ("道具物件", "食物"),
    "ice_cream": ("道具物件", "食物"),
    "coffee": ("道具物件", "食物"),
    "tea": ("道具物件", "食物"),
    "wine": ("道具物件", "食物"),
    "beer": ("道具物件", "食物"),
    "juice": ("道具物件", "食物"),
    "milk": ("道具物件", "食物"),
    "food": ("道具物件", "食物"),
    "drink": ("道具物件", "食物"),
    "cookie": ("道具物件", "食物"),
    "chocolate": ("道具物件", "食物"),
    "doughnut": ("道具物件", "食物"),
    "donut": ("道具物件", "食物"),
    "hamburger": ("道具物件", "食物"),
    "pizza": ("道具物件", "食物"),
    "sushi": ("道具物件", "食物"),
    "rice": ("道具物件", "食物"),
    "noodles": ("道具物件", "食物"),
    "mic": ("道具物件", "日用"),
    "microphone": ("道具物件", "日用"),
    "guitar": ("道具物件", "乐器"),
    "piano": ("道具物件", "乐器"),
    "violin": ("道具物件", "乐器"),
    "drum": ("道具物件", "乐器"),
    "flute": ("道具物件", "乐器"),
    "trumpet": ("道具物件", "乐器"),
    "harp": ("道具物件", "乐器"),
    "keyboard_instrument": ("道具物件", "乐器"),
    "car": ("道具物件", "载具"),
    "bicycle": ("道具物件", "载具"),
    "motorcycle": ("道具物件", "载具"),
    "ship": ("道具物件", "载具"),
    "boat": ("道具物件", "载具"),
    "airplane": ("道具物件", "载具"),
    "train_vehicle": ("道具物件", "载具"),
    "stuffed": ("道具物件", "玩具"),
    "doll": ("道具物件", "玩具"),
    "toy": ("道具物件", "玩具"),
    "figure": ("道具物件", "玩具"),
    # ===== 动植物 =====
    "flower": ("动植物", "植物"),
    "flowers": ("动植物", "植物"),
    "petal": ("动植物", "植物"),
    "petals": ("动植物", "植物"),
    "rose": ("动植物", "植物"),
    "sunflower": ("动植物", "植物"),
    "sakura": ("动植物", "植物"),
    "cherry_blossoms": ("动植物", "植物"),
    "lily": ("动植物", "植物"),
    "tulip": ("动植物", "植物"),
    "lotus": ("动植物", "植物"),
    "daisy": ("动植物", "植物"),
    "leaf": ("动植物", "植物"),
    "leaves": ("动植物", "植物"),
    "tree": ("动植物", "植物"),
    "trees": ("动植物", "植物"),
    "grass": ("动植物", "植物"),
    "branch": ("动植物", "植物"),
    "bamboo": ("动植物", "植物"),
    "plant": ("动植物", "植物"),
    "vine": ("动植物", "植物"),
    "mushroom": ("动植物", "植物"),
    "cactus": ("动植物", "植物"),
    "seed": ("动植物", "植物"),
    "animal": ("动植物", "动物"),
    "cat": ("动植物", "动物"),
    "dog": ("动植物", "动物"),
    "bird": ("动植物", "动物"),
    "rabbit": ("动植物", "动物"),
    "fox": ("动植物", "动物"),
    "wolf": ("动植物", "动物"),
    "horse": ("动植物", "动物"),
    "butterfly": ("动植物", "动物"),
    "bee": ("动植物", "动物"),
    "fish": ("动植物", "动物"),
    "snake": ("动植物", "动物"),
    "dragon": ("动植物", "动物"),
    "insect": ("动植物", "动物"),
    "spider": ("动植物", "动物"),
    "whale": ("动植物", "动物"),
    "penguin": ("动植物", "动物"),
    "bear": ("动植物", "动物"),
    "deer": ("动植物", "动物"),
    "eagle": ("动植物", "动物"),
    "owl": ("动植物", "动物"),
    "squirrel": ("动植物", "动物"),
    "dolphin": ("动植物", "动物"),
    "shark": ("动植物", "动物"),
    "octopus": ("动植物", "动物"),
    "jellyfish": ("动植物", "动物"),
    "pawprint": ("动植物", "动物"),
    "monkey": ("动植物", "动物"),
    "lion": ("动植物", "动物"),
    "tiger": ("动植物", "动物"),
    "elephant": ("动植物", "动物"),
    "sheep": ("动植物", "动物"),
    "cow": ("动植物", "动物"),
    "pig": ("动植物", "动物"),
    "chicken": ("动植物", "动物"),
    "duck": ("动植物", "动物"),
    "swan": ("动植物", "动物"),
    "frog": ("动植物", "动物"),
    "turtle": ("动植物", "动物"),
    "crab": ("动植物", "动物"),
    "shrimp": ("动植物", "动物"),
    "squid": ("动植物", "动物"),
    "bug": ("动植物", "动物"),
    "lizard": ("动植物", "动物"),
    "dinosaur": ("动植物", "动物"),
    "unicorn": ("动植物", "动物"),
    "phoenix": ("动植物", "动物"),
    # ===== 文字符号 =====
    "text": ("文字符号", "文字"),
    "words": ("文字符号", "文字"),
    "letters": ("文字符号", "文字"),
    "watermark": ("文字符号", "文字"),
    "signature": ("文字符号", "文字"),
    "logo": ("文字符号", "标志"),
    "symbol": ("文字符号", "符号"),
    "heart": ("文字符号", "符号"),
    "star": ("天气时间", "天体"),
    "cross": ("文字符号", "符号"),
    "arrow": ("文字符号", "符号"),
    "sparkle": ("光影", "特效"),
    "border": ("风格画质", "版式"),
    "speech_bubble": ("文字符号", "文字"),
    "thought_bubble": ("文字符号", "文字"),
    "onomatopoeia": ("文字符号", "文字"),
    "censoring": ("文字符号", "符号"),
    "mosaic": ("文字符号", "符号"),
    "username": ("文字符号", "文字"),
    "dated": ("文字符号", "文字"),
    # ===== 人物 =====
    "girl": ("人物主体", "人数构成"),
    "girls": ("人物主体", "人数构成"),
    "boy": ("人物主体", "人数构成"),
    "boys": ("人物主体", "人数构成"),
    "child": ("人物主体", "年龄体型"),
    "children": ("人物主体", "年龄体型"),
    "loli": ("人物主体", "年龄体型"),
    "shota": ("人物主体", "年龄体型"),
    "elderly": ("人物主体", "年龄体型"),
    "petite": ("人物主体", "年龄体型"),
    "muscular": ("人物主体", "年龄体型"),
    "tall": ("人物主体", "年龄体型"),
    "slim": ("人物主体", "年龄体型"),
    "obese": ("人物主体", "年龄体型"),
    "chubby": ("人物主体", "年龄体型"),
    "twins": ("人物主体", "关系"),
    "siblings": ("人物主体", "关系"),
    "sisters": ("人物主体", "关系"),
    "brothers": ("人物主体", "关系"),
    "family": ("人物主体", "关系"),
    "mother": ("人物主体", "关系"),
    "father": ("人物主体", "关系"),
    # ===== 成人 =====
    "sex": ("成人内容", "性行为"),
    "breasts_sex": ("成人内容", "性行为"),
    "cum": ("成人内容", "体液"),
    "penis": ("身体", "耻部"),
    "pussy": ("身体", "耻部"),
    "anus": ("身体", "耻部"),
    "pubic_hair": ("身体", "耻部"),
    "navel_sex": ("成人内容", "性行为"),
    "bondage": ("成人内容", "题材"),
    "bdsm": ("成人内容", "题材"),
    "panty_shot": ("成人内容", "视角"),
    "upskirt": ("成人内容", "视角"),
    "downblouse": ("成人内容", "视角"),
    "tag": ("成人内容", "题材"),
}


# ---------------------------------------------------------------------------
# 5. 子串兜底（吃长尾）
# ---------------------------------------------------------------------------

CONTAINS_RULES = [
    ("_clothes", ("服饰", "着装状态")),
    ("clothes_", ("服饰", "着装状态")),
    ("clothing", ("服饰",)),
    ("_wear", ("服饰",)),
    ("outfit", ("服饰",)),
    ("costume", ("服饰",)),
    ("footwear", ("服饰", "鞋袜")),
    ("legwear", ("服饰", "鞋袜")),
    ("headwear", ("服饰", "配饰")),
    ("neckwear", ("服饰", "配饰")),
    ("_hair", ("面部", "头发")),
    ("hair_", ("面部", "头发")),
    ("bangs", ("面部", "头发")),
    ("_eyes", ("面部", "眼睛")),
    ("eyes_", ("面部", "眼睛")),
    ("eyelash", ("面部", "眼睛")),
    ("eyebrow", ("面部", "眼睛")),
    ("pupil", ("面部", "眼睛")),
    ("sleeve", ("服饰", "上衣")),
    ("collar", ("服饰", "配饰")),
    ("cuff", ("服饰", "配饰")),
    ("frill", ("服饰", "配饰")),
    ("ruffle", ("服饰", "配饰")),
    ("_trim", ("服饰", "配饰")),
    ("uniform", ("服饰", "制服")),
    ("_skirt", ("服饰", "裙装")),
    ("skirt_", ("服饰", "裙装")),
    ("_dress", ("服饰", "裙装")),
    ("_sock", ("服饰", "鞋袜")),
    ("_boot", ("服饰", "鞋袜")),
    ("_shoe", ("服饰", "鞋袜")),
    ("stocking", ("服饰", "鞋袜")),
    ("legging", ("服饰", "裤装")),
    ("panties", ("服饰", "内衣")),
    ("lingerie", ("服饰", "内衣")),
    ("swimsuit", ("服饰", "泳装")),
    ("kimono", ("服饰", "传统服饰")),
    ("_necklace", ("服饰", "配饰")),
    ("_ribbon", ("服饰", "配饰")),
    ("_earring", ("服饰", "配饰")),
    ("_ornament", ("服饰", "配饰")),
    ("_background", ("场景", "背景类型")),
    ("lighting", ("光影", "光照")),
    ("_light", ("光影", "光照")),
    ("shadow", ("光影", "阴影")),
    ("_flower", ("动植物", "植物")),
    ("_sword", ("道具物件", "武器")),
    ("_blade", ("道具物件", "武器")),
    ("weapon", ("道具物件", "武器")),
    ("_nose", ("面部", "脸部")),
    ("_mouth", ("面部", "嘴部")),
    ("_leg", ("身体", "腿部")),
    ("_arm", ("身体", "臂部")),
    ("_hand", ("身体", "手部")),
    ("_ear", ("身体", "身体特征")),
    ("_tail", ("身体", "身体特征")),
    ("_wing", ("身体", "身体特征")),
    ("_horn", ("身体", "身体特征")),
    ("no_humans", ("人物主体", "人数构成")),
]

# ---------------------------------------------------------------------------
# 5b. 第二遍迭代补充：首轮未分类的高频缺口
# ---------------------------------------------------------------------------

EXACT_RULES.update({
    # 人数（超高热度，必须精确命中）
    "1girl": ("人物主体", "人数构成"), "2girls": ("人物主体", "人数构成"),
    "3girls": ("人物主体", "人数构成"), "4girls": ("人物主体", "人数构成"),
    "5girls": ("人物主体", "人数构成"), "6+girls": ("人物主体", "人数构成"),
    "1boy": ("人物主体", "人数构成"), "2boys": ("人物主体", "人数构成"),
    "3boys": ("人物主体", "人数构成"), "4boys": ("人物主体", "人数构成"),
    "5boys": ("人物主体", "人数构成"), "6+boys": ("人物主体", "人数构成"),
    "1other": ("人物主体", "人数构成"), "2others": ("人物主体", "人数构成"),
    "couple": ("人物主体", "关系"), "trio": ("人物主体", "人数构成"),
    "group": ("人物主体", "人数构成"), "onegai": ("元数据", "题材"),
    "pov": ("构图镜头", "视角"), "wariza": ("姿势", "坐姿"),
    "v": ("姿势", "手部姿势"),
    # 颜文字
    "^_^": ("文字符号", "颜文字"), ">_<": ("文字符号", "颜文字"),
    "^o^": ("文字符号", "颜文字"), "=_=": ("文字符号", "颜文字"),
    "^q^": ("文字符号", "颜文字"),
    # 身体
    "fingernails": ("身体", "手部"), "pectorals": ("身体", "胸部"),
    "testicles": ("身体", "耻部"), "soles": ("身体", "脚部"),
    "chest": ("身体", "胸部"), "crotch": ("身体", "耻部"),
    "belly": ("身体", "躯干"), "butt": ("身体", "臀部"),
    "buttocks": ("身体", "臀部"), "cheeks": ("面部", "脸部"),
    "forehead": ("面部", "脸部"), "chin": ("面部", "脸部"),
    "facial_mark": ("面部", "脸部"), "shaded_face": ("面部", "脸部"),
    "heterochromia": ("面部", "眼睛"), "skindentation": ("身体", "皮肤"),
    "dark-skinned_female": ("身体", "皮肤"), "dark-skinned_male": ("身体", "皮肤"),
    "dark_skinned_female": ("身体", "皮肤"), "dark_skinned_male": ("身体", "皮肤"),
    "aged_down": ("人物主体", "年龄体型"), "aged_up": ("人物主体", "年龄体型"),
    # 服饰
    "headphones": ("服饰", "配饰"), "beret": ("服饰", "配饰"),
    "headgear": ("服饰", "配饰"), "goggles": ("服饰", "配饰"),
    "bandages": ("服饰", "配饰"), "bandaid": ("服饰", "配饰"),
    "bell": ("服饰", "配饰"), "tassel": ("服饰", "配饰"),
    "strap": ("服饰", "配饰"), "highleg": ("服饰", "内衣"),
    "blazer": ("服饰", "外套"), "denim": ("服饰", "图案"),
    "jumpsuit": ("服饰", "上衣"), "sarong": ("服饰", "裙装"),
    "buruma": ("服饰", "裤装"), "fishnets": ("服饰", "鞋袜"),
    "hood": ("服饰", "上衣"), "hood_down": ("服饰", "上衣"),
    "capelet": ("服饰", "外套"), "waistcoat": ("服饰", "外套"),
    "kilt": ("服饰", "裙装"), "tutu": ("服饰", "裙装"),
    "bodice": ("服饰", "上衣"), "bustier": ("服饰", "内衣"),
    "loincloth": ("服饰", "内衣"), "fundoshi": ("服饰", "内衣"),
    "military": ("服饰", "制服"), "floral_print": ("服饰", "图案"),
    "camisole": ("服饰", "上衣"), "tank_top": ("服饰", "上衣"),
    "off-shoulder": ("服饰", "上衣"), "backless": ("服饰", "上衣"),
    "strapless": ("服饰", "上衣"), "sleeveless": ("服饰", "上衣"),
    "clothing_cutout": ("服饰", "着装状态"), "cleavage_cutout": ("服饰", "着装状态"),
    "open_clothes": ("服饰", "着装状态"), "clothes_lift": ("服饰", "着装状态"),
    "torn_clothes": ("服饰", "着装状态"), "see-through_clothes": ("服饰", "着装状态"),
    # 场景
    "building": ("场景", "室外"), "buildings": ("场景", "室外"),
    "roof": ("场景", "室外"), "fence": ("场景", "室外"),
    "gate": ("场景", "室外"), "sidewalk": ("场景", "室外"),
    "alley": ("场景", "室外"), "tunnel": ("场景", "室外"),
    "station": ("场景", "室外"), "airport": ("场景", "室外"),
    "castle": ("场景", "室外"), "tower": ("场景", "室外"),
    "lighthouse": ("场景", "室外"), "village": ("场景", "室外"),
    "town": ("场景", "室外"), "cave": ("场景", "室外"),
    "cliff": ("场景", "室外"), "valley": ("场景", "室外"),
    "island": ("场景", "室外"), "harbor": ("场景", "室外"),
    "lagoon": ("场景", "室外"), "swamp": ("场景", "室外"),
    "city_lights": ("场景", "室外"), "neon_lights": ("场景", "室外"),
    "fantasy": ("场景", "其它"), "sci-fi": ("场景", "其它"),
    # 动作 / 姿势 / 状态
    "straddling": ("动作", "姿势"), "groping": ("动作", "人际互动"),
    "trembling": ("身体", "状态"), "bound": ("成人内容", "题材"),
    "bowing": ("姿势", "站姿"), "spreading": ("成人内容", "姿势"),
    "on_one_knee": ("姿势", "跪姿"), "hand_on_another": ("动作", "人际互动"),
    "leaning_forward": ("姿势", "站姿"), "bent_over": ("姿势", "站姿"),
    "motion_lines": ("风格画质", "线条"), "speed_lines": ("风格画质", "线条"),
    "impact_lines": ("风格画质", "线条"), "focus_lines": ("风格画质", "线条"),
    "sparkle": ("光影", "特效"),
    # 元数据 / 风格
    "blurry": ("负面", "画质"), "4koma": ("元数据", "来源"),
    "comic": ("元数据", "来源"), "cover": ("元数据", "来源"),
    "letterboxed": ("风格画质", "版式"), "parody": ("元数据", "题材"),
    "crossover": ("元数据", "题材"), "furry": ("元数据", "题材"),
    "bara": ("元数据", "题材"), "game": ("元数据", "来源"),
    "screencap": ("元数据", "来源"), "still_life": ("风格画质", "画风"),
    "wallpaper": ("元数据", "用途"), "reference_sheet": ("元数据", "用途"),
    "character_sheet": ("元数据", "用途"), "sprite": ("元数据", "用途"),
    "yaoi": ("元数据", "题材"), "yuri": ("元数据", "题材"),
    "official_art": ("元数据", "来源"), "cosplay": ("元数据", "cosplay"),
    "copyright_name": ("元数据", "作品同名"), "artist_name": ("元数据", "画师同名"),
    "spoken_heart": ("文字符号", "符号"), "spoken_question_mark": ("文字符号", "符号"),
    "spoken_ellipsis": ("文字符号", "符号"), "spoken_exclamation": ("文字符号", "符号"),
    "spoken_blush": ("文字符号", "符号"), "note": ("文字符号", "文字"),
    "paper": ("道具物件", "日用"), "box": ("道具物件", "日用"),
    "cellphone": ("道具物件", "日用"), "headset": ("道具物件", "日用"),
    "egg": ("道具物件", "食物"), "ice": ("道具物件", "食物"),
    "water": ("场景", "元素"), "fire": ("场景", "元素"),
    "blood": ("成人内容", "元素"), "smoke": ("场景", "元素"),
    "air": ("场景", "元素"), "light_particles": ("光影", "特效"),
    # 成人
    "erection": ("成人内容", "身体反应"), "cameltoe": ("成人内容", "视角"),
    "pantyshot": ("成人内容", "视角"), "aroused": ("成人内容", "身体反应"),
    "bulge": ("成人内容", "身体反应"), "nsfw": ("成人内容", "题材"),
    "underwear_only": ("成人内容", "着装"),
    "completely_nude": ("成人内容", "着装"),
})

TAIL_RULES.update({
    # 身体细部
    "head": ("面部", "脸部"), "cheek": ("面部", "脸部"),
    "chin": ("面部", "脸部"), "forehead": ("面部", "脸部"),
    "face": ("面部", "脸部"), "chest": ("身体", "胸部"),
    "crotch": ("身体", "耻部"), "belly": ("身体", "躯干"),
    "butt": ("身体", "臀部"), "buttocks": ("身体", "臀部"),
    "ankle": ("身体", "脚部"), "elbow": ("身体", "臂部"),
    "calf": ("身体", "腿部"), "muscle": ("身体", "体型"),
    "muscles": ("身体", "体型"), "veins": ("身体", "皮肤"),
    "spine": ("身体", "躯干"), "pelvis": ("身体", "躯干"),
    "nails": ("身体", "手部"), "nail": ("身体", "手部"),
    "fingernails": ("身体", "手部"), "fingernail": ("身体", "手部"),
    "pectoral": ("身体", "胸部"), "pectorals": ("身体", "胸部"),
    "testicle": ("身体", "耻部"), "testicles": ("身体", "耻部"),
    "sole": ("身体", "脚部"), "soles": ("身体", "脚部"),
    "bandage": ("服饰", "配饰"), "bandages": ("服饰", "配饰"),
    "bandaid": ("服饰", "配饰"), "plaster": ("服饰", "配饰"),
    "plasters": ("服饰", "配饰"),
    # 服饰
    "headphone": ("服饰", "配饰"), "headphones": ("服饰", "配饰"),
    "earphone": ("服饰", "配饰"), "earphones": ("服饰", "配饰"),
    "beret": ("服饰", "配饰"), "headgear": ("服饰", "配饰"),
    "goggle": ("服饰", "配饰"), "goggles": ("服饰", "配饰"),
    "visor": ("服饰", "配饰"), "bonnet": ("服饰", "配饰"),
    "fedora": ("服饰", "配饰"), "beanie": ("服饰", "配饰"),
    "blazer": ("服饰", "外套"), "denim": ("服饰", "图案"),
    "jumpsuit": ("服饰", "上衣"), "sarong": ("服饰", "裙装"),
    "buruma": ("服饰", "裤装"), "fishnet": ("服饰", "鞋袜"),
    "fishnets": ("服饰", "鞋袜"), "tassel": ("服饰", "配饰"),
    "strap": ("服饰", "配饰"), "highleg": ("服饰", "内衣"),
    "waistcoat": ("服饰", "外套"), "kilt": ("服饰", "裙装"),
    "tutu": ("服饰", "裙装"), "bodice": ("服饰", "上衣"),
    "bustier": ("服饰", "内衣"), "loincloth": ("服饰", "内衣"),
    "bell": ("服饰", "配饰"), "bead": ("服饰", "配饰"),
    "beads": ("服饰", "配饰"), "pearl": ("服饰", "配饰"),
    "pearls": ("服饰", "配饰"), "gemstone": ("服饰", "配饰"),
    "print": ("服饰", "图案"), "pattern": ("服饰", "图案"),
    "trim": ("服饰", "配饰"), "frill": ("服饰", "配饰"),
    "ruffle": ("服饰", "配饰"), "ruffles": ("服饰", "配饰"),
    "hijab": ("服饰", "配饰"), "turban": ("服饰", "配饰"),
    "sombrero": ("服饰", "配饰"), "witch_hat": ("服饰", "配饰"),
    "santa_hat": ("服饰", "配饰"), "party_hat": ("服饰", "配饰"),
    # 场景
    "building": ("场景", "室外"), "buildings": ("场景", "室外"),
    "roof": ("场景", "室外"), "fence": ("场景", "室外"),
    "gate": ("场景", "室外"), "sidewalk": ("场景", "室外"),
    "alley": ("场景", "室外"), "tunnel": ("场景", "室外"),
    "station": ("场景", "室外"), "airport": ("场景", "室外"),
    "castle": ("场景", "室外"), "tower": ("场景", "室外"),
    "lighthouse": ("场景", "室外"), "house": ("场景", "室外"),
    "hut": ("场景", "室外"), "tent": ("场景", "室外"),
    "farm": ("场景", "室外"), "village": ("场景", "室外"),
    "town": ("场景", "室外"), "cave": ("场景", "室外"),
    "cliff": ("场景", "室外"), "valley": ("场景", "室外"),
    "island": ("场景", "室外"), "harbor": ("场景", "室外"),
    "port": ("场景", "室外"), "deck": ("场景", "室外"),
    "lagoon": ("场景", "室外"), "swamp": ("场景", "室外"),
    "marsh": ("场景", "室外"), "canyon": ("场景", "室外"),
    "flower_field": ("场景", "室外"), "snowfield": ("场景", "室外"),
    "magazine": ("道具物件", "日用"), "newspaper": ("道具物件", "日用"),
    "graffiti": ("风格画质", "版式"), "mural": ("风格画质", "版式"),
    "screencap": ("元数据", "来源"), "wallpaper": ("元数据", "用途"),
    "sprite": ("元数据", "用途"), "painting": ("风格画质", "媒介"),
    "drawing": ("风格画质", "媒介"), "photo": ("风格画质", "媒介"),
    "photograph": ("风格画质", "媒介"),
    "teacup": ("道具物件", "日用"), "teapot": ("道具物件", "日用"),
    "kettle": ("道具物件", "日用"), "pan": ("道具物件", "日用"),
    "jar": ("道具物件", "日用"), "can": ("道具物件", "日用"),
    "pouch": ("道具物件", "日用"), "pocket": ("服饰", "配饰"),
    "pockets": ("服饰", "配饰"), "zipper": ("服饰", "配饰"),
    "button": ("服饰", "配饰"), "buttons": ("服饰", "配饰"),
    "motorcycle": ("道具物件", "载具"), "scooter": ("道具物件", "载具"),
    "truck": ("道具物件", "载具"), "bus": ("道具物件", "载具"),
    "van": ("道具物件", "载具"), "yacht": ("道具物件", "载具"),
    "ferry": ("道具物件", "载具"), "helicopter": ("道具物件", "载具"),
    "chariot": ("道具物件", "载具"), "kart": ("道具物件", "载具"),
    "sled": ("道具物件", "载具"), "skateboard": ("道具物件", "载具"),
    "surfboard": ("道具物件", "载具"), "snowboard": ("道具物件", "载具"),
    "wheelchair": ("道具物件", "载具"), "stroller": ("道具物件", "载具"),
    "shirt": ("服饰", "上衣"), "vest": ("服饰", "上衣"),
    "loafers": ("服饰", "鞋袜"), "flip-flops": ("服饰", "鞋袜"),
    "geta": ("服饰", "鞋袜"), "clogs": ("服饰", "鞋袜"),
    "platforms": ("服饰", "鞋袜"), "wedges": ("服饰", "鞋袜"),
    "stiletto": ("服饰", "鞋袜"), "stilettos": ("服饰", "鞋袜"),
    # 动作
    "straddling": ("动作", "姿势"), "groping": ("动作", "人际互动"),
    "bowing": ("姿势", "站姿"), "spreading": ("成人内容", "姿势"),
    "trembling": ("身体", "状态"), "bound": ("成人内容", "题材"),
    "resting": ("姿势", "卧姿"), "slouching": ("姿势", "站姿"),
    "crouching": ("姿势", "蹲姿"), "crawling": ("动作", "移动"),
    "climbing": ("动作", "移动"), "falling": ("动作", "移动"),
    "floating": ("动作", "移动"), "diving": ("动作", "运动"),
    "boxing": ("动作", "运动"), "skiing": ("动作", "运动"),
    "skating": ("动作", "运动"), "cycling": ("动作", "运动"),
    "sports": ("动作", "运动"), "training": ("动作", "运动"),
    "stretching": ("动作", "日常行为"), "exercising": ("动作", "运动"),
    "posing": ("姿势",), "posing_for": ("姿势",),
    # 元数据 / 题材
    "couple": ("人物主体", "关系"), "trio": ("人物主体", "人数构成"),
    "group": ("人物主体", "人数构成"), "parody": ("元数据", "题材"),
    "crossover": ("元数据", "题材"), "furry": ("元数据", "题材"),
    "bara": ("元数据", "题材"), "loli": ("人物主体", "年龄体型"),
    "shota": ("人物主体", "年龄体型"), "toddler": ("人物主体", "年龄体型"),
    "baby": ("人物主体", "年龄体型"), "infant": ("人物主体", "年龄体型"),
    "boyfriend": ("人物主体", "关系"), "girlfriend": ("人物主体", "关系"),
    "husband": ("人物主体", "关系"), "wife": ("人物主体", "关系"),
    "father": ("人物主体", "关系"), "mother": ("人物主体", "关系"),
    "son": ("人物主体", "关系"), "daughter": ("人物主体", "关系"),
    "brother": ("人物主体", "关系"), "sister": ("人物主体", "关系"),
    "cousin": ("人物主体", "关系"), "grandmother": ("人物主体", "关系"),
    "grandfather": ("人物主体", "关系"),
})

CONTAINS_RULES += [
    ("_print", ("服饰", "图案")),
    ("_pattern", ("服饰", "图案")),
    ("dark-skinned", ("身体", "皮肤")),
    ("dark_skinned", ("身体", "皮肤")),
    ("_skinned", ("身体", "皮肤")),
    ("aged_", ("人物主体", "年龄体型")),
    ("genderbend", ("人物主体", "性别")),
    ("_cutout", ("服饰", "着装状态")),
    ("_lift", ("服饰", "着装状态")),
    ("_pull", ("服饰", "着装状态")),
    ("_around_", ("服饰", "着装状态")),
    ("_lines", ("风格画质", "线条")),
    ("_shots", ("成人内容", "视角")),
    ("_only", ("成人内容", "着装")),
    ("apron", ("服饰", "上衣")),
    ("earphone", ("服饰", "配饰")),
    ("headset", ("服饰", "配饰")),
    ("_gear", ("服饰", "配饰")),
    ("_tank", ("服饰", "上衣")),
    ("cellphone", ("道具物件", "日用")),
    ("building", ("场景", "室外")),
    ("_sheet", ("元数据", "用途")),
    ("_cap", ("服饰", "配饰")),
    ("_hat", ("服饰", "配饰")),
    ("_boots", ("服饰", "鞋袜")),
    ("_shoes", ("服饰", "鞋袜")),
    ("_print", ("服饰", "图案")),
]

# 6. 正则层：数字人数 / 颜文字（数量大且规整，用规则而不是词表）
REGEX_RULES = [
    (re.compile(r"^\d+(\+\d*)?\+?(girls?|boys?|others?)$"), ("人物主体", "人数构成")),
    (re.compile(r"^\d+\+\s*(girls?|boys?)$"), ("人物主体", "人数构成")),
    (re.compile(r"^[^\w\s]{1,8}$"), ("文字符号", "颜文字")),
]

# ---------------------------------------------------------------------------
# 5c. 第三遍迭代补充
# ---------------------------------------------------------------------------

EXACT_RULES.update({
    "one_side_up": ("面部", "头发"), "half_updo": ("面部", "头发"),
    "otoko_no_ko": ("人物主体", "性别"), "genderswap": ("人物主体", "性别"),
    "genderswap_(mtf)": ("人物主体", "性别"), "genderswap_(ftm)": ("人物主体", "性别"),
    "tomgirl": ("人物主体", "性别"), "femboy": ("人物主体", "性别"),
    "polearm": ("道具物件", "武器"), "instrument": ("道具物件", "乐器"),
    "handgun": ("道具物件", "武器"), "gift": ("道具物件", "物件"),
    "motor_vehicle": ("道具物件", "载具"), "innertube": ("道具物件", "载具"),
    "steam": ("场景", "元素"), "nature": ("场景", "风景"),
    "science_fiction": ("场景", "其它"), "space": ("场景", "其它"),
    "crescent": ("文字符号", "符号"), "musical_note": ("文字符号", "符号"),
    "note": ("文字符号", "符号"), "web_address": ("文字符号", "文字"),
    "drooling": ("面部", "嘴部"), "facial": ("成人内容", "体液"),
    "tearing_up": ("面部", "表情"), "licking": ("动作", "人际互动"),
    "foreshortening": ("构图镜头", "视角"), "meme": ("元数据", "梗图"),
    "claws": ("身体", "身体特征"), "tentacles": ("身体", "身体特征"),
    "spikes": ("身体", "身体特征"), "colored_sclera": ("面部", "眼睛"),
    "tsurime": ("面部", "眼睛"), "facial_mark": ("面部", "脸部"),
    "beard": ("面部", "脸部"), "faceless": ("面部", "脸部"),
    "gauntlets": ("服饰", "配饰"), "bridal_gauntlets": ("服饰", "配饰"),
    "buckle": ("服饰", "配饰"), "o-ring": ("服饰", "配饰"),
    "armlet": ("服饰", "配饰"), "mary_janes": ("服饰", "鞋袜"),
    "gauntlet": ("服饰", "配饰"),
    "pom_pom_(clothes)": ("服饰", "配饰"),
    "front-tie_top": ("服饰", "上衣"), "side_slit": ("服饰", "裙装"),
    "suit": ("服饰", "外套"), "shawl": ("服饰", "外套"),
    "curvy": ("身体", "体型"), "toned": ("身体", "体型"),
    "topless_male": ("身体", "状态"), "covering_privates": ("成人内容", "着装"),
    "restrained": ("成人内容", "题材"), "gag": ("成人内容", "题材"),
    "cowgirl_position": ("成人内容", "姿势"), "ejaculation": ("成人内容", "体液"),
    "breath": ("身体", "状态"), "hood_up": ("服饰", "上衣"),
    "cover_page": ("元数据", "来源"), "cover": ("元数据", "来源"),
    "game": ("元数据", "来源"), "mecha": ("元数据", "题材"),
    "dual_persona": ("元数据", "题材"), "christmas": ("天气时间", "节日"),
    "valentine": ("天气时间", "节日"), "halloween": ("天气时间", "节日"),
    "new_year": ("天气时间", "节日"), "outline": ("风格画质", "线条"),
    "spot_color": ("色彩", "色调"), "seiza": ("姿势", "坐姿"),
    "convenient_leg": ("成人内容", "姿势"), "aroused": ("成人内容", "身体反应"),
    "male": ("人物主体", "性别"), "female": ("人物主体", "性别"),
    "object": ("道具物件", "物件"), "vehicle": ("道具物件", "载具"),
    "egg": ("道具物件", "食物"), "water": ("场景", "元素"),
    "fire": ("场景", "元素"), "ice": ("场景", "元素"),
    "air": ("场景", "元素"), "blood": ("成人内容", "元素"),
    "paper": ("道具物件", "日用"), "toenails": ("身体", "脚部"),
    "male_focus": ("人物主体", "人数构成"), "reverse_trap": ("人物主体", "性别"),
})

TAIL_RULES.update({
    "hood": ("服饰", "上衣"), "ass": ("身体", "臀部"),
    "tattoo": ("身体", "皮肤"), "male": ("人物主体", "性别"),
    "female": ("人物主体", "性别"), "object": ("道具物件", "物件"),
    "vehicle": ("道具物件", "载具"), "egg": ("道具物件", "食物"),
    "water": ("场景", "元素"), "fire": ("场景", "元素"),
    "ice": ("场景", "元素"), "steam": ("场景", "元素"),
    "air": ("场景", "元素"), "blood": ("成人内容", "元素"),
    "paper": ("道具物件", "日用"), "note": ("文字符号", "符号"),
    "cover": ("元数据", "来源"), "game": ("元数据", "来源"),
    "beard": ("面部", "脸部"), "outline": ("风格画质", "线条"),
    "shawl": ("服饰", "外套"), "spike": ("身体", "身体特征"),
    "spikes": ("身体", "身体特征"), "claw": ("身体", "身体特征"),
    "claws": ("身体", "身体特征"), "tentacle": ("身体", "身体特征"),
    "tentacles": ("身体", "身体特征"), "buckle": ("服饰", "配饰"),
    "gift": ("道具物件", "物件"), "handgun": ("道具物件", "武器"),
    "toned": ("身体", "体型"), "curvy": ("身体", "体型"),
    "nature": ("场景", "风景"), "breath": ("身体", "状态"),
    "meme": ("元数据", "梗图"), "instrument": ("道具物件", "乐器"),
    "polearm": ("道具物件", "武器"), "armlet": ("服饰", "配饰"),
    "gauntlet": ("服饰", "配饰"), "gauntlets": ("服饰", "配饰"),
    "toenails": ("身体", "脚部"), "drooling": ("面部", "嘴部"),
    "stomach": ("身体", "躯干"), "hair_scrunchie": ("服饰", "配饰"),
    "pom_pom": ("服饰", "配饰"), "hair_pom_pom": ("服饰", "配饰"),
})

CONTAINS_RULES += [
    ("_suit", ("服饰", "外套")),
    ("_gauntlet", ("服饰", "配饰")),
    ("_armlet", ("服饰", "配饰")),
    ("mary_jane", ("服饰", "鞋袜")),
    ("_top", ("服饰", "上衣")),
    ("_slit", ("服饰", "裙装")),
    ("_position", ("成人内容", "姿势")),
    ("musical_note", ("文字符号", "符号")),
    ("_note", ("文字符号", "符号")),
    ("_privates", ("成人内容", "着装")),
    ("_updo", ("面部", "头发")),
    ("_beard", ("面部", "脸部")),
    ("_persona", ("元数据", "题材")),
    ("_vehicle", ("道具物件", "载具")),
    ("science_fiction", ("场景", "其它")),
    ("_sclera", ("面部", "眼睛")),
    ("_color", ("色彩", "颜色")),
    ("_colour", ("色彩", "颜色")),
]

# ---------------------------------------------------------------------------
# 5d. 第四遍迭代：高热度未分类（count>=1000 为主）
# ---------------------------------------------------------------------------

EXACT_RULES.update({
    # 颜文字（含字母/下划线，正则覆盖不到）
    "o_o": ("文字符号", "颜文字"), "0_0": ("文字符号", "颜文字"),
    "o_0": ("文字符号", "颜文字"), "@_@": ("文字符号", "颜文字"),
    "+_+": ("文字符号", "颜文字"), "|_|": ("文字符号", "颜文字"),
    ">_o": ("文字符号", "颜文字"), ":t": ("文字符号", "颜文字"),
    ":i": ("文字符号", "颜文字"), ":c": ("文字符号", "颜文字"),
    ":s": ("文字符号", "颜文字"), ":x": ("文字符号", "颜文字"),
    # 面部 / 眼睛 / 表情
    "tareme": ("面部", "眼睛"), "jitome": ("面部", "眼睛"),
    "wide-eyed": ("面部", "表情"), "furrowed_brow": ("面部", "表情"),
    "heavy_breathing": ("身体", "状态"), "steaming_body": ("身体", "状态"),
    "stubble": ("面部", "脸部"), "sideburns": ("面部", "脸部"),
    "mustache": ("面部", "脸部"), "goatee": ("面部", "脸部"),
    "eyeliner": ("面部", "脸部"), "blunt_ends": ("面部", "头发"),
    "kemonomimi_mode": ("身体", "身体特征"), "antennae": ("身体", "身体特征"),
    "antlers": ("身体", "身体特征"), "fins": ("身体", "身体特征"),
    "skull": ("身体", "身体特征"), "underbust": ("身体", "胸部"),
    "large_areolae": ("身体", "胸部"), "armpit_crease": ("身体", "臂部"),
    "kneepits": ("身体", "腿部"), "cleft_of_venus": ("身体", "耻部"),
    "plump": ("身体", "体型"), "injury": ("身体", "状态"),
    "crossdressing": ("人物主体", "性别"), "bishounen": ("人物主体", "年龄体型"),
    "minigirl": ("人物主体", "人数构成"), "mini_person": ("构图镜头", "构图"),
    "monster": ("人物主体", "种族"), "oni": ("人物主体", "种族"),
    "personification": ("元数据", "题材"),
    # 服饰
    "thong": ("服饰", "内衣"), "sportswear": ("服饰", "上衣"),
    "lolita_fashion": ("服饰", "风格"), "contemporary": ("服饰", "风格"),
    "pauldrons": ("服饰", "铠甲"), "breastplate": ("服饰", "铠甲"),
    "epaulettes": ("服饰", "铠甲"), "tabard": ("服饰", "外套"),
    "circlet": ("服饰", "配饰"), "headpiece": ("服饰", "配饰"),
    "anklet": ("服饰", "配饰"), "wristwatch": ("服饰", "配饰"),
    "bespectacled": ("服饰", "配饰"), "enmaided": ("服饰", "制服"),
    "criss-cross_halter": ("服饰", "上衣"), "drawstring": ("服饰", "配饰"),
    "double-breasted": ("服饰", "外层"), "center_opening": ("服饰", "着装状态"),
    "midriff_peek": ("服饰", "着装状态"),
    # 场景 / 道具
    "alcohol": ("道具物件", "食物"), "tray": ("道具物件", "日用"),
    "bubble": ("场景", "元素"), "cigarette": ("道具物件", "日用"),
    "broom": ("道具物件", "日用"), "machine": ("道具物件", "物件"),
    "machinery": ("道具物件", "物件"), "bouquet": ("道具物件", "物件"),
    "lollipop": ("道具物件", "食物"), "popsicle": ("道具物件", "食物"),
    "rock": ("场景", "元素"), "sand": ("场景", "元素"),
    "tiles": ("场景", "元素"), "railing": ("场景", "室外"),
    "underwater": ("场景", "水下"), "horizon": ("场景", "风景"),
    "turret": ("道具物件", "武器"), "aircraft": ("道具物件", "载具"),
    "folding_fan": ("道具物件", "日用"), "pen": ("道具物件", "日用"),
    "basket": ("道具物件", "日用"), "bookshelf": ("道具物件", "家具"),
    "bush": ("动植物", "植物"), "leash": ("道具物件", "物件"),
    "cable": ("道具物件", "物件"), "confetti": ("道具物件", "物件"),
    "ofuda": ("道具物件", "物件"), "condom": ("成人内容", "物品"),
    "dildo": ("成人内容", "物品"), "vibrator": ("成人内容", "物品"),
    # 动作 / 姿势
    "wading": ("动作", "移动"), "dual_wielding": ("动作", "战斗"),
    "contrapposto": ("姿势", "站姿"), "yokozuwari": ("姿势", "坐姿"),
    "double_v": ("姿势", "手部姿势"), "selfie": ("构图镜头", "视角"),
    "sheathed": ("动作", "状态"),
    # 构图 / 光影 / 色彩
    "out_of_frame": ("负面", "画面"), "blurry_foreground": ("构图镜头", "景深"),
    "looking_ahead": ("构图镜头", "视线"), "straight-on": ("构图镜头", "视角"),
    "sideways_glance": ("构图镜头", "视线"), "zoom_layer": ("构图镜头", "景别"),
    "top-down_bottom-up": ("构图镜头", "视角"), "glint": ("光影", "特效"),
    "electricity": ("光影", "特效"), "blue_theme": ("色彩", "色调"),
    # 成人
    "handjob": ("成人内容", "性行为"), "fingering": ("成人内容", "性行为"),
    "doggystyle": ("成人内容", "姿势"), "missionary": ("成人内容", "姿势"),
    "threesome": ("成人内容", "人数"), "ahegao": ("成人内容", "表情"),
    "lactation": ("成人内容", "身体反应"), "clitoris": ("身体", "耻部"),
    "pasties": ("成人内容", "着装"), "gagged": ("成人内容", "题材"),
    "cumdrip": ("成人内容", "体液"),
    "partially_submerged": ("动作", "状态"),
    "partially_visible_vulva": ("成人内容", "着装"),
    # 元数据
    "2koma": ("元数据", "来源"), "silent_comic": ("元数据", "来源"),
    "oekaki": ("风格画质", "媒介"), "tachi-e": ("风格画质", "媒介"),
    "music": ("元数据", "题材"), "interracial": ("元数据", "题材"),
    "borrowed_character": ("元数据", "题材"),
    "page_number": ("文字符号", "文字"), "emblem": ("文字符号", "标志"),
    "dakimakura_(medium)": ("元数据", "媒介"),
})

TAIL_RULES.update({
    "breathing": ("身体", "状态"), "glance": ("构图镜头", "视线"),
    "wielding": ("动作", "战斗"), "drip": ("成人内容", "体液"),
    "difference": ("构图镜头", "构图"), "koma": ("元数据", "来源"),
    "theme": ("色彩", "色调"), "fashion": ("服饰", "风格"),
    "eyed": ("面部", "眼睛"), "eyeliner": ("面部", "脸部"),
    "stubble": ("面部", "脸部"), "sideburns": ("面部", "脸部"),
    "mustache": ("面部", "脸部"), "goatee": ("面部", "脸部"),
    "thong": ("服饰", "内衣"), "pauldron": ("服饰", "铠甲"),
    "pauldrons": ("服饰", "铠甲"), "breastplate": ("服饰", "铠甲"),
    "epaulette": ("服饰", "铠甲"), "epaulettes": ("服饰", "铠甲"),
    "circlet": ("服饰", "配饰"), "headpiece": ("服饰", "配饰"),
    "anklet": ("服饰", "配饰"), "wristwatch": ("服饰", "配饰"),
    "tabard": ("服饰", "外套"), "halter": ("服饰", "上衣"),
    "drawstring": ("服饰", "配饰"), "bubble": ("场景", "元素"),
    "rock": ("场景", "元素"), "sand": ("场景", "元素"),
    "tray": ("道具物件", "日用"), "cigarette": ("道具物件", "日用"),
    "broom": ("道具物件", "日用"), "bouquet": ("道具物件", "物件"),
    "lollipop": ("道具物件", "食物"), "popsicle": ("道具物件", "食物"),
    "basket": ("道具物件", "日用"), "bookshelf": ("道具物件", "家具"),
    "bush": ("动植物", "植物"), "leash": ("道具物件", "物件"),
    "cable": ("道具物件", "物件"), "confetti": ("道具物件", "物件"),
    "ofuda": ("道具物件", "物件"), "aircraft": ("道具物件", "载具"),
    "alcohol": ("道具物件", "食物"), "turret": ("道具物件", "武器"),
    "injury": ("身体", "状态"), "glint": ("光影", "特效"),
    "electricity": ("光影", "特效"), "clitoris": ("身体", "耻部"),
    "underbust": ("身体", "胸部"), "kneepits": ("身体", "腿部"),
    "antennae": ("身体", "身体特征"), "antlers": ("身体", "身体特征"),
    "fins": ("身体", "身体特征"), "creature": ("人物主体", "种族"),
    "wading": ("动作", "移动"), "contrapposto": ("姿势", "站姿"),
})

CONTAINS_RULES += [
    ("_difference", ("构图镜头", "构图")),
    ("_glance", ("构图镜头", "视线")),
    ("_breathing", ("身体", "状态")),
    ("_wielding", ("动作", "战斗")),
    ("_drip", ("成人内容", "体液")),
    ("_theme", ("色彩", "色调")),
    ("_fashion", ("服饰", "风格")),
    ("_eyed", ("面部", "眼睛")),
    ("_koma", ("元数据", "来源")),
    ("_plate", ("服饰", "铠甲")),
    ("_pauldron", ("服饰", "铠甲")),
    ("_eyeliner", ("面部", "脸部")),
    ("_mustache", ("面部", "脸部")),
    ("_goatee", ("面部", "脸部")),
    ("_sideburns", ("面部", "脸部")),
]

# ---------------------------------------------------------------------------
# 5f. 抽样复核修正（Top230 逐条人工核对发现）
# ---------------------------------------------------------------------------

EXACT_RULES.update({
    "arm_up": ("姿势", "手部姿势"),
    "leg_up": ("姿势", "腿部姿势"),
    "arms_up": ("姿势", "手部姿势"),
    "legs_up": ("姿势", "腿部姿势"),
    "off_shoulder": ("服饰", "上衣"),
    "off-shoulder": ("服饰", "上衣"),
    "dark_skin": ("身体", "皮肤"),
    "light_skin": ("身体", "皮肤"),
    "pale_skin": ("身体", "皮肤"),
    "dark-skinned": ("身体", "皮肤"),
    "midriff": ("身体", "躯干"),
    "smile_(expression)": ("面部", "表情"),
    "medium_hair": ("面部", "头发"),
})

# ---------------------------------------------------------------------------
# 5e. 第五遍迭代：按"末尾词元分布"批量收口
# ---------------------------------------------------------------------------

SUFFIX_RULES.update({
    "identity": ("元数据", "消歧义"),
    "brand": ("元数据", "品牌"),
})

EXACT_RULES.update({
    # 品牌 / 厂商（画兵器、车、游戏机的常客）
    "h&k": ("元数据", "品牌"), "sig": ("元数据", "品牌"),
    "fn": ("元数据", "品牌"), "nissan": ("元数据", "品牌"),
    "toyota": ("元数据", "品牌"), "nintendo": ("元数据", "品牌"),
    "playstation": ("元数据", "品牌"), "king": ("元数据", "品牌"),
    "dance": ("动作", "表演"), "war": ("元数据", "题材"),
    "play": ("动作", "日常行为"), "gesture": ("姿势", "手部姿势"),
    "challenge": ("元数据", "题材"), "focus": ("构图镜头", "景深"),
    "art": ("风格画质", "媒介"), "paint": ("风格画质", "媒介"),
    "painting": ("风格画质", "媒介"), "line": ("风格画质", "线条"),
    "penetration": ("成人内容", "性行为"), "insertion": ("成人内容", "性行为"),
    "fellatio": ("成人内容", "性行为"), "paizuri": ("成人内容", "性行为"),
    "footjob": ("成人内容", "性行为"), "censor": ("文字符号", "符号"),
    "babydoll": ("服饰", "内衣"), "haori": ("服饰", "传统服饰"),
    "undershirt": ("服饰", "上衣"), "sash": ("服饰", "配饰"),
    "navel": ("身体", "躯干"), "limb": ("身体", "四肢"),
    "body": ("身体", "躯干"), "piercing": ("身体", "身体特征"),
    "scar": ("身体", "皮肤"), "shell": ("动植物", "动物"),
    "berry": ("道具物件", "食物"), "money": ("道具物件", "物件"),
    "wheel": ("道具物件", "物件"), "batons": ("道具物件", "物件"),
    "baton": ("道具物件", "物件"), "beam": ("光影", "特效"),
    "string": ("道具物件", "物件"), "pin": ("服饰", "配饰"),
    "set": ("元数据", "用途"), "board": ("元数据", "版式"),
    "frame": ("元数据", "版式"), "inset": ("元数据", "版式"),
    "chart": ("元数据", "版式"), "screen": ("元数据", "版式"),
    "room": ("场景", "室内"), "liquid": ("场景", "元素"),
    "viewer": ("构图镜头", "视角"), "self": ("构图镜头", "构图"),
    "stripes": ("服饰", "图案"), "diamond": ("文字符号", "符号"),
    "club": ("文字符号", "符号"), "spade": ("文字符号", "符号"),
    "mark": ("文字符号", "符号"), "name": ("文字符号", "文字"),
    "machine": ("道具物件", "物件"), "switch": ("道具物件", "物件"),
    "drill": ("道具物件", "物件"), "fan": ("道具物件", "日用"),
    "wheelchair": ("道具物件", "载具"),
})

TAIL_RULES.update({
    "stripe": ("服饰", "图案"), "stripes": ("服饰", "图案"),
    "mark": ("文字符号", "符号"), "club": ("文字符号", "符号"),
    "diamond": ("文字符号", "符号"), "spade": ("文字符号", "符号"),
    "heart": ("文字符号", "符号"), "connection": ("文字符号", "符号"),
    "room": ("场景", "室内"), "liquid": ("场景", "元素"),
    "driver": ("人物主体", "职业"), "wheel": ("道具物件", "物件"),
    "stick": ("道具物件", "物件"), "rod": ("道具物件", "物件"),
    "bar": ("道具物件", "物件"), "shell": ("动植物", "动物"),
    "berry": ("道具物件", "食物"), "babydoll": ("服饰", "内衣"),
    "haori": ("服饰", "传统服饰"), "undershirt": ("服饰", "上衣"),
    "sash": ("服饰", "配饰"), "dance": ("动作", "表演"),
    "gesture": ("姿势", "手部姿势"), "war": ("元数据", "题材"),
    "play": ("动作", "日常行为"), "limb": ("身体", "四肢"),
    "body": ("身体", "躯干"), "navel": ("身体", "躯干"),
    "scar": ("身体", "皮肤"), "piercing": ("身体", "身体特征"),
    "painting": ("风格画质", "媒介"), "art": ("风格画质", "媒介"),
    "paint": ("风格画质", "媒介"), "line": ("风格画质", "线条"),
    "focus": ("构图镜头", "景深"), "chart": ("元数据", "版式"),
    "board": ("元数据", "版式"), "frame": ("元数据", "版式"),
    "inset": ("元数据", "版式"), "screen": ("元数据", "版式"),
    "set": ("元数据", "用途"), "switch": ("道具物件", "物件"),
    "machine": ("道具物件", "物件"), "drill": ("道具物件", "物件"),
    "string": ("道具物件", "物件"), "money": ("道具物件", "物件"),
    "baton": ("道具物件", "物件"), "beam": ("光影", "特效"),
    "fan": ("道具物件", "日用"), "wheelchair": ("道具物件", "载具"),
    "pin": ("服饰", "配饰"), "censor": ("文字符号", "符号"),
    "penetration": ("成人内容", "性行为"), "insertion": ("成人内容", "性行为"),
    "fellatio": ("成人内容", "性行为"), "paizuri": ("成人内容", "性行为"),
    "footjob": ("成人内容", "性行为"), "viewer": ("构图镜头", "视角"),
    "name": ("文字符号", "文字"), "self": ("构图镜头", "构图"),
})

CONTAINS_RULES += [
    ("(identity)", ("元数据", "消歧义")),
    ("censor", ("文字符号", "符号")),
    ("_job", ("成人内容", "性行为")),
    ("_play", ("动作", "日常行为")),
    # 注意：这里曾经有一条 ("_art", ("风格画质", "媒介"))，已删除。
    # 它会被 banned_artist / master_artoria / galarian_articuno 这类
    # 「恰好在词内出现 _art」的名字误命中（实测误伤 56 条，含热度 84,629 的
    # banned_artist）。真正的「*_art」结尾已由 TAIL_RULES 的 "art" 覆盖，
    # 这条子串规则纯属冗余，代价却是系统性误判。
]

# 公告型 tag：名字里带 artist/banned 但语义是「标记」而非画师本人。
# 它们的同族 check_artist / check_copyright 在 danbooru 里就是元数据类，
# 这里把 banned_artist 也归到同一处，避免它成为「画师 / 超人气」的第一名。
#
# 注意：这是**类别例外表**，优先级高于类别权威层（classify 第 1 步），
# 用于「danbooru 的类别标注本身就是错的」这种极少数情况。
CATEGORY_OVERRIDES = {
    "banned_artist": ("元数据", "未细分"),
}
EXACT_RULES.update(CATEGORY_OVERRIDES)


# ---------------------------------------------------------------------------
# 把「需要能当后缀用」的词条从 EXACT 同步一份进末尾候选表
# ---------------------------------------------------------------------------
# 末尾候选表才是「后缀」查找发生的地方（X_hair_ornament 的末尾两词正是
# hair_ornament），但这类多词词条当初只写进了 EXACT_RULES，于是这些 tag
# 掉到单个词元 "hair" 上，被误判成头发 —— x_hair_ornament 热度 7.2 万，
# *_hair_ornament 一族合计影响 300+ 条。
#
# 单一事实来源：只在这里列一次，值从 EXACT_RULES 取，避免两张表写法漂移。
# 用 setdefault 是为了不打乱 TAIL_RULES 里已有的手工调优。
_SUFFIX_ALSO = (
    # 发饰：源自服饰/配饰
    "hair_ornament", "hair_ribbon", "hair_bow", "hair_flower", "hairclip",
    "hair_bobbles", "hair_scrunchy", "hair_tubes",
    # 面部毛发 / 体毛：这些不是头发颜色
    "facial_hair", "armpit_hair", "body_hair", "chest_hair",
    "arm_hair", "leg_hair", "nose_hair",
)
for _k in _SUFFIX_ALSO:
    TAIL_RULES.setdefault(_k, EXACT_RULES[_k])


# ---------------------------------------------------------------------------
# 分类主函数
# ---------------------------------------------------------------------------

def split_name(name):
    """拆出 (词元列表, 括号后缀)。后缀取最后一个括号组。"""
    suffix = None
    m = re.search(r"\(([^()]*)\)\s*$", name)
    base = name
    if m:
        suffix = m.group(1).strip().lower()
        base = name[: m.start()].strip()
    tokens = [t for t in base.split("_") if t]
    return tokens, suffix


def _variants(key):
    """单复数变形。danbooru 里 thighhighs / single_thighhigh 混用，
    不归一化会白白漏掉一大批（single_thighhigh / fingernails / bandages）。"""
    yield key
    if key.endswith("ies"):
        yield key[:-3] + "y"
    if key.endswith("es"):
        yield key[:-2]
    if key.endswith("s"):
        yield key[:-1]
    else:
        yield key + "s"


def candidates(tokens):
    """候选键序列：整体 → 末尾 n-gram → 逐词元（右→左），每个再带单复数变体。"""
    n = len(tokens)
    seen, out = set(), []

    def add(s):
        for v in _variants(s):
            if v and v not in seen:
                seen.add(v)
                out.append(v)

    add("_".join(tokens))
    for k in (4, 3, 2, 1):
        if n >= k:
            add("_".join(tokens[-k:]))
    for i in range(n - 1, -1, -1):
        add(tokens[i])
    return out


def classify(name, cat, cat3=None, count=0):
    """返回 (L1, L2[, L3])。

    cat3  已知作品名集合，用于把角色归到所属作品。
    count 用于画师 / 作品这类没有语义信息的类别，按使用热度分档。
    """
    tokens, suffix = split_name(name)
    low = name.strip().lower()

    # 1. 人工指定的类别例外（优先级最高）
    if low in CATEGORY_OVERRIDES:
        return CATEGORY_OVERRIDES[low]

    # 2. 类别权威层：画师 / 作品 / 角色都是**专有名词**，名字里出现通用词
    #    只是巧合。让语义规则先跑会把它们判到随机桶里 —— 实测误伤约
    #    7,000 条，且集中在高热度 tag：
    #      the_legend_of_zelda → 身体/腿部（leg）
    #      fire_emblem        → 场景/元素（emblem）
    #      neon_genesis_evangelion → 光影/光照（neon）
    #      cloud_strife       → 天气时间/天气（cloud）
    #      yae_miko           → 服饰/传统服饰（miko）
    #      minato_aqua        → 色彩/颜色（aqua）
    #    这些标签是「名字恰好含某个词」，不是「在描述那个词」。
    #    所以 cat 1/3/4 在这里直接定死，不再往下猜。
    if cat == 3:
        return ("作品", popularity_band(count, "work"))
    if cat == 1:
        return ("画师", popularity_band(count, "artist"))
    if cat == 4:
        if suffix and cat3 and suffix in cat3:
            return ("角色", "按作品", suffix)
        return ("角色", "其它角色")

    # 3. 括号后缀
    if suffix and suffix in SUFFIX_RULES:
        return SUFFIX_RULES[suffix]

    # 4. 精确表
    if low in EXACT_RULES:
        return EXACT_RULES[low]

    # 5. 前缀表
    for pref, path in PREFIX_RULES:
        if low.startswith(pref):
            return path

    # 5b. 正则层（数字人数 / 颜文字）
    for rx, path in REGEX_RULES:
        if rx.match(low):
            return path

    # 6. 末尾候选
    tail2 = "_".join(tokens[-2:]) if len(tokens) >= 2 else ""
    for key in candidates(tokens):
        path = TAIL_RULES.get(key)
        # 注：曾试过在这里兜一层「EXACT_RULES 词条也能当后缀」（这样
        # x_hair_ornament 就能借到 EXACT 里的 hair_ornament）。实测会连带
        # 把 final_fantasy→场景、fire_emblem→标志、weapon_on_back→卧姿 这类
        # 名字里的通用词条也当后缀用，误伤 1600+ 条。收益完全可以用「把
        # 该词条直接写进 TAIL_RULES」拿到，且零副作用 —— 所以这里不做兜底。
        if path is not None:
            # 头发细分：发色要求「整条 tag 就是发色词」（末词元必须就是 hair），
            # 否则 orange_hair_ornament 会被首词元 orange 拉进发色；
            # 长短看**紧邻** hair 的那个词（tail2），不能只看"名字里出现过
            # long"—— 那样 long_hair_extensions 也会被算成长发。
            if len(tokens) >= 2 and len(path) >= 2 and path[:2] == ("面部", "头发"):
                if (tokens[-1] == "hair" and tokens[0] in HAIR_COLOR
                        and not (HAIR_NON_COLOR & set(tokens))):
                    return ("面部", "头发", "发色")
                if tail2 == "long_hair":
                    return ("面部", "头发", "长发")
                if tail2 == "short_hair":
                    return ("面部", "头发", "短发")
            if len(tokens) >= 2 and len(path) >= 2 and path[:2] == ("面部", "眼睛"):
                if tokens[0] in EYE_COLOR:
                    return ("面部", "眼睛", "瞳色")
            return path

    # 6b. 颜色词：整词就是颜色（dark_blue / light_pink）
    if tokens and tokens[-1] in COLOR_TOKENS:
        return ("色彩", "颜色")
    # 7. 子串兜底
    for sub, path in CONTAINS_RULES:
        if sub in low:
            return path

    # 8. 兜底（cat 1/3/4 已在第 2 步定死，这里只剩 0 / 5 和其它）
    if cat == 5:
        return ("元数据", "未细分")
    return ("其它", "常用杂项" if count >= 100 else "长尾杂项")


# 热度档的展示顺序：由热到冷，与「条数降序」相反（长尾条数最多但没有浏览价值）
BAND_ORDER = ["超人气", "人气", "常见", "长尾"]


def popularity_band(count: int, kind: str = "work") -> str:
    """画师 / 作品这种没有语义信息的类别，按使用热度分档浏览。

    阈值必须按类目自适应：画师热度天然比作品低一个数量级（实测画师最高
    5,868，作品最高 100 万+），用同一套阈值会让「画师 / 超人气」永远是空桶。
    """
    if kind == "artist":
        # 实测分布：≥3000 约 18 人，≥1000 约 413 人，≥100 约 17,300 人
        if count >= 3000:
            return "超人气"
        if count >= 1000:
            return "人气"
        if count >= 100:
            return "常见"
        return "长尾"
    # 实测分布：≥10000 约 148 个，≥1000 约 913 个，≥100 约 4,215 个
    if count >= 10000:
        return "超人气"
    if count >= 1000:
        return "人气"
    if count >= 100:
        return "常见"
    return "长尾"


# ---------------------------------------------------------------------------
# 精选词表融合：让「质量词 / 负面」走的也是同一套分类，避免两处定义打架
# ---------------------------------------------------------------------------

EXACT_RULES.update({
    "masterpiece": ("质量词", "正向"),
    "best_quality": ("质量词", "正向"),
    "high_quality": ("质量词", "正向"),
    "highres": ("质量词", "正向"),
    "absurdres": ("质量词", "正向"),
    "ultra_detailed": ("质量词", "正向"),
    "very_aesthetic": ("质量词", "正向"),
    "amazing_quality": ("质量词", "正向"),
    "detailed_face": ("质量词", "正向"),
    "detailed_background": ("质量词", "正向"),
    "official_art": ("质量词", "正向"),
    "high_resolution": ("质量词", "正向"),
    "sharp_focus": ("质量词", "正向"),
    "extremely_detailed": ("质量词", "正向"),

    "lowres": ("负面", "画质"),
    "worst_quality": ("负面", "画质"),
    "low_quality": ("负面", "画质"),
    "normal_quality": ("负面", "画质"),
    "jpeg_artifacts": ("负面", "画质"),
    "compression_artifacts": ("负面", "画质"),
    "scan_artifacts": ("负面", "画质"),
    "out_of_focus": ("负面", "画质"),
    "error": ("负面", "画质"),

    "bad_anatomy": ("负面", "人体"),
    "bad_proportions": ("负面", "人体"),
    "bad_hands": ("负面", "人体"),
    "bad_feet": ("负面", "人体"),
    "poorly_drawn_hands": ("负面", "人体"),
    "poorly_drawn_face": ("负面", "人体"),
    "missing_fingers": ("负面", "人体"),
    "extra_fingers": ("负面", "人体"),
    "extra_digits": ("负面", "人体"),
    "fewer_digits": ("负面", "人体"),
    "fused_fingers": ("负面", "人体"),
    "mutated_hands": ("负面", "人体"),
    "malformed_hands": ("负面", "人体"),
    "extra_limbs": ("负面", "人体"),
    "extra_arms": ("负面", "人体"),
    "extra_legs": ("负面", "人体"),
    "missing_arms": ("负面", "人体"),
    "missing_legs": ("负面", "人体"),
    "long_neck": ("负面", "人体"),
    "extra_heads": ("负面", "人体"),
    "extra_eyes": ("负面", "人体"),
    "extra_ears": ("负面", "人体"),
    "conjoined": ("负面", "人体"),
    "disembodied_limb": ("负面", "人体"),
    "floating_limbs": ("负面", "人体"),

    "disfigured": ("负面", "画面"),
    "deformed": ("负面", "画面"),
    "mutated": ("负面", "画面"),
    "ugly": ("负面", "画面"),
    "cropped": ("负面", "画面"),
    "out_of_frame": ("负面", "画面"),
    "bad_composition": ("负面", "画面"),
    "watermark": ("负面", "文字"),
    "signature": ("负面", "文字"),
    "username": ("负面", "文字"),
    "artist_name": ("负面", "文字"),
    "text": ("负面", "文字"),
    "speech_bubble": ("负面", "文字"),
    "logo": ("负面", "文字"),
    "copyright_name": ("负面", "文字"),
    "dated": ("负面", "文字"),
    "patreon_username": ("负面", "文字"),
})


# ---------------------------------------------------------------------------
# 分类树
# ---------------------------------------------------------------------------

def build_tree(path_counts):
    """path_counts: {(L1[, L2[, L3]]): 条数} -> 嵌套树。

    每个节点带 count（含所有后代），供 UI 显示「服饰 (7352)」。
    """
    tree = {}
    for path, cnt in path_counts.items():
        node_map = tree
        for seg in path:
            node = node_map.setdefault(seg, {"count": 0, "children": {}})
            node["count"] += cnt
            node_map = node["children"]

    def to_list(node_map, order=None):
        items = []
        keys = list(node_map)
        if order:
            rank = {k: i for i, k in enumerate(order)}
            keys.sort(key=lambda k: (rank.get(k, 10 ** 6), -node_map[k]["count"]))
        else:
            keys.sort(key=lambda k: -node_map[k]["count"])
        for k in keys:
            n = node_map[k]
            # 热度档反着来：若子级全是热度档，按「由热到冷」排，
            # 否则默认的「条数降序」会把最没人用的「长尾」顶到第一个。
            kids = n["children"]
            sub = BAND_ORDER if kids and set(kids) <= set(BAND_ORDER) else None
            items.append({
                "id": k,
                "name": k,
                "count": n["count"],
                "children": to_list(kids, sub),
            })
        return items

    return to_list(tree, L1_ORDER)


