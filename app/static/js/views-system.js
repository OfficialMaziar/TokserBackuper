/* Storage, Telegram, Notifications, Logs views. */
"use strict";

registerViews({
  async storage(el) {
    el.innerHTML = `
      <div class="toolbar">
        <div class="spacer"></div>
        <button class="btn btn-primary" id="new-storage">${icon("database")}<span>${t("storage.new")}</span></button>
      </div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>${t("common.name")}</th><th>Type</th><th>${t("common.status")}</th>
          <th>Last test</th><th>${t("common.actions")}</th>
        </tr></thead><tbody id="storage-body">${skeletonRows(3, 5)}</tbody></table>
      </div></div></div>`;

    const load = async () => {
      const rows = await api("/api/v1/storage");
      const body = document.getElementById("storage-body");
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="5">${emptyState("No storage destinations", "Add a local, SFTP, FTP or S3-compatible destination.")}</td></tr>`;
        return;
      }
      body.innerHTML = rows.map((s) => `
        <tr>
          <td class="primary">${fmt.escape(s.name)}${s.is_default ? ' <span class="badge neutral">default</span>' : ""}</td>
          <td class="mono">${fmt.escape(s.storage_type)}</td>
          <td>${s.enabled ? '<span class="badge success">enabled</span>' : '<span class="badge disabled">disabled</span>'}</td>
          <td class="muted" style="font-size:12px">${s.last_test_at ? (s.last_test_ok ? '<span class="text-good">ok</span>' : '<span class="text-critical">failed</span>') + " · " + fmt.rel(s.last_test_at) : "—"}</td>
          <td class="actions">
            <button class="btn btn-sm btn-ghost" data-test="${s.id}">${t("common.test")}</button>
            <button class="btn btn-sm btn-ghost" data-edit="${s.id}">${t("common.edit")}</button>
            <button class="btn btn-sm btn-ghost" data-del="${s.id}">✕</button>
          </td>
        </tr>`).join("");

      body.querySelectorAll("[data-test]").forEach((b) => b.addEventListener("click", async () => {
        b.disabled = true; b.innerHTML = '<span class="spinner"></span>';
        try {
          const r = await api(`/api/v1/storage/${b.dataset.test}/test`, { method: "POST" });
          toast(r.message, r.ok ? "success" : "error");
          load();
        } catch (e) { toast(e.message, "error"); b.disabled = false; b.textContent = t("common.test"); }
      }));
      body.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => {
        const s = rows.find((x) => x.id === Number(b.dataset.edit));
        openStorageModal(s, load);
      }));
      body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
        if (!(await confirmDialog({ title: "Delete storage", message: "Only unused destinations can be deleted.", confirmText: "Delete" }))) return;
        try { await api(`/api/v1/storage/${b.dataset.del}`, { method: "DELETE" }); toast(t("common.deleted"), "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
    };

    document.getElementById("new-storage").addEventListener("click", () => openStorageModal(null, load));
    await load();
  },

  async telegram(el) {
    el.innerHTML = `
      <div class="toolbar">
        <div class="spacer"></div>
        <button class="btn btn-primary" id="new-tg">${icon("send")}<span>${t("telegram.new")}</span></button>
      </div>
      <div class="alert info">${ICONS.info}<span>Cloud Bot API limits uploads to 50 MB per file. Larger archives are split automatically and every part is tracked. A self-hosted local Bot API server raises this limit.</span></div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>${t("common.name")}</th><th>Chat ID</th><th>Bot token</th><th>${t("common.status")}</th><th>${t("common.actions")}</th>
        </tr></thead><tbody id="tg-body">${skeletonRows(2, 5)}</tbody></table>
      </div></div></div>`;

    const load = async () => {
      const rows = await api("/api/v1/telegram");
      const body = document.getElementById("tg-body");
      if (!rows.length) {
        body.innerHTML = `<tr><td colspan="5">${emptyState("No Telegram destinations", "Add a bot token and chat ID to deliver backups.")}</td></tr>`;
        return;
      }
      body.innerHTML = rows.map((d) => `
        <tr>
          <td class="primary">${fmt.escape(d.name)}</td>
          <td class="mono">${fmt.escape(d.chat_id || "—")}</td>
          <td class="mono muted">${fmt.escape(d.bot_token_masked || "—")}</td>
          <td>${d.enabled ? '<span class="badge success">enabled</span>' : '<span class="badge disabled">disabled</span>'}
            ${d.last_test_at ? `<div class="muted" style="font-size:11px">${d.last_test_ok ? '<span class="text-good">connected</span>' : '<span class="text-critical">error</span>'}</div>` : ""}</td>
          <td class="actions">
            <button class="btn btn-sm btn-ghost" data-test="${d.id}">${t("common.test")}</button>
            <button class="btn btn-sm btn-ghost" data-msg="${d.id}">Send test</button>
            <button class="btn btn-sm btn-ghost" data-edit="${d.id}">${t("common.edit")}</button>
            <button class="btn btn-sm btn-ghost" data-del="${d.id}">✕</button>
          </td>
        </tr>`).join("");

      body.querySelectorAll("[data-test]").forEach((b) => b.addEventListener("click", async () => {
        b.disabled = true; b.innerHTML = '<span class="spinner"></span>';
        try { const r = await api(`/api/v1/telegram/${b.dataset.test}/test`, { method: "POST" }); toast(r.message, r.ok ? "success" : "error"); load(); }
        catch (e) { toast(e.message, "error"); b.disabled = false; b.textContent = t("common.test"); }
      }));
      body.querySelectorAll("[data-msg]").forEach((b) => b.addEventListener("click", async () => {
        try { const r = await api(`/api/v1/telegram/${b.dataset.msg}/send-test`, { method: "POST" }); toast(r.message, r.ok ? "success" : "error"); }
        catch (e) { toast(e.message, "error"); }
      }));
      body.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => {
        const d = rows.find((x) => x.id === Number(b.dataset.edit));
        openTelegramModal(d, load);
      }));
      body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
        if (!(await confirmDialog({ title: "Delete destination", message: "Jobs using it must be updated first.", confirmText: "Delete" }))) return;
        try { await api(`/api/v1/telegram/${b.dataset.del}`, { method: "DELETE" }); toast(t("common.deleted"), "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
    };

    document.getElementById("new-tg").addEventListener("click", () => openTelegramModal(null, load));
    await load();
  },

  async notifications(el) {
    const settings = await api("/api/v1/notifications/settings");
    const isAdmin = TBM.user && TBM.user.role_name === "admin";

    el.innerHTML = `
      <div class="card mb-2"><div class="card-header"><h3>Event channels</h3>
        <div class="spacer"></div><span class="muted" style="font-size:12px">Choose where each event is delivered</span></div>
        <div class="card-body tight"><div class="table-wrap"><table class="data">
          <thead><tr><th>Event</th><th>Enabled</th><th>In-app</th><th>Telegram</th><th>Email</th></tr></thead>
          <tbody>${settings.map((s) => `
            <tr data-event="${fmt.escape(s.event)}">
              <td class="primary">${fmt.escape(s.label)}</td>
              <td><label class="switch"><input type="checkbox" data-ch="enabled" ${s.enabled ? "checked" : ""} ${isAdmin ? "" : "disabled"}><span class="track"></span></label></td>
              <td><label class="switch"><input type="checkbox" data-ch="in_app" ${s.in_app ? "checked" : ""} ${isAdmin ? "" : "disabled"}><span class="track"></span></label></td>
              <td><label class="switch"><input type="checkbox" data-ch="telegram" ${s.telegram ? "checked" : ""} ${isAdmin ? "" : "disabled"}><span class="track"></span></label></td>
              <td><label class="switch"><input type="checkbox" data-ch="email" ${s.email ? "checked" : ""} ${isAdmin ? "" : "disabled"}><span class="track"></span></label></td>
            </tr>`).join("")}
          </tbody></table></div></div>
      </div>
      <div class="card"><div class="card-header"><h3>Test delivery</h3></div>
        <div class="card-body flex" style="gap:10px;flex-wrap:wrap">
          <button class="btn" data-test-ch="in_app">Test in-app</button>
          <button class="btn" data-test-ch="telegram">Test Telegram</button>
          <button class="btn" data-test-ch="email">Test email</button>
        </div>
      </div>`;

    el.querySelectorAll("[data-ch]").forEach((input) => input.addEventListener("change", async () => {
      const row = input.closest("tr");
      const event = row.dataset.event;
      const payload = { event };
      row.querySelectorAll("[data-ch]").forEach((i) => { payload[i.dataset.ch] = i.checked; });
      try { await api("/api/v1/notifications/settings", { method: "PUT", body: payload }); toast(t("common.saved"), "success"); }
      catch (e) { toast(e.message, "error"); input.checked = !input.checked; }
    }));

    el.querySelectorAll("[data-test-ch]").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true; b.innerHTML = '<span class="spinner"></span>';
      try { const r = await api("/api/v1/notifications/test", { method: "POST", body: { channel: b.dataset.testCh } }); toast(r.message, r.ok ? "success" : "error"); }
      catch (e) { toast(e.message, "error"); }
      b.disabled = false; b.textContent = `Test ${b.dataset.testCh.replace("_", "-")}`;
    }));
  },

  async logs(el) {
    el.innerHTML = `
      <div class="toolbar">
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input type="search" id="log-search" placeholder="${t("common.search")}">
        </div>
        <select id="log-level" style="width:auto">
          <option value="">${t("common.all")}</option>
          <option value="info">info</option><option value="warning">warning</option><option value="error">error</option>
        </select>
        <div class="spacer"></div>
        <button class="btn" id="log-download">${t("common.download")} log</button>
      </div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>${t("common.date")}</th><th>User</th><th>Action</th><th>Detail</th><th>IP</th><th>Level</th>
        </tr></thead><tbody id="log-body">${skeletonRows(8, 6)}</tbody></table>
      </div></div>
      <div class="flex" style="justify-content:space-between;padding:12px 16px;border-top:1px solid var(--border)">
        <span class="muted" id="log-total" style="font-size:12px"></span>
        <div class="flex" style="gap:6px"><button class="btn btn-sm" id="log-prev">←</button><button class="btn btn-sm" id="log-next">→</button></div>
      </div></div>`;

    let offset = 0;
    const limit = 100;
    const load = async () => {
      const params = new URLSearchParams({ limit, offset });
      const q = document.getElementById("log-search").value.trim();
      const level = document.getElementById("log-level").value;
      if (q) params.set("q", q);
      if (level) params.set("level", level);
      const data = await api(`/api/v1/logs?${params}`);
      document.getElementById("log-total").textContent = `${data.total} entries`;
      const body = document.getElementById("log-body");
      if (!data.items.length) { body.innerHTML = `<tr><td colspan="6">${emptyState("No log entries", "")}</td></tr>`; return; }
      body.innerHTML = data.items.map((l) => `
        <tr>
          <td class="num muted nowrap">${fmt.date(l.created_at)}</td>
          <td class="primary">${fmt.escape(l.username)}</td>
          <td class="mono" style="font-size:11.5px">${fmt.escape(l.action)}</td>
          <td class="secondary truncate" style="max-width:420px">${fmt.escape(l.detail)}</td>
          <td class="mono muted">${fmt.escape(l.ip_address || "—")}</td>
          <td>${l.level === "error" ? '<span class="badge failed">error</span>' : l.level === "warning" ? '<span class="badge pending">warning</span>' : '<span class="badge neutral">info</span>'}</td>
        </tr>`).join("");
    };
    document.getElementById("log-prev").addEventListener("click", () => { offset = Math.max(0, offset - limit); load(); });
    document.getElementById("log-next").addEventListener("click", () => { offset += limit; load(); });
    document.getElementById("log-search").addEventListener("input", debounce(() => { offset = 0; load(); }, 250));
    document.getElementById("log-level").addEventListener("change", () => { offset = 0; load(); });
    document.getElementById("log-download").addEventListener("click", () => downloadUrl("/api/v1/logs/download"));
    await load();
  },
});

/* ------------------------------------------------------------------ */
/* Storage modal                                                       */
/* ------------------------------------------------------------------ */
function openStorageModal(existing, onSaved) {
  const types = ["local", "sftp", "ftp", "s3", "minio"];
  const cfg = existing ? existing.config || {} : {};
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="form-grid">
      <div class="form-row">
        <div class="field"><label>${t("common.name")} *</label><input id="st-name" value="${fmt.escape(existing ? existing.name : "")}" maxlength="128"></div>
        <div class="field"><label>Type</label><select id="st-type">${types.map((x) => `<option value="${x}" ${existing && existing.storage_type === x ? "selected" : ""}>${x}</option>`).join("")}</select></div>
      </div>
      <div id="st-fields"></div>
      <label class="checkbox"><input type="checkbox" id="st-enabled" ${!existing || existing.enabled ? "checked" : ""}><span>${t("common.enabled")}</span></label>
      <label class="checkbox"><input type="checkbox" id="st-default" ${existing && existing.is_default ? "checked" : ""}><span>Default destination</span></label>
    </div>`;

  const fieldsEl = body.querySelector("#st-fields");
  const renderFields = () => {
    const type = body.querySelector("#st-type").value;
    const v = (k, d = "") => fmt.escape(cfg[k] != null ? cfg[k] : d);
    let html = "";
    if (type === "local") {
      html = `<div class="field"><label>Directory path *</label><input id="st-path" class="mono" value="${v("path")}" placeholder="/var/backups/tokser"></div>`;
    } else if (type === "sftp" || type === "ftp") {
      html = `<div class="form-row">
          <div class="field"><label>Host *</label><input id="st-host" value="${v("host")}" placeholder="backup.example.com"></div>
          <div class="field"><label>Port</label><input id="st-port" type="number" value="${v("port", type === "sftp" ? 22 : 21)}"></div>
        </div>
        <div class="form-row" style="margin-top:10px">
          <div class="field"><label>Username</label><input id="st-user" value="${v("username")}"></div>
          <div class="field"><label>Password</label><input id="st-pass" type="password" autocomplete="new-password" placeholder="${existing ? "leave blank to keep" : ""}"></div>
        </div>
        <div class="field" style="margin-top:10px"><label>Remote path</label><input id="st-path" class="mono" value="${v("path", "/")}"></div>
        ${type === "ftp" ? `<label class="checkbox mt-1"><input type="checkbox" id="st-tls" ${cfg.tls !== false ? "checked" : ""}><span>Use FTPS (TLS)</span></label>` : ""}
        ${type === "sftp" ? `<div class="field" style="margin-top:10px"><label>Private key path (optional)</label><input id="st-key" class="mono" value="${v("private_key_path")}"></div>` : ""}`;
    } else {
      html = `<div class="form-row">
          <div class="field"><label>Endpoint</label><input id="st-endpoint" class="mono" value="${v("endpoint")}" placeholder="https://s3.example.com"></div>
          <div class="field"><label>Region</label><input id="st-region" value="${v("region", "us-east-1")}"></div>
        </div>
        <div class="form-row" style="margin-top:10px">
          <div class="field"><label>Bucket *</label><input id="st-bucket" value="${v("bucket")}"></div>
          <div class="field"><label>Prefix</label><input id="st-prefix" value="${v("prefix")}" placeholder="tokser/backups"></div>
        </div>
        <div class="form-row" style="margin-top:10px">
          <div class="field"><label>Access key</label><input id="st-ak" value="${v("access_key")}"></div>
          <div class="field"><label>Secret key</label><input id="st-sk" type="password" autocomplete="new-password" placeholder="${existing ? "leave blank to keep" : ""}"></div>
        </div>`;
    }
    fieldsEl.innerHTML = html;
  };
  body.querySelector("#st-type").addEventListener("change", renderFields);
  renderFields();

  const footer = document.createElement("div");
  footer.style.display = "contents";
  footer.innerHTML = `<button class="btn" data-test>${t("common.test")}</button><div style="flex:1"></div>
    <button class="btn" data-cancel>${t("common.cancel")}</button><button class="btn btn-primary" data-save>${t("common.save")}</button>`;
  const m = openModal({ title: existing ? "Edit storage" : "Add storage", body, footer, size: "wide" });

  const collect = () => {
    const type = body.querySelector("#st-type").value;
    const val = (id) => { const el = body.querySelector(id); return el ? el.value.trim() : ""; };
    const config = {};
    const secrets = {};
    if (type === "local") config.path = val("#st-path");
    else if (type === "sftp" || type === "ftp") {
      config.host = val("#st-host");
      config.port = Number(val("#st-port")) || (type === "sftp" ? 22 : 21);
      config.username = val("#st-user");
      config.path = val("#st-path") || "/";
      if (type === "ftp") config.tls = body.querySelector("#st-tls").checked;
      if (type === "sftp") config.private_key_path = val("#st-key");
      if (val("#st-pass")) secrets.password = val("#st-pass");
    } else {
      config.endpoint = val("#st-endpoint");
      config.region = val("#st-region") || "us-east-1";
      config.bucket = val("#st-bucket");
      config.prefix = val("#st-prefix");
      config.access_key = val("#st-ak");
      if (val("#st-sk")) secrets.secret_key = val("#st-sk");
    }
    return {
      name: val("#st-name"),
      storage_type: type,
      enabled: body.querySelector("#st-enabled").checked,
      is_default: body.querySelector("#st-default").checked,
      config, secrets,
    };
  };

  footer.querySelector("[data-test]").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      const r = await api("/api/v1/storage/test-unsaved", { method: "POST", body: collect() });
      toast(r.message, r.ok ? "success" : "error");
    } catch (err) { toast(err.message, "error"); }
    btn.disabled = false; btn.textContent = t("common.test");
  });
  footer.querySelector("[data-cancel]").addEventListener("click", () => m.close());
  footer.querySelector("[data-save]").addEventListener("click", async () => {
    const payload = collect();
    if (!payload.name) { toast("Name is required", "error"); return; }
    try {
      if (existing) await api(`/api/v1/storage/${existing.id}`, { method: "PUT", body: payload });
      else await api("/api/v1/storage", { method: "POST", body: payload });
      toast(t("common.saved"), "success");
      m.close();
      onSaved();
    } catch (err) { toast(err.message, "error"); }
  });
}

