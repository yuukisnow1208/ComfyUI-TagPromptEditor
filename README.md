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
│ [全部][推荐][质量词][负面][人物主体][面部][身体][服饰]…│  ← 一级：24 个大类
│ [全部][配饰][上衣][制服][泳装][鞋袜][图案][外套]…    │  ← 二级：点「服饰」后展开
│ [全部][长发][短发][发色]                          │  ← 三级：点「头发」后展开
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

### 分类栏（三级胶囊下钻）

- **全量 Danbooru 词库**，实测 **121,078 条**，其中 **87,860 条带中文说明（73%）**。
- **24 个一级大类**，每个大类下面再分小类，小类下面还有细类：

  ```
  推荐  质量词  负面  人物主体  面部  身体  服饰  姿势  动作  场景  光影
  天气时间  构图镜头  风格画质  色彩  道具物件  动植物  文字符号  成人内容
  画师  角色  作品  元数据  其它
  ```

  三级实例（第二级仍然太粗时会再切一刀）：

  | 一级 | 二级 | 三级 |
  | --- | --- | --- |
  | 服饰 | 裤装 | **短裤 / 牛仔裤 / 长裤** |
  | 服饰 | 鞋袜 | 袜子 / 靴子 / 高跟鞋 / 鞋子 / 赤足状态 |
  | 服饰 | 配饰 | 发饰 / 帽子 / 首饰 / 缎带领结 / 颈饰 / 眼镜 / 手套 / 腰带 |
  | 面部 | 头发 | 长发 / 短发 / 发色 |
  | 面部 | 脸部 | 妆容 / 胡须 / 痣与雀斑 / 面部印痕 / 眼部佩戴 |
  | 身体 | 身体特征 | 兽耳 / 尾巴 / 角 / 翼与羽 / 光环 / 穿刺 / 疤痕纹身 |
  | 道具物件 | 武器 | 刀剑 / 枪械 / 长杆兵器 / 弓弩 / 盾甲 |
  | 动植物 | 动物 | 猫 / 狗 / 兔 / 鸟 / 鱼与水族 / 虫 / 玩偶 / 幻想生物 |
  | 角色 | 按作品 | azur_lane / fate / pokemon / arknights… |
  | 画师 | 超人气 / 人气 / 常见 / 长尾 | — |

  **不是所有桶都有第三级** —— 没有自然的细分就保持两级（例如「姿势 / 坐姿」），
  不会硬造一个空的「其它」。

- **交互**：胶囊按层级横排，一行一级。点一级出第二行，点二级出第三行；每行的
  「全部」是回上一级。没有更细的层级就不会出现多余的空行。分类栏总高限制在
  112px 内部滚动，不会把下面的网格挤没。
- **搜索忽略分类**：一旦有搜索词，结果来自全库，不受当前分类限制 ——
  否则「在鞋袜里搜 long_hair」会什么都搜不到，人会以为是词库缺词。
- 搜索框**中英混搜**：输入 `长发` 能搜到 `long_hair`，输入 `miku` 也能搜到 `hatsune_miku`。
  排序按「完全匹配 → 前缀/词尾匹配 → 包含」三档，同档内按热度（danbooru 使用量）降序。
- 滚到底自动翻页加载，每页 60 条。

#### 分类是怎么定出来的

这份分类**不是** danbooru 自带的（它只有 5 个粗分类号，通用类里就挤了 2.8 万条）。
是真对 12 万条 tag 逐条算出来的，规则见 `taxonomy.py`：

| 指标 | 实测 |
| --- | --- |
| 分类节点 | **1,626 个**（24 个一级 / 154 个二级 / 1,448 个三级） |
| 未归类 | 9,113 条（**7.5%**） |
| 未归类 · 按使用热度加权 | **2.82%** |
| 使用量 ≥ 10 万的热门 tag | **100% 已归类** |
| 热度前 500 的 tag | **100% 已归类** |
| 全量加载 + 分类耗时 | 约 **0.5 s** |

两条贯穿始终的原则：

1. **中心词在末尾**。danbooru 的 tag 是 `a_b_c` 结构且中心词在末尾（`long_hair`
   的中心是 hair，`hair_bow` 的中心是 bow），所以匹配按「整体名 → 末尾 n-gram →
   逐词元」逐级下沉，每级带单复数变体。
2. **专有名词不按名字猜**。画师 / 作品 / 角色是专有名词，名字里出现通用词只是巧合。
   让语义规则先跑会把它们丢进随机桶 —— 实测误伤 **7,000 余条**且集中在高热度 tag：

   | tag | 被猜成 | 因为 |
   | --- | --- | --- |
   | `the_legend_of_zelda` | 身体 / 腿部 | leg |
   | `fire_emblem` | 场景 / 元素 | emblem |
   | `neon_genesis_evangelion` | 光影 / 光照 | neon |
   | `cloud_strife` | 天气时间 / 天气 | cloud |
   | `yae_miko` | 服饰 / 传统服饰 | miko |
   | `minato_aqua` | 色彩 / 颜色 | aqua |

   它们不是「在描述那个词」，而是「名字恰好含那个词」。所以词库的分类号
   （1/3/4）在这三类上直接定死，不再往下猜。

分类栏的路径以 `/` 拼在 `cat` 参数里（如 `服饰/鞋袜`、`服饰/裤装/牛仔裤`、
`面部/头发/发色`），后端按路径前缀索引查，是 O(1) 的。

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

