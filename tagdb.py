# -*- coding: utf-8 -*-
"""全量 Danbooru 标签库：加载 / 中英合并 / 语义分类 / 搜索索引。

数据沿用 a1111-sd-webui-tagcomplete 的 CSV 格式，直接把文件丢进
``<插件目录>/tags/`` 即可，也可以指向已有的 SD WebUI 安装目录：

    danbooru.csv            tag,category,count,"alias1,alias2,..."
    danbooru.zh_CN_SFW.csv  tag,中文

关于编码：``danbooru.csv`` 里含日文别名，实际是 **GB18030** 而不是 UTF-8；
中文表才是 UTF-8。所以读取时统一做「UTF-8 优先、失败退 GB18030」的嗅探，
不要写死编码，否则会直接 UnicodeDecodeError。

分类：CSV 只带一个 category 号（0 通用 / 1 画师 / 3 作品 / 4 角色 / 5 元数据），
通用类里挤了 2.8 万条没法用。加载后交给 :mod:`taxonomy` 给每条打一个三级
语义路径，并建立「路径前缀 -> 标签列表」索引，供 UI 的分级筛选查。

本模块刻意不依赖 ComfyUI，可脱离环境单独跑单测（见 dev/test_tagdb.py）。
"""

from __future__ import annotations

import codecs
import csv
import glob
import io
import os
import threading

try:                     # 作为包导入（ComfyUI 正常加载路径）
    from . import taxonomy
except ImportError:      # 单测里直接 import tagdb 时走这条
    import taxonomy

__all__ = ["TagDB", "CATEGORY_NAMES", "get_tag_db", "reload_tag_db"]

# Danbooru 分类号 → 中文显示名。2 号在 danbooru 里是废弃分类，不展示。
CATEGORY_NAMES = {
    0: "通用",
    1: "画师",
    3: "作品",
    4: "角色",
    5: "元数据",
}

# UI 里分类 tab 的展示顺序（数字分类按这个顺序排）
CATEGORY_ORDER = [0, 4, 3, 1, 5]

DANBOORU_FILENAMES = ("danbooru.csv", "danbooru_sfw.csv")
ZH_FILENAMES = ("danbooru.zh_CN_SFW.csv", "danbooru.zh_CN.csv", "zh_CN.csv")

ENV_TAGS_DIR = "TAG_PROMPT_EDITOR_TAGS_DIR"

# --------------------------------------------------------------------------
# 人工精选词表。这些词不一定出现在 danbooru.csv 里（比如质量词），
# 所以查不到时仍然展示，count 记 0。
# --------------------------------------------------------------------------

FAVORITE_TAGS = (
    # 质量
    "masterpiece", "best_quality", "highres", "absurdres", "high_quality",
    "ultra_detailed", "very_aesthetic",
    # 主体 / 构图
    "solo", "1girl", "1boy", "2girls", "looking_at_viewer",
    "close-up", "upper_body", "cowboy_shot", "full_body", "portrait", "wide_shot",
    "from_above", "from_below", "from_side", "from_behind", "dutch_angle",
    "depth_of_field", "blurry_background", "simple_background", "detailed_background",
    "white_background", "outdoors", "indoors", "scenery",
    # 光线
    "cinematic_lighting", "soft_lighting", "backlighting", "rim_lighting",
    "volumetric_lighting", "dramatic_lighting", "god_rays", "bloom", "lens_flare",
    # 头发 / 眼睛
    "long_hair", "short_hair", "twintails", "ponytail", "braid", "bangs", "ahoge",
    "hair_ornament", "blue_eyes", "red_eyes", "green_eyes", "heterochromia",
    "large_breasts", "medium_breasts", "small_breasts",
    # 表情
    "smile", "blush", "open_mouth", "closed_mouth", "seductive_smile",
    "expressionless", "half-closed_eyes", "closed_eyes", "tears", "pout", "surprised",
    # 姿势
    "standing", "sitting", "lying", "on_back", "on_stomach", "on_side", "kneeling",
    "squatting", "crossed_arms", "arms_up", "arm_up", "hand_on_hip", "hand_up",
    "outstretched_arm", "legs_crossed", "head_tilt", "v_sign",
    # 服装
    "dress", "shirt", "skirt", "school_uniform", "serafuku", "kimono", "swimsuit",
    "bikini", "lingerie", "panties", "bra", "thighhighs", "pantyhose", "socks",
    "gloves", "boots", "high_heels", "hat", "glasses", "necklace", "earrings",
    "jewelry", "choker", "ribbon", "hair_bow",
    # 动作
    "holding", "holding_object", "holding_book", "holding_sword", "reading",
    "eating", "sleeping", "walking", "running", "jumping", "dancing", "hug",
)