/* ------------------------------------------------------------------ */
/* Telegram modal                                                      */
/* ------------------------------------------------------------------ */
function openTelegramModal(existing, onSaved) {
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="form-grid">
      <div class="field"><label>${t("common.name")} *</label><input id="tg-name" value="${fmt.escape(existing ? existing.name : "")}" maxlength="128"></div>
      <div class="field"><label>Bot token ${existing ? "" : "*"}</label>
        <input id="tg-token" type="password" autocomplete="new-password" placeholder="${existing ? "leave blank to keep current" : "123456789:ABCdef..."}">
        <span class="hint">Create a bot with @BotFather and paste the token here.</span></div>
      <div class="field"><label>Chat ID *</label><input id="tg-chat" class="mono" value="${fmt.escape(existing ? existing.chat_id : "")}" placeholder="-100123456789"></div>
      <label class="checkbox"><input type="checkbox" id="tg-enabled" ${!existing || existing.enabled ? "checked" : ""}><span>${t("common.enabled")}</span></label>
      <label class="checkbox"><input type="checkbox" id="tg-notif" ${!existing || existing.send_notifications ? "checked" : ""}><span>Send notifications</span></label>
      <label class="checkbox"><input type="checkbox" id="tg-upload" ${!existing || existing.upload_enabled ? "checked" : ""}><span>Allow archive uploads</span></label>
    </div>`;
  const footer = document.createElement("div");
  footer.style.display = "contents";
  footer.innerHTML = `<button class="btn" data-test>${t("common.test")}</button><div style="flex:1"></div>
    <button class="btn" data-cancel>${t("common.cancel")}</button><button class="btn btn-primary" data-save>${t("common.save")}</button>`;
  const m = openModal({ title: existing ? "Edit Telegram destination" : t("telegram.new"), body, footer });

  footer.querySelector("[data-test]").addEventListener("click", async (e) => {
    const btn = e.target;
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      const r = await api("/api/v1/telegram/test-unsaved", {
        method: "POST",
        body: { bot_token: body.querySelector("#tg-token").value.trim(), chat_id: body.querySelector("#tg-chat").value.trim() },
      });
      toast(r.message, r.ok ? "success" : "error");
    } catch (err) { toast(err.message, "error"); }
    btn.disabled = false; btn.textContent = t("common.test");
  });
  footer.querySelector("[data-cancel]").addEventListener("click", () => m.close());
  footer.querySelector("[data-save]").addEventListener("click", async () => {
    const payload = {
      name: body.querySelector("#tg-name").value.trim(),
      bot_token: body.querySelector("#tg-token").value.trim(),
      chat_id: body.querySelector("#tg-chat").value.trim(),
      enabled: body.querySelector("#tg-enabled").checked,
      send_notifications: body.querySelector("#tg-notif").checked,
      upload_enabled: body.querySelector("#tg-upload").checked,
    };
    if (!payload.name) { toast("Name is required", "error"); return; }
    if (!existing && (!payload.bot_token || !payload.chat_id)) { toast("Bot token and chat ID are required", "error"); return; }
    try {
      if (existing) await api(`/api/v1/telegram/${existing.id}`, { method: "PUT", body: payload });
      else await api("/api/v1/telegram", { method: "POST", body: payload });
      toast(t("common.saved"), "success");
      m.close();
      onSaved();
    } catch (err) { toast(err.message, "error"); }
  });
}
