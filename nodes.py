# -*- coding: utf-8 -*-
"""ComfyUI-TagPromptEditor · 节点与标签库 HTTP 接口

节点本身是一个**极简透传**：``STRING -> STRING``。
所有编辑逻辑（标签块、权重、拖拽排序、预设选择器）都在前端 ``web/`` 里，
编辑完成后序列化回这个 ``text`` widget —— 于是工作流保存 / 复制粘贴 / 撤销
全部复用 ComfyUI 原生机制，后端不需要任何额外状态。
"""

import asyncio
import os

from aiohttp import web

from .favorites import get_favorites
from .tagdb import get_tag_db, reload_tag_db

try:
    from server import PromptServer
except Exception:  # 脱离 ComfyUI 环境导入时（比如跑单测）也不能炸
    PromptServer = None

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 节点
# ---------------------------------------------------------------------------

class TagPromptEditor:
    """WebUI 风格的标签块提示词编辑器（编辑界面在前端提供）。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "dynamicPrompts": False,
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    OUTPUT_TOOLTIPS = ("逗号分隔的提示词，带 (tag:权重) 语法，直接接 CLIPTextEncode",)
    FUNCTION = "run"
    CATEGORY = "utils/prompt"
    DESCRIPTION = (
        "WebUI 风格的标签块提示词编辑器。\n"
        "上方文本域是原始提示词，下方标签块区域可直接删除标签、"
        "调整权重、拖拽排序，最下方是带中文说明的全量 Danbooru 标签选择器。\n"
        "输出 STRING，接 CLIPTextEncode 的 text 输入。"
    )
    SEARCH_ALIASES = ["tag editor", "prompt editor", "提示词编辑器", "标签", "tags", "webui"]

    def run(self, text):
        return (text,)


NODE_CLASS_MAPPINGS = {
    "TagPromptEditor": TagPromptEditor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "TagPromptEditor": "🏷️ 标签提示词编辑器 (Tag Prompt Editor)",
}


# ---------------------------------------------------------------------------
# HTTP 接口：给前端预设选择器喂数据
#
# 全量 danbooru 有 12 万条，不可能一次性塞给浏览器 —— 所以走服务端分页搜索，
# 基础列表在 tagdb 里已按热度降序预排，收满 limit 就提前退出。
# ---------------------------------------------------------------------------

_ROUTES_REGISTERED = False


async def _ensure_loaded(db):
    """加载词库可能耗时（冷启动 + 杀毒扫描），丢到线程池里，别卡事件循环。"""
    return await asyncio.get_running_loop().run_in_executor(None, db.ensure_loaded)


def _sync_favorites(db):
    """把磁盘上的收藏同步进词库的「推荐」分类。

    db.set_favorites 只在列表真的变了时才重建，所以每次请求调它的代价可以忽略。
    """
    fav = get_favorites(_PLUGIN_DIR)
    names = fav.list()
    db.ensure_loaded()
    if names != db.favorites:
        db.set_favorites(names)
    return fav, set(names)


async def _health(request):
    db = get_tag_db(_PLUGIN_DIR)
    ok = await _ensure_loaded(db)
    fav, fav_set = _sync_favorites(db)
    data = db.stats()
    data["ok"] = ok
    data["hasMore"] = False
    data["favorites"] = len(fav_set)
    return web.json_response(data)


async def _categories(request):
    db = get_tag_db(_PLUGIN_DIR)
    await _ensure_loaded(db)
    _sync_favorites(db)
    return web.json_response({
        "categories": db.categories(),
        "error": db.error,
    })


async def _tags(request):
    db = get_tag_db(_PLUGIN_DIR)
    await _ensure_loaded(db)
    _, fav_set = _sync_favorites(db)

    raw_cat = request.query.get("cat")
    cat = None
    if raw_cat not in (None, "", "all"):
        raw_cat = raw_cat.strip()
        cat = int(raw_cat) if raw_cat.lstrip("-").isdigit() else raw_cat

    items, more = db.search(
        q=request.query.get("q", ""),
        cat=cat,
        limit=request.query.get("limit", 60),
        offset=request.query.get("offset", 0),
    )
    return web.json_response({
        "items": [dict(e.to_dict(), fav=e.name in fav_set) for e in items],
        "hasMore": more,
        "error": db.error,
    })


async def _lookup(request):
    """批量取中文名：GET /tag_prompt_editor/lookup?tags=1girl,solo,...

    标签块里的 tag 来自文本框，不经过 /tags 搜索接口，所以拿不到中文名。
    前端把当前块里的英文名攒起来一次性补查（结果在前端缓存，不重复问）。

    名字用逗号分隔：tag 名只会是 ``[a-z0-9_()'-]``，不会自带逗号。
    """
    db = get_tag_db(_PLUGIN_DIR)
    await _ensure_loaded(db)
    names = [s.strip() for s in request.query.get("tags", "").split(",")]
    names = [n for n in names if n][:500]     # 上限只是防滥用，一个块通常几十个
    return web.json_response({
        "lookup": db.lookup(names),
        "count": len(names),
        "error": db.error,
    })


async def _favorites_get(request):
    db = get_tag_db(_PLUGIN_DIR)
    fav, fav_set = _sync_favorites(db)
    names = sorted(fav_set)
    return web.json_response({"tags": names, "count": len(names), "error": db.error})


async def _favorites_post(request):
    """收藏 / 取消收藏。body: {"action": "toggle"|"add"|"remove", "tag": "..."}"""
    db = get_tag_db(_PLUGIN_DIR)
    fav = get_favorites(_PLUGIN_DIR)

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    tag = payload.get("tag") or payload.get("name") or ""
    action = payload.get("action") or "toggle"
    if not isinstance(tag, str) or not tag.strip():
        return web.json_response(
            {"ok": False, "error": "缺少 tag 参数", "tags": fav.list()}, status=400
        )

    loop = asyncio.get_running_loop()
    if action == "add":
        names = await loop.run_in_executor(None, fav.add, tag)
        now = fav.has(tag)
    elif action == "remove":
        names = await loop.run_in_executor(None, fav.remove, tag)
        now = False
    else:
        names, now = await loop.run_in_executor(None, fav.toggle, tag)

    db.set_favorites(names)
    return web.json_response({
        "ok": True,
        "fav": now,
        "tag": tag.strip(),
        "tags": sorted(names),
        "count": len(names),
    })


async def _reload(request):
    db = reload_tag_db(_PLUGIN_DIR)
    await _ensure_loaded(db)
    _sync_favorites(db)
    data = db.stats()
    data["ok"] = bool(db.source)
    return web.json_response(data)


def _register_routes():
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return
    instance = getattr(PromptServer, "instance", None) if PromptServer else None
    if instance is None:
        return
    routes = instance.routes
    routes.get("/tag_prompt_editor/health")(_health)
    routes.get("/tag_prompt_editor/categories")(_categories)
    routes.get("/tag_prompt_editor/tags")(_tags)
    routes.get("/tag_prompt_editor/lookup")(_lookup)
    routes.get("/tag_prompt_editor/favorites")(_favorites_get)
    routes.post("/tag_prompt_editor/favorites")(_favorites_post)
    routes.get("/tag_prompt_editor/reload")(_reload)
    _ROUTES_REGISTERED = True


_register_routes()
