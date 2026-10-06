# -*- coding: utf-8 -*-
"""收藏标签的持久化。

存成插件目录下的 ``favorites.json``（不是 ComfyUI 的 user 目录）—— 无依赖、
方便用户直接备份或手改，并且已加进 ``.gitignore``，不会污染仓库。

两个刻意的设计：

1. **原子写入**：先写同目录的临时文件再 ``os.replace`` 覆盖。同分区上这是原子操作，
   写到一半掉电也不会把整个收藏夹清空。
2. **读永不抛异常**：文件被手改坏、编码错乱、结构不对，一律退化成空列表 ——
   不能让一个收藏文件把整个编辑器搞到打不开。

本模块不依赖 ComfyUI，可脱离环境单测（见 dev/test_favorites.py）。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading

FAVORITES_VERSION = 1
MAX_FAVORITES = 5000      # 防手改或异常写入把文件撑爆
MAX_NAME_LEN = 200

FILENAME = "favorites.json"


def _normalize(value) -> str:
    """把任意输入收敛成合法的标签名，非法就返回空串。"""
    if isinstance(value, dict):
        value = value.get("name", "")
    if not isinstance(value, str):
        return ""
    name = value.strip()
    if not name or len(name) > MAX_NAME_LEN:
        return ""
    return name


class Favorites:
    def __init__(self, plugin_dir: str):
        self.path = os.path.join(plugin_dir, FILENAME)
        self._lock = threading.Lock()
        self._cache = None
        self._mtime = None

    # -- 读写 ---------------------------------------------------------------

    def _read_locked(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return []
        except Exception:
            # 坏文件不抛：退化成空列表，用户还能继续用编辑器
            return []

        if isinstance(data, dict):
            items = data.get("tags")
        else:
            items = data          # 容错：文件直接就是个数组也认

        if not isinstance(items, list):
            return []

        out, seen = [], set()
        for it in items:
            name = _normalize(it)
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(name)
            if len(out) >= MAX_FAVORITES:
                break
        return out

    def _mtime_locked(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def _read_cached_locked(self):
        """带 mtime 缓存 —— /tags 是高频路由，不该每次搜索都重新解析 JSON。
        但用户手改 favorites.json 也要能生效，所以按修改时间失效。"""
        mtime = self._mtime_locked()
        if self._cache is not None and mtime is not None and mtime == self._mtime:
            return list(self._cache)
        items = self._read_locked()
        self._cache = items
        self._mtime = mtime
        return list(items)

    def _write_locked(self, names):
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        payload = {"version": FAVORITES_VERSION, "tags": names}
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".favorites-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)   # 同分区原子替换
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self._cache = list(names)
        self._mtime = self._mtime_locked()

    # -- 对外 ---------------------------------------------------------------

    def list(self):
        with self._lock:
            return self._read_cached_locked()

    def count(self):
        return len(self.list())

    def has(self, name: str) -> bool:
        key = _normalize(name)
        return bool(key) and key in self.list()

    def add(self, name: str):
        key = _normalize(name)
        with self._lock:
            items = self._read_cached_locked()
            if not key or key in items or len(items) >= MAX_FAVORITES:
                return items
            items.append(key)
            self._write_locked(items)
            return list(items)

    def remove(self, name: str):
        key = _normalize(name)
        with self._lock:
            items = self._read_cached_locked()
            if not key or key not in items:
                return items
            items = [x for x in items if x != key]
            self._write_locked(items)
            return list(items)

    def toggle(self, name: str):
        """收藏 / 取消收藏，返回 (最新列表, 现在是否为收藏)。"""
        key = _normalize(name)
        if not key:
            return self.list(), False
        with self._lock:
            items = self._read_cached_locked()
            if key in items:
                items = [x for x in items if x != key]
                now = False
            else:
                if len(items) >= MAX_FAVORITES:
                    return list(items), False
                items.append(key)
                now = True
            self._write_locked(items)
            return list(items), now


_singletons = {}
_singletons_lock = threading.Lock()


def get_favorites(plugin_dir: str) -> Favorites:
    with _singletons_lock:
        fav = _singletons.get(plugin_dir)
        if fav is None:
            fav = Favorites(plugin_dir)
            _singletons[plugin_dir] = fav
        return fav
