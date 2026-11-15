/* Tokser Backup Manager — application shell and router. */
"use strict";

const NAV = [
  { group: "nav.overview", items: [
    { path: "/", key: "dashboard", i18n: "nav.dashboard", icon: "grid" },
    { path: "/monitoring", key: "monitoring", i18n: "nav.monitoring", icon: "activity" },
  ]},
  { group: "nav.backups", items: [
    { path: "/jobs", key: "jobs", i18n: "nav.jobs", icon: "layers" },
    { path: "/sources", key: "sources", i18n: "nav.sources", icon: "folder" },
    { path: "/backups", key: "backups", i18n: "nav.history", icon: "archive" },
    { path: "/restore", key: "restore", i18n: "nav.restore", icon: "rotate" },
    { path: "/schedules", key: "schedules", i18n: "nav.schedules", icon: "clock" },
  ]},
  { group: "nav.delivery", items: [
    { path: "/storage", key: "storage", i18n: "nav.storage", icon: "database" },
    { path: "/telegram", key: "telegram", i18n: "nav.telegram", icon: "send" },
    { path: "/notifications", key: "notifications", i18n: "nav.notifications", icon: "bell" },
  ]},
  { group: "nav.system", items: [
    { path: "/logs", key: "logs", i18n: "nav.logs", icon: "list" },
    { path: "/users", key: "users", i18n: "nav.users", icon: "users", admin: true },
    { path: "/security", key: "security", i18n: "nav.security", icon: "shield" },
    { path: "/settings", key: "settings", i18n: "nav.settings", icon: "sliders" },
    { path: "/api-docs", key: "apidocs", i18n: "nav.apidocs", icon: "code" },
    { path: "/about", key: "about", i18n: "nav.about", icon: "info" },
  ]},
];

const SVG_ICONS = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  layers: '<path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>',
  folder: '<path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>',
  archive: '<rect x="2" y="4" width="20" height="5" rx="1"/><path d="M4 9v11a2 2 0 002 2h12a2 2 0 002-2V9"/><path d="M10 13h4"/>',
  rotate: '<path d="M3 12a9 9 0 109-9 9 9 0 00-6.4 2.6L3 8"/><path d="M3 3v5h5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  database: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5"/><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3"/>',
  send: '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
  bell: '<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 01-3.4 0"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  users: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
  code: '<path d="M16 18l6-6-6-6"/><path d="M8 6l-6 6 6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
};

function icon(name) {
  const path = SVG_ICONS[name] || SVG_ICONS.info;
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
}

/* ------------------------------------------------------------------ */
/* Router                                                              */
/* ------------------------------------------------------------------ */
const ROUTES = [
  { re: /^\/?$/, view: "dashboard", title: "dash.title", subtitle: "dash.subtitle" },
  { re: /^\/monitoring\/?$/, view: "monitoring", title: "monitoring.title", subtitle: "" },
  { re: /^\/jobs\/?$/, view: "jobs", title: "jobs.title", subtitle: "" },
  { re: /^\/jobs\/new\/?$/, view: "jobForm", title: "jobs.new", subtitle: "" },
  { re: /^\/jobs\/(\d+)\/edit\/?$/, view: "jobForm", title: "jobs.edit", subtitle: "", params: ["id"] },
  { re: /^\/sources\/?$/, view: "sources", title: "sources.title", subtitle: "" },
  { re: /^\/backups\/?$/, view: "backups", title: "backups.title", subtitle: "" },
  { re: /^\/backups\/(\d+)\/?$/, view: "backupDetail", title: "backups.detail", subtitle: "", params: ["id"] },
  { re: /^\/restore\/?$/, view: "restore", title: "restore.title", subtitle: "" },
  { re: /^\/schedules\/?$/, view: "schedules", title: "schedules.title", subtitle: "" },
  { re: /^\/storage\/?$/, view: "storage", title: "storage.title", subtitle: "" },
  { re: /^\/telegram\/?$/, view: "telegram", title: "telegram.title", subtitle: "" },
  { re: /^\/notifications\/?$/, view: "notifications", title: "notif.title", subtitle: "" },
  { re: /^\/logs\/?$/, view: "logs", title: "logs.title", subtitle: "" },
  { re: /^\/users\/?$/, view: "users", title: "users.title", subtitle: "" },
  { re: /^\/security\/?$/, view: "security", title: "security.title", subtitle: "" },
  { re: /^\/settings\/?$/, view: "settings", title: "settings.title", subtitle: "" },
  { re: /^\/api-docs\/?$/, view: "apidocs", title: "nav.apidocs", subtitle: "" },
  { re: /^\/about\/?$/, view: "about", title: "about.title", subtitle: "" },
];

function matchRoute(path) {
  for (const route of ROUTES) {
    const m = path.match(route.re);
    if (m) {
      const params = {};
      (route.params || []).forEach((name, i) => { params[name] = m[i + 1]; });
      return { route, params };
    }
  }
  return null;
}

