"use strict";

/* ==========================================================================
   HQ: agents, feed, ladder, friends, chat and market - part of shiphub.
   Loaded after app.js and uses its helpers (h, $, $$, esc, api, icon, avatar,
   toast, view, state, openModal, closeModal, handleError, requireAuth, timeAgo).
   ========================================================================== */

const HQ_ICONS = {
  cpu: '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2M15 20v2M2 15h2M2 9h2M20 15h2M20 9h2M9 2v2M9 20v2"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  bag: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  trophy: '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z"/>',
  heart: '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  userPlus: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/>',
};

/* hq.js loads before app.js (so the router can always find renderHQ); app.js calls this on boot. */
function hqEnsureIcons() {
  if (!ICONS.cpu) Object.assign(ICONS, HQ_ICONS);
}

const HQ_TABS = [
  ["feed", "Feed", "zap"],
  ["ladder", "Ladder", "trophy"],
  ["agents", "Agents", "cpu"],
  ["chat", "Chat", "message"],
  ["market", "Market", "bag"],
  ["friends", "Friends", "users"],
  ["settings", "Settings", "settings"],
];
const HQ_PUBLIC_TABS = new Set(["feed", "ladder", "market"]);
const HQ_POST_KINDS = [["", "All"], ["ship", "🚀 Ships"], ["tip", "💡 Tips"], ["news", "📰 News"], ["post", "💬 Posts"]];
const HQ_PRODUCT_KINDS = ["template", "prompt", "agent", "mcp", "app", "course", "other"];
const COMMAND_LABELS = { ping: "Ping", sysinfo: "System info", list_agents: "List agents", agent_task: "Agent task", shell: "Shell" };

const hq = {
  config: null,
  me: null,
  rank: null,
  stream: null,
  tab: "feed",
  feedKind: "",
  feedScope: "global",
  ladderScope: "global",
  ladderPeriod: "all",
  marketKind: "",
  deviceId: null,
  chatChannel: "world",
  body: null,
};

/* ----- small helpers ------------------------------------------------------ */

function hqMoney(cents) {
  const currency = ((hq.config && hq.config.currency) || "usd").toUpperCase();
  if (!cents) return "Free";
  return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(cents / 100);
}

function tierBadge(tier) {
  return tier ? `<span class="tier tier-${esc(String(tier).toLowerCase())}">${esc(tier)}</span>` : "";
}

function personLink(person, size = 32) {
  return `<a class="hq-person" href="#/u/${esc(person.username)}">${avatar(person, size)}<span><strong>${esc(person.display_name || person.username)}</strong><span class="muted">@${esc(person.username)}</span></span></a>`;
}

function flag(country) {
  if (!country || !/^[A-Z]{2}$/.test(country)) return "";
  return String.fromCodePoint(...[...country].map((char) => 127397 + char.charCodeAt(0)));
}

function xpBar(me) {
  if (!me) return "";
  const span = me.next_tier_xp ? me.next_tier_xp - me.tier_floor : 1;
  const progress = me.next_tier_xp ? Math.min(100, ((me.xp - me.tier_floor) / span) * 100) : 100;
  const next = me.next_tier ? `${me.next_tier_xp - me.xp} XP to ${esc(me.next_tier)}` : "Top tier";
  return `<div class="xp"><div class="xp-top">${tierBadge(me.tier)}<span>Level ${me.level} · ${me.xp.toLocaleString()} XP</span><span class="muted">${next}</span></div><div class="xp-bar"><span style="width:${progress.toFixed(1)}%"></span></div></div>`;
}

async function hqLoadBasics() {
  if (!hq.config) {
    hq.config = await api("GET", "/api/hq/config").catch(() => ({ payments: "demo", currency: "usd", fee_percent: 10 }));
  }
  if (state.me) {
    try {
      const data = await api("GET", "/api/hq/me");
      hq.me = data.user;
      hq.rank = data.rank;
      hq.pendingFriends = data.pending_friend_requests;
    } catch {
      hq.me = null;
    }
  } else {
    hq.me = null;
  }
}

/* ----- live events (server-sent events, cookie-authenticated) -------------- */

function hqConnectStream() {
  if (hq.stream || !state.me || !("EventSource" in window)) return;
  const stream = new EventSource("/api/hq/stream");
  stream.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch {
      return;
    }
    hqHandleEvent(data);
  };
  stream.onerror = () => {
    if (!state.me) hqDisconnectStream();
  };
  hq.stream = stream;
}

function hqDisconnectStream() {
  if (hq.stream) hq.stream.close();
  hq.stream = null;
}

function hqHandleEvent(event) {
  const onHQ = location.hash.startsWith("#/hq");
  if (event.type === "notify") {
    setUnread((state.unread || 0) + 1);
    if (!onHQ || !String(event.link || "").startsWith(`hq/${hq.tab}`)) toast(event.text);
    return;
  }
  if (!onHQ || !hq.body) return;
  if (event.type === "chat" && hq.tab === "chat" && event.channel === hq.chatChannel) {
    hqAppendMessage(event.message);
  } else if ((event.type === "device" || event.type === "command") && hq.tab === "agents") {
    hqRenderAgents(hq.body, { keepSelection: true });
  } else if (event.type === "friends" && hq.tab === "friends") {
    hqRenderFriends(hq.body);
  } else if (event.type === "feed" && hq.tab === "feed" && hq.me && event.author !== hq.me.username) {
    const banner = $("[data-new-posts]", hq.body);
    if (banner) banner.hidden = false;
  }
}

window.addEventListener("hashchange", () => {
  if (!location.hash.startsWith("#/hq")) hqDisconnectStream();
});

/* ----- page shell ---------------------------------------------------------- */

