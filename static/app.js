"use strict";

/* ==========================================================================
   Constants
   ========================================================================== */

const SCOPES = ["Weekend", "1–2 weeks", "Month+"];

const COVERS = [
  "linear-gradient(135deg, #ff9a8b 0%, #ff6a88 55%, #ff99ac 100%)",
  "linear-gradient(135deg, #2b5876 0%, #4e4376 100%)",
  "linear-gradient(135deg, #0ba360 0%, #3cba92 100%)",
  "linear-gradient(135deg, #a18cd1 0%, #fbc2eb 100%)",
  "linear-gradient(135deg, #f6a365 0%, #f5576c 100%)",
  "linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%)",
  "linear-gradient(135deg, #4facfe 0%, #00c6fb 100%)",
  "linear-gradient(135deg, #f83600 0%, #f9a423 100%)",
  "linear-gradient(135deg, #134e5e 0%, #71b280 100%)",
  "linear-gradient(135deg, #232526 0%, #4b4d50 100%)",
];

const RATIOS = [1.3, 1.0, 1.5, 1.15, 0.85, 1.4, 1.2];

const SORTS = [
  ["hot", "Hot", "flame"],
  ["new", "New", "zap"],
  ["top", "Top", "trending"],
  ["discussed", "Discussed", "message"],
];

const STATUSES = [
  ["", "All"],
  ["open", "Up for grabs"],
  ["building", "Building"],
  ["shipped", "Shipped"],
];

const ICONS = {
  rocket: '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  arrowUp: '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
  arrowLeft: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  message: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
  fork: '<circle cx="12" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M18 9v2c0 .6-.4 1-1 1H7c-.6 0-1-.4-1-1V9"/><path d="M12 12v3"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  terminal: '<polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/>',
  hammer: '<path d="m15 12-8.5 8.5c-.83.83-2.17.83-3 0a2.12 2.12 0 0 1 0-3L12 9"/><path d="M17.64 15 22 10.64"/><path d="m20.91 11.7-1.25-1.25c-.6-.6-.93-1.4-.93-2.25v-.86L16.01 4.6a5.56 5.56 0 0 0-3.94-1.64H9l.92.82A6.18 6.18 0 0 1 12 8.4v1.56l2 2h2.47l2.26 1.91"/>',
  checkCircle: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  github: '<path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"/><path d="M9 18c-4.51 2-5-2-7-2"/>',
  external: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  code: '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>',
  pencil: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  shuffle: '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M20 21a8 8 0 0 0-16 0"/>',
  grid: '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  reply: '<polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 0 0-4-4H4"/>',
  clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  flame: '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.07-2.14-.22-4.05 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.15.43-2.29 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
  zap: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  trending: '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
  alert: '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
  sparkles: '<path d="M12 3 13.9 8.8 20 10.7 13.9 12.6 12 18.4 10.1 12.6 4 10.7 10.1 8.8Z"/><path d="M19 3v4"/><path d="M21 5h-4"/>',
  lightbulb: '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><path d="M10 22h4"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" x2="12" y1="3" y2="15"/>',
  image: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
};

const IMAGE_REF = /^(https?:\/\/|\/uploads\/)/i;
const IMAGE_ACCEPT = "image/png,image/jpeg,image/gif,image/webp";

/* ==========================================================================
   State + tiny helpers
   ========================================================================== */

