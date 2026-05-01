/* ============================================================
   鸣潮 · 面板/背景图编辑台 — frontend (vanilla JS)
   ============================================================ */

const API = "/waves/panel-edit/api";

const TYPE_INFO = {
  card:    { label: "面板图",    short: "PANEL",   color: "var(--type-card)",    preview: "panel" },
  bg:      { label: "MR 背景图", short: "MR/BG",    color: "var(--type-bg)",      preview: "mr" },
  stamina: { label: "MR 立绘",   short: "MR/PILE", color: "var(--type-stamina)", preview: "mr" },
};

const state = {
  meta: null,
  type: "card",
  folders: [],
  filterText: "",
  selectedCharId: null,
  selectedImage: null,        // {name, hash_id, ...}
  imagesByCharId: {},         // cache: {`${type}|${charId}`: [images]}

  // mode: "browse" | "single-crop" | "batch"
  mode: "browse",
  // single-crop tmp:
  cropTmp: null,              // {token, suffix, source: {w,h}, current: {w,h}, kind: "upload" | "edit-existing", origin: {char_id,name}? }
  cropRect: null,             // {x,y,w,h} display coords
  cropImgEl: null,
  // batch:
  batchItems: [],             // [{token,name,suffix,width,height,size,confirmed?,charId?}]
  batchAllow: false,          // confirm-all checkbox

  renderer: "html",           // for mr preview

  // preview auto-refresh:
  previewSeq: 0,

  // edit-existing warning dismissed
  editWarnDismissed: false,
};

// ============================================================
// DOM
// ============================================================
const $ = sel => document.querySelector(sel);
const el = (tag, props, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (v === false || v == null) continue;
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
};

// ============================================================
// API helpers
// ============================================================
async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res;
}
async function apiJson(path, body, method = "POST") {
  return api(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ============================================================
// Toasts
// ============================================================
function toast(msg, kind = "info", timeout = 3500) {
  const t = el("div", { class: `toast is-${kind}` },
    el("div", { class: "toast__msg", text: msg }),
    el("button", { class: "toast__close", "aria-label": "dismiss",
                   onClick: () => t.remove() }, "✕"),
  );
  $("#toasts").append(t);
  if (timeout) setTimeout(() => t.remove(), timeout);
}

// ============================================================
// Lazy thumb loader — IntersectionObserver + concurrency limiter
// ============================================================
const LazyImages = (() => {
  const queue = [];
  let inflight = 0;
  const MAX = 4;

  const next = () => {
    while (inflight < MAX && queue.length) {
      const node = queue.shift();
      if (!node.isConnected) continue;
      const src = node.dataset.src;
      if (!src) continue;
      inflight++;
      const onDone = () => {
        inflight--;
        next();
      };
      node.addEventListener("load", () => {
        node.parentElement?.classList.add("is-loaded");
        onDone();
      }, { once: true });
      node.addEventListener("error", onDone, { once: true });
      node.src = src;
    }
  };

  const observer = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const node = e.target;
      observer.unobserve(node);
      queue.push(node);
    }
    next();
  }, { rootMargin: "200px 0px", threshold: 0.01 });

  return {
    observe(node) { observer.observe(node); },
    reset() { queue.length = 0; }
  };
})();

// ============================================================
// META + initial load
// ============================================================
async function loadMeta() {
  state.meta = await api("/meta");
  renderTypeTabs();
}

function renderTypeTabs() {
  const root = $("#typeTabs");
  root.innerHTML = "";
  const order = ["card", "bg", "stamina"];
  for (const k of order) {
    const info = TYPE_INFO[k];
    const tab = el("button", {
      class: "tab" + (state.type === k ? " is-active" : ""),
      role: "tab",
      "aria-selected": String(state.type === k),
      onClick: () => switchType(k),
    },
      el("span", { class: "tab__swatch", style: `background:${info.color}` }),
      info.label,
    );
    root.append(tab);
  }
}

async function switchType(t) {
  if (state.type === t) return;
  state.type = t;
  state.selectedCharId = null;
  state.selectedImage = null;
  state.mode = "browse";
  renderTypeTabs();
  await loadFolders();
  renderCenter();
  renderPreview();
}

async function loadFolders() {
  try {
    const data = await api(`/folders?type=${state.type}`);
    state.folders = data.folders || [];
  } catch (e) {
    toast(`加载文件夹失败: ${e.message}`, "err");
    state.folders = [];
  }
  renderFolders();
}

