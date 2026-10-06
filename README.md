# 🏷️ ComfyUI-TagPromptEditor

把 **Stable Diffusion WebUI 的提示词编辑体验**搬进 ComfyUI。

ComfyUI 原生的提示词输入只有一个 `CLIPTextEncode` 的多行文本框：全英文、纯文本，
标签改权重靠手打括号、删一个词得从一串逗号里挑、排序靠剪切粘贴。
这个节点补上 WebUI 那一套「标签方块」交互：

```
┌──────────────────────────────────────────────┐
│ 1girl, long_hair, (masterpiece:1.2), smile   │  ← 原生 text widget（可折叠）
├──────────────────────────────────────────────┤
│ 去重  排序  权重归 1  清空   共 4 个标签 · 生效 4 个 │  ← 工具栏
│ ┌──────────┐ ┌───────────┐ ┌────────────────┐ │
│ │1girl   × │ │long_hair ×│ │masterpiece ×1.2│ │  ← 标签块：点文字=禁用，
│ └──────────┘ └───────────┘ └────────────────┘ │     点权重=调值，拖动=排序
├──────────────────────────────────────────────┤
│ 🔍 搜索标签，支持中文（长发 / miku / 微笑）        │
│ [推荐][质量词][负面][通用][角色][作品][画师][元数据][全部]│  ← 预设选择器
│ ┌────────────┐┌────────────┐┌────────────┐   │
│ │ 1girl      ││ long_hair  ││ masterpiece│   │
│ │ 一个女孩    ││ 长发        ││ 杰作        │   │
│ └────────────┘└────────────┘└────────────┘   │
└──────────────────────────────────────────────┘
```

输出 `STRING`，直接接原生 `CLIPTextEncode` 的 `text` 输入 —— **不替换、不劫持任何官方节点**。

---

## ✨ 功能

### 标签块区（对应 WebUI 的 tag 方块）

鼠标移到标签块上，会浮出一条**操作工具条**（模仿 WebUI 的
`sd-webui-prompt-all-in-one` 的 tag 面板）：

```
   ┌───┬─────┬───┬───┬───┬───┬───┬───┬───┐
   │ − │ 1.4 │ + │ ( │ ) │ ★ │ ✎ │ ⊘ │ × │
   └───┴─────┴───┴───┴───┴───┴───┴───┴───┘
     权重步进     括号   收藏 编辑 禁用 删除
```

| 操作 | 交互 |
| --- | --- |
| **编辑** | **单击**标签文字 → 原地输入（回车保存 / Esc 取消） |
| **启用 / 禁用** | **双击**标签文字，或点工具条的 `⊘`。禁用后不参与输出，但保留在编辑器里 |
| 改权重 | 工具条的 `−` `+` 按档位步进、输入框直接改；标签块上滚轮微调 ±0.05，`Shift+滚轮` 按档位 |
| 括号 | 工具条的 `(` `)` = 权重 ×1.1 / ÷1.1（ComfyUI 里 `(tag)` 本身就是 ×1.1） |
| 收藏 | 工具条的 `★`。收藏的标签会排到「推荐」分类最前面，并写进 `favorites.json` |
| 删除 | 点标签右侧的 `×`，或工具条的 `×` |
| 排序 | 按住标签块拖拽（HTML5 drag），落点有插入指示线 |
| 批量 | 工具栏：`去重` / `排序`（字母序） / `权重归 1` / `清空` |

> **工具条上为什么没有方括号按钮？** WebUI 用 `[tag]` 降权，但 ComfyUI 的
> `parse_parentheses()` **只认圆括号** —— `[tag]` 会原样进 tokenizer 变成无效 token。
> 所以「降权」统一走数值权重 `(tag:0.8)`，语义完全等价，也不会产出坏 prompt。

单击与双击靠 **250 ms 判定窗口**区分（和 WebUI 那套一致）：单击后先等一下，
确认没有第二下才进入编辑。

权重档位沿 WebUI 习惯：`0.3 0.4 0.5 0.6 0.7 0.8 0.9 1 1.05 1.1 1.15 1.2 1.3 1.4 1.5 1.6 1.8 2`，
走到两端会**饱和**而不是绕回去。权重为 `1` 时序列化成裸标签（不写括号），保持 prompt 干净。