async function renderHQ(subpath, params, isCurrent) {
  const [tabName, ...rest] = subpath.replace(/^\/+/, "").split("/");
  const tab = HQ_TABS.some(([key]) => key === tabName) ? tabName : "feed";
  hq.tab = tab;
  document.title = `HQ · ${HQ_TABS.find(([key]) => key === tab)[1]} · shiphub`;
  view().replaceChildren(pageLoading());
  await hqLoadBasics();
  if (!isCurrent()) return;
  await hqHandlePaymentReturn();

  const me = hq.me;
  const page = h(`<div class="hq container">
      <header class="hq-head">
        <div class="hq-title">
          <h1>HQ</h1>
          <p class="muted">Your devices and AI agents, ships, the ladder, friends, chat and the market, all in one place.</p>
        </div>
        ${me ? `<div class="hq-me">${avatar(me, 44)}<div class="hq-me-body"><div><strong>${esc(me.display_name)}</strong> <span class="muted">#${hq.rank} worldwide</span></div>${xpBar(me)}</div></div>` : ""}
      </header>
      <nav class="seg hq-tabs">${HQ_TABS.map(([key, label, iconName]) => `<a class="${key === tab ? "active" : ""}" href="#/hq/${key}">${icon(iconName, 15)}<span>${label}</span>${key === "friends" && hq.pendingFriends ? `<span class="hq-count">${hq.pendingFriends}</span>` : ""}</a>`).join("")}</nav>
      <section class="hq-body"></section>
    </div>`);
  view().replaceChildren(page);
  hq.body = $(".hq-body", page);

  if (!me && !HQ_PUBLIC_TABS.has(tab)) {
    hq.body.innerHTML = emptyState("cpu", "Log in to use HQ", "Connect your machines, chat with builders and climb the ladder. Your shiphub account works here.", `<button class="btn btn-primary" data-action="login">Log in</button> <button class="btn btn-secondary" data-action="signup">Sign up</button>`);
    return;
  }
  if (me) hqConnectStream();

  const renderers = {
    feed: hqRenderFeed,
    ladder: hqRenderLadder,
    agents: hqRenderAgents,
    chat: (body) => hqRenderChat(body, rest.join("/")),
    market: hqRenderMarket,
    friends: hqRenderFriends,
    settings: hqRenderSettings,
  };
  try {
    await renderers[tab](hq.body);
  } catch (error) {
    if (isCurrent()) hq.body.replaceChildren(pageError(error));
  }
}

async function hqHandlePaymentReturn() {
  const params = new URLSearchParams(location.search);
  const sessionId = params.get("checkout");
  const payouts = params.get("payouts");
  if (!sessionId && !payouts) return;
  history.replaceState(null, "", location.pathname + location.hash);
  try {
    if (sessionId) {
      const result = await api("GET", `/api/hq/checkout/confirm?session_id=${encodeURIComponent(sessionId)}`);
      toast(result.status === "paid" ? `Purchase confirmed: ${result.title}` : "Payment is still processing - we'll notify you");
    }
    if (payouts) {
      const result = await api("POST", "/api/hq/payouts/refresh");
      toast(result.payouts_enabled ? "Payouts active - you can sell paid products" : "Stripe setup isn't finished yet");
    }
  } catch (error) {
    handleError(error);
  }
}

/* ----- feed ----------------------------------------------------------------- */

function hqPostCard(post) {
  const kindLabel = { ship: "🚀 Ship", tip: "💡 Tip", news: "📰 News", post: "💬 Post" }[post.kind] || post.kind;
  return `<article class="hq-card hq-post" data-post="${post.id}">
      <div class="hq-post-head">${personLink(post.author, 36)}${tierBadge(post.author.tier)}<span class="hq-kind hq-kind-${esc(post.kind)}">${kindLabel}</span>${post.verified ? `<span class="badge badge-shipped" title="GitHub-verified ship">${icon("checkCircle", 13)} Verified</span>` : ""}<span class="muted hq-time">${timeAgo(post.created)}</span></div>
      <p class="hq-post-body">${esc(post.body)}</p>
      ${post.link ? `<a class="link-pill" href="${esc(post.link)}" target="_blank" rel="noopener noreferrer">${icon("external", 13)} ${esc(post.link.replace(/^https?:\/\//, "").slice(0, 60))}</a>` : ""}
      ${post.repo ? `<a class="link-pill" href="${esc(post.repo)}" target="_blank" rel="noopener noreferrer">${icon("github", 13)} ${esc(post.repo.replace(/^https?:\/\/(www\.)?github\.com\//, ""))}</a>` : ""}
      <div class="hq-post-foot"><button class="vote-btn ${post.liked ? "active" : ""}" data-like="${post.id}">${icon("heart", 15)} <span>${post.likes}</span></button></div>
    </article>`;
}

async function hqRenderFeed(body) {
  const me = hq.me;
  body.innerHTML = `<div class="hq-split">
      <aside class="hq-side">
        ${me ? `<form class="hq-card hq-compose" data-compose>
          <h3>Share with the world</h3>
          <select class="input" name="kind">
            <option value="ship">🚀 Ship - something you launched (+50 XP)</option>
            <option value="tip">💡 Tip - what worked for you (+20 XP)</option>
            <option value="news">📰 News - what's new in AI coding (+10 XP)</option>
            <option value="post" selected>💬 Post (+5 XP)</option>
          </select>
          <textarea class="textarea" name="body" rows="3" maxlength="2000" placeholder="What did you build or learn today?"></textarea>
          <input class="input" name="link" maxlength="500" placeholder="Link (optional)">
          <input class="input" name="repo" maxlength="300" placeholder="GitHub repo → verified ship (+50 XP)" hidden>
          <button class="btn btn-primary" type="submit">${icon("send", 15)} Post</button>
        </form>` : `<div class="hq-card">${emptyState("zap", "Join the feed", "Log in to post ships, tips and news and earn XP.", `<button class="btn btn-primary" data-action="login">Log in</button>`)}</div>`}
        <div class="hq-card hq-note"><h4>How XP works</h4><p class="muted">Ships, tips, news, likes you receive, finished agent tasks, sales, friends, new ideas and shipped builds all earn XP. Daily caps stop farming. Climb from Bronze to Legend.</p></div>
      </aside>
      <div class="hq-main">
        <div class="toolbar-row">
          <div class="seg seg-sm" data-feed-kinds>${HQ_POST_KINDS.map(([value, label]) => `<button class="${hq.feedKind === value ? "active" : ""}" data-kind="${value}">${label}</button>`).join("")}</div>
          ${me ? `<div class="seg seg-sm" data-feed-scope><button class="${hq.feedScope === "global" ? "active" : ""}" data-scope="global">Everyone</button><button class="${hq.feedScope === "friends" ? "active" : ""}" data-scope="friends">Friends</button></div>` : ""}
        </div>
        <button class="btn btn-secondary btn-sm btn-block" data-new-posts hidden>New posts - show them</button>
        <div class="hq-list" data-posts><div class="spinner"></div></div>
      </div>
    </div>`;

  const list = $("[data-posts]", body);
  const load = async () => {
    const query = new URLSearchParams();
    if (hq.feedKind) query.set("kind", hq.feedKind);
    if (hq.feedScope === "friends") query.set("scope", "friends");
    const data = await api("GET", `/api/hq/feed?${query}`);
    list.innerHTML = data.posts.length ? data.posts.map(hqPostCard).join("") : emptyState("zap", "Nothing here yet", "Be the first to share a ship, a tip or some news.");
    $("[data-new-posts]", body).hidden = true;
  };
  await load();

  const compose = $("[data-compose]", body);
  if (compose) {
    const repoInput = $('[name="repo"]', compose);
    $('[name="kind"]', compose).addEventListener("change", (event) => {
      repoInput.hidden = event.target.value !== "ship";
    });
    compose.addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(compose));
      if (values.kind !== "ship") delete values.repo;
      try {
        const result = await api("POST", "/api/hq/posts", values);
        compose.reset();
        repoInput.hidden = true;
        toast(result.verified ? `Verified ship! +${result.xp_gained} XP` : result.xp_gained ? `Posted · +${result.xp_gained} XP` : "Posted");
        if (result.verify_note && !result.verified) toast(result.verify_note, "error");
        await load();
      } catch (error) {
        handleError(error);
      }
    });
  }
  body.addEventListener("click", async (event) => {
    const kindButton = event.target.closest("[data-kind]");
    const scopeButton = event.target.closest("[data-scope]");
    const likeButton = event.target.closest("[data-like]");
    if (kindButton) {
      hq.feedKind = kindButton.dataset.kind;
      $$("[data-kind]", body).forEach((button) => button.classList.toggle("active", button === kindButton));
      await load().catch(handleError);
    } else if (scopeButton) {
      hq.feedScope = scopeButton.dataset.scope;
      $$("[data-scope]", body).forEach((button) => button.classList.toggle("active", button === scopeButton));
      await load().catch(handleError);
    } else if (likeButton) {
      if (!requireAuth()) return;
      try {
        const result = await api("POST", `/api/hq/posts/${likeButton.dataset.like}/like`);
        const count = $("span", likeButton);
        count.textContent = Number(count.textContent) + (result.liked ? 1 : -1);
        likeButton.classList.toggle("active", result.liked);
      } catch (error) {
        handleError(error);
      }
    } else if (event.target.closest("[data-new-posts]")) {
      await load().catch(handleError);
    }
  });
}

/* ----- ladder ----------------------------------------------------------------- */

async function hqRenderLadder(body) {
  const me = hq.me;
  const scopes = [["global", "🌍 Global"], ["country", `${flag(me && me.country) || "🏳️"} Country`], ["friends", "👥 Friends"]];
  body.innerHTML = `<div class="toolbar-row">
      <div class="seg seg-sm">${scopes.map(([value, label]) => `<button class="${hq.ladderScope === value ? "active" : ""}" data-ladder-scope="${value}" ${!me && value !== "global" ? "disabled" : ""}>${label}</button>`).join("")}</div>
      <div class="seg seg-sm"><button class="${hq.ladderPeriod === "all" ? "active" : ""}" data-ladder-period="all">All time</button><button class="${hq.ladderPeriod === "week" ? "active" : ""}" data-ladder-period="week">This week</button></div>
    </div>
    <div class="hq-card hq-ladder" data-ladder><div class="spinner"></div></div>`;
  const box = $("[data-ladder]", body);
  const load = async () => {
    try {
      const data = await api("GET", `/api/hq/ladder?scope=${hq.ladderScope}&period=${hq.ladderPeriod}`);
      box.innerHTML = `${data.my_rank ? `<div class="hq-myrank">You're <strong>#${data.my_rank}</strong> of ${data.total}</div>` : ""}
        <table class="hq-table"><thead><tr><th>#</th><th>Builder</th><th class="hide-sm">Country</th><th>Tier</th><th class="num">${hq.ladderPeriod === "week" ? "XP this week" : "XP"}</th></tr></thead><tbody>
        ${data.entries.map((entry) => `<tr class="${me && entry.id === me.id ? "me" : ""}"><td class="rank">${entry.rank <= 3 ? ["🥇", "🥈", "🥉"][entry.rank - 1] : entry.rank}</td><td>${personLink(entry, 30)}${entry.online ? '<span class="online-dot" title="online"></span>' : ""}</td><td class="hide-sm">${flag(entry.country)} ${esc(entry.country)}</td><td>${tierBadge(entry.tier)} <span class="muted small">Lv ${entry.level}</span></td><td class="num">${Number(entry.score).toLocaleString()}</td></tr>`).join("")}
        </tbody></table>`;
    } catch (error) {
      box.innerHTML = emptyState("trophy", "Can't show this ladder", esc(error.message), error.status === 400 ? `<a class="btn btn-secondary" href="#/hq/settings">Set your country</a>` : "");
    }
  };
  await load();
  body.addEventListener("click", async (event) => {
    const scope = event.target.closest("[data-ladder-scope]");
    const period = event.target.closest("[data-ladder-period]");
    if (!scope && !period) return;
    if (scope) hq.ladderScope = scope.dataset.ladderScope;
    if (period) hq.ladderPeriod = period.dataset.ladderPeriod;
    $$("[data-ladder-scope]", body).forEach((button) => button.classList.toggle("active", button.dataset.ladderScope === hq.ladderScope));
    $$("[data-ladder-period]", body).forEach((button) => button.classList.toggle("active", button.dataset.ladderPeriod === hq.ladderPeriod));
    await load();
  });
}

/* ----- agents & devices ----------------------------------------------------- */

function hqDeviceRow(device) {
  return `<button class="hq-device ${device.id === hq.deviceId ? "active" : ""}" data-device="${device.id}"><span class="status-dot ${device.online ? "on" : ""}"></span><span><strong>${esc(device.name)}</strong><span class="muted small">${device.online ? "online" : device.last_seen ? `seen ${timeAgo(device.last_seen)}` : "never connected"}</span></span></button>`;
}

function hqCommandRow(command) {
  const statusClass = { queued: "badge-open", running: "badge-building", done: "badge-shipped", failed: "badge-danger" }[command.status] || "";
  return `<div class="hq-command"><div class="hq-command-head"><strong>${esc(COMMAND_LABELS[command.kind] || command.kind)}</strong><span class="badge ${statusClass}">${esc(command.status)}</span><span class="muted small">${timeAgo(command.created)}</span></div>${command.payload ? `<div class="mono small">${esc(command.payload)}</div>` : ""}${command.result ? `<pre class="hq-result">${esc(command.result)}</pre>` : ""}</div>`;
}

async function hqRenderAgents(body, { keepSelection = false } = {}) {
  const { devices } = await api("GET", "/api/hq/devices");
  if (!keepSelection || !devices.some((device) => device.id === hq.deviceId)) {
    hq.deviceId = devices.length ? devices[0].id : null;
  }
  const device = devices.find((item) => item.id === hq.deviceId);
  const info = (device && device.info) || {};
  const agents = Array.isArray(info.agents) ? info.agents : [];
  body.innerHTML = `<div class="hq-split">
      <aside class="hq-side">
        <div class="hq-card">
          <h3>Your devices</h3>
          <div class="hq-devices">${devices.map(hqDeviceRow).join("") || `<p class="muted">No devices yet.</p>`}</div>
          <form class="hq-inline-form" data-add-device><input class="input input-sm" name="name" maxlength="40" placeholder="Name, e.g. laptop" required><button class="btn btn-secondary btn-sm" type="submit">${icon("plus", 14)} Add</button></form>
        </div>
        <div class="hq-card hq-note"><h4>Connect a machine</h4><p class="muted">Add a device, then run <code>agent.py</code> from this repo on it. Remote agent tasks and shell commands are off unless you start the bridge with <code>--allow-agent</code> / <code>--allow-shell</code>, and they always need your command PIN.</p></div>
      </aside>
      <div class="hq-main">${device ? `
        <div class="hq-card">
          <div class="hq-device-head"><h3><span class="status-dot ${device.online ? "on" : ""}"></span> ${esc(device.name)}</h3><button class="btn btn-ghost btn-sm" data-delete-device="${device.id}">${icon("trash", 14)} Remove</button></div>
          <div class="hq-facts">
            <div><span class="muted small">System</span><div>${esc(info.os || info.platform || "unknown")}</div></div>
            <div><span class="muted small">Host</span><div>${esc(info.hostname || "-")}</div></div>
            <div><span class="muted small">Agents running</span><div>${agents.length ? agents.map((name) => `<span class="chip chip-sm">${esc(typeof name === "string" ? name : name.name || "agent")}</span>`).join(" ") : "none detected"}</div></div>
          </div>
          <div class="hq-actions">${["ping", "sysinfo", "list_agents"].map((kind) => `<button class="btn btn-secondary btn-sm" data-command="${kind}">${COMMAND_LABELS[kind]}</button>`).join("")}</div>
          <form class="hq-task" data-task>
            <div class="seg seg-sm"><button type="button" class="active" data-task-kind="agent_task">${icon("sparkles", 14)} Agent task</button><button type="button" data-task-kind="shell">${icon("terminal", 14)} Shell</button></div>
            <textarea class="textarea" name="payload" rows="3" maxlength="4000" placeholder="Tell the agent what to do, e.g. 'run the tests and fix what fails'"></textarea>
            <div class="hq-inline-form"><input class="input input-sm" name="pin" type="password" inputmode="numeric" autocomplete="off" placeholder="Command PIN" required><button class="btn btn-primary btn-sm" type="submit">${icon("send", 14)} Send</button></div>
            ${hq.me.has_command_pin ? "" : `<p class="field-hint">Set a command PIN in <a href="#/hq/settings">Settings</a> first.</p>`}
          </form>
        </div>
        <div class="hq-card"><h3>Recent commands</h3><div data-commands><div class="spinner"></div></div></div>` : `<div class="hq-card">${emptyState("cpu", "No devices yet", "Add your laptop or a server on the left, then run the bridge there to see your AI agents and send them tasks.")}</div>`}
      </div>
    </div>`;

  if (device) {
    const { commands } = await api("GET", `/api/hq/devices/${device.id}/commands`);
    $("[data-commands]", body).innerHTML = commands.map(hqCommandRow).join("") || `<p class="muted">Nothing sent yet.</p>`;
  }
  hqBindAgents(body);
}

function hqBindAgents(body) {
  if (body.dataset.agentsBound) return;
  body.dataset.agentsBound = "1";
  let taskKind = "agent_task";
  body.addEventListener("click", async (event) => {
    const deviceButton = event.target.closest("[data-device]");
    const commandButton = event.target.closest("[data-command]");
    const deleteButton = event.target.closest("[data-delete-device]");
    const kindButton = event.target.closest("[data-task-kind]");
    try {
      if (deviceButton) {
        hq.deviceId = Number(deviceButton.dataset.device);
        await hqRenderAgents(body, { keepSelection: true });
      } else if (commandButton) {
        await api("POST", `/api/hq/devices/${hq.deviceId}/commands`, { kind: commandButton.dataset.command });
        toast("Sent - the device picks it up within a few seconds");
        await hqRenderAgents(body, { keepSelection: true });
      } else if (deleteButton) {
        if (!confirm("Remove this device? Its key stops working immediately.")) return;
        await api("POST", `/api/hq/devices/${deleteButton.dataset.deleteDevice}/delete`);
        await hqRenderAgents(body);
      } else if (kindButton) {
        taskKind = kindButton.dataset.taskKind;
        $$("[data-task-kind]", body).forEach((button) => button.classList.toggle("active", button === kindButton));
        $('[name="payload"]', body).placeholder = taskKind === "shell" ? "Command, e.g. git status" : "Tell the agent what to do, e.g. 'run the tests and fix what fails'";
      }
    } catch (error) {
      handleError(error);
    }
  });
  body.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      if (form.matches("[data-add-device]")) {
        const result = await api("POST", "/api/hq/devices", { name: form.name.value.trim() });
        hq.deviceId = result.id;
        hqShowDeviceKey(result.key);
        await hqRenderAgents(body, { keepSelection: true });
      } else if (form.matches("[data-task]")) {
        await api("POST", `/api/hq/devices/${hq.deviceId}/commands`, { kind: taskKind, payload: form.payload.value, pin: form.pin.value });
        toast("Task sent");
        await hqRenderAgents(body, { keepSelection: true });
      }
    } catch (error) {
      handleError(error);
    }
  });
}

function hqShowDeviceKey(key) {
  const command = `python agent.py --server ${location.origin} --key ${key} --allow-agent --approve`;
  const node = h(`<div>
      <header class="modal-head"><h2>Device added</h2><button type="button" class="icon-btn" data-close title="Close">${icon("x")}</button></header>
      <div class="modal-body">
        <p>Copy this key now - it's only shown once.</p>
        <pre class="hq-result">${esc(key)}</pre>
        <p>Then on that machine, from a copy of this repo:</p>
        <pre class="hq-result">${esc(command)}</pre>
        <p class="muted small"><code>--approve</code> asks for a y/N on the machine before every agent task. Drop <code>--allow-agent</code> to allow only status commands.</p>
      </div>
      <footer class="modal-foot"><button class="btn btn-secondary" data-copy>${icon("code", 15)} Copy command</button><button class="btn btn-primary" data-close>Done</button></footer>
    </div>`);
  $("[data-copy]", node).addEventListener("click", async () => {
    if (await copyText(command)) toast("Copied");
  });
  openModal(node, { size: "md" });
}

/* ----- chat ---------------------------------------------------------------- */

function hqMessageRow(message) {
  const mine = hq.me && message.sender.username === hq.me.username;
  return `<div class="hq-msg ${mine ? "mine" : ""}">${avatar(message.sender, 30)}<div><div class="hq-msg-head"><a href="#/u/${esc(message.sender.username)}">${esc(message.sender.display_name)}</a> <span class="muted small">${timeAgo(message.created)}</span></div><div class="hq-msg-body">${esc(message.body)}</div></div></div>`;
}

function hqAppendMessage(message) {
  const list = hq.body && $("[data-messages]", hq.body);
  if (!list || $(`[data-msg="${message.id}"]`, list)) return;
  const empty = $(".empty-note", list);
  if (empty) empty.remove();
  const row = h(hqMessageRow(message));
  row.dataset.msg = message.id;
  list.append(row);
  list.scrollTop = list.scrollHeight;
}

async function hqRenderChat(body, channel) {
  hq.chatChannel = channel && /^(world|dm:[A-Za-z0-9_]+)$/.test(channel) ? channel : "world";
  const [{ friends }, { messages }] = await Promise.all([
    api("GET", "/api/hq/friends"),
    api("GET", `/api/hq/chat/${encodeURIComponent(hq.chatChannel)}`),
  ]);
  const channels = [["world", "🌍 World", null], ...friends.map((friend) => [`dm:${friend.username}`, friend.display_name, friend])];
  body.innerHTML = `<div class="hq-chat hq-card">
      <aside class="hq-channels">${channels.map(([key, label, friend]) => `<a class="hq-channel ${key === hq.chatChannel ? "active" : ""}" href="#/hq/chat/${encodeURIComponent(key)}">${friend ? avatar(friend, 26) : ""}<span>${esc(label)}</span>${friend && friend.online ? '<span class="online-dot"></span>' : ""}</a>`).join("")}
        ${friends.length ? "" : `<p class="muted small hq-pad">Add friends to DM them.</p>`}</aside>
      <div class="hq-chat-main">
        <div class="hq-messages" data-messages>${messages.map((message) => hqMessageRow(message).replace('class="hq-msg', `data-msg="${message.id}" class="hq-msg`)).join("") || `<div class="empty-note">No messages yet. Say hi 👋</div>`}</div>
        <form class="hq-chat-form" data-chat-form><input class="input" name="body" maxlength="2000" placeholder="${hq.chatChannel === "world" ? "Message builders worldwide" : "Message"}" autocomplete="off"><button class="btn btn-primary" type="submit">${icon("send", 15)}</button></form>
      </div>
    </div>`;
  const list = $("[data-messages]", body);
  list.scrollTop = list.scrollHeight;
  $("[data-chat-form]", body).addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = event.target.body;
    const text = input.value.trim();
    if (!text) return;
    try {
      const { message } = await api("POST", `/api/hq/chat/${encodeURIComponent(hq.chatChannel)}`, { body: text });
      input.value = "";
      hqAppendMessage(message);
    } catch (error) {
      handleError(error);
    }
  });
}

/* ----- market -------------------------------------------------------------- */

function hqProductCard(product) {
  let action;
  if (product.mine) action = `<span class="badge">Yours · ${product.sales} sold</span>`;
  else if (product.owned) action = product.delivery_link ? `<a class="btn btn-secondary btn-sm" href="${esc(product.delivery_link)}" target="_blank" rel="noopener noreferrer">${icon("external", 14)} Open</a>` : `<span class="badge badge-shipped">Owned</span>`;
  else if (!product.seller_can_sell) action = `<span class="muted small">Seller is finishing payout setup</span>`;
  else action = `<button class="btn btn-primary btn-sm" data-buy="${product.id}">${product.price_cents ? `Buy · ${hqMoney(product.price_cents)}` : "Get it free"}</button>`;
  return `<article class="hq-card hq-product">
      <div class="hq-product-top"><span class="hq-kind">${esc(product.kind)}</span><span class="hq-price">${hqMoney(product.price_cents)}</span></div>
      <h3>${esc(product.title)}</h3>
      <p class="muted">${esc(product.description)}</p>
      <div class="hq-product-foot">${personLink(product.seller, 26)}${action}</div>
    </article>`;
}

async function hqRenderMarket(body) {
  const me = hq.me;
  const config = hq.config || {};
  body.innerHTML = `<div class="toolbar-row">
      <div class="seg seg-sm">${["", ...HQ_PRODUCT_KINDS].map((kind) => `<button class="${hq.marketKind === kind ? "active" : ""}" data-market-kind="${kind}">${kind || "All"}</button>`).join("")}</div>
      ${me ? `<div class="hq-actions"><button class="btn btn-primary btn-sm" data-sell>${icon("plus", 14)} Sell something</button>${config.payments === "stripe" ? `<button class="btn btn-secondary btn-sm" data-payouts>${me.payouts_enabled ? "Payouts active ✓" : "Get paid (Stripe)"}</button>` : ""}</div>` : ""}
    </div>
    ${config.payments === "demo" ? `<p class="hq-banner">Demo mode: purchases are simulated. Add <code>STRIPE_SECRET_KEY</code> on the server for real payments (platform fee ${config.fee_percent}%).</p>` : ""}
    <div class="hq-grid" data-products><div class="spinner"></div></div>
    ${me ? `<div class="hq-card" data-orders></div>` : ""}`;

  const grid = $("[data-products]", body);
  const load = async () => {
    const data = await api("GET", `/api/hq/products${hq.marketKind ? `?kind=${hq.marketKind}` : ""}`);
    grid.innerHTML = data.products.map(hqProductCard).join("") || emptyState("bag", "Nothing for sale yet", "Templates, prompts, agents, MCP servers - sell what you've built.");
    if (me) {
      const orders = await api("GET", "/api/hq/orders");
      $("[data-orders]", body).innerHTML = `<h3>Your orders</h3>
        <div class="hq-orders"><div><h4>Purchases</h4>${orders.purchases.map((order) => `<div class="hq-order"><span>${esc(order.title)}</span><span class="muted">${hqMoney(order.price_cents)}</span>${order.delivery_link ? `<a href="${esc(order.delivery_link)}" target="_blank" rel="noopener noreferrer">open</a>` : ""}</div>`).join("") || `<p class="muted small">None yet.</p>`}</div>
        <div><h4>Sales · ${hqMoney(orders.net_cents)} net</h4>${orders.sales.map((order) => `<div class="hq-order"><span>${esc(order.title)}</span><span class="muted">@${esc(order.buyer)}</span><span>${hqMoney(order.price_cents)}</span></div>`).join("") || `<p class="muted small">None yet.</p>`}</div></div>`;
    }
  };
  await load();

  body.addEventListener("click", async (event) => {
    const kindButton = event.target.closest("[data-market-kind]");
    const buyButton = event.target.closest("[data-buy]");
    try {
      if (kindButton) {
        hq.marketKind = kindButton.dataset.marketKind;
        $$("[data-market-kind]", body).forEach((button) => button.classList.toggle("active", button === kindButton));
        await load();
      } else if (buyButton) {
        if (!requireAuth()) return;
        buyButton.disabled = true;
        const result = await api("POST", `/api/hq/products/${buyButton.dataset.buy}/buy`);
        if (result.checkout_url) {
          location.href = result.checkout_url;
          return;
        }
        toast(result.demo ? "Demo purchase complete - it's yours" : "It's yours!");
        await load();
      } else if (event.target.closest("[data-sell]")) {
        hqOpenSellForm(load);
      } else if (event.target.closest("[data-payouts]")) {
        const result = await api("POST", "/api/hq/payouts/connect");
        location.href = result.url;
      }
    } catch (error) {
      if (buyButton) buyButton.disabled = false;
      handleError(error);
    }
  });
}

function hqOpenSellForm(onDone) {
  const node = h(`<form novalidate>
      <header class="modal-head"><h2>Sell something</h2><button type="button" class="icon-btn" data-close title="Close">${icon("x")}</button></header>
      <div class="modal-body">
        <label class="field"><span class="field-label">What is it?</span><select class="input" name="kind">${HQ_PRODUCT_KINDS.map((kind) => `<option>${kind}</option>`).join("")}</select></label>
        <label class="field"><span class="field-label">Title</span><input class="input" name="title" maxlength="80" required></label>
        <label class="field"><span class="field-label">Description</span><textarea class="textarea" name="description" rows="3" maxlength="2000" required></textarea></label>
        <div class="field-row">
          <label class="field"><span class="field-label">Price (${esc(((hq.config && hq.config.currency) || "usd").toUpperCase())}, 0 = free)</span><input class="input" name="price" type="number" min="0" max="10000" step="0.01" value="0"></label>
          <label class="field"><span class="field-label">Delivery link (buyers only)</span><input class="input" name="delivery_link" maxlength="500" placeholder="https://..."></label>
        </div>
        <div class="form-error"></div>
      </div>
      <footer class="modal-foot"><button type="button" class="btn btn-ghost" data-close>Cancel</button><button class="btn btn-primary" type="submit">List it</button></footer>
    </form>`);
  node.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api("POST", "/api/hq/products", Object.fromEntries(new FormData(node)));
      closeModal({ force: true });
      toast("Listed on the market");
      await onDone();
    } catch (error) {
      $(".form-error", node).textContent = error.message;
    }
  });
  openModal(node, { size: "md" });
}

/* ----- friends -------------------------------------------------------------- */

function hqFriendRow(person, actions) {
  return `<div class="hq-friend">${personLink(person, 36)}${person.online ? '<span class="online-dot" title="online"></span>' : ""}${tierBadge(person.tier)}<span class="spacer"></span>${actions}</div>`;
}

async function hqRenderFriends(body) {
  const data = await api("GET", "/api/hq/friends");
  body.innerHTML = `<div class="hq-split">
      <aside class="hq-side"><div class="hq-card">
        <h3>Find builders</h3>
        <form class="hq-inline-form" data-search><input class="input input-sm" name="q" placeholder="Name or @username"><button class="btn btn-secondary btn-sm" type="submit">${icon("search", 14)}</button></form>
        <div data-results></div>
      </div></aside>
      <div class="hq-main">
        ${data.incoming.length ? `<div class="hq-card"><h3>Friend requests</h3>${data.incoming.map((person) => hqFriendRow(person, `<button class="btn btn-primary btn-sm" data-friend="accept" data-user="${esc(person.username)}">Accept</button>`)).join("")}</div>` : ""}
        <div class="hq-card"><h3>Friends · ${data.friends.length}</h3>${data.friends.map((person) => hqFriendRow(person, `<a class="btn btn-secondary btn-sm" href="#/hq/chat/dm:${esc(person.username)}">${icon("message", 14)} Message</a><button class="btn btn-ghost btn-sm" data-friend="remove" data-user="${esc(person.username)}">Remove</button>`)).join("") || `<p class="muted">No friends yet - search for builders on the left or add people from their profile.</p>`}</div>
        ${data.outgoing.length ? `<div class="hq-card"><h3>Sent requests</h3>${data.outgoing.map((person) => hqFriendRow(person, `<span class="muted small">pending</span>`)).join("")}</div>` : ""}
      </div>
    </div>`;
  if (body.dataset.friendsBound) return;
  body.dataset.friendsBound = "1";
  body.addEventListener("submit", async (event) => {
    if (!event.target.matches("[data-search]")) return;
    event.preventDefault();
    try {
      const { users } = await api("GET", `/api/hq/users?q=${encodeURIComponent(event.target.q.value.trim())}`);
      $("[data-results]", body).innerHTML = users.map((person) => hqFriendRow(person, `<button class="icon-btn" title="Add friend" data-friend="request" data-user="${esc(person.username)}">${icon("userPlus", 16)}</button>`)).join("") || `<p class="muted small">No one found.</p>`;
    } catch (error) {
      handleError(error);
    }
  });
  body.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-friend]");
    if (!button) return;
    try {
      const result = await api("POST", `/api/hq/friends/${button.dataset.friend}`, { username: button.dataset.user });
      toast(result.status === "pending" ? "Friend request sent" : result.status === "accepted" ? "You're friends now" : "Updated");
      await hqRenderFriends(body);
    } catch (error) {
      handleError(error);
    }
  });
}

/* ----- settings ------------------------------------------------------------ */

function urlBase64ToBytes(text) {
  const padded = (text + "=".repeat((4 - (text.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (char) => char.charCodeAt(0));
}

async function hqPushSubscription() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  const registration = await navigator.serviceWorker.register("/sw.js");
  return registration.pushManager.getSubscription();
}

async function hqRenderSettings(body) {
  const me = hq.me;
  const pushSupported = "serviceWorker" in navigator && "PushManager" in window;
  const subscription = pushSupported ? await hqPushSubscription().catch(() => null) : null;
  const { sessions } = await api("GET", "/api/account/sessions");
  body.innerHTML = `<div class="hq-settings">
      <form class="hq-card" data-profile-form>
        <h3>HQ profile</h3>
        <div class="field-row">
          <label class="field"><span class="field-label">Country (2 letters)</span><input class="input" name="country" maxlength="2" value="${esc(me.country)}" placeholder="US"></label>
          <label class="field"><span class="field-label">Stack</span><input class="input" name="stack" maxlength="120" value="${esc(me.stack)}" placeholder="Claude Code, Next.js, Supabase"></label>
        </div>
        <p class="field-hint">Name, bio and avatar live in your <a href="#/u/${esc(me.username)}">profile</a>.</p>
        <button class="btn btn-primary btn-sm" type="submit">Save</button>
      </form>

      <form class="hq-card" data-pin-form>
        <h3>${icon("shield", 16)} Command PIN</h3>
        <p class="muted">Agent tasks and shell commands sent to your devices need this PIN, so a stolen login alone can't run code on your machines.</p>
        <div class="field-row">
          ${me.has_command_pin ? `<label class="field"><span class="field-label">Current PIN</span><input class="input" name="current_pin" type="password" inputmode="numeric" autocomplete="off"></label>` : ""}
          <label class="field"><span class="field-label">${me.has_command_pin ? "New PIN" : "PIN"} (6-12 digits)</span><input class="input" name="pin" type="password" inputmode="numeric" autocomplete="off" required></label>
        </div>
        ${me.has_command_pin ? `<p class="field-hint">Forgot it? Log out and back in - for 10 minutes after a fresh login you can set a new PIN without the old one.</p>` : ""}
        <button class="btn btn-primary btn-sm" type="submit">${me.has_command_pin ? "Change PIN" : "Set PIN"}</button>
      </form>

      <form class="hq-card" data-notify-form>
        <h3>${icon("bell", 16)} Phone notifications</h3>
        <p class="muted">Get pinged when an agent finishes, someone DMs you, or you make a sale.</p>
        ${pushSupported ? `<div class="hq-actions"><button type="button" class="btn btn-secondary btn-sm" data-push-toggle>${subscription ? "Turn off push on this device" : "Turn on push on this device"}</button><button type="button" class="btn btn-ghost btn-sm" data-push-test>Send a test</button></div>
        <p class="field-hint">On iPhone, first add shiphub to your home screen (Share → Add to Home Screen).</p>` : `<p class="field-hint">This browser doesn't support web push - use ntfy below.</p>`}
        <label class="field"><span class="field-label">ntfy topic (optional)</span><input class="input" name="ntfy_topic" maxlength="64" value="${esc(me.ntfy_topic || "")}" placeholder="a-long-random-topic-name"></label>
        <p class="field-hint">Install the ntfy app, subscribe to this topic on ${esc((hq.config && hq.config.ntfy_base) || "https://ntfy.sh")}. Make it long and hard to guess.</p>
        <button class="btn btn-primary btn-sm" type="submit">Save</button>
      </form>

      ${hq.config && hq.config.github_verify && me.github_login ? `<div class="hq-card"><h3>${icon("github", 16)} GitHub activity</h3><p class="muted">Earn XP for pushes to your public repos in the last 7 days (@${esc(me.github_login)}).</p><button class="btn btn-secondary btn-sm" data-github-sync>Sync pushes</button></div>` : ""}

      <div class="hq-card">
        <h3>Signed-in sessions</h3>
        ${sessions.map((session) => `<div class="hq-order"><span>${session.current ? "<strong>This device</strong>" : "Another device"}</span><span class="muted small">${session.created ? `signed in ${timeAgo(session.created)}` : "signed in earlier"}</span>${session.current ? "" : `<button class="btn btn-ghost btn-sm" data-revoke="${session.id}">Sign out</button>`}</div>`).join("")}
        ${sessions.length > 1 ? `<button class="btn btn-secondary btn-sm" data-revoke-all>Sign out everywhere else</button>` : ""}
      </div>

      <form class="hq-card" data-password-form>
        <h3>Password</h3>
        <div class="field-row">
          ${me.has_password ? `<label class="field"><span class="field-label">Current password</span><input class="input" name="current_password" type="password" autocomplete="current-password"></label>` : ""}
          <label class="field"><span class="field-label">New password (8+ chars)</span><input class="input" name="new_password" type="password" autocomplete="new-password" required></label>
        </div>
        <p class="field-hint">Changing it signs out your other devices.</p>
        <button class="btn btn-primary btn-sm" type="submit">${me.has_password ? "Change password" : "Set a password"}</button>
      </form>
    </div>`;

  if (body.dataset.settingsBound) return;
  body.dataset.settingsBound = "1";
  body.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const values = Object.fromEntries(new FormData(form));
    try {
      if (form.matches("[data-profile-form]")) {
        await api("POST", "/api/hq/profile", { ...values, ntfy_topic: hq.me.ntfy_topic || "" });
        toast("Saved");
      } else if (form.matches("[data-notify-form]")) {
        await api("POST", "/api/hq/profile", { country: hq.me.country, stack: hq.me.stack, ntfy_topic: values.ntfy_topic });
        toast("Saved");
      } else if (form.matches("[data-pin-form]")) {
        await api("POST", "/api/account/pin", values);
        toast("Command PIN saved");
      } else if (form.matches("[data-password-form]")) {
        const result = await api("POST", "/api/account/password", values);
        toast(result.signed_out_sessions ? `Password changed · ${result.signed_out_sessions} other session(s) signed out` : "Password changed");
      }
      await hqLoadBasics();
      await hqRenderSettings(body);
    } catch (error) {
      handleError(error);
    }
  });
  body.addEventListener("click", async (event) => {
    try {
      if (event.target.closest("[data-push-toggle]")) {
        await hqTogglePush();
        await hqRenderSettings(body);
      } else if (event.target.closest("[data-push-test]")) {
        await api("POST", "/api/hq/push/test");
        toast("Test sent");
      } else if (event.target.closest("[data-github-sync]")) {
        const result = await api("POST", "/api/hq/github/sync");
        toast(`${result.pushes_found} recent pushes · +${result.xp_gained} XP`);
      } else if (event.target.closest("[data-revoke]")) {
        await api("POST", "/api/account/sessions/revoke", { id: event.target.closest("[data-revoke]").dataset.revoke });
        await hqRenderSettings(body);
      } else if (event.target.closest("[data-revoke-all]")) {
        const result = await api("POST", "/api/account/sessions/revoke", { all_others: true });
        toast(`${result.signed_out} session(s) signed out`);
        await hqRenderSettings(body);
      }
    } catch (error) {
      handleError(error);
    }
  });
}

async function hqTogglePush() {
  const registration = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;
  const existing = await registration.pushManager.getSubscription();
  if (existing) {
    await api("POST", "/api/hq/push/unsubscribe", { endpoint: existing.endpoint }).catch(() => {});
    await existing.unsubscribe();
    toast("Push turned off on this device");
    return;
  }
  if ((await Notification.requestPermission()) !== "granted") {
    throw new Error("Notifications are blocked for this site in your browser settings");
  }
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToBytes(hq.config.vapid_public_key),
  });
  await api("POST", "/api/hq/push/subscribe", { endpoint: subscription.endpoint });
  toast("Push is on - try 'Send a test'");
}

/* ----- profile integration (used by renderProfile in app.js) ---------------- */

function hqProfileLine(data) {
  const info = data.hq;
  if (!info) return "";
  return `<div class="hq-profile-line">${tierBadge(info.tier)}<span>Level ${info.level} · ${Number(info.xp).toLocaleString()} XP</span>${info.country ? `<span>${flag(info.country)} ${esc(info.country)}</span>` : ""}${info.stack ? `<span class="muted">${esc(info.stack)}</span>` : ""}</div>`;
}

async function hqProfileActions(container, username) {
  if (!state.me || state.me.username === username) return;
  try {
    const data = await api("GET", `/api/hq/users/${encodeURIComponent(username)}`);
    const relation = data.relation;
    const buttons = {
      none: `<button class="btn btn-primary btn-sm" data-profile-friend="request">${icon("userPlus", 14)} Add friend</button>`,
      outgoing: `<button class="btn btn-secondary btn-sm" disabled>Request sent</button>`,
      incoming: `<button class="btn btn-primary btn-sm" data-profile-friend="accept">Accept friend request</button>`,
      friends: `<a class="btn btn-secondary btn-sm" href="#/hq/chat/dm:${esc(username)}">${icon("message", 14)} Message</a>`,
    };
    container.innerHTML = buttons[relation] || "";
    container.addEventListener("click", async (event) => {
      const button = event.target.closest("[data-profile-friend]");
      if (!button) return;
      try {
        const result = await api("POST", `/api/hq/friends/${button.dataset.profileFriend}`, { username });
        toast(result.status === "accepted" ? "You're friends now" : "Friend request sent");
        await hqProfileActions(container, username);
      } catch (error) {
        handleError(error);
      }
    }, { once: true });
  } catch {
    container.innerHTML = "";
  }
}

async function hqRenderProfileTab(body, username) {
  body.replaceChildren(pageLoading());
  try {
    const data = await api("GET", `/api/hq/users/${encodeURIComponent(username)}`);
    const stats = data.stats;
    const stat = (value, label) => `<div class="stat"><div class="stat-num">${compact(value)}</div><div class="stat-label">${label}</div></div>`;
    body.innerHTML = `<div class="hq-profile-tab">
        <div class="profile-stats">${stat(stats.global_rank, "Rank")}${stat(stats.ships, "Ships")}${stat(stats.friends, "Friends")}${stat(stats.tasks_done, "Agent tasks")}${stat(stats.sales, "Sales")}</div>
        <h3>Posts</h3>
        <div class="hq-list">${data.posts.map(hqPostCard).join("") || `<p class="muted">No posts yet.</p>`}</div>
        ${data.products.length ? `<h3>For sale</h3><div class="hq-grid">${data.products.map(hqProductCard).join("")}</div>` : ""}
      </div>`;
    body.addEventListener("click", async (event) => {
      const likeButton = event.target.closest("[data-like]");
      const buyButton = event.target.closest("[data-buy]");
      if (!likeButton && !buyButton) return;
      if (!requireAuth()) return;
      try {
        if (likeButton) {
          const result = await api("POST", `/api/hq/posts/${likeButton.dataset.like}/like`);
          const count = $("span", likeButton);
          count.textContent = Number(count.textContent) + (result.liked ? 1 : -1);
          likeButton.classList.toggle("active", result.liked);
        } else {
          location.hash = "#/hq/market";
        }
      } catch (error) {
        handleError(error);
      }
    });
  } catch (error) {
    body.replaceChildren(pageError(error));
  }
}