function renderFolders() {
  const root = $("#folderList");
  root.innerHTML = "";
  const ft = state.filterText.trim().toLowerCase();
  const list = state.folders.filter(f =>
    !ft ||
    f.char_id.toLowerCase().includes(ft) ||
    (f.char_name || "").toLowerCase().includes(ft)
  );
  $("#folderCount").textContent = `${list.length} / ${state.folders.length}`;
  if (!list.length) {
    root.append(el("div", { class: "sidebar__empty",
      text: state.folders.length ? "无匹配文件夹" : "此类型暂无文件夹" }));
    return;
  }
  for (const f of list) {
    const row = el("div", {
      class: "folder" + (state.selectedCharId === f.char_id ? " is-active" : ""),
      role: "button",
      tabindex: "0",
      onClick: () => selectFolder(f.char_id),
      onKeydown: (ev) => { if (ev.key === "Enter") selectFolder(f.char_id); },
    },
      el("span", { class: "folder__id", text: f.char_id }),
      el("span", { class: "folder__name", title: f.char_name, text: f.char_name || "—" }),
      el("span", { class: "folder__count", text: String(f.count) }),
    );
    root.append(row);
  }
}

async function selectFolder(charId) {
  state.selectedCharId = charId;
  state.selectedImage = null;
  state.mode = "browse";
  renderFolders();
  renderCenter();
  renderPreview();
  await loadImages();
}

async function loadImages() {
  if (!state.selectedCharId) return;
  const key = `${state.type}|${state.selectedCharId}`;
  try {
    const data = await api(`/images?type=${state.type}&char_id=${encodeURIComponent(state.selectedCharId)}`);
    state.imagesByCharId[key] = data.images || [];
  } catch (e) {
    toast(`加载图片失败: ${e.message}`, "err");
    state.imagesByCharId[key] = [];
  }
  renderCenter();
}

// ============================================================
// CENTER — head + body (mode-aware)
// ============================================================
function renderCenter() {
  renderCenterHead();
  renderCenterBody();
}

function renderCenterHead() {
  const head = $("#centerHead");
  head.innerHTML = "";

  if (!state.selectedCharId) {
    head.append(
      el("div", { class: "center__title" },
        el("h2", { text: "未选中文件夹" }),
        el("span", { class: "crumb", text: TYPE_INFO[state.type].label }),
      )
    );
    return;
  }

  const folder = state.folders.find(f => f.char_id === state.selectedCharId);
  const charName = folder?.char_name || state.meta?.id2name?.[state.selectedCharId] || "—";
  const info = TYPE_INFO[state.type];

  const titleBlock = el("div", { class: "center__title" },
    el("span", { class: "type-pill" },
      el("span", { class: "swatch", style: `background:${info.color}` }),
      info.short,
    ),
    el("h2", { text: charName }),
    el("span", { class: "crumb" },
      el("b", { text: state.selectedCharId }),
      " · ",
      `${(state.imagesByCharId[`${state.type}|${state.selectedCharId}`] || []).length} 张`
    ),
  );

  const actions = el("div", { class: "center__actions" });

  if (state.mode === "single-crop") {
    actions.append(
      el("button", { class: "btn btn--ghost", onClick: cancelCrop }, "返回"),
    );
  } else if (state.mode === "batch") {
    actions.append(
      el("button", { class: "btn btn--ghost", onClick: () => { state.mode = "browse"; renderCenter(); } }, "返回"),
    );
  } else {
    actions.append(
      el("button", { class: "btn", onClick: openSingleUpload }, "上传单张"),
      el("button", { class: "btn", onClick: openBatchUpload }, "批量上传"),
    );
  }

  head.append(titleBlock, actions);
}

function renderCenterBody() {
  const body = $("#centerBody");
  body.innerHTML = "";

  if (state.mode === "single-crop") return renderCropper(body);
  if (state.mode === "batch") return renderBatch(body);

  // browse
  if (!state.selectedCharId) {
    body.append(el("div", { class: "empty" },
      el("div", { class: "empty__title", text: "NO FOLDER" }),
      el("div", { text: "选择左侧文件夹开始浏览。" }),
    ));
    return;
  }

  body.append(renderDropzone());

  const key = `${state.type}|${state.selectedCharId}`;
  const images = state.imagesByCharId[key];
  if (!images) {
    body.append(el("div", { class: "empty", text: "加载中…" }));
    return;
  }
  if (!images.length) {
    body.append(el("div", { class: "empty" },
      el("div", { class: "empty__title", text: "EMPTY" }),
      el("div", { text: "此文件夹尚无图片，拖入或点击上方按钮上传。" }),
    ));
    return;
  }

  const grid = el("div", { class: "grid" });
  const isLandscape = state.type === "bg";
  for (const img of images) {
    grid.append(renderTile(img, isLandscape));
  }
  body.append(grid);
}