QUALITY_TAGS = (
    "masterpiece", "best_quality", "high_quality", "normal_quality",
    "low_quality", "worst_quality",
    "highres", "absurdres", "ultra_detailed", "extremely_detailed",
    "very_aesthetic", "amazing_quality", "detailed_face", "detailed_background",
    "official_art", "high_resolution", "sharp_focus",
)

NEGATIVE_TAGS = (
    # 画质
    "lowres", "worst_quality", "low_quality", "normal_quality", "jpeg_artifacts",
    "compression_artifacts", "chromatic_aberration", "scan_artifacts",
    "blurry", "out_of_focus", "error",
    # 人体
    "bad_anatomy", "bad_proportions", "bad_hands", "bad_feet", "poorly_drawn_hands",
    "poorly_drawn_face", "missing_fingers", "extra_fingers", "extra_digits",
    "fewer_digits", "fused_fingers", "mutated_hands", "malformed_hands",
    "extra_limbs", "extra_arms", "extra_legs", "missing_arms", "missing_legs",
    "long_neck", "extra_heads", "extra_eyes", "extra_ears", "conjoined",
    "disembodied_limb", "floating_limbs",
    # 画面
    "disfigured", "deformed", "mutated", "ugly", "cropped", "out_of_frame",
    "bad_composition", "sketch", "rough",
    # 文字 / 水印
    "watermark", "signature", "username", "artist_name", "text", "speech_bubble",
    "logo", "copyright_name", "dated", "patreon_username",
)

# 「推荐」是跨语义的精选列表（内置推荐 + 用户收藏），作为独立的虚拟分类栏，
# 不参与 taxonomy 的语义分类。
#
# 质量词 / 负面**不再**走 CURATED：原来 QUALITY_TAGS 里混着 low_quality、
# worst_quality 这种明显该算负面的词，两处定义会打架。现在统一由 taxonomy
# 分类，这里只保留词表用于「词库里没有时补虚拟条目」。
CURATED = {
    "fav": ("推荐", FAVORITE_TAGS),
}

VIRTUAL_TAGS = tuple(QUALITY_TAGS) + tuple(NEGATIVE_TAGS)


def _read_text(path: str) -> str:
    """读文本文件，自动嗅探编码。

    danbooru.csv 是 GB18030（含日文别名），中文表是 UTF-8 —— 不能写死。
    """
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


def _iter_candidates(dirs):
    """在给定目录里找第一组可用的 (danbooru.csv, zh.csv)。"""
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        main = None
        for name in DANBOORU_FILENAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                main = p
                break
        if not main:
            continue
        zh = None
        for name in ZH_FILENAMES:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                zh = p
                break
        yield d, main, zh


def discover_tag_dirs(plugin_dir: str):
    """把可能的标签目录按优先级排好序。

    1. 环境变量 TAG_PROMPT_EDITOR_TAGS_DIR 指定的目录
    2. 插件自带的 tags/
    3. 本机已有的 SD WebUI / Forge 里 a1111-sd-webui-tagcomplete 的词库
       （这样不用手动复制 6MB CSV 也能直接用）
    """
    dirs = []
    env = os.environ.get(ENV_TAGS_DIR)
    if env:
        dirs.append(env)
    dirs.append(os.path.join(plugin_dir, "tags"))

    patterns = [
        "{d}/AI/*/extensions/a1111-sd-webui-tagcomplete/tags",
        "{d}/AI/*/extensions/sd-webui-tagcomplete/tags",
        "{d}/*/extensions/a1111-sd-webui-tagcomplete/tags",
        "{d}/sd-webui-*/extensions/a1111-sd-webui-tagcomplete/tags",
        "{d}/AI/sd-webui-*/extensions/a1111-sd-webui-tagcomplete/tags",
    ]
    for drive in ("C:", "D:", "E:", "F:", "G:"):
        if not os.path.exists(drive + os.sep):
            continue
        for pat in patterns:
            try:
                dirs.extend(glob.glob(pat.format(d=drive)))
            except OSError:
                pass

    # 去重且保序
    seen, out = set(), []
    for d in dirs:
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


