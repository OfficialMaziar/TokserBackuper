/* Tokser Backup Manager — core client: API, i18n, formatting, UI primitives. */
"use strict";

/* ------------------------------------------------------------------ */
/* State                                                               */
/* ------------------------------------------------------------------ */
const TBM = {
  csrf: null,
  user: null,
  permissions: [],
  lang: localStorage.getItem("tbm_lang") || "en",
  theme: localStorage.getItem("tbm_theme") || "dark",
  accent: localStorage.getItem("tbm_accent") || "#6366f1",
  pollers: new Map(),
};

/* ------------------------------------------------------------------ */
/* i18n                                                                */
/* ------------------------------------------------------------------ */
const I18N = {
  en: {
    "nav.overview": "Overview", "nav.dashboard": "Dashboard", "nav.monitoring": "Server Monitoring",
    "nav.backups": "Backup", "nav.jobs": "Backup Jobs", "nav.sources": "Backup Sources",
    "nav.history": "Backup History", "nav.restore": "Restore Center", "nav.schedules": "Schedules",
    "nav.delivery": "Delivery", "nav.storage": "Storage", "nav.telegram": "Telegram",
    "nav.notifications": "Notifications", "nav.system": "System", "nav.logs": "Activity Logs",
    "nav.users": "Users & Roles", "nav.security": "Security", "nav.settings": "Settings",
    "nav.apidocs": "API Documentation", "nav.about": "About",
    "common.save": "Save", "common.cancel": "Cancel", "common.delete": "Delete", "common.edit": "Edit",
    "common.create": "Create", "common.close": "Close", "common.confirm": "Confirm",
    "common.search": "Search…", "common.loading": "Loading…", "common.none": "None",
    "common.enabled": "Enabled", "common.disabled": "Disabled", "common.yes": "Yes", "common.no": "No",
    "common.actions": "Actions", "common.name": "Name", "common.status": "Status",
    "common.size": "Size", "common.date": "Date", "common.duration": "Duration",
    "common.never": "Never", "common.all": "All", "common.back": "Back", "common.refresh": "Refresh",
    "common.run": "Run now", "common.pause": "Pause", "common.resume": "Resume",
    "common.duplicate": "Duplicate", "common.download": "Download", "common.retry": "Retry",
    "common.view": "View", "common.add": "Add", "common.remove": "Remove", "common.test": "Test",
    "common.saved": "Saved successfully", "common.deleted": "Deleted", "common.error": "Something went wrong",
    "common.noData": "No data yet", "common.required": "This field is required",
    "common.logout": "Sign out", "common.profile": "Profile", "common.language": "Language",
    "common.theme": "Theme", "common.dark": "Dark", "common.light": "Light",
    "status.success": "Success", "status.failed": "Failed", "status.running": "Running",
    "status.pending": "Pending", "status.cancelled": "Cancelled", "status.partial": "Partial",
    "status.idle": "Idle", "status.paused": "Paused", "status.disabled": "Disabled",
    "status.error": "Error", "status.unknown": "Unknown",
    "dash.title": "Dashboard", "dash.subtitle": "Live system and backup status",
    "dash.totalJobs": "Total Backup Jobs", "dash.successful": "Successful Backups",
    "dash.failed": "Failed Backups", "dash.running": "Running Backups",
    "dash.totalSize": "Total Backup Size", "dash.freeSpace": "Available Disk Space",
    "dash.lastBackup": "Last Backup", "dash.nextBackup": "Next Scheduled Backup",
    "dash.successRate": "Backup Success Rate", "dash.uptime": "Server Uptime",
    "dash.activity": "Backup Activity", "dash.activitySub": "Successful vs failed runs, last 14 days",
    "dash.storage": "Backup Storage Usage", "dash.sizeHistory": "Backup Size History",
    "dash.recent": "Recent Activity", "dash.systemHealth": "System Health",
    "dash.cpu": "CPU", "dash.memory": "Memory", "dash.disk": "Disk",
    "jobs.title": "Backup Jobs", "jobs.new": "New Backup Job", "jobs.edit": "Edit Backup Job",
    "jobs.empty": "No backup jobs yet", "jobs.emptyHint": "Create your first job to start protecting your data.",
    "jobs.sources": "Sources", "jobs.schedule": "Schedule", "jobs.lastRun": "Last run",
    "jobs.nextRun": "Next run", "jobs.runs": "Runs",
    "backups.title": "Backup History", "backups.empty": "No backups recorded yet",
    "backups.detail": "Backup Details", "backups.files": "Files", "backups.archive": "Archive contents",
    "backups.verify": "Verify archive", "backups.restore": "Restore", "backups.export": "Export",
    "restore.title": "Restore Center", "restore.destination": "Destination path",
    "restore.selectFiles": "Select files to restore (empty = everything)",
    "restore.overwrite": "Overwrite existing files", "restore.safety": "Create safety backup of destination first",
    "restore.start": "Start restore", "restore.history": "Restore history",
    "storage.title": "Storage Destinations", "storage.new": "Add Storage",
    "telegram.title": "Telegram", "telegram.new": "Add Telegram Destination",
    "notif.title": "Notification Settings", "logs.title": "Activity Logs",
    "users.title": "Users & Roles", "security.title": "Security",
    "settings.title": "General Settings", "about.title": "About Tokser Backup Manager",
    "monitoring.title": "Server Monitoring", "schedules.title": "Schedule Management",
    "sources.title": "Backup Sources",
  },
  fa: {
    "nav.overview": "نمای کلی", "nav.dashboard": "داشبورد", "nav.monitoring": "مانیتورینگ سرور",
    "nav.backups": "پشتیبان‌گیری", "nav.jobs": "کارهای بکاپ", "nav.sources": "منابع بکاپ",
    "nav.history": "تاریخچه بکاپ", "nav.restore": "مرکز بازیابی", "nav.schedules": "زمان‌بندی‌ها",
    "nav.delivery": "ارسال", "nav.storage": "فضای ذخیره‌سازی", "nav.telegram": "تلگرام",
    "nav.notifications": "اعلان‌ها", "nav.system": "سیستم", "nav.logs": "گزارش فعالیت‌ها",
    "nav.users": "کاربران و نقش‌ها", "nav.security": "امنیت", "nav.settings": "تنظیمات",
    "nav.apidocs": "مستندات API", "nav.about": "درباره",
    "common.save": "ذخیره", "common.cancel": "انصراف", "common.delete": "حذف", "common.edit": "ویرایش",
    "common.create": "ایجاد", "common.close": "بستن", "common.confirm": "تأیید",
    "common.search": "جستجو…", "common.loading": "در حال بارگذاری…", "common.none": "هیچ",
    "common.enabled": "فعال", "common.disabled": "غیرفعال", "common.yes": "بله", "common.no": "خیر",
    "common.actions": "عملیات", "common.name": "نام", "common.status": "وضعیت",
    "common.size": "حجم", "common.date": "تاریخ", "common.duration": "مدت",
    "common.never": "هرگز", "common.all": "همه", "common.back": "بازگشت", "common.refresh": "بروزرسانی",
    "common.run": "اجرای فوری", "common.pause": "توقف", "common.resume": "ادامه",
    "common.duplicate": "کپی", "common.download": "دانلود", "common.retry": "تلاش مجدد",
    "common.view": "مشاهده", "common.add": "افزودن", "common.remove": "حذف", "common.test": "تست",
    "common.saved": "با موفقیت ذخیره شد", "common.deleted": "حذف شد", "common.error": "خطایی رخ داد",
    "common.noData": "داده‌ای موجود نیست", "common.required": "این فیلد الزامی است",
    "common.logout": "خروج", "common.profile": "پروفایل", "common.language": "زبان",
    "common.theme": "پوسته", "common.dark": "تیره", "common.light": "روشن",
    "status.success": "موفق", "status.failed": "ناموفق", "status.running": "در حال اجرا",
    "status.pending": "در انتظار", "status.cancelled": "لغو شده", "status.partial": "ناقص",
    "status.idle": "آماده", "status.paused": "متوقف", "status.disabled": "غیرفعال",
    "status.error": "خطا", "status.unknown": "نامشخص",
    "dash.title": "داشبورد", "dash.subtitle": "وضعیت زنده سیستم و بکاپ",
    "dash.totalJobs": "کل کارهای بکاپ", "dash.successful": "بکاپ‌های موفق",
    "dash.failed": "بکاپ‌های ناموفق", "dash.running": "بکاپ‌های در حال اجرا",
    "dash.totalSize": "حجم کل بکاپ‌ها", "dash.freeSpace": "فضای آزاد دیسک",
    "dash.lastBackup": "آخرین بکاپ", "dash.nextBackup": "بکاپ زمان‌بندی‌شده بعدی",
    "dash.successRate": "نرخ موفقیت بکاپ", "dash.uptime": "زمان فعالیت سرور",
    "dash.activity": "فعالیت بکاپ", "dash.activitySub": "موفق در برابر ناموفق، ۱۴ روز اخیر",
    "dash.storage": "مصرف فضای بکاپ", "dash.sizeHistory": "تاریخچه حجم بکاپ",
    "dash.recent": "فعالیت اخیر", "dash.systemHealth": "سلامت سیستم",
    "dash.cpu": "پردازنده", "dash.memory": "حافظه", "dash.disk": "دیسک",
    "jobs.title": "کارهای بکاپ", "jobs.new": "کار بکاپ جدید", "jobs.edit": "ویرایش کار بکاپ",
    "jobs.empty": "هنوز کار بکاپی وجود ندارد", "jobs.emptyHint": "اولین کار را برای محافظت از داده‌ها ایجاد کنید.",
    "jobs.sources": "منابع", "jobs.schedule": "زمان‌بندی", "jobs.lastRun": "آخرین اجرا",
    "jobs.nextRun": "اجرای بعدی", "jobs.runs": "اجراها",
    "backups.title": "تاریخچه بکاپ", "backups.empty": "هنوز بکاپی ثبت نشده",
    "backups.detail": "جزئیات بکاپ", "backups.files": "فایل‌ها", "backups.archive": "محتوای آرشیو",
    "backups.verify": "بررسی آرشیو", "backups.restore": "بازیابی", "backups.export": "خروجی",
    "restore.title": "مرکز بازیابی", "restore.destination": "مسیر مقصد",
    "restore.selectFiles": "فایل‌های موردنظر برای بازیابی (خالی = همه)",
    "restore.overwrite": "بازنویسی فایل‌های موجود", "restore.safety": "ابتدا از مقصد بکاپ ایمنی گرفته شود",
    "restore.start": "شروع بازیابی", "restore.history": "تاریخچه بازیابی",
    "storage.title": "مقاصد ذخیره‌سازی", "storage.new": "افزودن فضای ذخیره‌سازی",
    "telegram.title": "تلگرام", "telegram.new": "افزودن مقصد تلگرام",
    "notif.title": "تنظیمات اعلان", "logs.title": "گزارش فعالیت‌ها",
    "users.title": "کاربران و نقش‌ها", "security.title": "امنیت",
    "settings.title": "تنظیمات عمومی", "about.title": "درباره Tokser Backup Manager",
    "monitoring.title": "مانیتورینگ سرور", "schedules.title": "مدیریت زمان‌بندی",
    "sources.title": "منابع بکاپ",
  },
};