function renderTile(img, isLandscape) {
  const isSelected = state.selectedImage?.name === img.name;
  const tile = el("div", {
    class: "tile" + (isLandscape ? " is-landscape" : "") + (isSelected ? " is-selected" : ""),
    role: "button",
    tabindex: "0",
    "aria-label": `${img.hash_id} ${img.name}`,
    onClick: () => selectImage(img),
    onKeydown: e => { if (e.key === "Enter") selectImage(img); },
  },
    el("div", { class: "tile__skeleton" }),
    (() => {
      const url = `${API}/thumb?type=${state.type}&char_id=${encodeURIComponent(state.selectedCharId)}&name=${encodeURIComponent(img.name)}&size=360`;
      const i = el("img", { alt: img.hash_id, loading: "lazy", decoding: "async", "data-src": url });
      LazyImages.observe(i);
      return i;
    })(),
    el("div", { class: "tile__menu" },
      el("a", {
        class: "tile-act tile-act--link",
        href: `${API}/image?type=${state.type}&char_id=${encodeURIComponent(state.selectedCharId)}&name=${encodeURIComponent(img.name)}`,
        download: img.name,
        title: "下载原图",
        "aria-label": "下载原图",
        onClick: e => e.stopPropagation(),
      }, "⤓"),
      el("button", {
        class: "tile-act",
        title: "编辑裁切",
        "aria-label": "编辑裁切",
        onClick: e => { e.stopPropagation(); editExisting(img); },
      }, "✎"),
      el("button", {
        class: "tile-act tile-act--danger",
        title: "删除",
        "aria-label": "删除",
        onClick: e => { e.stopPropagation(); deleteImage(img); },
      }, "✕"),
    ),
    el("div", { class: "tile__hash" },
      el("span", { text: img.hash_id }),
      el("span", { class: "meta", text: formatBytes(img.size) }),
    ),
  );
  return tile;
}

function selectImage(img) {
  state.selectedImage = img;
  // re-render only what changed
  renderCenterBody();
  renderPreview();
}

async function deleteImage(img) {
  if (!confirm(`确认删除 ${img.name}? 此操作不可撤销。`)) return;
  try {
    await apiJson("/delete", { type: state.type, char_id: state.selectedCharId, name: img.name });
    toast("已删除", "ok");
    if (state.selectedImage?.name === img.name) state.selectedImage = null;
    await loadImages();
    await loadFolders();
    renderCenter();
    renderPreview();
  } catch (e) {
    toast(`删除失败: ${e.message}`, "err");
  }
}

// ============================================================
// DROPZONE
// ============================================================
function renderDropzone() {
  const dz = el("div", { class: "dropzone" },
    el("div", { class: "dropzone__title", text: "DROP TO UPLOAD" }),
    el("div", { class: "dropzone__sub",
      text: "拖拽图片到此处。单张进入裁剪模式，多张则进入批量暂存。" }),
    el("div", { class: "dropzone__row" },
      el("button", { class: "btn", onClick: openSingleUpload }, "选择单张"),
      el("button", { class: "btn", onClick: openBatchUpload }, "批量选择"),
    ),
  );

  dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("is-hot"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("is-hot"));
  dz.addEventListener("drop", async e => {
    e.preventDefault();
    dz.classList.remove("is-hot");
    const files = [...e.dataTransfer.files].filter(f => f.type.startsWith("image/"));
    if (!files.length) return;
    if (files.length === 1) await uploadSingle(files[0]);
    else await uploadBatch(files);
  });
  return dz;
}

function openSingleUpload() {
  if (!state.selectedCharId) return toast("请先选中文件夹", "warn");
  pickFiles(false, files => {
    if (files[0]) uploadSingle(files[0]);
  });
}
function openBatchUpload() {
  if (!state.selectedCharId) return toast("请先选中文件夹", "warn");
  pickFiles(true, files => {
    if (files.length === 1) uploadSingle(files[0]);
    else if (files.length > 1) uploadBatch(files);
  });
}
function pickFiles(multiple, cb) {
  const input = el("input", { type: "file", accept: "image/*" });
  if (multiple) input.multiple = true;
  input.addEventListener("change", () => cb([...(input.files || [])]));
  input.click();
}

// ============================================================
// SINGLE UPLOAD + CROPPER
// ============================================================
async function uploadSingle(file) {
  const fd = new FormData();
  fd.append("file", file);
  try {
    const data = await api("/tmp/upload", { method: "POST", body: fd });
    state.cropTmp = {
      token: data.token,
      suffix: data.suffix,
      source: { w: data.width, h: data.height },
      current: { w: data.width, h: data.height },
      kind: "upload",
    };
    state.mode = "single-crop";
    renderCenter();
    renderPreview();
  } catch (e) {
    toast(`上传失败: ${e.message}`, "err");
  }
}

