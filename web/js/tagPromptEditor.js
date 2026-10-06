// ComfyUI-TagPromptEditor · 前端主扩展
//
// 设计要点（踩过的坑都写在注释里）：
//  1. 保留原生 STRING 文本框，不隐藏它。ComfyUI 把 widgets_values 存成**位置数组**，
//     一旦 widgets 数组长度/顺序变了，旧工作流加载时文本就会串到别的控件上。
//     保持它不动 = 工作流保存 / 复制粘贴 / 撤销全部零成本。addDOMWidget 默认
//     append 到 widgets 末尾，渲染出来正好在文本框下方，跟 WebUI 的布局一致。
//  2. 两个 DOM Widget（标签块区 + 预设选择器）都 serialize:false —— 数据只存在
//     text widget 里，它才是唯一真相源。
//  3. DOM Widget 的尺寸不走 computeSize，而是走 options.getMinHeight / getMaxHeight
//     / getHeight（前端 DOMWidgetImpl.computeLayoutSize 只认这三个）。
//  4. 高度必须手工量：DOM 元素不会自动把节点撑开，得测出内容高度后 node.setSize。

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import * as Core from "./tagEditorCore.js";

const NODE_NAME = "TagPromptEditor";
const API_BASE = "/tag_prompt_editor";

const CHIP_BOX_MAX = 200;   // 与 css 里 .tpe-chips 的 max-height 对齐
const PANEL_HEIGHT = 320;   // 预设面板的「期望」高度（节点默认尺寸下就是它）
const PANEL_MIN = 200;      // 节点被压矮时面板最多缩到这
const PANEL_MAX = 1200;     // 节点被拉高时面板最多涨到这
const PAGE_SIZE = 120;      // 一次拉多少条
const SEARCH_DEBOUNCE = 160;
const CURATED = new Set(["fav", "quality", "neg"]);

let styleInjected = false;
function injectStyle() {
  if (styleInjected && document.getElementById("tpe-style")) return;
  const link = document.createElement("link");
  link.id = "tpe-style";
  link.rel = "stylesheet";
  // 从 /extensions/<插件名>/js/xxx.js 往上找到 /extensions/<插件名>/css/editor.css
  link.href = new URL("../css/editor.css", import.meta.url).href;
  document.head.appendChild(link);
  styleInjected = true;
}

// ---------------------------------------------------------------------------
// 预设面板的数据源（多个节点实例共用一份分类缓存）
// ---------------------------------------------------------------------------

let categoriesPromise = null;
function loadCategories() {
  if (!categoriesPromise) {
    categoriesPromise = api
      .fetchApi(`${API_BASE}/categories`)
      .then((r) => r.json())
      .catch((e) => ({ categories: [], error: String(e) }));
  }
  return categoriesPromise;
}

async function fetchTags({ q, cat, offset, signal }) {
  const params = new URLSearchParams({
    q: q || "",
    cat: cat == null ? "all" : String(cat),
    limit: String(PAGE_SIZE),
    offset: String(offset || 0),
  });
  const res = await api.fetchApi(`${API_BASE}/tags?${params.toString()}`, { signal });
  return await res.json();
}

// ---------------------------------------------------------------------------
// ⚠️ 关键补丁：把 widget.width 钉死成 undefined
//
// 前端 1.53 的「节点内 widget」有个 Vue 渲染器 WidgetLegacy，它把每个 widget
// 画进自己的 canvas，`draw()` 里会执行：
//
//     let e = canvasEl.getBoundingClientRect().width || parent.clientWidth;
//     ...
//     s.width = e;          // s 就是这个 widget
//
// 而 DOM widget 容器的宽度是这样算的（GraphView 的 DomWidgets.updateWidgets）：
//
//     let c = (n.width ?? i.width) - t * 2;   // n=widget, i=node, t=margin
//     (r.size[0] !== c) && (r.size = [c, l]);
//
// 即 **widget.width 优先于 node.width**。于是只要 WidgetLegacy 跑过一次，
// widget.width 就被写成当时的 canvas 像素宽度（实测 254.8125 这种小数），
// 之后无论把节点拉多宽，下半部分 UI 都卡在这个死值上 —— 这就是
// 「下面的 UI 是固定的，放大节点后不跟着变宽」的直接原因。
//
// 原生 text 文本框是前端自己建的，不走 WidgetLegacy，所以它一直正常。
// 这里把 width 变成一个恒返回 undefined 的访问器 = 恢复前端「从未设置」的语义，
// 让容器老老实实回落到 node.width。setter 吞掉写入，不做任何事。
// ---------------------------------------------------------------------------
function lockWidgetWidth(widget) {
  if (!widget) return;
  try {
    Object.defineProperty(widget, "width", {
      configurable: true,
      enumerable: false,
      get: () => undefined,
      set: () => {},
    });
  } catch (e) {
    // 前端换了实现（或已不可配置）就静默放过，不能因此让节点起不来
    console.warn("[TagPromptEditor] 无法锁定 widget.width，宽度自适应可能失效", e);
  }
}

