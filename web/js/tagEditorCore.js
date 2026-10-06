// 纯函数层：提示词文本 <-> 标签数组。
// 不依赖 ComfyUI / DOM，可以直接用 node 跑单测（见 dev/test_tag_core.mjs）。
//
// 权重语法对齐后端 comfy/sd1_clip.py::token_weights()：
//   (tag)       -> ×1.1
//   (tag:1.2)   -> 1.2        （用 rfind(":")，所以 (<lora:x:1>:1.5) 也成立）
//   ((tag))     -> 1.21       （可嵌套）
//   [tag]       -> 不支持！ComfyUI 只处理圆括号，方括号会原样进 tokenizer。
//                  所以权重小于 1 也必须写成 (tag:0.8)，不能抄 A1111 的 [tag]。

export const WEIGHT_STEPS = [
  0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1,
  1.05, 1.1, 1.15, 1.2, 1.3, 1.4, 1.5, 1.6, 1.8, 2,
];
export const WEIGHT_MIN = 0.05;
export const WEIGHT_MAX = 4;

export function clampWeight(w) {
  const n = Number(w);
  if (!Number.isFinite(n)) return 1;
  return Math.min(WEIGHT_MAX, Math.max(WEIGHT_MIN, n));
}

/** 去掉浮点尾巴：1.2000000000000002 -> "1.2" */
export function formatWeight(w) {
  return String(Math.round(clampWeight(w) * 100) / 100);
}

/** 按逗号 / 换行切分，但忽略圆括号内的分隔符 —— (red hair, blue eyes:1.2) 不能被拆开。 */
export function splitTopLevel(text) {
  const out = [];
  const s = String(text ?? "");
  let depth = 0;
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c === "(") depth++;
    else if (c === ")") depth = Math.max(0, depth - 1);
    if ((c === "," || c === "\n") && depth === 0) {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += c;
  }
  out.push(cur);
  return out;
}

/** 括号是否配平。用来挡掉 `(a)(b:1.2)` 这种被贪婪正则误判的片段。 */
function balanced(s) {
  let d = 0;
  for (const c of s) {
    if (c === "(") d++;
    else if (c === ")") {
      d--;
      if (d < 0) return false;
    }
  }
  return d === 0;
}

const WEIGHTED_RE = /^\((.*):\s*([0-9]*\.?[0-9]+)\s*\)$/s;
const PAREN_RE = /^\((.*)\)$/s;

/**
 * 把提示词文本解析成标签数组。
 * @returns {{t:string,w:number,on:boolean,bracket?:boolean}[]}
 */
export function parsePrompt(text) {
  const tags = [];
  for (const chunk of splitTopLevel(text)) {
    const raw = chunk.trim();
    if (!raw) continue;

    const m = raw.match(WEIGHTED_RE);
    if (m && balanced(m[1])) {
      tags.push({ t: m[1].trim(), w: clampWeight(m[2]), on: true });
      continue;
    }

    const p = raw.match(PAREN_RE);
    if (p && balanced(p[1])) {
      // 归一化：(tag) 直接展开成显式权重 1.1，语义完全一致
      tags.push({ t: p[1].trim(), w: 1.1, on: true });
      continue;
    }

    const tag = { t: raw, w: 1, on: true };
    // ComfyUI 不支持方括号降权，标出来让 UI 提示用户
    if (/^\[.+\]$/.test(raw)) tag.bracket = true;
    tags.push(tag);
  }
  return tags.filter((x) => x.t);
}

/** 标签数组 -> 提示词文本。权重为 1 时输出裸标签，避免满屏无用括号。 */
export function serializeTags(tags) {
  return (tags || [])
    .filter((x) => x.on && x.t)
    .map((x) => (Math.abs(x.w - 1) < 1e-6 ? x.t : `(${x.t}:${formatWeight(x.w)})`))
    .join(", ");
}

/** 沿 WEIGHT_STEPS 走一格。走到两端就饱和，绝不会反向跑。 */
export function stepWeight(w, dir = 1) {
  const cur = clampWeight(w);
  if (dir > 0) {
    for (const s of WEIGHT_STEPS) if (s > cur + 1e-6) return s;
    return cur;
  }
  for (let i = WEIGHT_STEPS.length - 1; i >= 0; i--) {
    if (WEIGHT_STEPS[i] < cur - 1e-6) return WEIGHT_STEPS[i];
  }
  return cur;
}

export function dedupeTags(tags) {
  const seen = new Set();
  return tags.filter((x) => {
    const key = x.t.trim().toLowerCase();
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function sortTags(tags) {
  return [...tags].sort((a, b) => a.t.localeCompare(b.t, "en"));
}

export function normalizeWeights(tags) {
  return tags.map((x) => ({ ...x, w: 1 }));
}

export function moveItem(arr, from, to) {
  if (from === to || from < 0 || from >= arr.length) return arr;
  const next = [...arr];
  const [item] = next.splice(from, 1);
  next.splice(Math.max(0, Math.min(to, next.length)), 0, item);
  return next;
}

/** 标签是否已经在列表里（用于预设面板高亮） */
export function hasTag(tags, name) {
  const key = name.trim().toLowerCase();
  return (tags || []).some((x) => x.t.trim().toLowerCase() === key);
}