const state = {
  me: null,
  config: { github: false, demo: true, max_upload_bytes: 5 * 1024 * 1024 },
  unread: 0,
  feedCache: null,
  popover: null,
  modal: null,
  routeToken: 0,
  navCount: 0,
  pollTimer: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const view = () => document.getElementById("view");

function h(html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  return template.content.firstElementChild;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function icon(name, size = 18) {
  return `<svg class="i" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ""}</svg>`;
}

function avatar(user, size = 32) {
  if (!user) {
    return `<span class="avatar avatar-ghost" style="--size:${size}px"></span>`;
  }
  const name = user.display_name || user.username || "?";
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const hue = Number.isFinite(user.avatar_hue) ? user.avatar_hue : 200;
  const background = `linear-gradient(135deg, hsl(${hue} 80% 62%), hsl(${(hue + 40) % 360} 72% 45%))`;
  const photo = user.avatar_url && IMAGE_REF.test(user.avatar_url)
    ? `<img src="${esc(user.avatar_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">`
    : "";
  return `<span class="avatar" style="--size:${size}px;background:${background}" title="${esc(name)}">${esc(initials)}${photo}</span>`;
}

function timeAgo(timestamp) {
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  if (days < 35) return `${Math.floor(days / 7)}w ago`;
  return new Date(timestamp * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatJoined(timestamp) {
  return new Date(timestamp * 1000).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function compact(number) {
  if (number >= 10000) return `${Math.round(number / 1000)}k`;
  if (number >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(number);
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function shortUrl(url) {
  return url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function normalizeTag(raw) {
  return raw.trim().toLowerCase().replace(/^#/, "").replace(/\s+/g, "-").replace(/[^a-z0-9+.\-]/g, "").slice(0, 24);
}

/* ==========================================================================
   API
   ========================================================================== */

async function api(method, path, body) {
  const options = { method, headers: {}, credentials: "same-origin" };
  if (method !== "GET") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body ?? {});
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    const error = new Error("Can't reach the shiphub server. Is it still running?");
    error.status = 0;
    throw error;
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

/* Downscale big photos in the browser so uploads stay small and fast. GIFs keep their animation. */
async function prepareImage(file, maxDim) {
  if (!/^image\/(png|jpeg|gif|webp)$/.test(file.type)) {
    throw new Error("Use a PNG, JPEG, GIF or WebP image.");
  }
  if (file.type === "image/gif" || typeof createImageBitmap !== "function") return file;
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return file;
  }
  const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size <= 1.5 * 1024 * 1024) {
    if (bitmap.close) bitmap.close();
    return file;
  }
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  if (bitmap.close) bitmap.close();
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/webp", 0.86));
  return blob && blob.size < file.size ? blob : file;
}

async function uploadImage(file, { maxDim = 1600 } = {}) {
  const prepared = await prepareImage(file, maxDim);
  const limit = state.config.max_upload_bytes || 5 * 1024 * 1024;
  if (prepared.size > limit) {
    throw new Error(`That image is too big. The limit is ${Math.round(limit / (1024 * 1024))} MB.`);
  }
  let response;
  try {
    response = await fetch("/api/uploads", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": prepared.type || "application/octet-stream", "X-Shiphub-Upload": "1" },
      body: prepared,
    });
  } catch {
    throw new Error("The upload didn't go through. Check your connection and try again.");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `Upload failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data.url;
}

function firstImageFile(list) {
  return [...(list || [])].find((file) => file && /^image\//.test(file.type)) || null;
}

function isAdmin() {
  return Boolean(state.me && state.me.is_admin);
}

function githubSignInHref() {
  const next = location.hash && location.hash.startsWith("#/") ? location.hash : "#/";
  return `/auth/github?next=${encodeURIComponent(next)}`;
}

function handleError(error) {
  if (error && error.status === 401) {
    openAuth("login");
  }
  toast(error && error.message ? error.message : "Something went wrong", "error");
}

function requireAuth() {
  if (state.me) return true;
  openAuth("login");
  return false;
}

/* ==========================================================================
   Toasts, clipboard, theme
   ========================================================================== */

function toast(message, type = "success") {
  const el = h(`<div class="toast toast-${type}">${icon(type === "error" ? "alert" : "check", 16)}<span>${esc(message)}</span></div>`);
  $("#toasts").append(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  }, 2600);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = h(`<textarea style="position:fixed;top:-1000px;opacity:0"></textarea>`);
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("shiphub.theme", next);
  closePopover();
  renderTopbarActions();
}

/* ==========================================================================
   Markdown (small, safe subset)
   ========================================================================== */

function inlineMarkdown(text) {
  let out = esc(text);
  const codes = [];
  out = out.replace(/`([^`]+)`/g, (_, code) => {
    codes.push(`<code>${code}</code>`);
    return `\u0001${codes.length - 1}\u0001`;
  });
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    (_, label, url) => `<a href="${url}" target="_blank" rel="noopener noreferrer nofollow">${label}</a>`,
  );
  out = out.replace(
    /(^|[\s(])(https?:\/\/[^\s<]+[^\s<.,;:!?)])/g,
    (_, before, url) => `${before}<a href="${url}" target="_blank" rel="noopener noreferrer nofollow">${url}</a>`,
  );
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
  out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  out = out.replace(/\n/g, "<br>");
  out = out.replace(/\u0001(\d+)\u0001/g, (_, index) => codes[Number(index)]);
  return out;
}

function markdown(source) {
  const blocks = [];
  let text = String(source || "").replace(/\r\n/g, "\n");
  text = text.replace(/```[\w-]*\n([\s\S]*?)```/g, (_, code) => {
    blocks.push(`<pre><code>${esc(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });

  let html = "";
  let paragraph = [];
  let list = null;
  const flushParagraph = () => {
    if (paragraph.length) {
      html += `<p>${inlineMarkdown(paragraph.join("\n"))}</p>`;
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list) {
      html += `<${list.type}>${list.items.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</${list.type}>`;
      list = null;
    }
  };

  for (const line of text.split("\n")) {
    const block = line.match(/^\u0000(\d+)\u0000$/);
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (block) {
      flushParagraph();
      flushList();
      html += blocks[Number(block[1])];
    } else if (heading) {
      flushParagraph();
      flushList();
      const level = heading[1].length + 2;
      html += `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
    } else if (bullet || numbered) {
      flushParagraph();
      const type = bullet ? "ul" : "ol";
      if (!list || list.type !== type) {
        flushList();
        list = { type, items: [] };
      }
      list.items.push((bullet || numbered)[1]);
    } else if (/^>\s?/.test(line)) {
      flushParagraph();
      flushList();
      html += `<blockquote>${inlineMarkdown(line.replace(/^>\s?/, ""))}</blockquote>`;
    } else if (!line.trim()) {
      flushParagraph();
      flushList();
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return html;
}

/* ==========================================================================
   Cards + covers
   ========================================================================== */

function coverRatio(idea) {
  return idea.cover_image ? 1.25 : RATIOS[idea.id % RATIOS.length];
}

function coverStyle(index) {
  return COVERS[((index % COVERS.length) + COVERS.length) % COVERS.length];
}

function coverHTML(idea, { large = false } = {}) {
  if (idea.cover_image) {
    return `<img class="cover-img" src="${esc(idea.cover_image)}" alt="" loading="lazy" data-fallback="${idea.cover_style}">`;
  }
  const lines = Math.max(3, Math.round(coverRatio(idea) * (large ? 6 : 4.6)));
  const tag = idea.tags && idea.tags[0];
  return `<div class="cover-art" style="background:${coverStyle(idea.cover_style)}">
      <div class="cover-pattern p${idea.id % 4}"></div>
      <div class="cover-text" style="-webkit-line-clamp:${lines}">${esc(idea.pitch)}</div>
      ${tag ? `<div class="cover-tag">#${esc(tag)}</div>` : ""}
    </div>`;
}

function miniCover(preview) {
  if (preview.cover_image) {
    return `<img src="${esc(preview.cover_image)}" alt="" loading="lazy" data-fallback="${preview.cover_style}" class="cover-img">`;
  }
  return `<div class="mini-art" style="background:${coverStyle(preview.cover_style)}"><span>${esc(preview.title)}</span></div>`;
}

function statusBadge(status) {
  if (status === "shipped") return `<span class="badge badge-shipped">${icon("checkCircle", 12)} Shipped</span>`;
  if (status === "building") return `<span class="badge badge-building">${icon("hammer", 12)} Building</span>`;
  return "";
}

function voteInner(idea, size = 14) {
  return `${icon("arrowUp", size)}<span class="vote-count">${compact(idea.votes)}</span>`;
}

function ideaCard(idea) {
  return h(`<article class="pin" data-idea="${idea.id}">
      <div class="pin-cover" style="aspect-ratio:1 / ${coverRatio(idea)}">
        ${coverHTML(idea)}
        <a class="pin-link" href="#/i/${idea.id}" aria-label="${esc(idea.title)}"></a>
        <div class="pin-badges">${statusBadge(idea.status)}${idea.forked_from ? `<span class="badge badge-glass">${icon("fork", 12)} Fork</span>` : ""}</div>
        <div class="pin-hover">
          <button class="btn pin-save ${idea.saved ? "is-saved" : ""}" data-action="save" data-id="${idea.id}">${idea.saved ? "Saved" : "Save"}</button>
          <div class="pin-hover-bottom">
            <span class="pin-scope">${icon("clock", 13)} ${esc(SCOPES[idea.scope] || "")}</span>
            <button class="pin-icon-btn" data-action="copy-prompt" data-id="${idea.id}" title="Copy as AI prompt">${icon("terminal", 16)}</button>
          </div>
        </div>
      </div>
      <div class="pin-meta">
        <a class="pin-title" href="#/i/${idea.id}">${esc(idea.title)}</a>
        <div class="pin-foot">
          <a class="pin-author" href="#/u/${esc(idea.author.username)}">${avatar(idea.author, 20)}<span>${esc(idea.author.display_name)}</span></a>
          <span class="pin-stats">
            <button class="vote-pill ${idea.voted ? "voted" : ""}" data-action="vote" data-id="${idea.id}" title="Upvote">${voteInner(idea)}</button>
            <a class="pin-stat" href="#/i/${idea.id}" title="Comments">${icon("message", 14)}${compact(idea.comment_count)}</a>
          </span>
        </div>
      </div>
    </article>`);
}

document.addEventListener(
  "error",
  (event) => {
    const img = event.target;
    if (img instanceof HTMLImageElement && img.parentElement && img.parentElement.classList.contains("avatar")) {
      img.remove();
      return;
    }
    if (img instanceof HTMLImageElement && img.classList.contains("cover-img")) {
      img.replaceWith(h(`<div class="cover-art" style="background:${coverStyle(Number(img.dataset.fallback) || 0)}"><div class="cover-pattern p0"></div></div>`));
    }
  },
  true,
);

/* Keep every rendered copy of an idea (feed, related, cached feed) in sync. */
function eachRendered(selector, callback) {
  const roots = [document];
  if (state.feedCache && !state.feedCache.node.isConnected) roots.push(state.feedCache.node);
  roots.forEach((root) => root.querySelectorAll(selector).forEach(callback));
}

function syncVote(id, voted, votes) {
  eachRendered(`[data-action="vote"][data-id="${id}"]`, (button) => {
    button.classList.toggle("voted", voted);
    const count = button.querySelector(".vote-count");
    if (count) count.textContent = compact(votes);
  });
}

function syncSaved(id, saved) {
  eachRendered(`[data-action="save"][data-id="${id}"]`, (button) => {
    button.classList.toggle("is-saved", saved);
    button.textContent = saved ? "Saved" : "Save";
  });
}

/* ==========================================================================
   Masonry feed with infinite scroll
   ========================================================================== */

class Masonry {
  constructor({ fetchPage, emptyHTML = "", onEmpty = null }) {
    this.fetchPage = fetchPage;
    this.emptyHTML = emptyHTML;
    this.onEmpty = onEmpty;
    this.cards = [];
    this.columns = [];
    this.offset = 0;
    this.hasMore = true;
    this.loading = false;
    this.failed = false;
    this.el = h(`<div class="masonry-wrap"><div class="masonry"></div><div class="masonry-status"></div><div class="sentinel"></div></div>`);
    this.grid = $(".masonry", this.el);
    this.status = $(".masonry-status", this.el);
    this.sentinel = $(".sentinel", this.el);
  }

  start() {
    this.buildColumns(this.columnCount());
    this.showSkeletons();
    this.observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) this.loadMore();
      },
      { rootMargin: "1200px 0px" },
    );
    this.observer.observe(this.sentinel);
    this.resizeObserver = new ResizeObserver(() => this.relayoutIfNeeded());
    this.resizeObserver.observe(this.grid);
    this.loadMore();
  }

  columnCount() {
    const width = this.grid.clientWidth || document.documentElement.clientWidth - 48;
    return Math.max(2, Math.min(7, Math.floor((width + 16) / (236 + 16))));
  }

  buildColumns(count) {
    this.columns = Array.from({ length: count }, () => h(`<div class="masonry-col"></div>`));
    this.grid.replaceChildren(...this.columns);
  }

  shortestColumn() {
    return this.columns.reduce((best, column) => (column.offsetHeight < best.offsetHeight ? column : best));
  }

  relayoutIfNeeded() {
    if (!this.el.isConnected || !this.cards.length) return;
    const count = this.columnCount();
    if (count === this.columns.length) return;
    this.buildColumns(count);
    this.cards.forEach((card) => this.shortestColumn().append(card));
  }

  showSkeletons() {
    this.columns.forEach((column, index) => {
      for (let k = 0; k < 2; k += 1) {
        const ratio = RATIOS[(index + k * 3) % RATIOS.length];
        column.append(h(`<div class="sk-pin"><div class="sk-cover" style="aspect-ratio:1 / ${ratio}"></div><div class="sk-line" style="width:78%"></div><div class="sk-line" style="width:46%"></div></div>`));
      }
    });
  }

  async loadMore() {
    if (this.loading || !this.hasMore || this.failed || !this.el.isConnected) return;
    this.loading = true;
    if (this.offset > 0) this.status.innerHTML = `<div class="spinner"></div>`;
    try {
      const page = await this.fetchPage(this.offset);
      if (this.offset === 0) this.buildColumns(this.columnCount());
      for (const item of page.items) {
        const card = ideaCard(item);
        this.cards.push(card);
        this.shortestColumn().append(card);
      }
      this.offset += page.items.length;
      this.hasMore = page.has_more;
      if (!this.cards.length) {
        this.status.innerHTML = this.emptyHTML;
        if (this.onEmpty) this.onEmpty();
      } else if (!this.hasMore && this.cards.length > 10) {
        this.status.innerHTML = `<span class="end-mark">${icon("rocket", 16)} You've seen it all. Time to build something.</span>`;
      } else {
        this.status.innerHTML = "";
      }
    } catch (error) {
      this.failed = true;
      if (this.offset === 0) this.buildColumns(this.columnCount());
      this.status.innerHTML = `<div class="load-error">${esc(error.message)} <button class="btn btn-secondary btn-sm" data-retry>Retry</button></div>`;
      $("[data-retry]", this.status).addEventListener("click", () => {
        this.failed = false;
        this.loadMore();
      });
    } finally {
      this.loading = false;
    }
    if (this.hasMore && !this.failed) {
      requestAnimationFrame(() => {
        if (this.el.isConnected && this.sentinel.getBoundingClientRect().top < window.innerHeight + 1200) {
          this.loadMore();
        }
      });
    }
  }
}

function emptyState(iconName, title, text, actionHTML = "") {
  return `<div class="empty-state"><div class="empty-icon">${icon(iconName, 28)}</div><h3>${esc(title)}</h3><p>${text}</p>${actionHTML}</div>`;
}

function pageLoading() {
  return h(`<div class="page-loading"><div class="spinner"></div></div>`);
}

function pageError(error) {
  const notFound = error.status === 404;
  return h(`<div class="container">${emptyState(
    notFound ? "search" : "alert",
    notFound ? "Not found" : "Couldn't load this page",
    esc(error.message),
    `<a class="btn btn-secondary" href="#/">Back to Explore</a>`,
  )}</div>`);
}

/* ==========================================================================
   Router
   ========================================================================== */

function parseHash() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { path: path || "/", params: new URLSearchParams(query) };
}

function feedHref(params, overrides) {
  const next = new URLSearchParams(params);
  for (const [key, value] of Object.entries(overrides)) {
    if (value === null || value === undefined || value === "") next.delete(key);
    else next.set(key, value);
  }
  const query = next.toString();
  return `#/${query ? `?${query}` : ""}`;
}

function invalidateFeed() {
  state.feedCache = null;
}

function updateNav(path, params) {
  const shipped = path === "/" && params.get("status") === "shipped";
  $$("[data-nav]").forEach((link) => {
    let active = path === "/" && !shipped;
    if (link.dataset.nav === "shipped") active = shipped;
    if (link.dataset.nav === "hq") active = path === "/hq" || path.startsWith("/hq/");
    link.classList.toggle("active", active);
  });
  const searchInput = $("#search-input");
  if (document.activeElement !== searchInput) {
    searchInput.value = path === "/" ? params.get("q") || "" : "";
  }
}

function route() {
  const token = ++state.routeToken;
  const isCurrent = () => token === state.routeToken;
  state.navCount += 1;
  closePopover();
  closeModal({ force: true });

  const { path, params } = parseHash();
  const key = location.hash || "#/";
  const cache = state.feedCache;
  if (cache && cache.active) {
    cache.scrollY = window.scrollY;
    cache.active = false;
  }
  updateNav(path, params);

  if (path === "/") {
    if (cache && cache.key === key) {
      view().replaceChildren(cache.node);
      cache.active = true;
      document.title = cache.title;
      window.scrollTo(0, cache.scrollY);
      cache.masonry.relayoutIfNeeded();
      return;
    }
    window.scrollTo(0, 0);
    renderFeed(params, key);
    return;
  }

  window.scrollTo(0, 0);
  if (path === "/hq" || path.startsWith("/hq/")) {
    renderHQ(path.slice(3), params, isCurrent);
    return;
  }
  let match = path.match(/^\/i\/(\d+)$/);
  if (match) {
    renderIdea(Number(match[1]), isCurrent);
    return;
  }
  match = path.match(/^\/u\/([A-Za-z0-9_]+)(?:\/(ideas|builds|boards|hq))?$/);
  if (match) {
    renderProfile(match[1], match[2] || "ideas", isCurrent);
    return;
  }
  match = path.match(/^\/b\/(\d+)$/);
  if (match) {
    renderBoard(Number(match[1]), isCurrent);
    return;
  }
  document.title = "Not found · shiphub";
  view().replaceChildren(pageError({ status: 404, message: "That page doesn't exist." }));
}

function goBack() {
  if (state.navCount > 1 && window.history.length > 1) history.back();
  else location.hash = "#/";
}

/* ==========================================================================
   Feed page
   ========================================================================== */

function renderFeed(params, key) {
  const sort = params.get("sort") || "hot";
  const status = params.get("status") || "";
  const tag = params.get("tag") || "";
  const query = params.get("q") || "";
  const showHero = !status && !tag && !query && sort === "hot";

  let title = "shiphub · fork an idea, ship an app";
  if (query) title = `“${query}” · shiphub`;
  else if (tag) title = `#${tag} · shiphub`;
  else if (status === "shipped") title = "Shipped · shiphub";
  document.title = title;

  let summary = "";
  if (query || tag) {
    const label = query ? `Results for “${esc(query)}”` : `#${esc(tag)}`;
    summary = `<div class="search-summary">${label}<a class="btn btn-ghost btn-sm" href="${feedHref(params, { q: null, tag: null })}">${icon("x", 14)} Clear</a></div>`;
  } else if (status === "shipped") {
    summary = `<div class="search-summary">${icon("checkCircle", 22)} Ideas that became real apps</div>`;
  }

  const node = h(`<div class="feed container">
      ${showHero ? heroHTML() : ""}
      <div class="feed-toolbar">
        <div class="toolbar-row">
          <div class="seg">${SORTS.map(([value, label, iconName]) => `<a class="${sort === value ? "active" : ""}" href="${feedHref(params, { sort: value === "hot" ? null : value })}">${icon(iconName, 15)}${label}</a>`).join("")}</div>
          <div class="seg">${STATUSES.map(([value, label]) => `<a class="${status === value ? "active" : ""}" href="${feedHref(params, { status: value || null })}">${label}</a>`).join("")}</div>
        </div>
        <div class="tag-scroller"></div>
      </div>
      ${summary}
    </div>`);

  const search = new URLSearchParams({ sort, status, tag, q: query, limit: "30" });
  const masonry = new Masonry({
    fetchPage: (offset) => api("GET", `/api/ideas?${search}&offset=${offset}`),
    emptyHTML: emptyState(
      "lightbulb",
      query || tag ? "No ideas match that yet" : "Nothing here yet",
      query || tag ? "Try another search, or be the first to post an idea for it." : "Post the first idea and get the board going.",
      `<button class="btn btn-primary" data-action="new-idea">${icon("plus", 16)} Post an idea</button>`,
    ),
  });
  node.append(masonry.el);
  view().replaceChildren(node);
  state.feedCache = { key, node, masonry, title, scrollY: 0, active: true };
  masonry.start();
  loadTagScroller($(".tag-scroller", node), params, tag);
  if (showHero) loadHeroStats(node);
}

function heroHTML() {
  return `<section class="hero">
      <div class="hero-text">
        <h1>Find your next build.<br><span class="accent">Then ship it.</span></h1>
        <p>A pinboard of app ideas worth vibe-coding. Save the ones you love, argue about them in threads, fork them into your own spin, and link your repo when you ship.</p>
        <div class="hero-cta">
          <button class="btn btn-primary btn-lg" data-action="new-idea">${icon("plus", 18)} Post an idea</button>
          <button class="btn btn-secondary btn-lg" data-action="inspire">${icon("shuffle", 18)} Inspire me</button>
        </div>
      </div>
      <div class="hero-stats">
        <div class="stat"><div class="stat-num" data-stat="ideas">–</div><div class="stat-label">Ideas</div></div>
        <div class="stat"><div class="stat-num" data-stat="builds">–</div><div class="stat-label">Builders</div></div>
        <div class="stat"><div class="stat-num" data-stat="shipped">–</div><div class="stat-label">Shipped</div></div>
        <div class="stat"><div class="stat-num" data-stat="makers">–</div><div class="stat-label">Makers</div></div>
      </div>
    </section>`;
}

async function loadHeroStats(node) {
  try {
    const stats = await api("GET", "/api/stats");
    for (const [key, value] of Object.entries(stats)) {
      const el = $(`[data-stat="${key}"]`, node);
      if (el) el.textContent = compact(value);
    }
  } catch {
    /* stats are decorative */
  }
}

async function loadTagScroller(container, params, activeTag) {
  try {
    const { tags } = await api("GET", "/api/tags");
    container.innerHTML =
      `<a class="chip ${activeTag ? "" : "active"}" href="${feedHref(params, { tag: null })}">All ideas</a>` +
      tags
        .map(({ tag, count }) => `<a class="chip ${activeTag === tag ? "active" : ""}" href="${feedHref(params, { tag: activeTag === tag ? null : tag })}">#${esc(tag)} <span class="chip-count">${count}</span></a>`)
        .join("");
  } catch {
    container.remove();
  }
}

/* ==========================================================================
   Idea page
   ========================================================================== */

async function renderIdea(id, isCurrent) {
  view().replaceChildren(pageLoading());
  let data;
  try {
    data = await api("GET", `/api/ideas/${id}`);
  } catch (error) {
    if (isCurrent()) {
      document.title = "Not found · shiphub";
      view().replaceChildren(pageError(error));
    }
    return;
  }
  if (!isCurrent()) return;
  mountIdeaPage(data);
}

function buildPrompt(idea, comments = []) {
  const lines = [`Build this app: ${idea.title}`, "", idea.pitch];
  if (idea.body) lines.push("", idea.body);
  lines.push("", `Suggested stack: ${idea.stack || "your choice"}`, `Scope: ${SCOPES[idea.scope]}`);
  if (idea.tags.length) lines.push(`Tags: ${idea.tags.join(", ")}`);
  const top = comments
    .filter((comment) => !comment.deleted)
    .sort((a, b) => b.votes - a.votes)
    .slice(0, 5);
  if (top.length) {
    lines.push("", "Community suggestions worth considering:");
    top.forEach((comment) => lines.push(`- ${comment.body.replace(/\s+/g, " ").slice(0, 280)}`));
  }
  lines.push("", "Start with a minimal working version, then suggest the next three improvements.");
  return lines.join("\n");
}

function buildTree(comments, sortMode) {
  const nodes = new Map(comments.map((comment) => [comment.id, { ...comment, children: [] }]));
  const roots = [];
  nodes.forEach((node) => {
    const parent = node.parent_id ? nodes.get(node.parent_id) : null;
    (parent ? parent.children : roots).push(node);
  });
  const rootSort = sortMode === "top"
    ? (a, b) => b.votes - a.votes || a.created_at - b.created_at
    : (a, b) => b.created_at - a.created_at;
  const replySort = (a, b) => a.created_at - b.created_at;
  const prune = (list, sorter) =>
    list
      .filter((node) => {
        node.children = prune(node.children, replySort);
        return !node.deleted || node.children.length;
      })
      .sort(sorter);
  return prune(roots, rootSort);
}

function countDescendants(node) {
  return node.children.reduce((total, child) => total + 1 + countDescendants(child), 0);
}

function mountIdeaPage(initial) {
  let data = initial;
  let threadSort = "top";

  const page = h(`<div class="idea-page container">
      <div class="idea-back"><button class="btn btn-ghost btn-sm" data-act="back">${icon("arrowLeft", 16)} Back</button></div>
      <article class="idea-card">
        <div class="idea-cover-col"><div class="idea-cover"></div></div>
        <div class="idea-main">
          <div class="idea-actions"></div>
          <div class="idea-header"></div>
          <section class="section builders"></section>
          <section class="section thread"></section>
        </div>
      </article>
      <section class="more"><h2 class="section-title">More like this</h2></section>
    </div>`);

  const coverEl = $(".idea-cover", page);
  const actionsEl = $(".idea-actions", page);
  const headerEl = $(".idea-header", page);
  const buildersEl = $(".builders", page);
  const threadEl = $(".thread", page);

  const isOwner = () => state.me && state.me.id === data.idea.author.id;

  function renderCover() {
    coverEl.style.aspectRatio = `1 / ${coverRatio(data.idea)}`;
    coverEl.innerHTML = coverHTML(data.idea, { large: true });
  }

  function renderActions() {
    const idea = data.idea;
    actionsEl.innerHTML = `<div class="action-group">
        <button class="btn btn-secondary vote-btn ${idea.voted ? "voted" : ""}" data-action="vote" data-id="${idea.id}" title="Upvote">${voteInner(idea, 18)}</button>
        <button class="icon-btn" data-act="fork" title="Fork this idea">${icon("fork")}</button>
        <button class="icon-btn" data-act="share" title="Copy link">${icon("link")}</button>
        <button class="icon-btn" data-act="prompt" title="Copy as AI prompt">${icon("terminal")}</button>
        ${isOwner() || isAdmin() ? `<button class="icon-btn" data-act="owner-menu" title="More">${icon("more")}</button>` : ""}
      </div>
      <button class="btn btn-primary ${idea.saved ? "is-saved" : ""}" data-action="save" data-id="${idea.id}">${idea.saved ? "Saved" : "Save"}</button>`;
  }

  function renderHeader() {
    const idea = data.idea;
    const edited = idea.updated_at - idea.created_at > 60;
    headerEl.innerHTML = `
      ${data.forked_from ? `<a class="forked-from" href="#/i/${data.forked_from.id}">${icon("fork", 14)} Forked from <strong>${esc(data.forked_from.title)}</strong></a>` : ""}
      <h1 class="idea-title">${esc(idea.title)}</h1>
      <p class="idea-pitch">${esc(idea.pitch)}</p>
      <div class="idea-byline">
        <a class="idea-author" href="#/u/${esc(idea.author.username)}">${avatar(idea.author, 38)}<span><strong>${esc(idea.author.display_name)}</strong><span class="muted">@${esc(idea.author.username)}</span></span></a>
        <span class="muted">· ${timeAgo(idea.created_at)}${edited ? " · edited" : ""}</span>
      </div>
      <div class="idea-facts">
        <div class="fact"><span class="fact-label">${icon("clock", 13)} Scope</span><span class="fact-value">${esc(SCOPES[idea.scope])}</span></div>
        <div class="fact"><span class="fact-label">${icon("layers", 13)} Stack</span><span class="fact-value">${esc(idea.stack || "Your call")}</span></div>
        <div class="fact"><span class="fact-label">${icon("rocket", 13)} Status</span><span class="fact-value">${statusBadge(idea.status) || '<span class="badge badge-open">Up for grabs</span>'}</span></div>
      </div>
      ${idea.tags.length ? `<div class="tag-row">${idea.tags.map((tag) => `<a class="chip" href="#/?tag=${encodeURIComponent(tag)}">#${esc(tag)}</a>`).join("")}</div>` : ""}
      ${idea.body ? `<div class="prose">${markdown(idea.body)}</div>` : ""}
      ${data.forks.length ? `<div class="forks"><div class="fact-label">${icon("fork", 13)} ${plural(data.forks.length, "fork")}</div><div class="fork-list">${data.forks.map((fork) => `<a class="fork-item" href="#/i/${fork.id}">${avatar(fork.author, 22)}<span>${esc(fork.title)}</span></a>`).join("")}</div></div>` : ""}`;
  }

  function buildRow(build) {
    const repo = build.repo_url
      ? `<a class="link-pill" href="${esc(build.repo_url)}" target="_blank" rel="noopener noreferrer">${icon(/github\.com/i.test(build.repo_url) ? "github" : "code", 14)} ${esc(shortUrl(build.repo_url))}</a>`
      : "";
    const demo = build.demo_url
      ? `<a class="link-pill" href="${esc(build.demo_url)}" target="_blank" rel="noopener noreferrer">${icon("external", 14)} Live demo</a>`
      : "";
    return `<div class="build-row">
        ${avatar(build.user, 36)}
        <div class="build-info">
          <div class="build-top">
            <a class="build-name" href="#/u/${esc(build.user.username)}">${esc(build.user.display_name)}</a>
            ${statusBadge(build.status)}
            <span class="muted small">${timeAgo(build.updated_at)}</span>
          </div>
          ${build.note ? `<p class="build-note">${esc(build.note)}</p>` : ""}
          ${repo || demo ? `<div class="build-links">${repo}${demo}</div>` : ""}
        </div>
      </div>`;
  }

  function renderBuilders() {
    const builds = data.builds;
    const mine = builds.find((build) => build.mine);
    buildersEl.innerHTML = `<div class="section-head">
        <h3>${icon("hammer", 18)} Builders <span class="count">${builds.length}</span></h3>
        <button class="btn btn-secondary btn-sm" data-act="build-form">${mine ? `${icon("pencil", 14)} Update my build` : `${icon("hammer", 14)} I'm building this`}</button>
      </div>
      <div class="build-form-slot"></div>
      ${builds.length
        ? `<div class="build-list">${builds.map(buildRow).join("")}</div>`
        : `<div class="empty-note">Nobody has claimed this yet. Building it? Claim it and drop your repo so others can follow along.</div>`}`;
  }

  function openBuildForm() {
    if (!requireAuth()) return;
    const slot = $(".build-form-slot", buildersEl);
    if (slot.firstChild) {
      slot.replaceChildren();
      return;
    }
    const existing = data.builds.find((build) => build.mine);
    const mine = existing || { status: "building", repo_url: "", demo_url: "", note: "" };
    let status = mine.status;
    const form = h(`<form class="build-form" novalidate>
        <div class="seg seg-sm">
          <button type="button" data-status="building" class="${status === "building" ? "active" : ""}">${icon("hammer", 14)} Building</button>
          <button type="button" data-status="shipped" class="${status === "shipped" ? "active" : ""}">${icon("checkCircle", 14)} Shipped</button>
        </div>
        <div class="field-row">
          <label class="field"><span class="field-label">Repository</span><input class="input" name="repo_url" type="url" maxlength="300" placeholder="https://github.com/you/project" value="${esc(mine.repo_url)}"></label>
          <label class="field"><span class="field-label">Live demo</span><input class="input" name="demo_url" type="url" maxlength="300" placeholder="https://…" value="${esc(mine.demo_url)}"></label>
        </div>
        <label class="field"><span class="field-label">Note</span><input class="input" name="note" maxlength="280" placeholder="Your angle, stack, progress, or what you need help with" value="${esc(mine.note)}"></label>
        <div class="form-error"></div>
        <div class="form-actions">
          ${existing ? `<button type="button" class="btn btn-ghost btn-danger-text" data-remove>${icon("trash", 14)} Remove my build</button>` : ""}
          <span class="spacer"></span>
          <button type="button" class="btn btn-ghost" data-cancel>Cancel</button>
          <button type="submit" class="btn btn-primary">${existing ? "Save" : "Claim it"}</button>
        </div>
      </form>`);

    form.addEventListener("click", async (event) => {
      const statusButton = event.target.closest("[data-status]");
      if (statusButton) {
        status = statusButton.dataset.status;
        $$("[data-status]", form).forEach((button) => button.classList.toggle("active", button === statusButton));
      }
      if (event.target.closest("[data-cancel]")) slot.replaceChildren();
      if (event.target.closest("[data-remove]")) {
        try {
          await api("DELETE", `/api/ideas/${data.idea.id}/build`);
          toast("Removed from builders");
          await refresh();
        } catch (error) {
          handleError(error);
        }
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form));
      const submit = $('[type="submit"]', form);
      submit.disabled = true;
      try {
        await api("POST", `/api/ideas/${data.idea.id}/build`, { ...values, status });
        toast(status === "shipped" ? "Congrats on shipping! 🚀" : "You're on the builders list");
        await refresh();
      } catch (error) {
        $(".form-error", form).textContent = error.message;
        submit.disabled = false;
      }
    });

    slot.replaceChildren(form);
    $('input[name="repo_url"]', form).focus();
  }

  function commentHTML(node) {
    const own = state.me && node.author && node.author.id === state.me.id;
    const isOP = node.author && node.author.id === data.idea.author.id;
    const hidden = countDescendants(node);
    return `<div class="comment" data-comment="${node.id}">
        <div class="comment-rail">${avatar(node.author, 28)}<button class="rail-line" data-act="collapse" title="Collapse thread" aria-label="Collapse thread"></button></div>
        <div class="comment-content">
          <div class="comment-head">
            ${node.deleted
              ? `<span class="muted">[deleted]</span>`
              : `<a class="comment-author" href="#/u/${esc(node.author.username)}">${esc(node.author.display_name)}</a>${isOP ? `<span class="op-badge">OP</span>` : ""}`}
            <span class="muted">· ${timeAgo(node.created_at)}</span>
            ${node.edited_at ? `<span class="muted">· edited</span>` : ""}
            <span class="collapsed-note">${hidden ? `· ${plural(hidden, "reply")} hidden` : "· collapsed"}</span>
          </div>
          <div class="comment-collapsible">
            <div class="comment-body prose">${node.deleted ? `<p class="muted">This comment was deleted.</p>` : markdown(node.body)}</div>
            ${node.deleted ? "" : `<div class="comment-actions">
                <button class="comment-action ${node.voted ? "voted" : ""}" data-act="comment-vote" title="Upvote">${icon("arrowUp", 14)}<span class="vote-count">${node.votes}</span></button>
                <button class="comment-action" data-act="reply">${icon("reply", 14)} Reply</button>
                ${own ? `<button class="comment-action" data-act="edit">${icon("pencil", 14)} Edit</button>` : ""}
                ${own || isAdmin() ? `<button class="comment-action" data-act="delete-comment">${icon("trash", 14)} Delete</button>` : ""}
              </div>`}
            <div class="reply-slot"></div>
            ${node.children.length ? `<div class="comment-children">${node.children.map(commentHTML).join("")}</div>` : ""}
          </div>
        </div>
      </div>`;
  }

  function composerHTML(parentId, placeholder, submitLabel) {
    return `<form class="comment-composer" data-parent="${parentId || ""}">
        ${avatar(state.me, 32)}
        <div class="composer-box">
          <textarea class="textarea" rows="1" maxlength="4000" placeholder="${esc(placeholder)}"></textarea>
          <div class="composer-box-foot">
            <span class="muted small">Markdown supported</span>
            <span class="form-actions">
              ${parentId ? `<button type="button" class="btn btn-ghost btn-sm" data-act="cancel-reply">Cancel</button>` : ""}
              <button class="btn btn-primary btn-sm" type="submit" disabled>${submitLabel}</button>
            </span>
          </div>
        </div>
      </form>`;
  }

  function renderThread() {
    const visible = data.comments.filter((comment) => !comment.deleted).length;
    const tree = buildTree(data.comments, threadSort);
    threadEl.innerHTML = `<div class="section-head">
        <h3>${icon("message", 18)} Discussion <span class="count">${visible}</span></h3>
        <div class="seg seg-sm">
          <button type="button" data-act="thread-sort" data-sort="top" class="${threadSort === "top" ? "active" : ""}">Top</button>
          <button type="button" data-act="thread-sort" data-sort="new" class="${threadSort === "new" ? "active" : ""}">Newest</button>
        </div>
      </div>
      ${state.me
        ? composerHTML(null, "Add a twist, a feature idea, or a critique…", "Comment")
        : `<button class="login-prompt" data-action="login">${icon("message", 16)} Log in to join the discussion</button>`}
      <div class="comment-list">${tree.length
        ? tree.map(commentHTML).join("")
        : `<div class="empty-note">No comments yet. What would make this idea ten times better?</div>`}</div>`;
  }

  function renderAll() {
    renderCover();
    renderActions();
    renderHeader();
    renderBuilders();
    renderThread();
  }

  async function refresh() {
    data = await api("GET", `/api/ideas/${data.idea.id}`);
    renderAll();
  }

  const findComment = (id) => data.comments.find((comment) => comment.id === id);

  async function openOwnerMenu(anchor) {
    const menu = h(`<div class="menu">
        ${isOwner() ? `<button class="menu-item" data-menu="edit">${icon("pencil", 16)} Edit idea</button>` : `<div class="menu-note">${icon("shield", 14)} Moderator</div>`}
        <button class="menu-item danger" data-menu="delete">${icon("trash", 16)} Delete idea</button>
      </div>`);
    if (!openPopover(menu, anchor)) return;
    menu.addEventListener("click", async (event) => {
      const item = event.target.closest("[data-menu]");
      if (!item) return;
      closePopover();
      if (item.dataset.menu === "edit") {
        openComposer({ idea: data.idea, onSaved: (fresh) => { data = fresh; renderAll(); } });
        return;
      }
      const confirmed = await confirmDialog({
        title: "Delete this idea?",
        message: "It will disappear from the board, boards and search. Comments and builds go with it.",
        confirmLabel: "Delete idea",
        danger: true,
      });
      if (!confirmed) return;
      try {
        await api("DELETE", `/api/ideas/${data.idea.id}`);
        invalidateFeed();
        toast("Idea deleted");
        location.hash = "#/";
      } catch (error) {
        handleError(error);
      }
    });
  }

  page.addEventListener("click", async (event) => {
    const target = event.target.closest("[data-act]");
    if (!target) return;
    const act = target.dataset.act;
    const commentEl = target.closest("[data-comment]");
    const commentId = commentEl ? Number(commentEl.dataset.comment) : null;
    try {
      if (act === "back") {
        goBack();
      } else if (act === "fork") {
        openComposer({ fork: data.idea });
      } else if (act === "share") {
        await copyText(location.href);
        toast("Link copied");
      } else if (act === "prompt") {
        await copyText(buildPrompt(data.idea, data.comments));
        toast("Prompt copied. Paste it into your AI coding tool");
      } else if (act === "owner-menu") {
        openOwnerMenu(target);
      } else if (act === "build-form") {
        openBuildForm();
      } else if (act === "thread-sort") {
        threadSort = target.dataset.sort;
        renderThread();
      } else if (act === "collapse") {
        commentEl.classList.add("collapsed");
      } else if (act === "comment-vote") {
        if (!requireAuth()) return;
        const result = await api("POST", `/api/comments/${commentId}/vote`);
        const comment = findComment(commentId);
        Object.assign(comment, { voted: result.voted, votes: result.votes });
        target.classList.toggle("voted", result.voted);
        $(".vote-count", target).textContent = result.votes;
      } else if (act === "reply") {
        if (!requireAuth()) return;
        const slot = $(".reply-slot", commentEl);
        if (slot.firstChild) {
          slot.replaceChildren();
          return;
        }
        slot.innerHTML = composerHTML(commentId, "Write a reply…", "Reply");
        $("textarea", slot).focus();
      } else if (act === "cancel-reply") {
        target.closest(".reply-slot").replaceChildren();
      } else if (act === "edit") {
        const body = $(".comment-body", commentEl);
        const original = findComment(commentId).body;
        const form = h(`<form class="edit-form"><textarea class="textarea" rows="3" maxlength="4000"></textarea><div class="form-actions"><span class="spacer"></span><button type="button" class="btn btn-ghost btn-sm" data-act="cancel-edit">Cancel</button><button type="submit" class="btn btn-primary btn-sm">Save</button></div></form>`);
        $("textarea", form).value = original;
        body.replaceWith(form);
        $(".comment-actions", commentEl).hidden = true;
        form.addEventListener("submit", async (submitEvent) => {
          submitEvent.preventDefault();
          try {
            await api("PATCH", `/api/comments/${commentId}`, { body: $("textarea", form).value });
            await refresh();
          } catch (error) {
            handleError(error);
          }
        });
        $("textarea", form).focus();
      } else if (act === "cancel-edit") {
        renderThread();
      } else if (act === "delete-comment") {
        const confirmed = await confirmDialog({
          title: "Delete comment?",
          message: "Replies stay visible, but your text will be removed.",
          confirmLabel: "Delete",
          danger: true,
        });
        if (!confirmed) return;
        await api("DELETE", `/api/comments/${commentId}`);
        await refresh();
        toast("Comment deleted");
      }
    } catch (error) {
      handleError(error);
    }
  });

  page.addEventListener("click", (event) => {
    const head = event.target.closest(".comment.collapsed > .comment-content > .comment-head");
    if (head && !event.target.closest("a")) head.closest(".comment").classList.remove("collapsed");
  });

  page.addEventListener("input", (event) => {
    const area = event.target.closest(".composer-box textarea");
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 320)}px`;
    const hasText = area.value.trim().length > 0;
    area.closest(".composer-box").classList.toggle("has-text", hasText);
    $('[type="submit"]', area.closest("form")).disabled = !hasText;
  });

  page.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && event.target.closest(".composer-box textarea")) {
      event.preventDefault();
      event.target.closest("form").requestSubmit();
    }
  });

  page.addEventListener("submit", async (event) => {
    const form = event.target.closest(".comment-composer");
    if (!form) return;
    event.preventDefault();
    const area = $("textarea", form);
    const submit = $('[type="submit"]', form);
    submit.disabled = true;
    try {
      await api("POST", `/api/ideas/${data.idea.id}/comments`, {
        body: area.value,
        parent_id: form.dataset.parent ? Number(form.dataset.parent) : null,
      });
      await refresh();
      toast(form.dataset.parent ? "Reply posted" : "Comment posted");
    } catch (error) {
      submit.disabled = false;
      handleError(error);
    }
  });

  renderAll();
  document.title = `${data.idea.title} · shiphub`;
  view().replaceChildren(page);

  const more = $(".more", page);
  const related = new Masonry({
    fetchPage: (offset) => api("GET", `/api/ideas?related=${data.idea.id}&sort=top&limit=24&offset=${offset}`),
    onEmpty: () => more.remove(),
  });
  more.append(related.el);
  related.start();
}

/* ==========================================================================
   Profile + boards
   ========================================================================== */

async function renderProfile(username, tab, isCurrent) {
  view().replaceChildren(pageLoading());
  let data;
  try {
    data = await api("GET", `/api/users/${encodeURIComponent(username)}`);
  } catch (error) {
    if (isCurrent()) view().replaceChildren(pageError(error));
    return;
  }
  if (!isCurrent()) return;

  const { user, stats } = data;
  const own = state.me && state.me.id === user.id;
  document.title = `${user.display_name} (@${user.username}) · shiphub`;
  const stat = (value, label) => `<div class="stat"><div class="stat-num">${compact(value)}</div><div class="stat-label">${label}</div></div>`;

  const page = h(`<div class="profile container">
      <header class="profile-head">
        ${avatar(user, 104)}
        <h1 class="profile-name">${esc(user.display_name)}</h1>
        <div class="profile-handle">@${esc(user.username)} · joined ${formatJoined(user.created_at)}</div>
        ${user.github_login ? `<a class="profile-gh" href="https://github.com/${encodeURIComponent(user.github_login)}" target="_blank" rel="noopener noreferrer">${icon("github", 14)} ${esc(user.github_login)}</a>` : ""}
        ${user.bio ? `<p class="profile-bio">${esc(user.bio)}</p>` : own ? `<p class="profile-bio muted">Add a short bio so people know what you build.</p>` : ""}
        ${hqProfileLine(data)}
        <div class="profile-stats">${stat(stats.ideas, "Ideas")}${stat(stats.upvotes, "Upvotes")}${stat(stats.building, "Building")}${stat(stats.shipped, "Shipped")}</div>
        ${own ? `<button class="btn btn-secondary btn-sm" data-edit-profile>${icon("pencil", 14)} Edit profile</button>` : `<div class="profile-actions" data-profile-actions></div>`}
      </header>
      <nav class="tabs">${[["ideas", "Ideas"], ["builds", "Builds"], ["boards", "Boards"], ["hq", "HQ"]]
        .map(([key, label]) => `<a class="tab ${tab === key ? "active" : ""}" href="#/u/${esc(user.username)}/${key}">${label}</a>`)
        .join("")}</nav>
      <div class="profile-body"></div>
    </div>`);
  view().replaceChildren(page);

  const editButton = $("[data-edit-profile]", page);
  if (editButton) {
    editButton.addEventListener("click", () => openEditProfile());
  }

  const actions = $("[data-profile-actions]", page);
  if (actions) hqProfileActions(actions, user.username);

  const body = $(".profile-body", page);
  if (tab === "hq") {
    hqRenderProfileTab(body, user.username);
    return;
  }
  if (tab === "boards") {
    renderBoardGrid(body, user, own);
    return;
  }
  const isIdeas = tab === "ideas";
  const masonry = new Masonry({
    fetchPage: (offset) => api("GET", `/api/ideas?${isIdeas ? "author" : "builder"}=${encodeURIComponent(user.username)}&sort=new&limit=30&offset=${offset}`),
    emptyHTML: isIdeas
      ? emptyState("lightbulb", own ? "You haven't posted an idea yet" : "No ideas yet", own ? "Every app starts as a one-liner. Post yours." : `${esc(user.display_name)} hasn't posted any ideas yet.`, own ? `<button class="btn btn-primary" data-action="new-idea">${icon("plus", 16)} Post an idea</button>` : "")
      : emptyState("hammer", own ? "You're not building anything yet" : "Not building anything yet", own ? "Find an idea you like and hit “I'm building this”." : `${esc(user.display_name)} hasn't claimed any ideas yet.`, own ? `<a class="btn btn-primary" href="#/?status=open">Browse ideas up for grabs</a>` : ""),
  });
  body.append(masonry.el);
  masonry.start();
}

function openEditProfile() {
  const me = state.me;
  const draft = { avatar_url: me.avatar_url || "" };
  let githubRow = "";
  if (me.github_login) {
    githubRow = `<div class="connected-row">${icon("github", 16)}<span>Connected to <a href="https://github.com/${encodeURIComponent(me.github_login)}" target="_blank" rel="noopener noreferrer">@${esc(me.github_login)}</a></span></div>`;
  } else if (state.config.github) {
    githubRow = `<a class="btn btn-secondary btn-block" href="${githubSignInHref()}">${icon("github", 16)} Connect your GitHub account</a>`;
  }
  const node = h(`<form novalidate>
      <header class="modal-head"><h2>Edit profile</h2><button type="button" class="icon-btn" data-close title="Close">${icon("x")}</button></header>
      <div class="modal-body">
        <div class="avatar-edit">
          <div class="avatar-edit-preview"></div>
          <div class="avatar-edit-actions">
            <div class="avatar-edit-buttons">
              <button type="button" class="btn btn-secondary btn-sm" data-avatar-upload>${icon("upload", 14)} <span>Upload photo</span></button>
              <button type="button" class="btn btn-ghost btn-sm" data-avatar-remove>Remove</button>
            </div>
            <div class="field-hint">Square images look best.</div>
            <input type="file" accept="${IMAGE_ACCEPT}" hidden data-avatar-file>
          </div>
        </div>
        <label class="field"><span class="field-label">Display name</span><input class="input" name="display_name" maxlength="40"></label>
        <label class="field"><span class="field-label">Bio</span><textarea class="textarea" name="bio" rows="3" maxlength="280" placeholder="What do you like to build?"></textarea></label>
        ${githubRow}
      </div>
      <footer class="modal-foot"><div class="form-error"></div><button type="button" class="btn btn-ghost" data-close>Cancel</button><button type="submit" class="btn btn-primary">Save</button></footer>
    </form>`);
  $('[name="display_name"]', node).value = me.display_name;
  $('[name="bio"]', node).value = me.bio || "";

  const preview = $(".avatar-edit-preview", node);
  const removeButton = $("[data-avatar-remove]", node);
  const renderAvatar = () => {
    preview.innerHTML = avatar({ ...me, display_name: $('[name="display_name"]', node).value || me.username, avatar_url: draft.avatar_url }, 72);
    removeButton.hidden = !draft.avatar_url;
  };
  renderAvatar();
  $('[name="display_name"]', node).addEventListener("input", renderAvatar);

  const uploadButton = $("[data-avatar-upload]", node);
  const fileInput = $("[data-avatar-file]", node);
  uploadButton.addEventListener("click", () => fileInput.click());
  removeButton.addEventListener("click", () => {
    draft.avatar_url = "";
    renderAvatar();
  });
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    uploadButton.disabled = true;
    $("span", uploadButton).textContent = "Uploading…";
    $(".form-error", node).textContent = "";
    try {
      draft.avatar_url = await uploadImage(file, { maxDim: 512 });
      renderAvatar();
    } catch (error) {
      $(".form-error", node).textContent = error.message;
    } finally {
      uploadButton.disabled = false;
      $("span", uploadButton).textContent = "Upload photo";
      fileInput.value = "";
    }
  });

  node.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $('[type="submit"]', node);
    submit.disabled = true;
    try {
      const result = await api("PATCH", "/api/me", {
        display_name: $('[name="display_name"]', node).value,
        bio: $('[name="bio"]', node).value,
        avatar_url: draft.avatar_url,
      });
      state.me = result.user;
      renderTopbarActions();
      invalidateFeed();
      closeModal({ force: true });
      toast("Profile updated");
      route();
    } catch (error) {
      $(".form-error", node).textContent = error.message;
      submit.disabled = false;
    }
  });
  openModal(node, { size: "sm" });
}