function renderCropper(body) {
  if (state.cropTmp?.kind === "edit-existing" && !state.editWarnDismissed) {
    body.append(el("div", { class: "warn-banner" },
      el("span", { class: "warn-banner__icon", text: "!" }),
      el("div", { class: "warn-banner__msg",
        text: "编辑会覆盖原图并重建索引，无法撤销，请谨慎。" }),
      el("button", { class: "btn btn--ghost",
        onClick: () => { state.editWarnDismissed = true; renderCenterBody(); } }, "知道了"),
    ));
  }

  const tmp = state.cropTmp;
  const readout = el("div", { class: "cropper__readout" },
    el("span", null, el("span", { class: "k", text: "源:" }),
      el("b", { text: `${tmp.source.w}×${tmp.source.h}` })),
    el("span", null, el("span", { class: "k", text: "当前:" }),
      el("b", { id: "cropCurSize", text: `${tmp.current.w}×${tmp.current.h}` })),
    el("span", null, el("span", { class: "k", text: "裁剪 (源像素):" }),
      el("b", { id: "cropRectReadout", text: "—" })),
  );

  const bar = el("div", { class: "cropper__bar" },
    readout,
    el("div", { class: "cropper__actions" },
      el("button", { class: "btn", onClick: applyCrop }, "应用裁剪"),
      el("button", { class: "btn", onClick: restoreCrop }, "还原"),
      el("button", { class: "btn btn--ghost", onClick: cancelCrop }, "取消"),
      el("button", { class: "btn btn--primary",
        onClick: tmp.kind === "edit-existing" ? confirmReplace : confirmUpload },
        tmp.kind === "edit-existing" ? "确认覆盖" : "确认上传"),
    ),
  );

  const stage = el("div", { class: "cropper__stage" });
  const wrap = el("div", { class: "cropper__canvas-wrap" });
  const img = el("img", {
    class: "cropper__img",
    src: `${API}/tmp/image?token=${tmp.token}&_=${Date.now()}`,
    onLoad: () => initCropRect(img, wrap),
  });
  state.cropImgEl = img;
  wrap.append(img);
  stage.append(wrap);

  body.append(bar, stage);
}

function initCropRect(img, wrap) {
  // Initialize crop rect to full image (display coords)
  const w = img.clientWidth;
  const h = img.clientHeight;
  state.cropRect = { x: 0, y: 0, w, h };
  drawCropRect(wrap);
  updateRectReadout();
}

function drawCropRect(wrap) {
  let rect = wrap.querySelector(".cropper__rect");
  if (!state.cropRect) {
    rect?.remove();
    return;
  }
  if (!rect) {
    rect = el("div", { class: "cropper__rect" });
    for (const h_ of ["nw", "n", "ne", "e", "se", "s", "sw", "w"]) {
      rect.append(el("span", { class: `handle h-${h_}`, "data-h": h_ }));
    }
    rect.addEventListener("pointerdown", ev => startDrag(ev, wrap, rect));
    wrap.append(rect);
  }
  applyRectStyle(rect, state.cropRect);
}

function applyRectStyle(rect, r) {
  rect.style.left = `${r.x}px`;
  rect.style.top = `${r.y}px`;
  rect.style.width = `${r.w}px`;
  rect.style.height = `${r.h}px`;
}

function startDrag(ev, wrap, rect) {
  ev.preventDefault();
  const target = ev.target;
  const isHandle = target.classList.contains("handle");
  const direction = target.dataset.h;
  const startState = { sx: ev.clientX, sy: ev.clientY, ...state.cropRect };
  const maxW = state.cropImgEl.clientWidth;
  const maxH = state.cropImgEl.clientHeight;

  // 让指针捕获到 rect (即使光标移出元素也持续收到 move 事件), 修复"框不跟鼠标"。
  try { rect.setPointerCapture(ev.pointerId); } catch (_) {}

  let pending = null;
  const flush = () => {
    pending = null;
    applyRectStyle(rect, state.cropRect);
    updateRectReadout();
  };

  const move = e => {
    const dx = e.clientX - startState.sx;
    const dy = e.clientY - startState.sy;
    let { x, y, w, h } = startState;
    if (!isHandle) {
      x += dx; y += dy;
    } else {
      if (direction.includes("w")) { x += dx; w -= dx; }
      if (direction.includes("e")) { w += dx; }
      if (direction.includes("n")) { y += dy; h -= dy; }
      if (direction.includes("s")) { h += dy; }
    }
    if (w < 8) w = 8;
    if (h < 8) h = 8;
    x = Math.max(0, Math.min(x, maxW - w));
    y = Math.max(0, Math.min(y, maxH - h));
    w = Math.min(w, maxW - x);
    h = Math.min(h, maxH - y);
    state.cropRect = { x, y, w, h };
    if (pending == null) pending = requestAnimationFrame(flush);
  };

  const up = () => {
    rect.removeEventListener("pointermove", move);
    rect.removeEventListener("pointerup", up);
    rect.removeEventListener("pointercancel", up);
    try { rect.releasePointerCapture(ev.pointerId); } catch (_) {}
    if (pending != null) {
      cancelAnimationFrame(pending);
      flush();
    }
    // 释放后立即应用裁剪 + 触发右侧预览重渲染。
    scheduleAutoCrop();
  };

  rect.addEventListener("pointermove", move);
  rect.addEventListener("pointerup", up);
  rect.addEventListener("pointercancel", up);
}