// ---------------------------------------------------------------------------
// 节点初始化
// ---------------------------------------------------------------------------

function setupEditor(node) {
  if (node.__tpe) return;

  const textWidget = node.widgets?.find((w) => w.name === "text");
  if (!textWidget) return;

  injectStyle();

  const st = {
    node,
    textWidget,
    tags: [],
    syncing: false,
    originCallback: textWidget.callback,
    toolbar: null,
    chipBox: null,
    warnBar: null,
    panel: null,
    searchEl: null,
    tabsEl: null,
    gridEl: null,
    statusEl: null,
    tab: "fav",
    query: "",
    items: [],
    hasMore: false,
    fetching: null,
    searchTimer: null,
    chipHeight: 78,
    pop: null,
    popTag: null,
    popIndex: -1,
    dragFrom: -1,
    observer: null,
    lastSynced: null,
  };
  node.__tpe = st;

  // ---- 顶部工具栏 + 标签块区（同一个 DOM Widget）----
  const wrap = document.createElement("div");
  wrap.className = "tpe-chips-wrap";

  st.toolbar = document.createElement("div");
  st.toolbar.className = "tpe-toolbar";

  st.chipBox = document.createElement("div");
  st.chipBox.className = "tpe-chips";

  st.warnBar = document.createElement("div");
  st.warnBar.className = "tpe-warnbar";
  st.warnBar.style.display = "none";

  wrap.append(st.toolbar, st.chipBox, st.warnBar);

  const chipsWidget = node.addDOMWidget("tpe_chips", "tpeChips", wrap, {
    serialize: false,
    hideOnZoom: false,
    getMinHeight: () => st.chipHeight,
    getMaxHeight: () => st.chipHeight,
    getHeight: () => st.chipHeight,
  });
  lockWidgetWidth(chipsWidget);
  // 别让标签块区域把鼠标事件漏给画布——否则按住标签拖拽会连节点一起拖走
  for (const ev of ["pointerdown", "mousedown", "wheel"]) {
    wrap.addEventListener(ev, (e) => e.stopPropagation(), { passive: ev === "wheel" ? false : true });
  }
  wrap.addEventListener("contextmenu", (e) => e.stopPropagation());

  // ---- 预设选择器 ----
  const panel = document.createElement("div");
  panel.className = "tpe-panel";
  panel.innerHTML = `
    <div class="tpe-searchrow">
      <input class="tpe-search" type="search" spellcheck="false" />
      <span class="tpe-status"></span>
    </div>
    <div class="tpe-tabs"></div>
    <div class="tpe-grid"></div>`;
  st.panel = panel;
  st.searchEl = panel.querySelector(".tpe-search");
  st.statusEl = panel.querySelector(".tpe-status");
  st.tabsEl = panel.querySelector(".tpe-tabs");
  st.gridEl = panel.querySelector(".tpe-grid");
  st.searchEl.placeholder = "搜索标签，支持中文（长发 / miku / 微笑）";

  const presetsWidget = node.addDOMWidget("tpe_presets", "tpePresets", panel, {
    serialize: false,
    hideOnZoom: false,
    // min < max 是有意为之：前端 _arrangeWidgets + distributeSpace 会把节点多出来的
    // 高度按 minHeight..maxHeight 弹性分配，于是「把节点拉高 → 标签选择器变高」，
    // 不需要我们自己算、也不会形成 setSize 反馈环。
    getMinHeight: () => PANEL_MIN,
    getMaxHeight: () => PANEL_MAX,
    getHeight: () => PANEL_HEIGHT,
  });
  lockWidgetWidth(presetsWidget);
  for (const ev of ["pointerdown", "mousedown", "wheel"]) {
    panel.addEventListener(ev, (e) => e.stopPropagation(), { passive: ev === "wheel" ? false : true });
  }

  // ---- 原生文本框改动 -> 重新解析 ----
  textWidget.callback = function (value, ...rest) {
    const ret = st.originCallback?.apply(this, [value, ...rest]);
    if (!st.syncing) pullFromText(st);
    return ret;
  };

  // ---- 高度同步 ----
  st.observer = new ResizeObserver(() => syncHeight(st));
  st.observer.observe(wrap);

  // ---- 事件绑定 ----
  wireSearch(st);
  wireTabs(st);

  // ---- 初始状态 ----
  pullFromText(st);
  refreshGrid(st, false);
  // computeSize() 只累加各 widget 的 minHeight，而面板的 minHeight 是 PANEL_MIN，
  // 这里补上 (PANEL_HEIGHT - PANEL_MIN)，让默认高度下正好给面板留出 PANEL_HEIGHT。
  const fitH = node.computeSize()[1] + (PANEL_HEIGHT - PANEL_MIN);
  node.setSize([Math.max(node.size[0], 460), Math.max(node.size[1], fitH)]);
  syncHeight(st);

  // 加载旧工作流时 widgets_values 在 onConfigure 之后才到位，这里补一次
  setTimeout(() => {
    if (!node.__tpe) return;
    if (textWidget.value !== st.lastSynced) pullFromText(st);
  }, 60);
}