async function renderBoardGrid(container, user, own) {
  container.replaceChildren(pageLoading());
  try {
    const { boards } = await api("GET", `/api/boards?user=${encodeURIComponent(user.username)}`);
    const tiles = boards.map((board) => `<a class="board-tile" href="#/b/${board.id}">
        <div class="board-collage">${[0, 1, 2].map((index) => `<div class="collage-cell c${index}">${board.previews[index] ? miniCover(board.previews[index]) : ""}</div>`).join("")}</div>
        <div class="board-tile-name">${esc(board.name)}</div>
        <div class="board-tile-meta">${plural(board.item_count, "idea")}</div>
      </a>`);
    if (own) {
      tiles.unshift(`<button class="board-tile" data-new-board>
          <div class="board-collage new">${icon("plus", 30)}</div>
          <div class="board-tile-name">New board</div>
          <div class="board-tile-meta">Group ideas by theme</div>
        </button>`);
    }
    container.innerHTML = tiles.length
      ? `<div class="board-grid">${tiles.join("")}</div>`
      : emptyState("bookmark", "No boards yet", `${esc(user.display_name)} hasn't made any boards.`);
    const newBoard = $("[data-new-board]", container);
    if (newBoard) newBoard.addEventListener("click", () => openBoardForm());
  } catch (error) {
    container.replaceChildren(pageError(error));
  }
}