// 拖拽结束后应用裁剪并刷新预览; 防止快速连续拖动堆积请求。
let _autoCropTimer = null;
let _autoCropInflight = false;
function scheduleAutoCrop() {
  clearTimeout(_autoCropTimer);
  _autoCropTimer = setTimeout(async () => {
    if (_autoCropInflight) {
      // 在途时排队再触发一次, 保证最新一次操作一定被应用
      _autoCropTimer = setTimeout(scheduleAutoCrop, 80);
      return;
    }
    _autoCropInflight = true;
    try {
      await applyCrop({ silent: true });
    } finally {
      _autoCropInflight = false;
    }
  }, 80);
}

function displayToSourceRect(rect) {
  const img = state.cropImgEl;
  if (!img) return null;
  const sx = img.naturalWidth / img.clientWidth;
  const sy = img.naturalHeight / img.clientHeight;
  return {
    x: Math.max(0, Math.round(rect.x * sx)),
    y: Math.max(0, Math.round(rect.y * sy)),
    w: Math.max(1, Math.round(rect.w * sx)),
    h: Math.max(1, Math.round(rect.h * sy)),
  };
}

function updateRectReadout() {
  const node = document.getElementById("cropRectReadout");
  if (!node || !state.cropRect) return;
  const s = displayToSourceRect(state.cropRect);
  node.textContent = s ? `${s.x},${s.y} ${s.w}×${s.h}` : "—";
}

async function applyCrop(opts = {}) {
  const { silent = false } = opts;
  const tmp = state.cropTmp;
  if (!tmp) return;
  const src = displayToSourceRect(state.cropRect);
  if (!src) return;
  try {
    const r = await apiJson("/tmp/crop", { token: tmp.token, ...src });
    tmp.current = { w: r.width, h: r.height };
    const sizeEl = document.getElementById("cropCurSize");
    if (sizeEl) sizeEl.textContent = `${r.width}×${r.height}`;
    refreshCropImg();
    triggerPreview(true);
    if (!silent) toast("已裁剪", "ok", 1800);
  } catch (e) {
    toast(`裁剪失败: ${e.message}`, "err");
  }
}

async function restoreCrop() {
  const tmp = state.cropTmp;
  if (!tmp) return;
  try {
    const r = await apiJson("/tmp/restore", { token: tmp.token });
    tmp.current = { w: r.width, h: r.height };
    document.getElementById("cropCurSize").textContent = `${r.width}×${r.height}`;
    refreshCropImg();
    triggerPreview();
    toast("已还原", "ok", 1800);
  } catch (e) {
    toast(`还原失败: ${e.message}`, "err");
  }
}

function refreshCropImg() {
  if (!state.cropImgEl) return;
  state.cropImgEl.src = `${API}/tmp/image?token=${state.cropTmp.token}&_=${Date.now()}`;
}

function _resetCropState() {
  state.cropTmp = null;
  state.cropRect = null;
  state.cropImgEl = null;
  state.editWarnDismissed = false;
}

async function cancelCrop() {
  const tmp = state.cropTmp;
  // 来自批量暂存的 item: 取消裁剪只是回到暂存区, 不丢弃 tmp 文件。
  const fromBatch = tmp?.fromBatch === true;
  if (tmp && !fromBatch) {
    try { await apiJson("/tmp/discard", { token: tmp.token }); } catch (_) {}
  }
  _resetCropState();
  state.mode = (fromBatch && state.batchItems.length) ? "batch" : "browse";
  renderCenter();
  renderPreview();
}

async function confirmUpload() {
  const tmp = state.cropTmp;
  if (!tmp) return;
  const fromBatch = tmp.fromBatch === true;
  try {
    const r = await apiJson("/confirm", {
      token: tmp.token, type: state.type, char_id: state.selectedCharId,
    });
    toast(`已上传 ${r.hash_id}`, "ok");
    if (fromBatch) {
      state.batchItems = state.batchItems.filter(x => x.token !== tmp.token);
    }
    _resetCropState();
    state.selectedImage = { name: r.name, hash_id: r.hash_id };
    state.mode = (fromBatch && state.batchItems.length) ? "batch" : "browse";
    await loadImages();
    await loadFolders();
    renderCenter();
    renderPreview();
  } catch (e) {
    toast(`确认失败: ${e.message}`, "err");
  }
}

