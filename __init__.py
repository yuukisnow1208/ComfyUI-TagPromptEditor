# -*- coding: utf-8 -*-
"""ComfyUI-TagPromptEditor · WebUI 风格的标签块提示词编辑器

从 Stable Diffusion WebUI 搬过来的提示词编辑体验：
    ① 顶部文本域 —— 逗号分隔的原始提示词（ComfyUI 原生 widget）
    ② 标签块区   —— 每个 tag 一个彩色块，可删除 / 调权重 / 拖拽排序
    ③ 分类栏     —— 全量 Danbooru 标签库（12 万条）三级分类 + 中文说明，点一下即加入

输出 STRING，直接接原生 CLIPTextEncode 的 text 输入。

注意：这里刻意**不提供** pyproject.toml 的 ``[tool.comfy] web`` 字段。
因为 ComfyUI 会同时按「模块名」和「project.name」注册 web 目录，
两边都写会让同一份 JS 被导入两次，扩展注册两遍。
只保留 ``WEB_DIRECTORY`` 这一条路径最稳。
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

__version__ = "1.2.5"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