class TagEntry:
    """一条标签。用 __slots__ 省内存 —— 12 万条时差别很明显。"""

    __slots__ = ("name", "cat", "count", "zh", "blob", "nl", "path")

    def __init__(self, name: str, cat: int, count: int, zh: str, aliases: str):
        self.name = name
        self.cat = cat
        self.count = count
        self.zh = zh
        self.nl = name.lower()
        # 三级语义分类路径，加载完成后由 taxonomy.classify 填入
        self.path = ()
        # 搜索用的小写大杂烩：英文名 / 下划线转空格后的名字 / 中文 / 别名。
        # 存成一份是为了避免每次搜索重复做字符串拼接。
        parts = [name, name.replace("_", " ")]
        if zh:
            parts.append(zh)
        if aliases:
            parts.append(aliases.replace("_", " "))
        self.blob = " ".join(parts).lower()

    def to_dict(self):
        return {
            "t": self.name,
            "zh": self.zh,
            "n": self.count,
            "cat": self.cat,
        }


class TagDB:
    def __init__(self, plugin_dir: str, dirs=None):
        self.plugin_dir = plugin_dir
        self._dirs = dirs if dirs is not None else discover_tag_dirs(plugin_dir)
        self._lock = threading.Lock()
        self._loaded = False
        self._error = None
        self.source = None
        self.zh_source = None
        self._all = []          # 全量，按 count 降序
        self._by_cat = {}       # 分类号 → 按 count 降序
        self._by_name = {}      # 标签名 → TagEntry
        self._by_prefix = {}    # 语义路径前缀 → 按 count 降序
        self._curated = {}      # fav → [TagEntry]
        self._fav_base = []     # 内置「推荐」词（收藏会插到它前面）
        self._favorites = []    # 用户收藏的标签名
        self._tree = []         # 分类树（含每级条数），供 /categories 用
        self._cat3 = set()      # 作品名集合（含 X_(series) 的短名）

    # -- 加载 ---------------------------------------------------------------

    def ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        with self._lock:
            if self._loaded:
                return True
            try:
                self._load()
            except Exception as exc:  # 词库坏了也不能让 ComfyUI 起不来
                self._error = f"{type(exc).__name__}: {exc}"
                self._loaded = True
            return bool(self._all)

    def _load(self):
        found = next(_iter_candidates(self._dirs), None)
        if not found:
            self._error = (
                "没找到 danbooru.csv。请把 a1111-sd-webui-tagcomplete 的 "
                "tags/danbooru.csv 与 danbooru.zh_CN_SFW.csv 复制到 "
                f"{os.path.join(self.plugin_dir, 'tags')}，"
                f"或设置环境变量 {ENV_TAGS_DIR} 指向词库目录。"
            )
            # 没有词库也不能让「推荐」栏空着 —— 内置推荐词是硬编码的，照常可用
            self._curated = {
                "fav": [TagEntry(n, 5, 0, "", "") for n in FAVORITE_TAGS]
            }
            self._fav_base = list(self._curated["fav"])
            self._tree = self._build_tree_locked()
            self._loaded = True
            return

        tags_dir, main_path, zh_path = found
        self.source, self.zh_source = main_path, zh_path

        zh_map = {}
        if zh_path:
            for row in csv.reader(io.StringIO(_read_text(zh_path))):
                if len(row) >= 2 and row[0].strip():
                    val = row[1].strip()
                    if val:
                        zh_map[row[0].strip()] = val

        entries = []
        by_name = {}
        for row in csv.reader(io.StringIO(_read_text(main_path))):
            if len(row) < 3:
                continue
            name = row[0].strip()
            if not name:
                continue
            try:
                cat = int(row[1])
            except ValueError:
                continue
            try:
                count = int(row[2])
            except ValueError:
                count = 0
            aliases = row[3] if len(row) > 3 else ""
            e = TagEntry(name, cat, count, zh_map.get(name, ""), aliases)
            entries.append(e)
            by_name[name] = e

        entries.sort(key=lambda e: e.count, reverse=True)

        # 精选词表里有、danbooru 词表里没有的（质量词等）补成虚拟条目。
        # 它们也要进全量表，否则全局搜 "masterpiece" 根本搜不到它本人
        # （会被 world_masterpiece_theater 这类长尾抢走）。count=0 自然排在末尾。
        extra = []
        for n in list(FAVORITE_TAGS) + list(VIRTUAL_TAGS):
            if n not in by_name:
                e = TagEntry(n, 5, 0, zh_map.get(n, ""), "")
                by_name[n] = e
                extra.append(e)
        if extra:
            entries = entries + extra

        # --- 语义分类：给每条 tag 打三级路径 ---
        # 角色要按所属作品归小类，先收集作品名集合（danbooru category 3）。
        # 作品 tag 常带消歧后缀（fate_(series)），而角色后缀只写 (fate)，
        # 所以把短名也注册进去 —— 否则近一半角色匹配不上作品。
        cat3 = {e.nl for e in entries if e.cat == 3}
        cat3 |= {e.nl.split("_(")[0] for e in entries
                 if e.cat == 3 and "_(" in e.nl}
        self._cat3 = cat3          # 留给测试断言「角色挂的作品确实是作品」
        for e in entries:
            e.path = taxonomy.classify(e.name, e.cat, cat3, e.count)

        by_cat = {c: [] for c in CATEGORY_NAMES}
        for e in entries:
            by_cat.setdefault(e.cat, []).append(e)

        # 路径前缀索引：任意前缀（"服饰" / "服饰/上衣"）→ 标签列表。
        # entries 已按 count 降序，顺序 append 即可保证每个桶内也是降序。
        by_prefix = {}
        for e in entries:
            p = e.path
            for i in range(1, len(p) + 1):
                by_prefix.setdefault(p[:i], []).append(e)

        curated = {"fav": [by_name[n] for n in FAVORITE_TAGS if n in by_name]}

        self._all, self._by_cat, self._by_name = entries, by_cat, by_name
        self._curated, self._by_prefix = curated, by_prefix
        self._fav_base = list(curated.get("fav", []))
        self._tree = self._build_tree_locked()
        self._loaded = True

    # -- 分类树 -------------------------------------------------------------

    def _build_tree_locked(self):
        """把「路径 → 条数」交给 taxonomy.build_tree，并在最前面插入「推荐」。"""
        counts = {}
        for e in self._all:
            counts[e.path] = counts.get(e.path, 0) + 1
        tree = taxonomy.build_tree(counts)
        tree.insert(0, {
            "id": "fav",
            "name": "推荐",
            "count": len(self._curated.get("fav", [])),
            "children": [],
        })
        return tree

    # -- 收藏 ---------------------------------------------------------------

    @property
    def favorites(self):
        """当前使用的收藏列表（供路由层给结果打 fav 标记，不必再读一次文件）。"""
        return list(self._favorites)

    def set_favorites(self, names):
        """把用户收藏的标签重建进 fav 分类（收藏排在内置推荐之前）。

        每次收藏变动只重建这一个列表，不用重新加载 12 万条词库。
        """
        self.ensure_loaded()

        wanted, seen = [], set()
        for raw in names or []:
            name = raw.strip() if isinstance(raw, str) else ""
            if not name or name in seen:
                continue
            seen.add(name)
            wanted.append(name)
            if len(wanted) >= 5000:
                break

        with self._lock:
            self._favorites = wanted
            self._rebuild_fav_locked()
            # 分类树里的「推荐」节点条数要跟着变，否则 UI 上的数字是旧的
            if self._tree and self._tree[0].get("id") == "fav":
                self._tree[0]["count"] = len(self._curated.get("fav", []))
        return list(self._curated.get("fav", []))

    def _rebuild_fav_locked(self):
        lst, seen = [], set()
        for name in self._favorites:
            e = self._by_name.get(name)
            if e is None:
                # 词库里没有这条（用户手输的）也要能显示和点选，
                # 造个临时条目即可，不进全量表，免得污染搜索。
                e = TagEntry(name, 5, 0, "", "")
            if e.name in seen:
                continue
            seen.add(e.name)
            lst.append(e)
        for e in self._fav_base:
            if e.name in seen:
                continue
            seen.add(e.name)
            lst.append(e)
        self._curated["fav"] = lst

    # -- 查询 ---------------------------------------------------------------

    @property
    def error(self):
        return self._error

    def stats(self):
        self.ensure_loaded()
        n_nodes = 0

        def walk(nodes):
            nonlocal n_nodes
            for n in nodes:
                n_nodes += 1
                walk(n.get("children") or [])

        walk(self._tree)
        return {
            "total": len(self._all),
            "with_zh": sum(1 for e in self._all if e.zh),
            "categories": {str(c): len(v) for c, v in self._by_cat.items()},
            "taxonomy_nodes": n_nodes,
            "taxonomy_l1": len(self._tree),
            "unclassified": len(self._by_prefix.get(("其它",), [])),
            "source": self.source,
            "zh_source": self.zh_source,
            "search_dirs": self._dirs,
            "error": self._error,
        }

    def categories(self):
        """分类树，供 UI 的分级胶囊用。每个节点是 id / name / count / children。"""
        self.ensure_loaded()
        return self._tree

    def lookup(self, names):
        """按标签名批量取中文名，给标签块的「英文下方显示中文」用。

        标签块里的 tag 是用户在文本框里打的，压根没经过 :meth:`search`，
        所以手上只有英文名。这里回词库查一遍。

        返回 ``{请求名: 中文名}``；**没有中文的条目不会出现在结果里**，
        调用方据此把中文行留空（不显示一个空壳）。
        查表前统一小写：词库里的名字都小写，而用户可能打成 ``1Girl``。
        """
        self.ensure_loaded()
        out = {}
        for raw in names or ():
            if not isinstance(raw, str):
                continue
            name = raw.strip()
            if not name:
                continue
            e = self._by_name.get(name) or self._by_name.get(name.lower())
            if e and e.zh:
                out[name] = e.zh
        return out

    def search(self, q: str = "", cat=None, limit: int = 60, offset: int = 0):
        """返回 (items, has_more)。

        无关键词时直接对预排好的列表切片（O(1)）。
        有关键词时按「匹配质量优先、热度次之」排序：
            0 = 完全相等
            1 = 词边界命中（以关键词开头，或关键词出现在某个下划线分段的开头）
            2 = 名字里包含
            3 = 只在中文 / 别名里命中
        否则搜 "masterpiece" 会被 "world_masterpiece_theater" 这种高热度长尾顶掉，
        而 masterpiece 恰好不在 danbooru 词表里（只在精选词表中），热度为 0 —— 体验会很差。
        同理搜 "hair" 应该先给 long_hair，而不是 hair_ornament。
        """
        self.ensure_loaded()
        q = (q or "").strip().lower()
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 60
        try:
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            offset = 0

        cat_key = str(cat).strip() if cat is not None else ""
        if cat_key in CURATED:
            base = self._curated.get(cat_key, [])
        elif not cat_key or cat_key == "all":
            base = self._all
        else:
            # 分类路径："服饰" / "服饰/上衣" / "面部/头发/长发"
            path = tuple(seg for seg in cat_key.split("/") if seg)
            base = self._by_prefix.get(path)
            if base is None:
                # 兼容旧的数字分类号（cat=0/4/3/1/5）
                try:
                    base = self._by_cat.get(int(cat_key), [])
                except (TypeError, ValueError):
                    base = []

        if not q:
            page = base[offset:offset + limit]
            return page, offset + limit < len(base)

        scored = []
        spaced = " " in q  # 只有关键词带空格时才需要看「下划线换成空格」的形式
        for e in base:
            if q in e.blob:
                nl = e.nl
                ns = nl.replace("_", " ") if spaced else nl
                if nl == q or ns == q:
                    rank = 0
                elif nl.startswith(q) or ns.startswith(q) or nl.endswith("_" + q):
                    rank = 1
                elif q in nl or q in ns:
                    rank = 2
                else:
                    rank = 3
                scored.append((rank, -e.count, e))
        scored.sort(key=lambda item: (item[0], item[1]))
        page = [item[2] for item in scored[offset:offset + limit]]
        return page, offset + limit < len(scored)


# --------------------------------------------------------------------------
# 模块级单例
# --------------------------------------------------------------------------

_DB = None
_DB_LOCK = threading.Lock()


def get_tag_db(plugin_dir: str) -> TagDB:
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                _DB = TagDB(plugin_dir)
    return _DB


def reload_tag_db(plugin_dir: str) -> TagDB:
    """丢掉缓存重新加载（词库更新后调用）。"""
    global _DB
    with _DB_LOCK:
        _DB = TagDB(plugin_dir)
    return _DB