async function confirmReplace() {
  const tmp = state.cropTmp;
  if (!tmp || tmp.kind !== "edit-existing") return;
  if (!confirm("确认用裁剪后的内容覆盖原图? 此操作不可撤销。")) return;
  try {
    const r = await apiJson("/replace-existing", {
      token: tmp.token, type: state.type,
      char_id: state.selectedCharId,
      name: tmp.origin.name,
    });
    toast(`已覆盖 ${r.hash_id}`, "ok");
    _resetCropState();
    state.mode = "browse";
    state.selectedImage = { name: r.name, hash_id: r.hash_id };
    await loadImages();
    renderCenter();
    renderPreview();
  } catch (e) {
    toast(`覆盖失败: ${e.message}`, "err");
  }
}

// ============================================================
// EDIT EXISTING (load original into a fresh tmp)
// ============================================================
async function editExisting(img) {
  try {
    const url = `${API}/image?type=${state.type}&char_id=${encodeURIComponent(state.selectedCharId)}&name=${encodeURIComponent(img.name)}`;
    const blob = await (await fetch(url)).blob();
    const fd = new FormData();
    fd.append("file", new File([blob], img.name, { type: blob.type || "image/jpeg" }));
    const r = await api("/tmp/upload", { method: "POST", body: fd });
    state.cropTmp = {
      token: r.token,
      suffix: r.suffix,
      source: { w: r.width, h: r.height },
      current: { w: r.width, h: r.height },
      kind: "edit-existing",
      origin: { char_id: state.selectedCharId, name: img.name },
    };
    state.editWarnDismissed = false;
    state.mode = "single-crop";
    renderCenter();
    renderPreview();
  } catch (e) {
    toast(`无法编辑: ${e.message}`, "err");
  }
}

// ============================================================
// BATCH
// ============================================================
async function uploadBatch(files) {
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  try {
    const data = await api("/tmp/upload-batch", { method: "POST", body: fd });
    state.batchItems = data.items || [];
    state.batchAllow = false;
    state.mode = "batch";
    renderCenter();
    renderPreview();
  } catch (e) {
    toast(`批量上传失败: ${e.message}`, "err");
  }
}

function renderBatch(body) {
  body.append(el("div", { class: "warn-banner" },
    el("span", { class: "warn-banner__icon", text: "!" }),
    el("div", { class: "warn-banner__msg",
      text: "批量上传不会逐张确认效果，请确认无误后再点击「全部确认上传」。" }),
  ));

  body.append(el("div", { class: "batch-bar" },
    el("div", { class: "batch-bar__msg" },
      el("span", { class: "icon", text: state.batchItems.length }),
      `共 ${state.batchItems.length} 张暂存于临时区。`
    ),
    el("div", { class: "row" },
      el("label", { class: "batch-bar__check" },
        el("input", {
          type: "checkbox",
          ...(state.batchAllow ? { checked: "checked" } : {}),
          onChange: e => { state.batchAllow = e.target.checked; renderCenterBody(); },
        }),
        "我已确认风险",
      ),
      el("button", {
        class: "btn btn--primary",
        ...((!state.batchAllow || !state.batchItems.length) ? { disabled: "disabled" } : {}),
        onClick: confirmAllBatch,
      }, "全部确认上传"),
    ),
  ));

  if (!state.batchItems.length) {
    body.append(el("div", { class: "empty",
      text: "暂存区空。" }));
    return;
  }

  const grid = el("div", { class: "batch-grid" });
  for (const it of state.batchItems) {
    const card = el("div", { class: "staging-card" },
      el("img", {
        loading: "lazy",
        decoding: "async",
        src: `${API}/tmp/image?token=${it.token}`,
        alt: it.name,
      }),
      el("div", { class: "staging-card__meta" },
        el("span", { text: `${it.width}×${it.height}` }),
        el("span", { text: formatBytes(it.size) }),
      ),
      el("div", { class: "staging-card__row" },
        el("button", { class: "btn",
          onClick: () => editBatchItem(it) }, "裁剪"),
        el("button", { class: "btn btn--danger",
          onClick: () => discardBatchItem(it) }, "丢弃"),
      ),
    );
    grid.append(card);
  }
  body.append(grid);
}

async function editBatchItem(it) {
  // 暂存 item → single-crop; cancel/confirm 会用 fromBatch 决定是否回到 batch。
  state.cropTmp = {
    token: it.token,
    suffix: it.suffix,
    source: { w: it.width, h: it.height },
    current: { w: it.width, h: it.height },
    kind: "upload",
    fromBatch: true,
  };
  state.mode = "single-crop";
  renderCenter();
  renderPreview();
}

async function discardBatchItem(it) {
  try { await apiJson("/tmp/discard", { token: it.token }); } catch (_) {}
  state.batchItems = state.batchItems.filter(x => x.token !== it.token);
  renderCenterBody();
}

