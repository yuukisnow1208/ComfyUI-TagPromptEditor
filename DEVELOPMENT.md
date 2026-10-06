# 开发文档

面向二次开发与排查问题。用户请先读 [README.md](README.md)。

---

## 项目结构

```
ComfyUI-TagPromptEditor/
├── __init__.py        节点注册 + WEB_DIRECTORY（web 目录**只在这里**声明）
├── nodes.py           节点定义 + 6 个 HTTP 路由
├── tagdb.py           词库加载 / 分类 / 索引 / 分页搜索
├── taxonomy.py        分类规则（纯规则，只依赖标准库 re，~123 KB）
├── favorites.py       收藏读写（原子写）
├── tags/              自带词库 CSV
├── web/
│   ├── js/tagEditorCore.js    纯逻辑：解析 / 序列化 / 权重 / 排序 / 去重
│   ├── js/tagPromptEditor.js  节点 UI：标签块 / 工具条 / 分类栏 / 网格
│   └── css/editor.css         样式（全部走 ComfyUI CSS 变量，跟随明暗主题）
└── docs/screenshot.png
```

数据流：UI 的所有编辑最终都序列化回节点原生的 `text` widget ——
后端**不保存任何状态**，所以工作流保存 / 复制粘贴 / 撤销重做全部复用 ComfyUI 原生机制。

---

## 开发环境

- 改 `web/` 下的 JS / CSS：刷新页面即可生效。
- 改 Python：**必须重启 ComfyUI**，`/reload` 只重载前端资源、不重载 Python 模块。
- 同步到 `custom_nodes` 用 `dev/sync_plugin.py`（见下），别手动 `cp`：
  手动拷贝漏一个文件、或 `__pycache__` 没失效，都会表现为「改了代码但行为没变」，
  极难排查。

```bash
python dev/sync_plugin.py            # 拷贝插件文件 + 逐文件 md5 校验 + 清 __pycache__
python dev/sync_plugin.py --check    # 只校验不拷贝
```

浏览器测试需要一个实例。**不要动用户正在跑的那个**，另起一个端口：

```bash
cd E:/AI/ComfyUI-aki-v3/ComfyUI
E:/AI/ComfyUI-aki-v3/python/python.exe main.py \
  --cpu --port 8288 --listen 127.0.0.1 \
  --disable-all-custom-nodes --whitelist-custom-nodes ComfyUI-TagPromptEditor
```

本机访问 localhost 要绕开代理：`curl` 加 `--noproxy '*'`，
Chromium 加 `proxy: {server: "direct://"}` + `--no-proxy-server`。
Playwright 用 `channel: "msedge"` 启动（默认的 headless shell 本机没装）。

---

## 测试

```bash
# 纯逻辑，不需要 ComfyUI
node dev/test_tag_core.mjs
E:/AI/ComfyUI-aki-v3/python/python.exe dev/test_tagdb.py
E:/AI/ComfyUI-aki-v3/python/python.exe dev/test_favorites.py
E:/AI/ComfyUI-aki-v3/python/python.exe dev/verify_git_eol.py

# 端到端：会自己起一个临时实例
E:/AI/ComfyUI-aki-v3/python/python.exe dev/e2e_tag_editor.py

# 浏览器测试：需要 8288 上有个实例
node dev/ui_tag_cats.mjs --port 8288
node dev/ui_tag_editor.mjs --port 8288
node dev/ui_tag_bar.mjs --port 8288
node dev/verify_resize.mjs --port 8288
```

`test_tag_core.mjs` 的特别之处：它把 `comfy/sd1_clip.py` 里的 `parse_parentheses`
和 `token_weights` 原样移植成 JS 作为**真值**，断言前端序列化结果 ——
保证生成的 prompt 权重与 ComfyUI 官方解析器逐位一致，而不是「看起来对」。

### 浏览器测试的两个坑

- **加载时序竞态**：页面自己也会加载一份默认工作流，可能**晚于**测试里的
  `loadGraphData` 完成，把刚注入的节点顶掉 —— 表现为随机超时，且看节点类型
  全是 `SaveImage` / `KSampler`。统一用「重试到真的出现 `TagPromptEditor` 为止」。
- **DOM 里有 ≠ 用户看得见**：分类栏有 `max-height` + 内部滚动，
  而测试里点胶囊用的是 DOM `click()`（不检查可见性）。所以断言「第三行存在」是不够的 ——
  必须量 `getBoundingClientRect()` 确认它落在容器的可视区内。
  （第 3 行被 `max-height: 112px` 藏掉的 bug 就是这样漏过去的。）

---

