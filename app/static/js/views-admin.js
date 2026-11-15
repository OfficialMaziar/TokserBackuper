/* Users, Security, Settings, API docs, About views. */
"use strict";

registerViews({
  async users(el) {
    if (!TBM.user || TBM.user.role_name !== "admin") {
      el.innerHTML = emptyState("Administrator access required", "Only administrators can manage users.");
      return;
    }
    el.innerHTML = `
      <div class="toolbar">
        <div class="spacer"></div>
        <button class="btn btn-primary" id="new-user">${icon("users")}<span>Add user</span></button>
      </div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>${t("common.name")}</th><th>Role</th><th>${t("common.status")}</th>
          <th>Last login</th><th>2FA</th><th>${t("common.actions")}</th>
        </tr></thead><tbody id="users-body">${skeletonRows(3, 6)}</tbody></table>
      </div></div></div>`;

    const load = async () => {
      const rows = await api("/api/v1/users");
      const body = document.getElementById("users-body");
      body.innerHTML = rows.map((u) => `
        <tr>
          <td class="primary">${fmt.escape(u.full_name || u.username)}
            <div class="muted" style="font-size:11.5px">@${fmt.escape(u.username)}${u.email ? " · " + fmt.escape(u.email) : ""}</div></td>
          <td><span class="badge ${u.role_name === "admin" ? "running" : "neutral"}">${fmt.escape(u.role_name)}</span></td>
          <td>${u.is_active ? '<span class="badge success">active</span>' : '<span class="badge disabled">disabled</span>'}</td>
          <td class="muted" style="font-size:12px">${u.last_login_at ? fmt.rel(u.last_login_at) : t("common.never")}</td>
          <td>${u.totp_enabled ? '<span class="badge success">on</span>' : '<span class="muted">off</span>'}</td>
          <td class="actions">
            <button class="btn btn-sm btn-ghost" data-edit="${u.id}">${t("common.edit")}</button>
            <button class="btn btn-sm btn-ghost" data-reset="${u.id}">Reset password</button>
            ${u.id !== TBM.user.id ? `<button class="btn btn-sm btn-ghost" data-del="${u.id}">✕</button>` : ""}
          </td>
        </tr>`).join("");

      body.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => {
        openUserModal(rows.find((x) => x.id === Number(b.dataset.edit)), load);
      }));
      body.querySelectorAll("[data-reset]").forEach((b) => b.addEventListener("click", () => openResetModal(Number(b.dataset.reset))));
      body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
        if (!(await confirmDialog({ title: "Delete user", message: "This permanently removes the account.", confirmText: "Delete user" }))) return;
        try { await api(`/api/v1/users/${b.dataset.del}`, { method: "DELETE" }); toast(t("common.deleted"), "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
    };
    document.getElementById("new-user").addEventListener("click", () => openUserModal(null, load));
    await load();
  },

  async security(el) {
    const [sessions, me] = await Promise.all([
      api("/api/v1/auth/sessions"),
      api("/api/v1/auth/me"),
    ]);
    el.innerHTML = `
      ${me.user.must_change_password ? `<div class="alert warning">${ICONS.alert}<span>You must change your password before continuing.</span></div>` : ""}
      <div class="grid grid-2 mb-2" style="align-items:start">
        <div class="card"><div class="card-header"><h3>Change password</h3></div>
          <div class="card-body">
            <div class="field mb-2"><label for="cp-current">Current password</label><input id="cp-current" type="password" autocomplete="current-password"></div>
            <div class="field mb-2"><label for="cp-new">New password</label><input id="cp-new" type="password" autocomplete="new-password" minlength="10">
              <span class="hint">At least 10 characters with letters and digits.</span></div>
            <div class="field mb-2"><label for="cp-confirm">Confirm new password</label><input id="cp-confirm" type="password" autocomplete="new-password"></div>
            <button class="btn btn-primary" id="cp-submit">Update password</button>
          </div>
        </div>
        <div class="card"><div class="card-header"><h3>Account</h3></div>
          <div class="card-body"><dl class="kv">
            <dt>Username</dt><dd>${fmt.escape(me.user.username)}</dd>
            <dt>Role</dt><dd>${fmt.escape(me.user.role_name)}</dd>
            <dt>Email</dt><dd>${fmt.escape(me.user.email || "—")}</dd>
            <dt>Two-factor</dt><dd>${me.user.totp_enabled ? '<span class="text-good">enabled</span>' : '<span class="muted">disabled</span>'}</dd>
            <dt>Last login</dt><dd>${me.user.last_login_at ? fmt.date(me.user.last_login_at) : "—"}</dd>
          </dl></div>
        </div>
      </div>
      <div class="card"><div class="card-header"><h3>Active sessions</h3>
        <div class="spacer"></div><button class="btn btn-sm" id="refresh-sessions">${t("common.refresh")}</button></div>
        <div class="card-body tight"><div class="table-wrap"><table class="data">
          <thead><tr><th>IP</th><th>Device</th><th>Created</th><th>Last seen</th><th>Expires</th><th></th></tr></thead>
          <tbody>${sessions.map((s) => `
            <tr>
              <td class="mono">${fmt.escape(s.ip_address || "—")}${s.current ? ' <span class="badge success">current</span>' : ""}</td>
              <td class="muted truncate" style="max-width:280px;font-size:12px">${fmt.escape(s.user_agent || "—")}</td>
              <td class="num muted">${fmt.date(s.created_at)}</td>
              <td class="num muted">${fmt.rel(s.last_seen_at)}</td>
              <td class="num muted">${fmt.date(s.expires_at)}</td>
              <td class="actions">${s.current ? "" : `<button class="btn btn-sm btn-ghost" data-revoke="${s.id}">Revoke</button>`}</td>
            </tr>`).join("")}
          </tbody></table></div></div>
      </div>`;

    document.getElementById("cp-submit").addEventListener("click", async () => {
      const current = document.getElementById("cp-current").value;
      const next = document.getElementById("cp-new").value;
      const confirm = document.getElementById("cp-confirm").value;
      if (next !== confirm) { toast("Passwords do not match", "error"); return; }
      try {
        await api("/api/v1/auth/change-password", { method: "POST", body: { current_password: current, new_password: next } });
        toast("Password updated", "success");
        navigate("/security", false);
      } catch (e) { toast(e.message, "error"); }
    });

    el.querySelectorAll("[data-revoke]").forEach((b) => b.addEventListener("click", async () => {
      try { await api(`/api/v1/auth/sessions/${b.dataset.revoke}`, { method: "DELETE" }); toast("Session revoked", "success"); navigate("/security", false); }
      catch (e) { toast(e.message, "error"); }
    }));
    document.getElementById("refresh-sessions").addEventListener("click", () => navigate("/security", false));
  },

  async settings(el) {
    const data = await api("/api/v1/settings");
    const v = data.values;
    const isAdmin = TBM.user && TBM.user.role_name === "admin";
    const dis = isAdmin ? "" : "disabled";

    el.innerHTML = `
      <div class="grid grid-2" style="align-items:start">
        <div class="flex-col" style="gap:16px">
          <div class="form-section"><div class="form-section-head"><h3>Appearance</h3></div>
            <div class="form-section-body form-grid">
              <div class="field"><label>Application title</label><input id="set-title" value="${fmt.escape(v.app_title || data.defaults.app_title)}" ${dis}></div>
              <div class="form-row">
                <div class="field"><label>Language</label>
                  <select id="set-lang" ${dis}>
                    <option value="en" ${(v.default_language || "en") === "en" ? "selected" : ""}>English</option>
                    <option value="fa" ${v.default_language === "fa" ? "selected" : ""}>فارسی</option>
                  </select></div>
                <div class="field"><label>Theme</label>
                  <select id="set-theme" ${dis}>
                    <option value="dark" ${(v.default_theme || "dark") === "dark" ? "selected" : ""}>Dark</option>
                    <option value="light" ${v.default_theme === "light" ? "selected" : ""}>Light</option>
                  </select></div>
              </div>
            </div>
          </div>

          <div class="form-section"><div class="form-section-head"><h3>Backup engine</h3></div>
            <div class="form-section-body form-grid">
              <div class="field"><label>Minimum free disk (MB)</label><input id="set-minfree" type="number" min="0" value="${v.min_free_disk_mb || data.defaults.min_free_disk_mb}" ${dis}></div>
              <div class="field"><label>Max concurrent backups</label><input id="set-conc" type="number" min="1" max="16" value="${v.max_concurrent_backups || data.defaults.max_concurrent_backups}" ${dis}></div>
              <label class="checkbox"><input type="checkbox" id="set-verify" ${String(v.verify_archives || data.defaults.verify_archives) === "true" || v.verify_archives === true || (!v.verify_archives && data.defaults.verify_archives) ? "checked" : ""} ${dis}><span>Verify archives after creation</span></label>
            </div>
          </div>

          <div class="form-section"><div class="form-section-head"><h3>Email (SMTP)</h3></div>
            <div class="form-section-body form-grid">
              <div class="form-row">
                <div class="field"><label>SMTP host</label><input id="set-smtp-host" value="${fmt.escape(v.smtp_host || "")}" ${dis}></div>
                <div class="field"><label>Port</label><input id="set-smtp-port" type="number" value="${fmt.escape(v.smtp_port || "587")}" ${dis}></div>
              </div>
              <div class="form-row">
                <div class="field"><label>Username</label><input id="set-smtp-user" value="${fmt.escape(v.smtp_username || "")}" ${dis}></div>
                <div class="field"><label>Password</label><input id="set-smtp-pass" type="password" placeholder="${v.smtp_password ? "unchanged" : ""}" ${dis}></div>
              </div>
              <div class="form-row">
                <div class="field"><label>From address</label><input id="set-smtp-from" value="${fmt.escape(v.smtp_from || "")}" ${dis}></div>
                <div class="field"><label>To address</label><input id="set-smtp-to" value="${fmt.escape(v.smtp_to || "")}" ${dis}></div>
              </div>
              <label class="checkbox"><input type="checkbox" id="set-smtp-tls" ${v.smtp_tls !== "false" ? "checked" : ""} ${dis}><span>Use STARTTLS</span></label>
            </div>
          </div>
        </div>

        <div class="flex-col" style="gap:16px">
          <div class="form-section"><div class="form-section-head"><h3>Environment</h3></div>
            <div class="form-section-body"><dl class="kv">
              <dt>Version</dt><dd>${fmt.escape(data.app.version)}</dd>
              <dt>Vendor</dt><dd>${fmt.escape(data.app.vendor)}</dd>
              <dt>Environment</dt><dd>${fmt.escape(data.app.environment)}</dd>
              <dt>Database</dt><dd>${fmt.escape(data.app.database)}</dd>
              <dt>Backup directory</dt><dd class="mono" style="font-size:11.5px">${fmt.escape(data.app.backup_dir)}</dd>
            </dl></div>
          </div>
          ${isAdmin ? `<button class="btn btn-primary w-full" id="save-settings">${t("common.save")}</button>` : `<p class="muted" style="font-size:12.5px">Only administrators can change settings.</p>`}
        </div>
      </div>`;

    const saveBtn = document.getElementById("save-settings");
    if (saveBtn) saveBtn.addEventListener("click", async () => {
      const val = (id) => { const e = document.getElementById(id); return e ? e.value : ""; };
      const values = {
        app_title: val("set-title"),
        default_language: val("set-lang"),
        default_theme: val("set-theme"),
        min_free_disk_mb: val("set-minfree"),
        max_concurrent_backups: val("set-conc"),
        verify_archives: document.getElementById("set-verify").checked,
        smtp_host: val("set-smtp-host"),
        smtp_port: val("set-smtp-port"),
        smtp_username: val("set-smtp-user"),
        smtp_from: val("set-smtp-from"),
        smtp_to: val("set-smtp-to"),
        smtp_tls: document.getElementById("set-smtp-tls").checked,
      };
      const pass = val("set-smtp-pass");
      if (pass) values.smtp_password = pass;
      try {
        await api("/api/v1/settings", { method: "PUT", body: { values } });
        toast(t("common.saved"), "success");
      } catch (e) { toast(e.message, "error"); }
    });
  },

  async apidocs(el) {
    el.innerHTML = `
      <div class="card mb-2"><div class="card-header"><h3>REST API v1</h3>
        <div class="spacer"></div>
        <a class="btn btn-sm" href="/api/docs" target="_blank" rel="noopener">OpenAPI (Swagger UI)</a>
        <a class="btn btn-sm" href="/api/redoc" target="_blank" rel="noopener">ReDoc</a>
      </div>
      <div class="card-body">
        <p class="secondary mb-2" style="font-size:13px">All endpoints require an authenticated session cookie (or a Bearer session token).
        State-changing requests must include the <code class="mono">X-CSRF-Token</code> header.</p>
        <div class="code-block">curl -c cookies.txt -X POST https://your-host/api/v1/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"..."}'

# Response includes csrf_token — reuse it on every mutating call
curl -b cookies.txt https://your-host/api/v1/dashboard</div>
      </div></div>
      <div class="card"><div class="card-header"><h3>Endpoints</h3></div><div class="card-body tight">
        <div class="table-wrap"><table class="data"><thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
        <tbody>${[
          ["GET", "/api/v1/dashboard", "Dashboard aggregates"],
          ["GET", "/api/v1/monitoring", "Server metrics"],
          ["GET", "/api/v1/jobs", "List jobs"],
          ["POST", "/api/v1/jobs", "Create job"],
          ["PUT", "/api/v1/jobs/{id}", "Update job"],
          ["DELETE", "/api/v1/jobs/{id}", "Delete job"],
          ["POST", "/api/v1/jobs/{id}/run", "Run job now"],
          ["POST", "/api/v1/jobs/{id}/pause", "Pause schedule"],
          ["POST", "/api/v1/jobs/{id}/resume", "Resume schedule"],
          ["GET", "/api/v1/backups", "Backup history (filterable)"],
          ["GET", "/api/v1/backups/{id}", "Backup detail"],
          ["GET", "/api/v1/backups/{id}/archive", "List archive contents"],
          ["POST", "/api/v1/backups/{id}/restore", "Start restore"],
          ["GET", "/api/v1/storage", "List storage destinations"],
          ["POST", "/api/v1/storage", "Create storage"],
          ["POST", "/api/v1/storage/{id}/test", "Test storage connection"],
          ["GET", "/api/v1/telegram", "List Telegram destinations"],
          ["GET", "/api/v1/settings", "Read settings"],
          ["PUT", "/api/v1/settings", "Update settings (admin)"],
          ["POST", "/api/v1/notifications/test", "Send test notification"],
          ["GET", "/api/v1/logs", "Activity logs"],
          ["GET", "/api/v1/health", "Health check"],
        ].map(([m, p, d]) => `<tr><td><span class="badge ${m === "GET" ? "running" : m === "DELETE" ? "failed" : "pending"}">${m}</span></td>
          <td class="mono">${fmt.escape(p)}</td><td class="secondary">${fmt.escape(d)}</td></tr>`).join("")}
        </tbody></table></div>
      </div></div>`;
  },

  async about(el) {
    const a = await api("/api/v1/about");
    el.innerHTML = `
      <div class="grid grid-2" style="align-items:start">
        <div class="card"><div class="card-body">
          <div class="flex mb-2" style="gap:14px">
            <div class="brand-mark" style="width:52px;height:52px;flex-basis:52px;font-size:20px;border-radius:14px">TB</div>
            <div>
              <h1 style="font-size:20px">${fmt.escape(a.name)}</h1>
              <div class="muted" style="font-size:12.5px">Version ${fmt.escape(a.version)} · ${fmt.escape(a.vendor)}</div>
            </div>
          </div>
          <p class="secondary mb-2" style="font-size:13px">${fmt.escape(a.description)}</p>
          <dl class="kv">
            <dt>Python</dt><dd>${fmt.escape(a.python)}</dd>
            <dt>Environment</dt><dd>${fmt.escape(a.environment)}</dd>
            <dt>Database</dt><dd>${fmt.escape(a.database)}</dd>
            <dt>Backup directory</dt><dd class="mono" style="font-size:11.5px">${fmt.escape(a.backup_dir)}</dd>
            <dt>Backup disk</dt><dd>${fmt.bytes(a.backup_disk.free)} free of ${fmt.bytes(a.backup_disk.total)}</dd>
          </dl>
        </div></div>
        <div class="flex-col" style="gap:16px">
          <div class="card"><div class="card-header"><h3>Features</h3></div>
            <div class="card-body"><ul style="margin:0;padding-inline-start:18px;font-size:13px;color:var(--text-secondary);line-height:1.9">
              ${a.features.map((f) => `<li>${fmt.escape(f)}</li>`).join("")}
            </ul></div></div>
          <div class="card"><div class="card-header"><h3>Roadmap</h3></div>
            <div class="card-body"><ul style="margin:0;padding-inline-start:18px;font-size:13px;color:var(--text-muted);line-height:1.9">
              ${a.roadmap.map((f) => `<li>${fmt.escape(f)}</li>`).join("")}
            </ul></div></div>
        </div>
      </div>`;
  },
});