/** 量内容高度并同步给节点。注意测的是子元素，不是被 ComfyUI 强制设高的外层。 */
function syncHeight(st) {
  const { node, toolbar, chipBox, warnBar } = st;
  let h = toolbar.offsetHeight + 6 + chipBox.offsetHeight;
  if (warnBar.style.display !== "none") h += warnBar.offsetHeight + 6;
  h = Math.ceil(h);
  if (h < 40) h = 40;
  if (Math.abs(h - st.chipHeight) < 1) return;
  const delta = h - st.chipHeight;
  st.chipHeight = h;
  if (node.size) {
    // 用增量而不是 node.computeSize()，这样用户手动拉高过节点的高度不会被强行复位
    node.setSize([node.size[0], Math.max(120, node.size[1] + delta)]);
  }
  app.graph?.setDirtyCanvas(true, false);
}

// ---------------------------------------------------------------------------
// 文本 <-> 标签 双向同步
// ---------------------------------------------------------------------------

function pullFromText(st) {
  st.tags = Core.parsePrompt(st.textWidget.value || "");
  st.lastSynced = st.textWidget.value;
  renderChips(st);
}

/** 把标签数组写回 text widget，并按 ComfyUI 原生方式记一次撤销点。 */
function commit(st) {
  const value = Core.serializeTags(st.tags);
  const graph = st.node.graph;
  graph?.beforeChange?.();
  st.syncing = true;
  st.textWidget.value = value;
  st.lastSynced = value;
  try {
    st.textWidget.callback?.(value);
  } catch (e) {
    console.error("[TagPromptEditor] callback failed", e);
  }
  st.syncing = false;
  graph?.afterChange?.();
  renderChips(st);
  st.node.graph?.setDirtyCanvas(true, false);
}

// ---------------------------------------------------------------------------
// 标签块渲染
// ---------------------------------------------------------------------------