分类栏是服务端分页搜索的（12 万条不可能一次性塞给浏览器）。
冷启动加载 + 全量分类约 **0.5 s**，最坏情况（单字母搜索）约 **90 ms**。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/tag_prompt_editor/health` | 词库统计：总数、带中文数、来源、分类节点数、未归类数、加载错误 |
| GET | `/tag_prompt_editor/categories` | **分类树**（嵌套 `{id, name, count, children}`），首项是「推荐」 |
| GET | `/tag_prompt_editor/tags?q=&cat=&limit=60&offset=0` | 分页搜索，返回 `{items, hasMore}`，每项带 `fav` |
| GET | `/tag_prompt_editor/favorites` | 收藏列表 `{tags, count}` |
| POST | `/tag_prompt_editor/favorites` | body `{action: "toggle"\|"add"\|"remove", tag}` |
| GET | `/tag_prompt_editor/reload` | 更新词库 CSV 后热重载，不用重启 ComfyUI |

`cat` 支持三种写法：

```
/tags?cat=服饰                        按一级
/tags?cat=服饰/鞋袜                   按二级
/tags?cat=面部/头发/发色              按三级
/tags?cat=4                           数字分类号（向后兼容）
```

```bash
curl --noproxy '*' "http://127.0.0.1:8188/tag_prompt_editor/tags?q=长发&limit=5"

curl --noproxy '*' --get --data-urlencode "cat=服饰/鞋袜" \
  "http://127.0.0.1:8188/tag_prompt_editor/tags?limit=5"

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
| `dev/test_tagdb.py` | 词库加载、编码嗅探、**语义分类**、分类树、**三级下钻**、搜索排序、分页 | 172 项 ✅ |
| `dev/test_favorites.py` | 收藏读写、原子写入、坏文件容错、并发、fav 分类合并 | 47 项 ✅ |
| `dev/e2e_tag_editor.py` | 起真实 ComfyUI 实例，验节点注册 + 6 个路由 + STRING 透传 | 全过 ✅ |
| `dev/ui_tag_cats.mjs` | **分类栏专项**：一级/二级/三级下钻、叶子筛选与后端对拍、返回上层、搜索不受分类限制 | 53 项 ✅ |
| `dev/ui_tag_editor.mjs` | Playwright：结构恢复、工具条、拖拽、删除、编辑、搜索、上下联动，截图 | 53 项 ✅ |
| `dev/ui_tag_bar.mjs` | 工具条专项：悬停 / 权重 / 括号 / 收藏落盘 / 单击编辑 / 双击禁用 / 上下联动 | 49 项 ✅ |
| `dev/verify_resize.mjs` | 节点缩放自适应：拖文本框、拖宽、拖高、拖矮 + 功能回归 | 14 项 ✅ |
| `dev/verify_git_eol.py` | 模拟 `git clone`，对比 CRLF 源文件与 LF 检出后的词库加载结果 | 27 项 ✅ |
| `dev/taxonomy_proto.py` | 分类器原型：覆盖率统计、`--miss` 列未归类、`--sample` 抽样核对 | 开发工具 |

`dev/sync_plugin.py` 负责「源码 → `custom_nodes`」的同步并逐文件 md5 校验，
顺便清掉 `__pycache__` —— 手动 `cp` 时漏一个文件、或字节码没失效，
都会表现为「改了代码但行为没变」，很难查。

分类器的迭代方式：先用 `taxonomy_proto.py` 看覆盖率与未归类清单，改规则，
再用「**隔离对拍**」确认改动面 —— 造一份禁用该改动的变体，全量跑一遍比出
受影响的 tag 清单逐条看。`_art` 子串规则就是这样被抓出来的：
它把 `banned_artist`（热度 8.4 万）判成了「风格画质 / 媒介」，
同族的 `master_artoria`、`galarian_articuno` 也一并中招。

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

# 浏览器测试需要一个实例在 8288（--cpu 即可，不需要显卡）
node dev/ui_tag_cats.mjs --port 8288

# 同步到 ComfyUI 并校验
python dev/sync_plugin.py
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
- **规则表分层时，「通用词条」不能跨层复用。** 我们一度让「精确词条也能当后缀用」
  （想让 `x_hair_ornament` 借到 `hair_ornament`），结果 `emblem`/`fantasy`/`on_back`
  这些通用词条被当成后缀，把 `fire_emblem`→场景、`final_fantasy`→场景、
  `weapon_on_back`→卧姿，误伤 1,600+ 条。
  正确做法是把该词条**显式写进后缀表**（本次只动 218 条、零误伤），
  而不是放宽查找范围 —— 收益一样，风险差一个数量级。
- **分档阈值要按类目自适应。** 画师和作品的 danbooru 使用量差一个数量级
  （实测画师最高 5,868，作品最高 100 万+）。用同一套阈值，
  「画师 / 超人气」会是个永远点不开的空桶。
- **子级排序要跟着语义走，不能一律按条数降序。** 「画师 / 作品」的热度档里
  「长尾」条数最多，按条数降序会把它顶到第一个，用户得先划过 3 万条冷门才见到
  「超人气」—— 语义顺序（由热到冷）才对。其余分类仍按条数降序。
- **热度长尾极度分散时，别硬凑覆盖率。** 通用类里 `>=100k` 的只有 401 条、
  `>=1k` 的 7,531 条，到后面「末尾词元 top1 只出现 26 次」—— 进入这个区间后再
  手工补词，投入产出比会迅速崩塌。这时候应该换指标：不看条数占比
  （长尾天然难看），改看「**按使用热度加权**的覆盖率」和「热度前 N 条是否 100% 归类」。

---

## 📄 License

MIT