let currentView = null;

async function navigate(path, push = true) {
  if (push && location.pathname + location.search !== path) {
    history.pushState({}, "", path);
  }
  const match = matchRoute(path.split("?")[0]);
  const viewEl = document.getElementById("view");
  stopAllPolls();
  if (currentView && Views[currentView] && Views[currentView].destroy) {
    try { Views[currentView].destroy(); } catch (e) { console.warn(e); }
  }
  viewEl.innerHTML = `<div style="display:grid;place-items:center;padding:80px"><span class="spinner lg"></span></div>`;

  if (!match) {
    document.getElementById("page-title").textContent = "Not found";
    viewEl.innerHTML = emptyState("Page not found", "The page you requested does not exist.",
      '<a class="btn btn-primary" href="/">Go to dashboard</a>');
    return;
  }

  const { route, params } = match;
  document.getElementById("page-title").textContent = t(route.title);
  document.getElementById("page-subtitle").textContent = route.subtitle ? t(route.subtitle) : "";
  document.title = `${t(route.title)} — Tokser Backup Manager`;
  setActiveNav(path);
  currentView = route.view;

  const fn = Views[route.view];
  if (!fn) {
    viewEl.innerHTML = emptyState("View unavailable", "This view has not been implemented.");
    return;
  }
  try {
    await fn(viewEl, params);
  } catch (err) {
    console.error(err);
    viewEl.innerHTML = emptyState("Failed to load", err.message || "An unexpected error occurred.",
      '<button class="btn" onclick="location.reload()">Reload</button>');
  }
  viewEl.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
}

function setActiveNav(path) {
  const clean = path.split("?")[0].replace(/\/$/, "") || "/";
  document.querySelectorAll(".nav-item").forEach((el) => {
    const href = el.getAttribute("data-path");
    const isActive = href === "/" ? clean === "/" : clean === href || clean.startsWith(href + "/");
    el.classList.toggle("active", isActive);
  });
}

/* ------------------------------------------------------------------ */
/* Sidebar                                                             */
/* ------------------------------------------------------------------ */
function renderNav() {
  const nav = document.getElementById("nav");
  const isAdmin = TBM.user && TBM.user.role_name === "admin";
  nav.innerHTML = NAV.map((group) => {
    const items = group.items.filter((it) => !it.admin || isAdmin);
    if (!items.length) return "";
    return `<div class="nav-group-label" data-i18n="${group.group}">${t(group.group)}</div>` +
      items.map((it) =>
        `<a class="nav-item" href="${it.path}" data-path="${it.path}" data-key="${it.key}">
           ${icon(it.icon)}<span data-i18n="${it.i18n}">${t(it.i18n)}</span>
         </a>`
      ).join("");
  }).join("");

  nav.querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      navigate(el.getAttribute("data-path"));
      document.getElementById("sidebar").classList.remove("open");
    });
  });
}

/* ------------------------------------------------------------------ */
/* Notifications badge                                                 */
/* ------------------------------------------------------------------ */
async function refreshNotifBadge() {
  try {
    const data = await api("/api/v1/notifications?limit=1");
    const dot = document.getElementById("notif-dot");
    if (data.unread > 0) {
      dot.textContent = data.unread > 99 ? "99+" : data.unread;
      dot.style.display = "";
    } else {
      dot.style.display = "none";
    }
  } catch { /* ignore */ }
}

function openNotificationsModal() {
  const m = openModal({
    title: t("nav.notifications"),
    size: "wide",
    body: `<div id="notif-list"><div style="padding:30px;text-align:center"><span class="spinner"></span></div></div>`,
    footer: `<button class="btn" data-readall>Mark all read</button><button class="btn btn-primary" data-close2>${t("common.close")}</button>`,
  });
  const load = async () => {
    const data = await api("/api/v1/notifications?limit=50");
    const list = m.body.querySelector("#notif-list");
    if (!data.items.length) {
      list.innerHTML = emptyState("No notifications", "You're all caught up.");
      return;
    }
    list.innerHTML = data.items.map((n) => `
      <div class="list-row" style="${n.read ? "opacity:.6" : ""}">
        <div class="grow">
          <div class="title">${fmt.escape(n.title)}</div>
          <div class="sub">${fmt.escape(n.message)}</div>
          <div class="sub" style="margin-top:3px">${fmt.rel(n.created_at)}</div>
        </div>
        ${n.link ? `<a class="btn btn-sm" href="${fmt.escape(n.link)}" data-navlink>${t("common.view")}</a>` : ""}
        ${!n.read ? `<button class="btn btn-sm btn-ghost" data-read="${n.id}">✓</button>` : ""}
      </div>`).join("");
    list.querySelectorAll("[data-read]").forEach((b) => {
      b.addEventListener("click", async () => {
        await api(`/api/v1/notifications/${b.getAttribute("data-read")}/read`, { method: "POST" });
        load(); refreshNotifBadge();
      });
    });
    list.querySelectorAll("[data-navlink]").forEach((a) => {
      a.addEventListener("click", (e) => { e.preventDefault(); m.close(); navigate(a.getAttribute("href")); });
    });
  };
  load().catch((err) => { m.body.innerHTML = `<p class="text-critical">${fmt.escape(err.message)}</p>`; });
  m.el.querySelector("[data-readall]").addEventListener("click", async () => {
    await api("/api/v1/notifications/read-all", { method: "POST" });
    load(); refreshNotifBadge();
  });
  m.el.querySelector("[data-close2]").addEventListener("click", () => m.close());
}