### 预设选择器

- **全量 Danbooru 词库**，实测 **121,078 条**，其中 **87,860 条带中文说明（73%）**。
- 9 个分类 tab：`推荐` `质量词` `负面` `通用` `角色` `作品` `画师` `元数据` `全部`。
  前三个是人工精选常用词（质量词如 `masterpiece` 在 danbooru 里查不到，单独补的），后六个按 danbooru 官方分类。
- 搜索框**中英混搜**：输入 `长发` 能搜到 `long_hair`，输入 `miku` 也能搜到 `hatsune_miku`。
  排序按「完全匹配 → 前缀/词尾匹配 → 包含」三档，同档内按热度（danbooru 使用量）降序。
  所以在精选分类里搜索时会**自动切到全部标签**，避免只搜那百来条精选。
- 滚到底自动翻页加载，每页 60 条。

### 其他

- **尺寸自适应**：把节点拉宽，标签块会自动重排、预设网格会自动加列；把节点拉高，
  预设面板会跟着变高（多出来的高度在文本框和面板之间自动分配）。压矮到面板只剩 200px 就不再缩。
- 检测到 `[方括号]` 标签时会给出黄色警告条 —— ComfyUI 的权重解析器（`comfy/sd1_clip.py::parse_parentheses`）
  **只认圆括号**，`[tag]` 不生效。这是从 A1111 迁移工作流时最容易踩的坑。
- 撤销 / 重做复用 ComfyUI 原生机制（每次编辑写一个 `beforeChange`/`afterChange` 检查点），
  `Ctrl+Z` 就能回退标签操作。

---