function openBoardForm(board = null) {
  formModal({
    title: board ? "Edit board" : "Create a board",
    submitLabel: board ? "Save" : "Create",
    fields: [
      { name: "name", label: "Name", value: board ? board.name : "", max: 40, placeholder: "e.g. Weekend builds" },
      { name: "description", label: "Description", value: board ? board.description : "", max: 200, multiline: true, placeholder: "Optional" },
    ],
    onSubmit: async (values) => {
      const result = board
        ? await api("PATCH", `/api/boards/${board.id}`, values)
        : await api("POST", "/api/boards", values);
      closeModal({ force: true });
      toast(board ? "Board updated" : "Board created");
      if (board) route();
      else location.hash = `#/b/${result.board.id}`;
    },
  });
}

async function renderBoard(id, isCurrent) {
  view().replaceChildren(pageLoading());
  let board;
  try {
    ({ board } = await api("GET", `/api/boards/${id}`));
  } catch (error) {
    if (isCurrent()) view().replaceChildren(pageError(error));
    return;
  }
  if (!isCurrent()) return;
  const own = state.me && state.me.id === board.owner.id;
  document.title = `${board.name} · shiphub`;
  const page = h(`<div class="container">
      <header class="board-head">
        <h1>${esc(board.name)}</h1>
        ${board.description ? `<p class="muted">${esc(board.description)}</p>` : ""}
        <div class="board-owner">${avatar(board.owner, 24)}<a href="#/u/${esc(board.owner.username)}/boards">${esc(board.owner.display_name)}</a><span>· ${plural(board.item_count, "idea")}</span></div>
        ${own ? `<div class="board-head-actions">
            <button class="btn btn-secondary btn-sm" data-board-edit>${icon("pencil", 14)} Edit</button>
            <button class="btn btn-ghost btn-sm btn-danger-text" data-board-delete>${icon("trash", 14)} Delete</button>
          </div>` : ""}
      </header>
    </div>`);
  const masonry = new Masonry({
    fetchPage: (offset) => api("GET", `/api/ideas?board=${board.id}&sort=saved&limit=30&offset=${offset}`),
    emptyHTML: emptyState("bookmark", "This board is empty", own ? "Hit Save on any idea to pin it here." : "Nothing pinned yet.", own ? `<a class="btn btn-primary" href="#/">Explore ideas</a>` : ""),
  });
  page.append(masonry.el);
  view().replaceChildren(page);
  masonry.start();

  if (own) {
    $("[data-board-edit]", page).addEventListener("click", () => openBoardForm(board));
    $("[data-board-delete]", page).addEventListener("click", async () => {
      const confirmed = await confirmDialog({
        title: `Delete “${board.name}”?`,
        message: "The ideas stay on shiphub; only this board is removed.",
        confirmLabel: "Delete board",
        danger: true,
      });
      if (!confirmed) return;
      try {
        await api("DELETE", `/api/boards/${board.id}`);
        invalidateFeed();
        toast("Board deleted");
        location.hash = `#/u/${board.owner.username}/boards`;
      } catch (error) {
        handleError(error);
      }
    });
  }
}