function t(key, fallback) {
  const dict = I18N[TBM.lang] || I18N.en;
  return dict[key] || I18N.en[key] || fallback || key;
}

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */
const fmt = {
  bytes(n) {
    n = Number(n || 0);
    if (!n) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB", "PB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  },
  num(n) { return Number(n || 0).toLocaleString(TBM.lang === "fa" ? "fa-IR" : "en-US"); },
  pct(n) { return `${Number(n || 0).toFixed(1)}%`; },
  date(iso, withTime = true) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d)) return "—";
    const opts = { year: "numeric", month: "short", day: "2-digit" };
    if (withTime) { opts.hour = "2-digit"; opts.minute = "2-digit"; }
    return d.toLocaleString(TBM.lang === "fa" ? "fa-IR" : "en-US", opts);
  },
  rel(iso) {
    if (!iso) return "—";
    const d = new Date(iso).getTime();
    if (isNaN(d)) return "—";
    const diff = Math.round((d - Date.now()) / 1000);
    const abs = Math.abs(diff);
    const rtf = new Intl.RelativeTimeFormat(TBM.lang === "fa" ? "fa" : "en", { numeric: "auto" });
    if (abs < 60) return rtf.format(diff, "second");
    if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
    if (abs < 2592000) return rtf.format(Math.round(diff / 86400), "day");
    return rtf.format(Math.round(diff / 2592000), "month");
  },
  duration(sec) {
    sec = Math.round(Number(sec || 0));
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60), s = sec % 60;
    if (m < 60) return `${m}m ${s}s`;
    const h = Math.floor(m / 60);
    return `${h}h ${m % 60}m`;
  },
  uptime(sec) {
    sec = Math.round(Number(sec || 0));
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  },
  escape(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  },
};