## 实现要点（ComfyUI 前端坑）

给同样在写 ComfyUI 插件的同学：

- **【最容易踩】DOM widget 的宽度会被前端写脏，导致「节点拉宽、下半部分 UI 不动」。**
  前端 1.53 有个 `WidgetLegacy` Vue 渲染器，它把 widget 画进自己的 canvas，
  `draw()` 里执行 `s.width = canvasEl.getBoundingClientRect().width`；
  而 DOM widget 容器的宽度在 `GraphView` 的 `DomWidgets.updateWidgets` 里是：

  ```js
  let c = (n.width ?? i.width) - t * 2;   // n = widget, i = node, t = margin
  (r.size[0] !== c) && (r.size = [c, l]);
  ```

  **`widget.width` 优先于 `node.width`** —— 一旦被写成当时的 canvas 像素宽度
  （实测 254.8125 这种小数），节点再拉多宽容器都卡死在这个值上。
  解法是把 `width` 定义成恒返回 `undefined` 的访问器，恢复前端「从未设置」的语义：

  ```js
  Object.defineProperty(widget, "width", {
    configurable: true, enumerable: false,
    get: () => undefined, set: () => {},
  });
  ```

  原生 `text` 文本框是前端自己建的、不走 `WidgetLegacy`，所以它一直正常 ——
  这正是「文本框撑满了、下面的 UI 却不动」的来源。
- **DOM Widget 的高度**由 `options.getMinHeight` / `getMaxHeight` / `getHeight`（函数）决定，
  **不是** `computeSize`。改高度时对 `node.size` 做**增量**调整，别硬设绝对值。
  `minHeight < maxHeight` 时前端 `_arrangeWidgets` + `distributeSpace` 会把多出来的高度
  **弹性分配**给它 —— 这就是「拉高节点 → 面板变高」不用自己算的原因。
- **绝不隐藏原生 `text` widget**。widget 按位置序列化（`widgets_values` 数组），
  顺序或数量一变，旧工作流的值就会串位。本节点新增的两个 DOM widget 都是
  `serialize: false`，数据只存在 `text` 里，`widgets_values` 长度保持不变。
- **DOM Widget 在 `onNodeCreated` 之后才异步初始化**，测试里要 `waitForFunction`
  等 `node.widgets.length` 就位，不能 `loadGraphData` 后立刻断言。
- **浮层别放在 node 里**。工具条最初做在 DOM widget 内部，被后渲染的兄弟面板遮挡，
  还受 `Comfy.DOMClippingEnabled` 裁剪。改成挂到 `document.body` +
  `position: fixed; z-index: 10000` 才彻底解决。
- **浮层内容要跟着状态刷新**。工具条是「悬停时构建一次」的，但收藏 / 禁用 / 权重都会变；
  只在 `commit` 后重新定位的话，`★` 会一直停在旧状态。用一串签名
  （`名称|权重|启用|收藏`）比对，变了才重建 DOM。
- **同一份状态被两处渲染时，别让两边走不同的更新路径**。「标签块」和「结果网格」
  都依赖 `tags` 数组：高亮在 `renderGrid()` 里算，但改标签的 `commit()` 只重渲染 chips，
  只有「点卡片加入」那条路额外补了一次 `renderGrid()`。结果加标签时高亮同步、
  删标签时不同步 —— 这就是「上面点 × 删掉 tag，下面网格还留着绿色描边」的原因。
  做法是在 `renderChips()` 末尾统一调一次增量同步 `syncGridSelection()`。
  注意**不要**用整块重建来同步：`grid.innerHTML = ""` 会把滚动位置清零。
- **`WEB_DIRECTORY` 只在 `__init__.py` 里声明**，`pyproject.toml` 里**不要**写
  `[tool.comfy] web`。两边都写会让 ComfyUI 按「模块名」和「project.name」各注册一次，
  JS 被导入两遍。
- **排查这类前端问题的有效手法**：给可疑属性装 `defineProperty` setter 抓调用栈，
  `new Error().stack` 会直接指出是哪个前端函数写的值 —— 比翻 minified bundle 快得多。

---

## 分类器（taxonomy.py）

### 为什么要自己分

`danbooru.csv` 只有 5 个粗分类号（0 通用 28,141 / 1 画师 49,441 / 3 作品 8,284 /
4 角色 34,755 / 5 元数据 457），通用类挤了 2.8 万条。
外部数据源也走不通：Danbooru 的 `tag_groups.json` 端点 404；
本机 tagcomplete 的 `danbooru.csv` 与插件内的是同一版本（md5 一致）。
→ **纯规则是唯一路径。**