function renderChips(st) {
  const box = st.chipBox;
  box.innerHTML = "";

  if (!st.tags.length) {
    const hint = document.createElement("span");
    hint.className = "tpe-empty";
    hint.textContent = "还没有标签 —— 在文本框里打字，或从下面的选择器点选";
    box.appendChild(hint);
  }

  st.tags.forEach((tag, index) => {
    const chip = document.createElement("span");
    chip.className = "tpe-chip";
    chip.draggable = true;
    if (!tag.on) chip.classList.add("tpe-off");
    if (tag.bracket) {
      chip.classList.add("tpe-bracket");
      chip.title = "方括号写法：ComfyUI 不支持 [tag] 降权，方括号会原样进编码器。要降权请用 (tag:0.8)";
    }

    const label = document.createElement("span");
    label.className = "tpe-chip-label";
    label.textContent = tag.t;
    label.title = "点击启用 / 禁用（禁用只是不参与输出，不会删除）";
    label.addEventListener("click", (e) => {
      e.stopPropagation();
      tag.on = !tag.on;
      commit(st);
    });

    const weight = document.createElement("span");
    weight.className = "tpe-chip-w";
    if (tag.w > 1) weight.classList.add("tpe-w-up");
    else if (tag.w < 1) weight.classList.add("tpe-w-down");
    weight.textContent = Core.formatWeight(tag.w);
    weight.title = "点击打开权重滑块（滚轮微调 0.05，Shift+滚轮按档位调）";
    weight.addEventListener("click", (e) => {
      e.stopPropagation();
      st.popIndex = index;
      openWeightPop(st, chip, tag);
    });

    const del = document.createElement("span");
    del.className = "tpe-chip-del";
    del.textContent = "×";
    del.title = "删除这个标签";
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      st.tags.splice(index, 1);
      commit(st);
    });

    chip.append(label, weight, del);

    chip.addEventListener("wheel", (e) => {
      e.preventDefault();
      e.stopPropagation();
      // 滚轮 = 细调 0.05；按住 Shift = 沿预设档位粗调
      tag.w = e.shiftKey
        ? Core.stepWeight(tag.w, e.deltaY < 0 ? 1 : -1)
        : Core.clampWeight(tag.w + (e.deltaY < 0 ? 0.05 : -0.05));
      commit(st);
    }, { passive: false });

    chip.addEventListener("dragstart", (e) => {
      st.dragFrom = index;
      chip.classList.add("tpe-drag");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", String(index)); } catch { /* 忽略 */ }
    });
    chip.addEventListener("dragend", () => {
      st.dragFrom = -1;
      box.querySelectorAll(".tpe-chip").forEach((c) => c.classList.remove("tpe-drag", "tpe-drop"));
    });
    chip.addEventListener("dragover", (e) => {
      e.preventDefault();
      if (st.dragFrom === -1 || st.dragFrom === index) return;
      chip.classList.add("tpe-drop");
    });
    chip.addEventListener("dragleave", () => chip.classList.remove("tpe-drop"));
    chip.addEventListener("drop", (e) => {
      e.preventDefault();
      chip.classList.remove("tpe-drop");
      if (st.dragFrom === -1 || st.dragFrom === index) return;
      st.tags = Core.moveItem(st.tags, st.dragFrom, index);
      st.dragFrom = -1;
      commit(st);
    });

    box.appendChild(chip);
  });

  renderToolbar(st);
  renderWarn(st);
  reanchorPop(st);
  syncHeight(st);
}

/** 重渲染标签块后，把还开着的权重气泡重新贴回原来那个标签块上。
 *  （气泡挂在 wrap 上，不会被 box.innerHTML 清掉，所以只需要重新定位。） */
function reanchorPop(st) {
  if (!st.pop) return;
  const chip = st.chipBox.children[st.popIndex];
  if (!chip || st.popIndex >= st.tags.length) {
    st.pop.remove();
    st.pop = null;
    st.popIndex = -1;
    return;
  }
  positionPop(st, chip);
}

function renderToolbar(st) {
  const on = st.tags.filter((t) => t.on).length;
  st.toolbar.innerHTML = "";

  const count = document.createElement("span");
  count.className = "tpe-count";
  count.textContent = st.tags.length
    ? `共 ${st.tags.length} 个标签 · 生效 ${on} 个`
    : "共 0 个标签";

  st.toolbar.appendChild(count);
  for (const [label, title, fn] of [
    ["去重", "删掉重复的标签（保留第一个）", () => Core.dedupeTags(st.tags)],
    ["排序", "按英文字母排序", () => Core.sortTags(st.tags)],
    ["权重归 1", "把所有标签权重重置为 1", () => Core.normalizeWeights(st.tags)],
    ["清空", "删除全部标签", () => []],
  ]) {
    const btn = document.createElement("button");
    btn.className = "tpe-btn";
    btn.textContent = label;
    btn.title = title;
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      st.tags = fn();
      commit(st);
    });
    st.toolbar.appendChild(btn);
  }
}