async function confirmAllBatch() {
  if (!state.batchAllow || !state.batchItems.length) return;
  let ok = 0, fail = 0;
  for (const it of state.batchItems.slice()) {
    try {
      await apiJson("/confirm", {
        token: it.token, type: state.type, char_id: state.selectedCharId,
      });
      state.batchItems = state.batchItems.filter(x => x.token !== it.token);
      ok++;
    } catch (_) { fail++; }
  }
  toast(`确认完成 — 成功 ${ok} 张${fail ? ` / 失败 ${fail}` : ""}`, fail ? "warn" : "ok");
  if (!state.batchItems.length) state.mode = "browse";
  await loadImages();
  await loadFolders();
  renderCenter();
  renderPreview();
}

// ============================================================
// PREVIEW
// ============================================================
function renderPreview() {
  const head = $("#previewControls");
  head.innerHTML = "";
  const titleEl = $("#previewTitle");
  const subEl = $("#previewSub");
  const foot = $("#previewFoot");
  foot.innerHTML = "";

  // decide what to render
  const needPreview = (
    (state.mode === "browse" && state.selectedImage && state.selectedCharId) ||
    (state.mode === "single-crop" && state.cropTmp && state.selectedCharId)
  );

  if (state.type === "card") {
    titleEl.textContent = "角色面板预览";
  } else {
    titleEl.textContent = "MR 预览";
    head.append(buildRendererToggle());
  }

  // sub
  if (state.mode === "browse" && state.selectedImage) {
    subEl.textContent = `${state.selectedImage.hash_id} · ${state.selectedImage.name}`;
  } else if (state.mode === "single-crop" && state.cropTmp) {
    subEl.textContent = `tmp · ${state.cropTmp.token.slice(0, 8)}…`;
  } else {
    subEl.textContent = "未选中";
  }

  // refresh button
  if (needPreview) {
    head.append(el("button", { class: "btn btn--ghost", title: "刷新预览",
      onClick: () => triggerPreview(true) }, "刷新"));
  }

  if (!needPreview) {
    setPreviewSrc(null, false);
    foot.append(el("span", { class: "muted", text: "无预览。" }));
    return;
  }

  // foot meta
  if (state.mode === "browse" && state.selectedImage) {
    const img = state.selectedImage;
    foot.append(
      el("span", null, "id ", el("b", { text: img.hash_id })),
      el("span", null, "size ", el("b", { text: formatBytes(img.size) })),
      el("span", null, "char ", el("b", { text: state.selectedCharId })),
    );
  } else if (state.mode === "single-crop" && state.cropTmp) {
    const t = state.cropTmp;
    foot.append(
      el("span", null, "tmp ", el("b", { text: t.token.slice(0, 12) })),
      el("span", null, "src ", el("b", { text: `${t.source.w}×${t.source.h}` })),
      el("span", null, "now ", el("b", { text: `${t.current.w}×${t.current.h}` })),
    );
  }

  triggerPreview();
}

function buildRendererToggle() {
  const seg = el("div", { class: "seg", role: "tablist", "aria-label": "渲染器" });
  for (const r of ["html", "pil"]) {
    seg.append(el("button", {
      class: state.renderer === r ? "is-active" : "",
      role: "tab",
      "aria-selected": String(state.renderer === r),
      onClick: () => {
        if (state.renderer === r) return;
        state.renderer = r;
        renderPreview();
      },
    }, r.toUpperCase()));
  }
  return seg;
}

function buildPreviewUrl() {
  if (state.mode === "browse" && state.selectedImage && state.selectedCharId) {
    const p = new URLSearchParams({
      type: state.type,
      char_id: state.selectedCharId,
      name: state.selectedImage.name,
      renderer: state.renderer,
    });
    return `${API}/preview?${p.toString()}`;
  }
  if (state.mode === "single-crop" && state.cropTmp && state.selectedCharId) {
    const p = new URLSearchParams({
      type: state.type,
      char_id: state.selectedCharId,
      token: state.cropTmp.token,
      renderer: state.renderer,
    });
    return `${API}/preview-tmp?${p.toString()}`;
  }
  return null;
}

function setPreviewSrc(url, loading) {
  const vp = $("#previewViewport");
  const img = $("#previewImg");
  const overlay = $("#previewOverlay");
  if (!url) {
    img.removeAttribute("src");
    vp.classList.remove("has-image");
    overlay.classList.remove("is-on");
    return;
  }
  if (loading) overlay.classList.add("is-on");
  img.onload = () => {
    overlay.classList.remove("is-on");
    vp.classList.add("has-image");
  };
  img.onerror = () => {
    overlay.classList.remove("is-on");
    vp.classList.remove("has-image");
    toast("预览渲染失败", "err");
  };
  img.src = url;
}

let previewTimer = null;
function triggerPreview(force = false) {
  const url = buildPreviewUrl();
  if (!url) return setPreviewSrc(null, false);
  // debounce frequent changes (crop spam)
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    state.previewSeq++;
    setPreviewSrc(`${url}&_=${state.previewSeq}`, true);
  }, force ? 0 : 60);
}