/* ------------------------------------------------------------------ */
/* API client                                                          */
/* ------------------------------------------------------------------ */
class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function api(path, options = {}) {
  const opts = {
    method: options.method || "GET",
    headers: { "Accept": "application/json", ...(options.headers || {}) },
    credentials: "same-origin",
  };
  if (options.body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(options.body);
  }
  if (opts.method !== "GET" && opts.method !== "HEAD" && TBM.csrf) {
    opts.headers["X-CSRF-Token"] = TBM.csrf;
  }
  let resp;
  try {
    resp = await fetch(path, opts);
  } catch (err) {
    throw new ApiError("Network error — cannot reach the server", 0, String(err));
  }
  if (resp.status === 401) {
    if (!location.pathname.startsWith("/login") && !location.pathname.startsWith("/setup")) {
      location.href = "/login";
    }
    throw new ApiError("Authentication required", 401);
  }
  const isJson = (resp.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await resp.json().catch(() => null) : await resp.text();
  if (!resp.ok) {
    let msg = "Request failed";
    if (payload && typeof payload === "object") {
      if (typeof payload.detail === "string") msg = payload.detail;
      else if (Array.isArray(payload.detail)) {
        msg = payload.detail.map(d => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
      }
    } else if (typeof payload === "string" && payload) {
      msg = payload.slice(0, 200);
    }
    throw new ApiError(msg, resp.status, payload);
  }
  return payload;
}

/* ------------------------------------------------------------------ */
/* Toasts                                                              */
/* ------------------------------------------------------------------ */
const ICONS = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>',
};

function toast(message, type = "info", title = "") {
  let stack = document.querySelector(".toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "toast-stack";
    document.body.appendChild(stack);
  }
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icon = type === "success" ? ICONS.check : type === "error" ? ICONS.x
    : type === "warning" ? ICONS.alert : ICONS.info;
  el.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <div class="toast-body">
      ${title ? `<div class="toast-title">${fmt.escape(title)}</div>` : ""}
      <div class="toast-msg">${fmt.escape(message)}</div>
    </div>
    <button class="toast-close" aria-label="Close">&times;</button>`;
  stack.appendChild(el);
  const remove = () => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 200);
  };
  el.querySelector(".toast-close").addEventListener("click", remove);
  setTimeout(remove, type === "error" ? 7000 : 4200);
}

/* ------------------------------------------------------------------ */
/* Modal                                                               */
/* ------------------------------------------------------------------ */
function openModal({ title, body, footer, size = "", onClose }) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.innerHTML = `
    <div class="modal ${size}" role="dialog" aria-modal="true">
      <div class="modal-head">
        <h3>${fmt.escape(title || "")}</h3>
        <div class="spacer"></div>
        <button class="btn btn-ghost btn-icon btn-sm" data-close aria-label="Close">&times;</button>
      </div>
      <div class="modal-body"></div>
      ${footer ? '<div class="modal-foot"></div>' : ""}
    </div>`;
  const modal = backdrop.querySelector(".modal");
  const bodyEl = modal.querySelector(".modal-body");
  if (typeof body === "string") bodyEl.innerHTML = body;
  else if (body) bodyEl.appendChild(body);
  if (footer) {
    const footEl = modal.querySelector(".modal-foot");
    if (typeof footer === "string") footEl.innerHTML = footer;
    else footEl.appendChild(footer);
  }
  const close = () => {
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  modal.querySelector("[data-close]").addEventListener("click", close);
  document.body.appendChild(backdrop);
  const focusable = modal.querySelector("input, select, textarea, button.btn-primary");
  if (focusable) setTimeout(() => focusable.focus(), 60);
  return { el: modal, body: bodyEl, close };
}

function confirmDialog({ title, message, confirmText, danger = true }) {
  return new Promise((resolve) => {
    const footer = document.createElement("div");
    footer.style.display = "contents";
    footer.innerHTML = `
      <button class="btn" data-cancel>${t("common.cancel")}</button>
      <button class="btn ${danger ? "btn-danger" : "btn-primary"}" data-ok>${fmt.escape(confirmText || t("common.confirm"))}</button>`;
    const m = openModal({
      title: title || t("common.confirm"),
      body: `<p class="secondary">${fmt.escape(message || "")}</p>`,
      footer,
      onClose: () => resolve(false),
    });
    footer.querySelector("[data-cancel]").addEventListener("click", () => { m.close(); resolve(false); });
    footer.querySelector("[data-ok]").addEventListener("click", () => { m.close(); resolve(true); });
  });
}

/* ------------------------------------------------------------------ */
/* Status helpers                                                      */
/* ------------------------------------------------------------------ */
function statusBadge(status) {
  const s = String(status || "unknown").toLowerCase();
  const label = t(`status.${s}`, s);
  return `<span class="badge ${s}">${fmt.escape(label)}</span>`;
}

function emptyState(title, hint, actionHtml = "") {
  return `<div class="empty-state">
    <div class="icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/></svg></div>
    <h3>${fmt.escape(title)}</h3>
    <p>${fmt.escape(hint || "")}</p>
    ${actionHtml}
  </div>`;
}

function skeletonRows(count = 5, cols = 5) {
  let html = "";
  for (let i = 0; i < count; i++) {
    html += "<tr>";
    for (let c = 0; c < cols; c++) {
      html += `<td><div class="skeleton" style="height:14px;width:${60 + Math.random() * 35}%"></div></td>`;
    }
    html += "</tr>";
  }
  return html;
}

/* ------------------------------------------------------------------ */
/* Theme / language                                                    */
/* ------------------------------------------------------------------ */
function applyTheme() {
  document.documentElement.setAttribute("data-theme", TBM.theme);
  document.documentElement.style.setProperty("--accent", TBM.accent);
  const hover = shade(TBM.accent, 12);
  document.documentElement.style.setProperty("--accent-hover", hover);
  document.documentElement.style.setProperty("--accent-soft", hexA(TBM.accent, 0.14));
  document.documentElement.style.setProperty("--accent-ring", hexA(TBM.accent, 0.4));
}

function applyLanguage() {
  document.documentElement.lang = TBM.lang;
  document.documentElement.dir = TBM.lang === "fa" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    const val = t(key);
    if (val) el.textContent = val;
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.getAttribute("data-i18n-placeholder"));
  });
}

function setTheme(theme) {
  TBM.theme = theme;
  localStorage.setItem("tbm_theme", theme);
  applyTheme();
  document.dispatchEvent(new CustomEvent("tbm:theme", { detail: theme }));
}

function setLanguage(lang) {
  TBM.lang = lang;
  localStorage.setItem("tbm_lang", lang);
  applyLanguage();
  document.dispatchEvent(new CustomEvent("tbm:lang", { detail: lang }));
}

function shade(hex, percent) {
  const { r, g, b } = hexToRgb(hex);
  const amt = Math.round(2.55 * percent);
  const clamp = (v) => Math.max(0, Math.min(255, v + amt));
  return rgbToHex(clamp(r), clamp(g), clamp(b));
}
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const full = h.length === 3 ? h.split("").map(c => c + c).join("") : h;
  return { r: parseInt(full.slice(0, 2), 16), g: parseInt(full.slice(2, 4), 16), b: parseInt(full.slice(4, 6), 16) };
}
function rgbToHex(r, g, b) {
  return "#" + [r, g, b].map(v => v.toString(16).padStart(2, "0")).join("");
}
function hexA(hex, alpha) {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${r},${g},${b},${alpha})`;
}

/* ------------------------------------------------------------------ */
/* Polling                                                             */
/* ------------------------------------------------------------------ */
function poll(name, fn, intervalMs) {
  stopPoll(name);
  const id = setInterval(() => { fn().catch(() => {}); }, intervalMs);
  TBM.pollers.set(name, id);
  return id;
}
function stopPoll(name) {
  const id = TBM.pollers.get(name);
  if (id) { clearInterval(id); TBM.pollers.delete(name); }
}
function stopAllPolls() {
  TBM.pollers.forEach((id) => clearInterval(id));
  TBM.pollers.clear();
}

/* ------------------------------------------------------------------ */
/* Misc                                                                */
/* ------------------------------------------------------------------ */
function debounce(fn, ms = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function downloadUrl(path) {
  window.location.href = path;
}

function qs(name) {
  return new URLSearchParams(location.search).get(name);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard", "success");
  } catch {
    toast("Copy failed", "error");
  }
}

applyTheme();