function renderWarn(st) {
  const bad = st.tags.filter((t) => t.bracket);
  if (!bad.length) {
    st.warnBar.style.display = "none";
    return;
  }
  st.warnBar.style.display = "";
  st.warnBar.textContent =
    `检测到 ${bad.length} 个方括号标签：ComfyUI 的权重解析只认圆括号，` +
    `[tag] 会被原样送进编码器而不会降权。要降权请改成 (tag:0.8)。`;
}

// ---------------------------------------------------------------------------
// 权重气泡
// ---------------------------------------------------------------------------

function openWeightPop(st, chip, tag) {
  st.pop?.remove();
  st.pop = null;

  const pop = document.createElement("div");
  pop.className = "tpe-pop";
  pop.addEventListener("pointerdown", (e) => e.stopPropagation());

  const title = document.createElement("div");
  title.className = "tpe-pop-title";
  title.textContent = tag.t;

  const row = document.createElement("div");
  row.className = "tpe-pop-row";
  const range = document.createElement("input");
  range.type = "range";
  range.min = "0.1";
  range.max = "2";
  range.step = "0.05";
  range.value = String(tag.w);
  const num = document.createElement("input");
  num.type = "number";
  num.min = String(Core.WEIGHT_MIN);
  num.max = String(Core.WEIGHT_MAX);
  num.step = "0.05";
  num.value = Core.formatWeight(tag.w);
  row.append(range, num);

  const actions = document.createElement("div");
  actions.className = "tpe-pop-actions";
  for (const preset of [0.5, 0.8, 1, 1.2, 1.5]) {
    const b = document.createElement("button");
    b.className = "tpe-btn";
    b.textContent = String(preset);
    b.addEventListener("click", () => {
      tag.w = preset;
      commit(st);
      openWeightPop(st, chip, tag);
    });
    actions.appendChild(b);
  }

  const sync = (v) => {
    tag.w = Core.clampWeight(v);
    commit(st);
    const txt = Core.formatWeight(tag.w);
    range.value = String(tag.w);
    if (num.value !== txt) num.value = txt;
  };
  range.addEventListener("input", () => sync(range.value));
  num.addEventListener("change", () => sync(num.value));

  pop.append(title, row, actions);
  // 挂到 body 而不是节点内部：DOM widget 会被后面渲染的预设面板盖住，
  // 而且 Comfy.DOMClippingEnabled 打开时还会被裁掉。
  document.body.appendChild(pop);
  st.pop = pop;
  st.popTag = tag;
  positionPop(st, chip);

  const close = (e) => {
    if (pop.contains(e.target)) return;
    pop.remove();
    if (st.pop === pop) {
      st.pop = null;
      st.popTag = null;
      st.popIndex = -1;
    }
    document.removeEventListener("pointerdown", close, true);
  };
  setTimeout(() => document.addEventListener("pointerdown", close, true), 0);
}

/** 把气泡贴到标签块下方（视口坐标，越界就翻到上方 / 夹进屏幕内）。 */
function positionPop(st, chip) {
  const pop = st.pop;
  if (!pop || !chip.isConnected) return;
  const cr = chip.getBoundingClientRect();
  const pw = pop.offsetWidth;
  const ph = pop.offsetHeight;
  let left = Math.min(Math.max(4, cr.left), Math.max(4, window.innerWidth - pw - 4));
  let top = cr.bottom + 6;
  if (top + ph > window.innerHeight - 4) top = Math.max(4, cr.top - ph - 6);
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
}

// ---------------------------------------------------------------------------
// 预设面板
// ---------------------------------------------------------------------------

function wireSearch(st) {
  st.searchEl.addEventListener("input", () => {
    clearTimeout(st.searchTimer);
    st.searchTimer = setTimeout(() => {
      st.query = st.searchEl.value;
      refreshGrid(st, false);
    }, SEARCH_DEBOUNCE);
  });
  st.searchEl.addEventListener("pointerdown", (e) => e.stopPropagation());
}

function wireTabs(st) {
  loadCategories().then((data) => {
    st.tabsEl.innerHTML = "";
    for (const cat of data.categories || []) {
      const btn = document.createElement("button");
      btn.className = "tpe-tab";
      btn.dataset.cat = String(cat.id);
      btn.textContent = `${cat.name}`;
      btn.title = `${cat.count} 个标签`;
      if (String(cat.id) === String(st.tab)) btn.classList.add("tpe-active");
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        st.tab = cat.id;
        st.tabsEl.querySelectorAll(".tpe-tab").forEach((b) => b.classList.remove("tpe-active"));
        btn.classList.add("tpe-active");
        refreshGrid(st, false);
      });
      st.tabsEl.appendChild(btn);
    }
    if (data.error) setStatus(st, data.error, true);
    else refreshGrid(st, false);
  });
}