/* ==========================================================================
   Popovers: board picker, notifications, user menu
   ========================================================================== */

function openPopover(content, anchor, { align = "right" } = {}) {
  if (state.popover && state.popover.anchor === anchor) {
    closePopover();
    return null;
  }
  closePopover();
  const pop = h(`<div class="popover" role="dialog"></div>`);
  pop.append(content);
  document.body.append(pop);
  state.popover = { pop, anchor, align };
  const pin = anchor.closest(".pin");
  if (pin) pin.classList.add("pin-active");
  repositionPopover();
  requestAnimationFrame(() => pop.classList.add("open"));
  return pop;
}

function repositionPopover() {
  if (!state.popover) return;
  const { pop, anchor, align } = state.popover;
  const rect = anchor.getBoundingClientRect();
  const popRect = pop.getBoundingClientRect();
  let left = align === "right" ? rect.right - popRect.width : rect.left;
  left = Math.max(8, Math.min(left, window.innerWidth - popRect.width - 8));
  let top = rect.bottom + 8;
  if (top + popRect.height > window.innerHeight - 8 && rect.top - popRect.height - 8 > 8) {
    top = rect.top - popRect.height - 8;
  }
  pop.style.left = `${left + window.scrollX}px`;
  pop.style.top = `${top + window.scrollY}px`;
}