/* ------------------------------------------------------------------ */
/* User modals                                                         */
/* ------------------------------------------------------------------ */
function openUserModal(existing, onSaved) {
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="form-grid">
      <div class="field"><label>Username *</label><input id="u-name" value="${fmt.escape(existing ? existing.username : "")}" ${existing ? "disabled" : ""} maxlength="64" pattern="[A-Za-z0-9_.\\-]+"></div>
      ${existing ? "" : `<div class="field"><label>Password *</label><input id="u-pass" type="password" autocomplete="new-password" minlength="10">
        <span class="hint">At least 10 characters with letters and digits. The user must change it on first login.</span></div>`}
      <div class="form-row">
        <div class="field"><label>Full name</label><input id="u-full" value="${fmt.escape(existing ? existing.full_name : "")}" maxlength="128"></div>
        <div class="field"><label>Email</label><input id="u-email" type="email" value="${fmt.escape(existing ? existing.email : "")}" maxlength="255"></div>
      </div>
      <div class="field"><label>Role</label><select id="u-role">
        ${["admin", "operator", "viewer"].map((r) => `<option value="${r}" ${existing && existing.role_name === r ? "selected" : ""}>${r}</option>`).join("")}
      </select><span class="hint">admin: full access · operator: run/restore · viewer: read-only</span></div>
      <label class="checkbox"><input type="checkbox" id="u-active" ${!existing || existing.is_active ? "checked" : ""}><span>${t("common.enabled")}</span></label>
    </div>`;
  const footer = document.createElement("div");
  footer.style.display = "contents";
  footer.innerHTML = `<button class="btn" data-cancel>${t("common.cancel")}</button><button class="btn btn-primary" data-save>${t("common.save")}</button>`;
  const m = openModal({ title: existing ? "Edit user" : "Add user", body, footer });

  footer.querySelector("[data-cancel]").addEventListener("click", () => m.close());
  footer.querySelector("[data-save]").addEventListener("click", async () => {
    try {
      if (existing) {
        await api(`/api/v1/users/${existing.id}`, {
          method: "PUT",
          body: {
            full_name: body.querySelector("#u-full").value.trim(),
            email: body.querySelector("#u-email").value.trim(),
            role: body.querySelector("#u-role").value,
            is_active: body.querySelector("#u-active").checked,
          },
        });
      } else {
        await api("/api/v1/users", {
          method: "POST",
          body: {
            username: body.querySelector("#u-name").value.trim(),
            password: body.querySelector("#u-pass").value,
            full_name: body.querySelector("#u-full").value.trim(),
            email: body.querySelector("#u-email").value.trim(),
            role: body.querySelector("#u-role").value,
            is_active: body.querySelector("#u-active").checked,
          },
        });
      }
      toast(t("common.saved"), "success");
      m.close();
      onSaved();
    } catch (e) { toast(e.message, "error"); }
  });
}

function openResetModal(userId) {
  const body = document.createElement("div");
  body.innerHTML = `<div class="field"><label>New password</label><input id="rp-pass" type="password" autocomplete="new-password" minlength="10">
    <span class="hint">The user will be required to change it at next login. All their sessions are revoked.</span></div>`;
  const footer = document.createElement("div");
  footer.style.display = "contents";
  footer.innerHTML = `<button class="btn" data-cancel>${t("common.cancel")}</button><button class="btn btn-primary" data-save>Reset</button>`;
  const m = openModal({ title: "Reset password", body, footer });
  footer.querySelector("[data-cancel]").addEventListener("click", () => m.close());
  footer.querySelector("[data-save]").addEventListener("click", async () => {
    try {
      await api(`/api/v1/users/${userId}/reset-password`, { method: "POST", body: { password: body.querySelector("#rp-pass").value } });
      toast("Password reset", "success");
      m.close();
    } catch (e) { toast(e.message, "error"); }
  });
}