// ============================================================
// utilities
// ============================================================
function formatBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(2)}MB`;
}

// debounce input
function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ============================================================
// Layout — resizable side / preview panes + mobile drawers
// ============================================================
const LAYOUT_KEY = "ww.panelEdit.layout.v1";

function loadLayout() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (!raw) return;
    const v = JSON.parse(raw);
    if (typeof v.side === "number") setPaneWidth("--side-w", v.side, 200, 480);
    if (typeof v.preview === "number") setPaneWidth("--preview-w", v.preview, 280, 720);
  } catch (_) {}
}

function saveLayout() {
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify({
      side: parsePx(getComputedStyle(document.documentElement).getPropertyValue("--side-w")),
      preview: parsePx(getComputedStyle(document.documentElement).getPropertyValue("--preview-w")),
    }));
  } catch (_) {}
}

function parsePx(s) { const n = parseFloat(s); return Number.isFinite(n) ? n : 0; }

function setPaneWidth(varName, px, min, max) {
  const v = Math.max(min, Math.min(max, Math.round(px)));
  document.documentElement.style.setProperty(varName, `${v}px`);
}

function bindResizer(elNode, varName, dir, min, max) {
  let startX = 0, startW = 0, dragging = false;
  const onDown = (ev) => {
    ev.preventDefault();
    dragging = true;
    elNode.classList.add("is-active");
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    startX = ev.clientX;
    startW = parsePx(getComputedStyle(document.documentElement).getPropertyValue(varName));
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp, { once: true });
  };
  const onMove = (ev) => {
    if (!dragging) return;
    const delta = (ev.clientX - startX) * dir;
    setPaneWidth(varName, startW + delta, min, max);
  };
  const onUp = () => {
    dragging = false;
    elNode.classList.remove("is-active");
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    document.removeEventListener("pointermove", onMove);
    saveLayout();
  };
  elNode.addEventListener("pointerdown", onDown);
  elNode.addEventListener("dblclick", () => {
    setPaneWidth(varName, varName === "--side-w" ? 296 : 440, min, max);
    saveLayout();
  });
  elNode.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const cur = parsePx(getComputedStyle(document.documentElement).getPropertyValue(varName));
    const step = e.shiftKey ? 32 : 8;
    const delta = (e.key === "ArrowRight" ? 1 : -1) * dir * step;
    setPaneWidth(varName, cur + delta, min, max);
    saveLayout();
  });
}

function setupLayout() {
  loadLayout();
  bindResizer($("#resizerSide"), "--side-w", +1, 200, 480);
  bindResizer($("#resizerPreview"), "--preview-w", -1, 280, 720);

  // mobile drawers
  const sidebar = $("#sidebar");
  const preview = $("#previewPane");
  const scrim = $("#scrim");
  const closeAll = () => {
    sidebar.classList.remove("is-open");
    preview.classList.remove("is-open");
    scrim.classList.remove("is-on");
  };
  $("#mobileMenu").addEventListener("click", () => {
    const wasOpen = sidebar.classList.contains("is-open");
    closeAll();
    if (!wasOpen) {
      sidebar.classList.add("is-open");
      scrim.classList.add("is-on");
    }
  });
  $("#mobilePreview").addEventListener("click", () => {
    const wasOpen = preview.classList.contains("is-open");
    closeAll();
    if (!wasOpen) {
      preview.classList.add("is-open");
      scrim.classList.add("is-on");
    }
  });
  scrim.addEventListener("click", closeAll);
  // tap inside sidebar list closes drawer when picking a folder (mobile UX)
  sidebar.addEventListener("click", (e) => {
    if (window.matchMedia("(max-width: 820px)").matches && e.target.closest(".folder")) {
      // 等本次 click 触发完 selectFolder 后再收
      setTimeout(closeAll, 60);
    }
  });
}


// ============================================================
// Init
// ============================================================
async function init() {
  setupLayout();
  // type tab tabs render after meta.
  $("#folderFilter").addEventListener("input", debounce(e => {
    state.filterText = e.target.value;
    renderFolders();
  }, 80));

  try {
    await loadMeta();
  } catch (e) {
    if (e.status === 503) {
      $("#topbarMeta").innerHTML = "";
      $("#topbarMeta").append(
        el("span", { class: "status-dot status-dot--err" }),
        el("span", { class: "topbar__status", text: "未启用 / 配置 WavesPanelEditPassword" }),
      );
      $("#centerBody").append(el("div", { class: "empty" },
        el("div", { class: "empty__title", text: "DISABLED" }),
        el("div", { text: "请在 WutheringWavesConfig 中设置 WavesPanelEditPassword 后重启或刷新。" }),
      ));
      return;
    }
    toast(`初始化失败: ${e.message}`, "err");
    return;
  }

  await loadFolders();
  renderCenter();
  renderPreview();
}

document.addEventListener("DOMContentLoaded", init);