必须基于**英文 tag 名**：标签库的中文名覆盖 73% 但质量极差
（`short_hair` → 「短毛短毛猫」、`bow` → 「鞠躬」），拿它当依据会错得离谱。

### 匹配优先级

```
1  类别例外（CATEGORY_OVERRIDES）
2  类别权威：cat 1/3/4（画师/作品/角色）直接定死 —— 专有名词不猜
3  后缀规则 SUFFIX_RULES
4  精确规则 EXACT_RULES
5  前缀规则 PREFIX_RULES
5b 正则规则 REGEX_RULES
6  末尾候选（整体名 → 末尾 4/3/2/1-gram → 逐词元，每级带单复数变体）
6b 颜色词
7  子串规则 CONTAINS_RULES
8  兜底
```

上面只算到**二级**。二级桶仍然太粗时，再由 `DEEP_RULES`（按父路径给「关键词 → 三级桶」）
切第三刀；`classify = _deepen(_classify_base(...))`。
**命中即返回；全不命中就保持两级**，不硬造空「其它」。

### 几条踩过的坑

- **规则表分层时，通用词条不能跨层复用。** 曾让「精确词条也能当后缀用」
  （想让 `x_hair_ornament` 借到 `hair_ornament`），结果 `emblem` / `fantasy` / `on_back`
  被当后缀，把 `fire_emblem` → 场景、`final_fantasy` → 场景、`weapon_on_back` → 卧姿，
  误伤 1,600+ 条。正解是把该词条**显式写进后缀表**（只动 218 条、零误伤）。
- **顺序敏感**。裤装「牛仔裤」原先写 `("jeans", "denim")`，`denim` 把
  `denim_overalls`（牛仔**背带裤**，长款 overalls）错拉进来 —— 改成只认 `jeans`。
  同理鞋袜里 `barefoot_sandals`（是鞋不是赤足）、`no_shoes` / `no_socks`
  必须排在通用词元之前，否则会被 `shoes` / `socks` 吃掉。
- **分档阈值要按类目自适应**。画师和作品的使用量差一个数量级
  （画师最高 5,868，作品最高 100 万+）。同一套阈值下「画师 / 超人气」会是个永远空着的桶。
- **子级排序要跟语义走**。「画师 / 作品」的热度档里「长尾」条数最多，
  按条数降序会把它顶到第一个，用户得先划过 3 万条冷门才见到「超人气」——
  语义顺序（由热到冷）才对。其余分类仍按条数降序。
- **长尾极度分散时别硬凑覆盖率**。进入「末尾词元 top1 只出现 26 次」的区间后，
  手工补词的投入产出比会迅速崩塌。这时该换指标：不看条数占比（长尾天然难看），
  改看「**按使用热度加权**的覆盖率」和「热度前 N 条是否 100% 归类」。

### 迭代方法

1. 用 `dev/taxonomy_proto.py` 看覆盖率与未归类清单
   （`--miss` 列未归类，`--sample` 抽样核对）。
2. 改规则。
3. 用「**隔离对拍**」确认改动面：造一份禁用该改动的变体，全量跑一遍比出受影响的
   tag 清单，逐条审。`_art` 子串规则就是这样被抓出来的 ——
   它把 `banned_artist`（热度 8.4 万）判成了「风格画质 / 媒介」，
   同族的 `master_artoria`、`galarian_articuno` 也一并中招。

> 对拍时注意：**锚点别含换行**。文件是 CRLF，`str.replace` 的换行锚点会静默失配，
> 结果拿到一份没改过的「变体」白看一遍数据。

---

## 发布流程

1. 改完代码 → `python dev/sync_plugin.py`（校验 md5 一致）。
2. 跑全量测试（上表 9 个脚本）。
3. `git commit` + `git push origin main`。
4. 打附注标签 `git tag -a vX.Y.Z -m "..."` 并 `git push origin vX.Y.Z`。

仓库 `.gitattributes` 是 `* text=auto eol=lf`：`tags/*.csv` 源文件是 CRLF、
仓库里存 LF，用户 clone 拿到的是 LF 版（文件小约 121 KB = 行数 × 1 字节）。
`dev/verify_git_eol.py` 验证过两种换行符下词库加载结果**逐项一致**
（代码走 `csv.reader(io.StringIO(text))`，天然兼容）。

推送走 SSH（`git@github.com:...`），`github.com` 的 HTTPS 在本机需要走代理。

> **先做完再打标签。** 曾经在功能只做了一半时就推了 tag，只能
> `git tag -d` + 重建 + `--force` 把它移到最后一次提交。已推送的 tag 属于公开历史，
> 能不动就不动。