function closePopover() {
  if (!state.popover) return;
  const { pop, anchor } = state.popover;
  state.popover = null;
  const pin = anchor.closest(".pin");
  if (pin) pin.classList.remove("pin-active");
  pop.classList.remove("open");
  setTimeout(() => pop.remove(), 150);
}

function boardThumb(board) {
  const preview = board.previews[0];
  return `<span class="board-thumb">${preview ? miniCover(preview) : icon("bookmark", 18)}</span>`;
}

async function openBoardPicker(ideaId, anchor) {
  if (!requireAuth()) return;
  const node = h(`<div class="board-picker">
      <div class="popover-head">Save to board</div>
      <div class="board-list"><div class="spinner"></div></div>
      <form class="board-new"><input class="input input-sm" name="name" placeholder="Create a new board…" maxlength="40" autocomplete="off"><button class="btn btn-primary btn-sm" type="submit">Create</button></form>
    </div>`);
  if (!openPopover(node, anchor)) return;
  const list = $(".board-list", node);

  const renderList = (boards) => {
    list.innerHTML = boards.length
      ? boards.map((board) => `<button type="button" class="board-option ${board.contains ? "checked" : ""}" data-board="${board.id}" data-name="${esc(board.name)}">
            ${boardThumb(board)}
            <span class="board-option-text"><span class="board-option-name">${esc(board.name)}</span><span class="board-option-meta" data-count="${board.item_count}">${plural(board.item_count, "idea")}</span></span>
            <span class="board-check">${icon("check", 15)}</span>
          </button>`).join("")
      : `<div class="popover-empty">No boards yet. Create your first one below.</div>`;
    repositionPopover();
  };
  const load = async () => renderList((await api("GET", `/api/boards?idea=${ideaId}`)).boards);

  try {
    await load();
  } catch (error) {
    closePopover();
    handleError(error);
    return;
  }

  list.addEventListener("click", async (event) => {
    const option = event.target.closest(".board-option");
    if (!option) return;
    try {
      const result = await api("POST", `/api/boards/${option.dataset.board}/items`, { idea_id: ideaId });
      option.classList.toggle("checked", result.contains);
      const meta = $(".board-option-meta", option);
      const count = Number(meta.dataset.count) + (result.contains ? 1 : -1);
      meta.dataset.count = count;
      meta.textContent = plural(count, "idea");
      syncSaved(ideaId, result.saved);
      toast(result.contains ? `Saved to ${option.dataset.name}` : `Removed from ${option.dataset.name}`);
    } catch (error) {
      handleError(error);
    }
  });

  $(".board-new", node).addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("input", event.target);
    const name = input.value.trim();
    if (!name) {
      input.focus();
      return;
    }
    try {
      await api("POST", "/api/boards", { name, idea_id: ideaId });
      input.value = "";
      await load();
      syncSaved(ideaId, true);
      toast(`Saved to ${name}`);
    } catch (error) {
      handleError(error);
    }
  });
}

function notificationText(item) {
  if (item.kind === "hq") return esc(item.text);
  const who = `<strong>${esc(item.actor.display_name)}</strong>`;
  const what = `<strong>${esc(item.idea_title || "an idea")}</strong>`;
  switch (item.kind) {
    case "comment":
      return `${who} commented on ${what}`;
    case "reply":
      return `${who} replied to your comment on ${what}`;
    case "build":
      return `${who} is building ${what}`;
    case "shipped":
      return `${who} shipped ${what} 🚀`;
    case "fork":
      return `${who} forked your idea into ${what}`;
    default:
      return `${who} interacted with ${what}`;
  }
}

async function openNotifications(anchor) {
  const node = h(`<div class="notif-panel"><div class="popover-head">Notifications</div><div class="notif-list"><div class="spinner"></div></div></div>`);
  if (!openPopover(node, anchor)) return;
  try {
    const { items } = await api("GET", "/api/notifications");
    $(".notif-list", node).innerHTML = items.length
      ? items.map((item) => `<a class="notif ${item.is_read ? "" : "unread"}" href="${item.kind === "hq" ? `#/${esc(item.link || "hq")}` : `#/i/${item.idea_id}`}">${avatar(item.actor, 34)}<div><div>${notificationText(item)}</div><div class="notif-time">${timeAgo(item.created_at)}</div></div></a>`).join("")
      : `<div class="popover-empty">You're all caught up. Replies, builders, forks, friends, chats, agents and sales show up here.</div>`;
    repositionPopover();
    if (state.unread) {
      await api("POST", "/api/notifications/read");
      setUnread(0);
    }
  } catch (error) {
    handleError(error);
  }
}

function openUserMenu(anchor) {
  const me = state.me;
  const dark = currentTheme() === "dark";
  const menu = h(`<div class="menu">
      <a class="menu-user" href="#/u/${esc(me.username)}">${avatar(me, 40)}<div><strong>${esc(me.display_name)}</strong><span>@${esc(me.username)}</span></div></a>
      <div class="menu-sep"></div>
      <a class="menu-item" href="#/u/${esc(me.username)}">${icon("user", 16)} Your ideas</a>
      <a class="menu-item" href="#/u/${esc(me.username)}/builds">${icon("hammer", 16)} Your builds</a>
      <a class="menu-item" href="#/u/${esc(me.username)}/boards">${icon("grid", 16)} Your boards</a>
      <a class="menu-item" href="#/hq/agents">${icon("cpu", 16)} Your devices &amp; agents</a>
      <a class="menu-item" href="#/hq/settings">${icon("settings", 16)} HQ settings</a>
      <div class="menu-sep"></div>
      <button class="menu-item" data-action="toggle-theme">${icon(dark ? "sun" : "moon", 16)} ${dark ? "Light" : "Dark"} mode</button>
      <button class="menu-item" data-action="new-idea">${icon("plus", 16)} New idea <kbd>N</kbd></button>
      <div class="menu-sep"></div>
      <button class="menu-item danger" data-action="logout">${icon("logout", 16)} Log out</button>
    </div>`);
  openPopover(menu, anchor);
}

/* ==========================================================================
   Modals
   ========================================================================== */

function openModal(content, { size = "md", onClose = null, beforeClose = null } = {}) {
  closeModal({ force: true });
  closePopover();
  const overlay = h(`<div class="modal-overlay"><div class="modal modal-${size}" role="dialog" aria-modal="true"></div></div>`);
  overlay.firstElementChild.append(content);
  overlay.addEventListener("mousedown", (event) => {
    if (event.target === overlay) closeModal();
  });
  overlay.addEventListener("click", (event) => {
    if (event.target.closest("[data-close]")) {
      event.preventDefault();
      closeModal();
    }
  });
  document.body.append(overlay);
  document.body.classList.add("no-scroll");
  requestAnimationFrame(() => overlay.classList.add("open"));
  state.modal = { overlay, onClose, beforeClose };
  const focusTarget = content.querySelector("[autofocus], input:not([type=hidden]), textarea");
  if (focusTarget) setTimeout(() => focusTarget.focus(), 60);
}

function closeModal({ force = false } = {}) {
  const modal = state.modal;
  if (!modal) return true;
  if (!force && modal.beforeClose && !modal.beforeClose()) return false;
  state.modal = null;
  modal.overlay.classList.remove("open");
  setTimeout(() => modal.overlay.remove(), 180);
  document.body.classList.remove("no-scroll");
  if (modal.onClose) modal.onClose();
  return true;
}

function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    let answered = false;
    const node = h(`<div>
        <div class="modal-body"><h2 class="confirm-title">${esc(title)}</h2><p class="muted">${esc(message)}</p></div>
        <footer class="modal-foot">
          <button type="button" class="btn btn-ghost" data-answer="no">Cancel</button>
          <button type="button" class="btn ${danger ? "btn-danger" : "btn-primary"}" data-answer="yes">${esc(confirmLabel)}</button>
        </footer>
      </div>`);
    node.addEventListener("click", (event) => {
      const button = event.target.closest("[data-answer]");
      if (!button) return;
      answered = true;
      closeModal({ force: true });
      resolve(button.dataset.answer === "yes");
    });
    openModal(node, {
      size: "sm",
      onClose: () => {
        if (!answered) resolve(false);
      },
    });
    setTimeout(() => $('[data-answer="yes"]', node).focus(), 60);
  });
}