/* ------------------------------------------------------------------ */
/* Accent picker                                                       */
/* ------------------------------------------------------------------ */
const ACCENTS = ["#6366f1", "#8b5cf6", "#3987e5", "#199e70", "#d95926", "#d55181", "#c98500", "#e66767"];

function openAccentPicker() {
  const body = document.createElement("div");
  body.innerHTML = `<p class="secondary mb-2">Choose an accent color for the interface.</p>
    <div style="display:flex;flex-wrap:wrap;gap:10px">
      ${ACCENTS.map((c) => `<button data-color="${c}" style="width:38px;height:38px;border-radius:10px;border:2px solid ${c === TBM.accent ? "var(--text-primary)" : "transparent"};background:${c};cursor:pointer" aria-label="${c}"></button>`).join("")}
    </div>`;
  const m = openModal({ title: "Accent color", body });
  body.querySelectorAll("[data-color]").forEach((b) => {
    b.addEventListener("click", () => {
      TBM.accent = b.getAttribute("data-color");
      localStorage.setItem("tbm_accent", TBM.accent);
      applyTheme();
      m.close();
      toast("Accent color updated", "success");
    });
  });
}

/* ------------------------------------------------------------------ */
/* Boot                                                                */
/* ------------------------------------------------------------------ */
async function boot() {
  applyTheme();
  applyLanguage();

  let me;
  try {
    me = await api("/api/v1/auth/me");
  } catch (err) {
    if (err.status === 401) { location.href = "/login"; return; }
    document.getElementById("view").innerHTML = emptyState("Cannot reach server", err.message);
    return;
  }
  TBM.user = me.user;
  TBM.csrf = me.csrf_token;
  TBM.permissions = me.permissions || [];

  document.getElementById("user-name").textContent = me.user.full_name || me.user.username;
  document.getElementById("user-role").textContent = me.user.role_name;
  document.getElementById("user-avatar").textContent = (me.user.username || "?").slice(0, 2).toUpperCase();

  renderNav();

  document.getElementById("logout-btn").addEventListener("click", async () => {
    try { await api("/api/v1/auth/logout", { method: "POST" }); } catch {}
    location.href = "/login";
  });

  document.getElementById("notif-btn").addEventListener("click", openNotificationsModal);
  document.getElementById("accent-btn").addEventListener("click", openAccentPicker);

  document.getElementById("theme-btn").addEventListener("click", () => {
    setTheme(TBM.theme === "dark" ? "light" : "dark");
  });

  const langBtn = document.getElementById("lang-btn");
  langBtn.textContent = TBM.lang === "fa" ? "FA" : "EN";
  langBtn.addEventListener("click", () => {
    setLanguage(TBM.lang === "fa" ? "en" : "fa");
    langBtn.textContent = TBM.lang === "fa" ? "FA" : "EN";
    renderNav();
    setActiveNav(location.pathname);
    navigate(location.pathname + location.search, false);
  });

  const menuBtn = document.getElementById("menu-btn");
  const updateMenuVisibility = () => {
    menuBtn.style.display = window.innerWidth <= 900 ? "" : "none";
  };
  updateMenuVisibility();
  window.addEventListener("resize", updateMenuVisibility);
  menuBtn.addEventListener("click", () => document.getElementById("sidebar").classList.toggle("open"));

  document.addEventListener("tbm:lang", () => {
    document.getElementById("page-title").textContent = t(
      (matchRoute(location.pathname.split("?")[0]) || { route: { title: "" } }).route.title
    );
  });

  window.addEventListener("popstate", () => navigate(location.pathname + location.search, false));

  // Intercept internal links
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href^='/']");
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
    if (a.getAttribute("href").startsWith("/api/") || a.getAttribute("href").startsWith("/static/")) return;
    e.preventDefault();
    navigate(a.getAttribute("href"));
  });

  refreshNotifBadge();
  poll("notif", refreshNotifBadge, 30000);

  if (me.user.must_change_password && !location.pathname.startsWith("/security")) {
    toast("You must change your password", "warning", "Security");
  }

  await navigate(location.pathname + location.search, false);

  if (qs("force") === "1") {
    toast("Please set a new password before continuing", "warning");
  }
}

boot();