function setStatus(st, text, isError = false) {
  st.statusEl.textContent = text || "";
  st.statusEl.style.color = isError ? "#ba7517" : "";
  st.statusEl.title = text || "";
}

async function refreshGrid(st, append) {
  // 在精选分类里搜关键词没意义（一共才百来条），自动切到全部标签搜
  const searching = !!st.query.trim();
  const cat = searching && CURATED.has(st.tab) ? "all" : st.tab;

  st.fetching?.abort();
  const ctrl = new AbortController();
  st.fetching = ctrl;
  setStatus(st, "加载中…");

  try {
    const data = await fetchTags({
      q: st.query,
      cat,
      offset: append ? st.items.length : 0,
      signal: ctrl.signal,
    });
    if (st.fetching !== ctrl) return;
    st.items = append ? st.items.concat(data.items || []) : data.items || [];
    st.hasMore = !!data.hasMore;
    renderGrid(st);
    if (data.error) setStatus(st, data.error, true);
    else {
      setStatus(
        st,
        `已显示 ${st.items.length}${st.hasMore ? "+" : ""} 条${searching ? ` · 搜「${st.query.trim()}」` : ""}`,
      );
    }
  } catch (e) {
    if (e?.name === "AbortError") return;
    setStatus(st, `加载失败：${e?.message || e}`, true);
  }
}

function renderGrid(st) {
  const grid = st.gridEl;
  grid.innerHTML = "";
  const used = new Set(st.tags.map((t) => t.t.toLowerCase()));

  for (const item of st.items) {
    const card = document.createElement("button");
    card.className = "tpe-card";
    if (used.has(item.t.toLowerCase())) card.classList.add("tpe-added");
    card.title = `${item.t}${item.zh ? " — " + item.zh : ""}${item.n ? `\n热度 ${item.n.toLocaleString()}` : ""}`;

    const en = document.createElement("span");
    en.className = "tpe-card-en";
    en.textContent = item.t;
    const zh = document.createElement("span");
    zh.className = "tpe-card-zh";
    zh.textContent = item.zh || "";
    card.append(en, zh);

    card.addEventListener("click", (e) => {
      e.stopPropagation();
      addTag(st, item);
    });
    grid.appendChild(card);
  }

  if (st.hasMore) {
    const more = document.createElement("button");
    more.className = "tpe-more";
    more.textContent = "载入更多…";
    more.addEventListener("click", (e) => {
      e.stopPropagation();
      refreshGrid(st, true);
    });
    grid.appendChild(more);
  }
}

function addTag(st, item) {
  const key = item.t.toLowerCase();
  const existing = st.tags.find((t) => t.t.toLowerCase() === key);
  if (existing) {
    existing.on = true;
  } else {
    st.tags.push({ t: item.t, w: 1, on: true });
  }
  commit(st);
  renderGrid(st);
}

// ---------------------------------------------------------------------------
// 扩展注册
// ---------------------------------------------------------------------------

app.registerExtension({
  name: "TagPromptEditor",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData?.name !== NODE_NAME) return;
    injectStyle();

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const ret = onNodeCreated?.apply(this, arguments);
      try {
        setupEditor(this);
      } catch (e) {
        // 前端出错就退回原生文本框，功能降级但不影响出图
        console.error("[TagPromptEditor] 初始化失败，已降级为普通文本框", e);
      }
      return ret;
    };

    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const ret = onConfigure?.apply(this, arguments);
      const node = this;
      setTimeout(() => {
        const st = node.__tpe;
        if (!st) return;
        if (st.textWidget.value !== st.lastSynced) pullFromText(st);
      }, 0);
      return ret;
    };

    const onRemoved = nodeType.prototype.onRemoved;
    nodeType.prototype.onRemoved = function () {
      const st = this.__tpe;
      if (st) {
        st.observer?.disconnect();
        st.fetching?.abort();
        clearTimeout(st.searchTimer);
        st.pop?.remove();
        this.__tpe = null;
      }
      return onRemoved?.apply(this, arguments);
    };
  },
});