function formModal({ title, fields, submitLabel, onSubmit }) {
  const node = h(`<form novalidate>
      <header class="modal-head"><h2>${esc(title)}</h2><button type="button" class="icon-btn" data-close title="Close">${icon("x")}</button></header>
      <div class="modal-body">${fields
        .map((field) => `<label class="field"><span class="field-label">${esc(field.label)}</span>${field.multiline
          ? `<textarea class="textarea" name="${field.name}" rows="3" maxlength="${field.max}" placeholder="${esc(field.placeholder || "")}">${esc(field.value || "")}</textarea>`
          : `<input class="input" name="${field.name}" maxlength="${field.max}" placeholder="${esc(field.placeholder || "")}" value="${esc(field.value || "")}">`}</label>`)
        .join("")}</div>
      <footer class="modal-foot"><div class="form-error"></div><button type="button" class="btn btn-ghost" data-close>Cancel</button><button type="submit" class="btn btn-primary">${esc(submitLabel)}</button></footer>
    </form>`);
  node.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $('[type="submit"]', node);
    submit.disabled = true;
    try {
      await onSubmit(Object.fromEntries(new FormData(node)));
    } catch (error) {
      $(".form-error", node).textContent = error.message;
      submit.disabled = false;
    }
  });
  openModal(node, { size: "sm" });
}

/* ----- Auth ----- */

function openAuth(mode = "login") {
  const node = h(`<div class="auth" data-mode="${mode}">
      <div class="auth-top"><span class="brand"><span class="brand-icon">${icon("rocket", 20)}</span><span>ship<b>hub</b></span></span><button type="button" class="icon-btn" data-close title="Close">${icon("x")}</button></div>
      <div>
        <h2 data-title></h2>
        <p class="muted" data-subtitle></p>
      </div>
      ${state.config.github ? `<a class="btn btn-github btn-lg btn-block" href="${githubSignInHref()}" data-github>${icon("github", 18)} Continue with GitHub</a><div class="divider">or use a password</div>` : ""}
      <form novalidate>
        <label class="field signup-only"><span class="field-label">Display name</span><input class="input" name="display_name" maxlength="40" placeholder="Ada Lovelace" autocomplete="name"></label>
        <label class="field"><span class="field-label">Username</span><input class="input" name="username" maxlength="20" placeholder="ada" autocomplete="username" required></label>
        <label class="field"><span class="field-label">Password</span><input class="input" name="password" type="password" maxlength="128" placeholder="At least 8 characters" required></label>
        <div class="form-error"></div>
        <button class="btn btn-primary btn-lg btn-block" type="submit" data-submit></button>
      </form>
      ${state.config.demo ? `<div class="divider">or</div>
      <button class="btn btn-secondary btn-block" type="button" data-demo>${icon("sparkles", 16)} Continue with the demo account</button>` : ""}
      <p class="auth-switch" data-switch></p>
    </div>`);

  const setMode = (next) => {
    node.dataset.mode = next;
    const login = next === "login";
    $("[data-title]", node).textContent = login ? "Welcome back" : "Join shiphub";
    $("[data-subtitle]", node).textContent = login
      ? "Log in to save, vote, discuss and claim ideas."
      : "Post ideas, build in public, and ship with others.";
    $("[data-submit]", node).textContent = login ? "Log in" : "Create account";
    $("[data-switch]", node).innerHTML = login
      ? `New here? <button type="button" data-mode-switch="signup">Create an account</button>`
      : `Already have an account? <button type="button" data-mode-switch="login">Log in</button>`;
    $('[name="password"]', node).autocomplete = login ? "current-password" : "new-password";
    $(".form-error", node).textContent = "";
  };
  setMode(mode);

  const submitAuth = async (path, values) => {
    const result = await api("POST", path, values);
    state.me = result.user;
    setUnread(result.unread || 0);
    renderTopbarActions();
    invalidateFeed();
    closeModal({ force: true });
    toast(`Welcome, ${result.user.display_name}!`);
    startPolling();
    route();
  };

  node.addEventListener("click", async (event) => {
    const switcher = event.target.closest("[data-mode-switch]");
    if (switcher) setMode(switcher.dataset.modeSwitch);
    if (event.target.closest("[data-demo]")) {
      try {
        await submitAuth("/api/auth/login", { username: "demo", password: "demo1234" });
      } catch (error) {
        $(".form-error", node).textContent = error.message;
      }
    }
  });

  $("form", node).addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.target));
    const button = $("[data-submit]", node);
    button.disabled = true;
    try {
      if (node.dataset.mode === "signup") await submitAuth("/api/auth/signup", values);
      else await submitAuth("/api/auth/login", { username: values.username, password: values.password });
    } catch (error) {
      $(".form-error", node).textContent = error.message;
      button.disabled = false;
    }
  });

  openModal(node, { size: "sm" });
  setTimeout(() => $(mode === "signup" ? '[name="display_name"]' : '[name="username"]', node).focus(), 60);
}

async function logout() {
  try {
    await api("POST", "/api/auth/logout");
  } catch {
    /* the cookie is cleared either way */
  }
  state.me = null;
  setUnread(0);
  clearInterval(state.pollTimer);
  closePopover();
  renderTopbarActions();
  invalidateFeed();
  toast("Logged out");
  route();
}

/* ----- Composer ----- */

function openComposer({ idea = null, fork = null, onSaved = null } = {}) {
  if (!requireAuth()) return;
  const source = idea || fork;
  const draft = {
    title: source ? source.title : "",
    pitch: source ? source.pitch : "",
    body: source ? source.body || "" : "",
    stack: source ? source.stack : "",
    scope: source ? source.scope : 0,
    cover_style: source ? source.cover_style : Math.floor(Math.random() * COVERS.length),
    cover_image: source ? source.cover_image : "",
    tags: source ? [...source.tags] : [],
  };
  const initial = JSON.stringify(draft);
  const heading = idea ? "Edit idea" : fork ? "Fork this idea" : "Post an idea";
  const submitLabel = idea ? "Save changes" : fork ? "Publish fork" : "Publish idea";

  const node = h(`<form class="composer" novalidate>
      <header class="modal-head"><h2>${heading}</h2><button type="button" class="icon-btn" data-close title="Close">${icon("x")}</button></header>
      ${fork ? `<div class="fork-banner">${icon("fork", 16)}<span>Forking <strong>${esc(fork.title)}</strong> by @${esc(fork.author.username)}. Change the angle, audience or stack to make it yours.</span></div>` : ""}
      <div class="composer-body">
        <div class="composer-fields">
          <label class="field"><span class="field-label">Title <span class="counter" data-counter="title"></span></span><input class="input input-lg" name="title" maxlength="80" placeholder="e.g. Fridge Roulette"></label>
          <label class="field"><span class="field-label">Pitch <span class="counter" data-counter="pitch"></span></span><textarea class="textarea" name="pitch" rows="2" maxlength="200" placeholder="One or two sentences. This is what shows on the card."></textarea></label>
          <div class="field">
            <div class="field-label">Details <span class="field-hint">optional</span><span class="md-tabs"><button type="button" class="active" data-md="write">Write</button><button type="button" data-md="preview">Preview</button></span></div>
            <textarea class="textarea mono" name="body" rows="7" maxlength="5000" placeholder="### Core features&#10;- …&#10;&#10;### The twist&#10;What makes it different? Markdown supported."></textarea>
            <div class="prose md-preview" hidden></div>
          </div>
          <div class="field"><span class="field-label">Tags <span class="field-hint">up to 6 · Enter to add</span></span><div class="chip-input"><input placeholder="ai, mobile, devtools…" maxlength="24" aria-label="Add tag"></div></div>
          <div class="field-row">
            <div class="field"><span class="field-label">Scope</span><div class="seg seg-full" data-scope>${SCOPES.map((label, index) => `<button type="button" data-value="${index}">${label}</button>`).join("")}</div></div>
            <label class="field"><span class="field-label">Suggested stack</span><input class="input" name="stack" maxlength="80" placeholder="Next.js · Supabase"></label>
          </div>
          <div class="field">
            <span class="field-label">Cover</span>
            <div class="swatches">${COVERS.map((cover, index) => `<button type="button" class="swatch" data-swatch="${index}" style="background:${cover}" aria-label="Cover ${index + 1}"></button>`).join("")}</div>
            <div class="cover-upload">
              <button type="button" class="btn btn-secondary" data-upload-cover>${icon("upload", 16)} <span>Upload image</span></button>
              <input class="input" name="cover_image" type="text" inputmode="url" maxlength="300" placeholder="…or paste an image link" aria-label="Image link">
              <input type="file" accept="${IMAGE_ACCEPT}" hidden data-cover-file>
            </div>
            <div class="cover-current" hidden><img alt=""><span>Custom cover</span><button type="button" class="btn btn-ghost btn-sm" data-clear-cover>${icon("x", 14)} Remove</button></div>
            <div class="field-hint">You can also drop or paste an image here. PNG, JPEG, GIF or WebP.</div>
          </div>
        </div>
        <aside class="composer-preview"><div class="preview-label">Live preview</div><div class="preview-slot"></div></aside>
      </div>
      <footer class="modal-foot"><div class="form-error"></div><button type="button" class="btn btn-ghost" data-close>Cancel</button><button type="submit" class="btn btn-primary">${submitLabel}</button></footer>
    </form>`);

  for (const name of ["title", "pitch", "body", "stack"]) {
    $(`[name="${name}"]`, node).value = draft[name];
  }
  $('[name="cover_image"]', node).value = /^https?:\/\//i.test(draft.cover_image) ? draft.cover_image : "";

  const chipBox = $(".chip-input", node);
  const chipInput = $("input", chipBox);
  const previewSlot = $(".preview-slot", node);

  const renderChips = () => {
    $$(".tag-chip", chipBox).forEach((chip) => chip.remove());
    draft.tags.forEach((tag, index) => {
      chipInput.before(h(`<span class="tag-chip">#${esc(tag)}<button type="button" data-remove-tag="${index}" aria-label="Remove ${esc(tag)}">${icon("x", 12)}</button></span>`));
    });
    chipInput.placeholder = draft.tags.length >= 6 ? "" : draft.tags.length ? "Add another…" : "ai, mobile, devtools…";
  };

  const renderPreview = () => {
    const card = ideaCard({
      id: idea ? idea.id : 3,
      title: draft.title || "Your idea title",
      pitch: draft.pitch || "Your one-line pitch shows up right here on the cover.",
      tags: draft.tags,
      scope: draft.scope,
      cover_style: draft.cover_style,
      cover_image: IMAGE_REF.test(draft.cover_image) ? draft.cover_image : "",
      forked_from: fork ? fork.id : idea ? idea.forked_from : null,
      author: state.me,
      votes: idea ? idea.votes : 1,
      comment_count: idea ? idea.comment_count : 0,
      voted: true,
      saved: false,
      status: idea ? idea.status : "open",
    });
    card.classList.add("pin-preview");
    $$("[data-action]", card).forEach((el) => el.removeAttribute("data-action"));
    $$("a[href]", card).forEach((el) => el.removeAttribute("href"));
    previewSlot.replaceChildren(card);
  };

  const renderControls = () => {
    $$("[data-swatch]", node).forEach((swatch) => swatch.classList.toggle("active", Number(swatch.dataset.swatch) === draft.cover_style && !draft.cover_image));
    const hasImage = IMAGE_REF.test(draft.cover_image);
    const current = $(".cover-current", node);
    current.hidden = !hasImage;
    if (hasImage && $("img", current).getAttribute("src") !== draft.cover_image) {
      $("img", current).src = draft.cover_image;
    }
    $$("[data-scope] button", node).forEach((button) => button.classList.toggle("active", Number(button.dataset.value) === draft.scope));
    $('[data-counter="title"]', node).textContent = `${draft.title.length}/80`;
    $('[data-counter="pitch"]', node).textContent = `${draft.pitch.length}/200`;
  };

  const update = () => {
    renderControls();
    renderPreview();
  };

  const addTag = (raw) => {
    raw.split(",").forEach((part) => {
      const tag = normalizeTag(part);
      if (tag && !draft.tags.includes(tag) && draft.tags.length < 6) draft.tags.push(tag);
    });
    chipInput.value = "";
    renderChips();
    update();
  };

  node.addEventListener("input", (event) => {
    const name = event.target.name;
    if (name && name in draft && typeof draft[name] === "string") {
      draft[name] = event.target.value;
      update();
    }
    if (event.target === chipInput && chipInput.value.includes(",")) addTag(chipInput.value);
  });

  chipInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addTag(chipInput.value);
    } else if (event.key === "Backspace" && !chipInput.value && draft.tags.length) {
      draft.tags.pop();
      renderChips();
      update();
    }
  });
  chipInput.addEventListener("blur", () => {
    if (chipInput.value.trim()) addTag(chipInput.value);
  });

  node.addEventListener("click", (event) => {
    if (event.target === chipBox) chipInput.focus();
    const removeTag = event.target.closest("[data-remove-tag]");
    if (removeTag) {
      draft.tags.splice(Number(removeTag.dataset.removeTag), 1);
      renderChips();
      update();
    }
    const swatch = event.target.closest("[data-swatch]");
    if (swatch) {
      draft.cover_style = Number(swatch.dataset.swatch);
      draft.cover_image = "";
      $('[name="cover_image"]', node).value = "";
      update();
    }
    const scope = event.target.closest("[data-scope] button");
    if (scope) {
      draft.scope = Number(scope.dataset.value);
      update();
    }
    const mdTab = event.target.closest("[data-md]");
    if (mdTab) {
      const preview = mdTab.dataset.md === "preview";
      $$("[data-md]", node).forEach((tab) => tab.classList.toggle("active", tab === mdTab));
      $('[name="body"]', node).hidden = preview;
      const previewEl = $(".md-preview", node);
      previewEl.hidden = !preview;
      previewEl.innerHTML = draft.body.trim() ? markdown(draft.body) : `<p class="muted">Nothing to preview yet.</p>`;
    }
  });

  const uploadButton = $("[data-upload-cover]", node);
  const coverFileInput = $("[data-cover-file]", node);
  const useCoverFile = async (file) => {
    if (!file || uploadButton.disabled) return;
    const errorEl = $(".form-error", node);
    errorEl.textContent = "";
    uploadButton.disabled = true;
    $("span", uploadButton).textContent = "Uploading…";
    try {
      draft.cover_image = await uploadImage(file);
      $('[name="cover_image"]', node).value = "";
      update();
    } catch (error) {
      errorEl.textContent = error.message;
    } finally {
      uploadButton.disabled = false;
      $("span", uploadButton).textContent = "Upload image";
      coverFileInput.value = "";
    }
  };
  uploadButton.addEventListener("click", () => coverFileInput.click());
  coverFileInput.addEventListener("change", () => useCoverFile(coverFileInput.files[0]));
  $("[data-clear-cover]", node).addEventListener("click", () => {
    draft.cover_image = "";
    $('[name="cover_image"]', node).value = "";
    update();
  });
  node.addEventListener("dragover", (event) => {
    if ([...(event.dataTransfer?.types || [])].includes("Files")) {
      event.preventDefault();
      node.classList.add("is-dragging");
    }
  });
  node.addEventListener("dragleave", (event) => {
    if (!node.contains(event.relatedTarget)) node.classList.remove("is-dragging");
  });
  node.addEventListener("drop", (event) => {
    const file = firstImageFile(event.dataTransfer?.files);
    node.classList.remove("is-dragging");
    if (!file) return;
    event.preventDefault();
    useCoverFile(file);
  });
  node.addEventListener("paste", (event) => {
    const file = firstImageFile(event.clipboardData?.files);
    if (!file) return;
    event.preventDefault();
    useCoverFile(file);
  });

  node.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (chipInput.value.trim()) addTag(chipInput.value);
    const errorEl = $(".form-error", node);
    if (draft.title.trim().length < 3) {
      errorEl.textContent = "Give it a title (at least 3 characters).";
      $('[name="title"]', node).focus();
      return;
    }
    if (draft.pitch.trim().length < 10) {
      errorEl.textContent = "Write a pitch of at least 10 characters.";
      $('[name="pitch"]', node).focus();
      return;
    }
    const submit = $('[type="submit"]', node);
    submit.disabled = true;
    errorEl.textContent = "";
    const payload = { ...draft };
    if (fork) payload.forked_from = fork.id;
    try {
      const result = idea
        ? await api("PATCH", `/api/ideas/${idea.id}`, payload)
        : await api("POST", "/api/ideas", payload);
      invalidateFeed();
      closeModal({ force: true });
      if (idea) {
        toast("Idea updated");
        if (onSaved) onSaved(result);
      } else {
        toast(fork ? "Fork published" : "Idea published");
        location.hash = `#/i/${result.idea.id}`;
      }
    } catch (error) {
      errorEl.textContent = error.message;
      submit.disabled = false;
    }
  });

  renderChips();
  update();
  openModal(node, {
    size: "lg",
    beforeClose: () => JSON.stringify(draft) === initial || window.confirm("Discard this draft?"),
  });
}