## 📦 安装

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/yuukisnow1208/ComfyUI-TagPromptEditor.git
```

没有 git 的话，直接下载 ZIP 解压到 `ComfyUI/custom_nodes/` 也一样。

> 尚未提交到 ComfyUI-Manager 的插件注册表，所以 Manager 里暂时搜不到，请用上面的方式安装。
>
> **不支持**放进 `custom_nodes` 的二级子目录（如 `custom_nodes/my-plugins/xxx`），
> 必须直接是 `custom_nodes/ComfyUI-TagPromptEditor/`。

重启 ComfyUI，节点出现在 `utils/prompt` 分类下，搜「标签」或「tag editor」都能找到。

**零第三方依赖** —— 只用 Python 标准库 + 一个原生 JS，不需要 `pip install`。
（`aiohttp` 是 ComfyUI 自带的。）

### 词库

插件**自带**词库在 `tags/` 下：

```
tags/danbooru.csv            # 3.19 MB（GB18030 编码）
tags/danbooru.zh_CN_SFW.csv  # 3.14 MB（UTF-8 编码）
```

如果不想让仓库带着 6 MB CSV，删掉 `tags/` 也能用 —— 会自动去本机已装的 SD WebUI / Forge 里找
`extensions/a1111-sd-webui-tagcomplete/tags/`（扫描 `C:`~`G:/AI/*/` 等常见路径）。
也可以用环境变量手动指定：

```bash
TAG_PROMPT_EDITOR_TAGS_DIR=/path/to/tags
```

查找优先级：**环境变量 → 插件自带 `tags/` → 本机 SD WebUI 目录**。

---

## 🔌 HTTP 接口

预设选择器是服务端分页搜索的（12 万条不可能一次性塞给浏览器）。
冷启动加载约 **300 ms**，最坏情况（单字母搜索）约 **90 ms**。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/tag_prompt_editor/health` | 词库统计：总数、带中文数、来源、加载错误 |
| GET | `/tag_prompt_editor/categories` | tab 列表（id / 中文名 / 条数） |
| GET | `/tag_prompt_editor/tags?q=&cat=&limit=60&offset=0` | 分页搜索，返回 `{items, hasMore}`，每项带 `fav` 标记 |
| GET | `/tag_prompt_editor/favorites` | 收藏列表 `{tags, count}` |
| POST | `/tag_prompt_editor/favorites` | body `{action: "toggle"\|"add"\|"remove", tag}` |
| GET | `/tag_prompt_editor/reload` | 更新词库 CSV 后热重载，不用重启 ComfyUI |

```bash
curl --noproxy '*' "http://127.0.0.1:8188/tag_prompt_editor/tags?q=长发&limit=5"

curl --noproxy '*' -X POST -H "Content-Type: application/json" \
  -d '{"action":"toggle","tag":"masterpiece"}' \
  "http://127.0.0.1:8188/tag_prompt_editor/favorites"
```

收藏数据存在插件目录的 `favorites.json`（已加进 `.gitignore`，不会提交）。
写入用「临时文件 + `os.replace`」保证原子性，读到坏文件会退化成空列表 ——
一个收藏文件不该把编辑器搞到打不开。

---

## 🧪 开发与测试

测试脚本在 `dev/`，三层验证：

| 脚本 | 覆盖 | 结果 |
| --- | --- | --- |
| `dev/test_tag_core.mjs` | 前端纯逻辑（解析/序列化/权重/排序/去重） | 49 项 ✅ |
| `dev/test_tagdb.py` | 词库加载、编码嗅探、分类、搜索排序、分页 | 73 项 ✅ |
| `dev/test_favorites.py` | 收藏读写、原子写入、坏文件容错、并发、fav 分类合并 | 47 项 ✅ |
| `dev/e2e_tag_editor.py` | 起真实 ComfyUI 实例，验节点注册 + 6 个路由 + STRING 透传 | 全过 ✅ |
| `dev/ui_tag_editor.mjs` | Playwright：结构恢复、工具条、拖拽、删除、编辑、搜索、上下联动，截图 | 53 项 ✅ |
| `dev/ui_tag_bar.mjs` | 工具条专项：悬停 / 权重 / 括号 / 收藏落盘 / 单击编辑 / 双击禁用 / 上下联动 | 49 项 ✅ |
| `dev/verify_resize.mjs` | 节点缩放自适应：拖文本框、拖宽、拖高、拖矮 + 功能回归 | 14 项 ✅ |
| `dev/verify_git_eol.py` | 模拟 `git clone`，对比 CRLF 源文件与 LF 检出后的词库加载结果 | 27 项 ✅ |

`test_tag_core.mjs` 的特别之处：它把 `comfy/sd1_clip.py` 里的 `parse_parentheses` 和
`token_weights` 原样移植成 JS，作为**真值**来断言前端序列化的结果 —— 保证生成的 prompt
权重与 ComfyUI 官方解析器逐位一致，而不是「看起来对」。

跑测试：

```bash
# 纯逻辑（不需要 ComfyUI）
node dev/test_tag_core.mjs
E:/AI/ComfyUI-aki-v3/python/python.exe dev/test_tagdb.py

# 端到端（会另起一个临时实例，不动 8188 上正在跑的）
E:/AI/ComfyUI-aki-v3/python/python.exe dev/e2e_tag_editor.py
```

---

## ⚠️ 已知限制

1. **不支持 `[tag]` 语法** —— ComfyUI 后端只解析圆括号。节点会主动警告并给出修正提示。
2. **`<lora:xxx>` 语法**是 ComfyUI 的模型加载器语法，不属于 `CLIPTextEncode`，
   本节点只把它当普通文本透传（在标签块区会显示为一个不可调权重的块）。
3. 词库里的中文来自 tagcomplete 的 zh_CN 翻译表，**覆盖 73%**，冷门 tag 没有中文属正常。
4. 用 Vue Nodes 模式（`Comfy.VueNodes.Enabled`）时 DOM widget 由 Vue 接管，
   本节点按 canvas 模式实现，Vue 模式下不保证交互完整。

---

## 🧱 实现要点

给同样在写 ComfyUI 插件的同学几个值得记的坑：

- **【最容易踩】DOM widget 的宽度会被前端写脏，导致「节点拉宽、下半部分 UI 不动」。**
  前端 1.53 有个 `WidgetLegacy` Vue 渲染器，它把 widget 画进自己的 canvas，`draw()` 里执行
  `s.width = canvasEl.getBoundingClientRect().width`。而 DOM widget 容器的宽度是这样算的
  （`GraphView` 的 `DomWidgets.updateWidgets`）：

  ```js
  let c = (n.width ?? i.width) - t * 2;   // n = widget, i = node, t = margin
  (r.size[0] !== c) && (r.size = [c, l]);
  ```

  **`widget.width` 优先于 `node.width`** —— 一旦被写成当时的 canvas 像素宽度（实测 254.8125
  这种小数），节点再拉多宽容器都卡死在这个值上。
  本插件的解法是把 `width` 定义为恒返回 `undefined` 的访问器，恢复前端「从未设置」的语义：

  ```js
  Object.defineProperty(widget, "width", {
    configurable: true, enumerable: false,
    get: () => undefined, set: () => {},
  });
  ```

  原生 `text` 文本框是前端自己建的、不走 `WidgetLegacy`，所以它一直正常 —— 这正是
  「文本框撑满了、下面的 UI 却不动」这一现象的来源。
- **DOM Widget 的高度**由 `options.getMinHeight` / `getMaxHeight` / `getHeight`（函数）决定，
  **不是** `computeSize`。改高度时对 `node.size` 做**增量**调整，别硬设绝对值。
  另外 `minHeight < maxHeight` 时，前端 `_arrangeWidgets` + `distributeSpace` 会把节点多出来的
  高度**弹性分配**给它 —— 这正是「拉高节点 → 面板变高」不用自己算的原因。
- **绝不隐藏原生 `text` widget**。widget 是按位置序列化的（`widgets_values` 数组），
  顺序或数量一变，旧工作流的值就会串位。所以本节点新增的两个 DOM widget 都 `serialize: false`，
  数据只存在 `text` 里，`widgets_values` 长度保持不变。
- **DOM Widget 在 `onNodeCreated` 之后才异步初始化**，测试里要 `waitForFunction` 等
  `node.widgets.length` 就位，不能 `loadGraphData` 后立刻断言。
- **浮层别放在 node 里**。工具条最初做在 DOM widget 内部，被后渲染的兄弟面板遮挡，
  还受 `Comfy.DOMClippingEnabled` 裁剪。改成挂到 `document.body` + `position: fixed; z-index: 10000`
  才彻底解决。
- **浮层的内容要跟着状态刷新**。工具条是「悬停时构建一次」的，但收藏 / 禁用 / 权重都会变 ——
  只在 `commit` 后重新定位的话，`★` 会一直停在旧状态（这个 bug 就是被 `dev/ui_tag_bar.mjs` 抓出来的）。
  用一串签名（`名称|权重|启用|收藏`）比对，变了才重建 DOM，既保证刷新又不至于每次编辑都闪。
- **同一份状态被两处渲染时，别让两边走不同的更新路径**。「标签块」和「预设网格」都依赖
  `tags` 数组：高亮是在 `renderGrid()` 里算的，但改标签的 `commit()` 只重渲染 chips，
  只有「点卡片加入」那条路额外补了一次 `renderGrid()`。结果是加标签时高亮同步、删标签时不同步 ——
  这正是「上面点 × 删掉 tag，下面方格还留着绿色描边」的原因。做法是在 `renderChips()` 末尾
  统一调一次增量同步 `syncGridSelection()`，让所有改动路径都覆盖到。
  注意**不要**用整块重建来同步：`grid.innerHTML = ""` 会把网格滚动位置清零。
- **浏览器测试有加载时序竞态**。页面自己也会加载一遍默认工作流，可能**晚于**
  测试里的 `loadGraphData` 完成，把它刚塞进去的节点顶掉 —— 表现为随机超时、且看节点类型
  会全是 `SaveImage`/`KSampler` 这些默认节点。`dev/*.mjs` 统一用「重试到真的出现
  `TagPromptEditor` 为止」来消除，不要只等 `app.graph` 就绪就往下跑。
- **`WEB_DIRECTORY` 只在 `__init__.py` 里声明**，pyproject.toml 里**不要**写 `[tool.comfy] web`。
  两边都写会让 ComfyUI 按「模块名」和「project.name」各注册一次，JS 被导入两遍。
- **排查这类前端问题的有效手法**：给可疑属性装 `defineProperty` setter 抓调用栈。
  `new Error().stack` 会直接指出是哪个前端函数写的值 —— 比翻 minified bundle 快得多。

---

## 📄 License

MIT