/* ==========================================================================
   Top bar
   ========================================================================== */

function renderTopbarActions() {
  const box = $("#topbar-actions");
  const themeIcon = currentTheme() === "dark" ? "sun" : "moon";
  if (!state.me) {
    box.innerHTML = `
      <button class="icon-btn" data-action="inspire" title="Inspire me (random idea)">${icon("shuffle")}</button>
      <button class="icon-btn" data-action="toggle-theme" title="Toggle theme">${icon(themeIcon)}</button>
      <button class="btn btn-ghost" data-action="login">Log in</button>
      <button class="btn btn-primary" data-action="signup">Sign up</button>`;
    return;
  }
  box.innerHTML = `
    <button class="icon-btn" data-action="inspire" title="Inspire me (random idea)">${icon("shuffle")}</button>
    <button class="btn btn-primary" data-action="new-idea" title="New idea (N)">${icon("plus", 16)}<span class="hide-sm">New idea</span></button>
    <button class="icon-btn" data-action="notifications" title="Notifications" data-bell>${icon("bell")}</button>
    <button class="avatar-btn" data-action="user-menu" title="Account">${avatar(state.me, 34)}</button>`;
  setUnread(state.unread);
}

function setUnread(count) {
  state.unread = count;
  const bell = $("[data-bell]");
  if (!bell) return;
  const existing = $(".dot-badge", bell);
  if (existing) existing.remove();
  if (count > 0) bell.append(h(`<span class="dot-badge">${count > 9 ? "9+" : count}</span>`));
}

function startPolling() {
  clearInterval(state.pollTimer);
  if (!state.me) return;
  state.pollTimer = setInterval(async () => {
    if (document.hidden || !state.me) return;
    try {
      const result = await api("GET", "/api/me");
      if (!result.user) {
        state.me = null;
        renderTopbarActions();
        return;
      }
      if (result.unread !== state.unread) setUnread(result.unread);
    } catch {
      /* offline; try again next tick */
    }
  }, 30000);
}

async function inspire() {
  const { id } = await api("GET", "/api/random");
  location.hash = `#/i/${id}`;
}

async function copyPromptFor(id) {
  const data = await api("GET", `/api/ideas/${id}`);
  await copyText(buildPrompt(data.idea, data.comments));
  toast("Prompt copied. Paste it into your AI coding tool");
}

async function toggleIdeaVote(id) {
  if (!requireAuth()) return;
  const result = await api("POST", `/api/ideas/${id}/vote`);
  syncVote(id, result.voted, result.votes);
}

const ACTIONS = {
  vote: (el) => toggleIdeaVote(Number(el.dataset.id)),
  save: (el) => openBoardPicker(Number(el.dataset.id), el),
  "copy-prompt": (el) => copyPromptFor(Number(el.dataset.id)),
  "new-idea": () => {
    closePopover();
    openComposer();
  },
  inspire: () => inspire(),
  login: () => openAuth("login"),
  signup: () => openAuth("signup"),
  "toggle-theme": () => toggleTheme(),
  logout: () => logout(),
  notifications: (el) => openNotifications(el),
  "user-menu": (el) => openUserMenu(el),
};

/* ==========================================================================
   Global events + boot
   ========================================================================== */

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const handler = ACTIONS[target.dataset.action];
  if (!handler) return;
  event.preventDefault();
  event.stopPropagation();
  try {
    await handler(target, event);
  } catch (error) {
    handleError(error);
  }
});

document.addEventListener("mousedown", (event) => {
  if (!state.popover) return;
  const { pop, anchor } = state.popover;
  if (!pop.contains(event.target) && !anchor.contains(event.target)) closePopover();
});

document.addEventListener("click", (event) => {
  if (state.popover && event.target.closest(".popover a[href]")) closePopover();
});

window.addEventListener("resize", debounce(repositionPopover, 50));

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    if (state.popover) closePopover();
    else if (state.modal) closeModal();
    return;
  }
  const typing = event.target.closest("input, textarea, select, [contenteditable]");
  if (typing || event.metaKey || event.ctrlKey || event.altKey || state.modal) return;
  if (event.key === "/") {
    event.preventDefault();
    $("#search-input").focus();
  } else if (event.key.toLowerCase() === "n" && state.me) {
    event.preventDefault();
    openComposer();
  }
});

function setupSearch() {
  const form = $(".search");
  const input = $("#search-input");
  const go = (replace) => {
    const { path, params } = parseHash();
    const base = path === "/" ? params : new URLSearchParams();
    const href = feedHref(base, { q: input.value.trim() || null });
    if (href === (location.hash || "#/")) return;
    if (replace && path === "/") location.replace(href);
    else location.hash = href;
  };
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    go(false);
    input.blur();
  });
  input.addEventListener("input", debounce(() => go(true), 350));
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      input.value = "";
      input.blur();
      go(true);
    }
  });
}

function setFavicon() {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#e5484d" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS.rocket}</svg>`;
  const link = document.createElement("link");
  link.rel = "icon";
  link.href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  document.head.append(link);
}

/* After GitHub sign-in the server redirects to /?auth=… or /?auth_error=… */
function handleAuthRedirect() {
  const params = new URLSearchParams(location.search);
  const outcome = params.get("auth");
  const error = params.get("auth_error");
  if (!outcome && !error) return;
  history.replaceState(null, "", location.pathname + location.hash);
  if (error) {
    toast(error, "error");
  } else if (outcome === "linked") {
    toast("GitHub account connected");
  } else if (state.me && outcome === "signup") {
    toast(`Welcome to shiphub, ${state.me.display_name}!`);
  } else if (state.me) {
    toast(`Welcome back, ${state.me.display_name}!`);
  }
}

async function boot() {
  hqEnsureIcons();
  $(".brand-icon").innerHTML = icon("rocket", 22);
  $(".search-icon").innerHTML = icon("search", 18);
  setFavicon();
  setupSearch();
  const [meResult, configResult] = await Promise.allSettled([api("GET", "/api/me"), api("GET", "/api/config")]);
  if (configResult.status === "fulfilled") {
    state.config = { ...state.config, ...configResult.value };
  }
  if (meResult.status === "fulfilled") {
    state.me = meResult.value.user;
    state.unread = meResult.value.unread;
  }
  handleAuthRedirect();
  renderTopbarActions();
  startPolling();
  window.addEventListener("hashchange", route);
  route();
}

boot();
