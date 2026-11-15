/* Backup jobs: list, create/edit form, and source management. */
"use strict";

const SCHEDULE_TYPES = [
  ["manual", "Manual"], ["minutes", "Every N minutes"], ["hourly", "Every N hours"],
  ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["cron", "Custom cron"],
];
const DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const COMPRESSION = [["tar.gz", "TAR.GZ (gzip)"], ["tar", "TAR (uncompressed)"], ["zip", "ZIP"], ["zst", "Zstandard"]];

registerViews({
  async jobs(el) {
    el.innerHTML = `
      <div class="toolbar">
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input type="search" id="job-search" placeholder="${t("common.search")}">
        </div>
        <select id="job-filter" style="width:auto">
          <option value="">${t("common.all")}</option>
          <option value="true">${t("common.enabled")}</option>
          <option value="false">${t("common.disabled")}</option>
        </select>
        <div class="spacer"></div>
        <button class="btn btn-primary" id="new-job">${icon("layers")}<span>${t("jobs.new")}</span></button>
      </div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>${t("common.name")}</th><th>${t("jobs.schedule")}</th><th>${t("common.status")}</th>
          <th>${t("jobs.lastRun")}</th><th>${t("jobs.nextRun")}</th><th>${t("jobs.runs")}</th><th></th>
        </tr></thead><tbody id="jobs-body">${skeletonRows(5, 7)}</tbody></table>
      </div></div></div>`;

    document.getElementById("new-job").addEventListener("click", () => navigate("/jobs/new"));

    const load = async () => {
      const q = document.getElementById("job-search").value.trim();
      const enabled = document.getElementById("job-filter").value;
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (enabled) params.set("enabled", enabled);
      const jobs = await api(`/api/v1/jobs?${params}`);
      const body = document.getElementById("jobs-body");
      if (!jobs.length) {
        body.innerHTML = `<tr><td colspan="7">${emptyState(t("jobs.empty"), t("jobs.emptyHint"),
          `<button class="btn btn-primary" onclick="navigate('/jobs/new')">${t("jobs.new")}</button>`)}</td></tr>`;
        return;
      }
      body.innerHTML = jobs.map((j) => `
        <tr>
          <td class="primary">
            <a href="/jobs/${j.id}/edit" style="color:inherit">${fmt.escape(j.name)}</a>
            <div class="sub muted" style="font-size:11.5px">${j.sources.length} ${t("jobs.sources").toLowerCase()} · ${j.compression}</div>
          </td>
          <td class="secondary" style="font-size:12.5px">${fmt.escape(j.schedule_description)}</td>
          <td>${j.running ? statusBadge("running") : statusBadge(j.enabled ? (j.status === "paused" ? "paused" : "idle") : "disabled")}</td>
          <td class="num muted">${j.last_run_at ? fmt.rel(j.last_run_at) : t("common.never")}</td>
          <td class="num muted">${j.next_run_at ? fmt.rel(j.next_run_at) : "—"}</td>
          <td class="num">${j.success_runs}/${j.total_runs}</td>
          <td class="actions">
            <button class="btn btn-sm btn-ghost" data-run="${j.id}" title="${t("common.run")}" ${j.running ? "disabled" : ""}>▶</button>
            <button class="btn btn-sm btn-ghost" data-toggle="${j.id}" title="Toggle">${j.enabled ? "⏸" : "⏵"}</button>
            <a class="btn btn-sm btn-ghost" href="/jobs/${j.id}/edit" title="${t("common.edit")}">✎</a>
            <button class="btn btn-sm btn-ghost" data-dup="${j.id}" title="${t("common.duplicate")}">⧉</button>
            <button class="btn btn-sm btn-ghost" data-del="${j.id}" title="${t("common.delete")}">🗑</button>
          </td>
        </tr>`).join("");

      body.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", async () => {
        b.disabled = true;
        try {
          const r = await api(`/api/v1/jobs/${b.dataset.run}/run`, { method: "POST" });
          toast("Backup started", "success");
          navigate(`/backups/${r.backup_id}`);
        } catch (e) { toast(e.message, "error"); b.disabled = false; }
      }));
      body.querySelectorAll("[data-toggle]").forEach((b) => b.addEventListener("click", async () => {
        try { await api(`/api/v1/jobs/${b.dataset.toggle}/toggle`, { method: "POST" }); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
      body.querySelectorAll("[data-dup]").forEach((b) => b.addEventListener("click", async () => {
        try { await api(`/api/v1/jobs/${b.dataset.dup}/duplicate`, { method: "POST" }); toast("Job duplicated", "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
      body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
        const ok = await confirmDialog({ title: "Delete job", message: "This deletes the job and its backup history records. Archive files on disk are not removed.", confirmText: "Delete job" });
        if (!ok) return;
        try { await api(`/api/v1/jobs/${b.dataset.del}`, { method: "DELETE" }); toast(t("common.deleted"), "success"); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
    };

    document.getElementById("job-search").addEventListener("input", debounce(load, 250));
    document.getElementById("job-filter").addEventListener("change", load);
    await load();
  },

  async jobForm(el, params) {
    const isEdit = !!params.id;
    let job = null;
    if (isEdit) {
      try { job = await api(`/api/v1/jobs/${params.id}`); }
      catch (e) { el.innerHTML = emptyState("Job not found", e.message); return; }
    }
    const [storages, telegrams] = await Promise.all([
      api("/api/v1/storage").catch(() => []),
      api("/api/v1/telegram").catch(() => []),
    ]);

    const sched = job && job.schedule ? job.schedule : {
      schedule_type: "manual", interval_value: 1, hour: 3, minute: 0,
      day_of_week: 1, day_of_month: 1, cron_expression: "", timezone: "UTC", paused: false,
    };
    const sources = job ? job.sources : [];
    const dbs = job ? job.database_sources : [];

    el.innerHTML = `
      <form id="job-form" novalidate>
        <div class="grid grid-2" style="align-items:start">
          <div class="flex-col" style="gap:16px">

            <div class="form-section">
              <div class="form-section-head"><h3>General</h3></div>
              <div class="form-section-body form-grid">
                <div class="field">
                  <label for="j-name">${t("common.name")} *</label>
                  <input id="j-name" required maxlength="128" value="${fmt.escape(job ? job.name : "")}">
                </div>
                <div class="field">
                  <label for="j-desc">Description</label>
                  <textarea id="j-desc" maxlength="2000">${fmt.escape(job ? job.description : "")}</textarea>
                </div>
                <label class="checkbox"><input type="checkbox" id="j-enabled" ${!job || job.enabled ? "checked" : ""}>
                  <span>${t("common.enabled")}</span></label>
              </div>
            </div>

            <div class="form-section">
              <div class="form-section-head">
                <h3>${t("jobs.sources")}</h3>
                <div class="spacer" style="flex:1"></div>
                <button type="button" class="btn btn-sm" id="add-source">+ ${t("common.add")}</button>
              </div>
              <div class="form-section-body">
                <div id="source-list" class="flex-col" style="gap:10px"></div>
                <div id="source-empty" class="muted" style="font-size:12.5px;padding:8px 0">No sources yet — add at least one path or database.</div>
              </div>
            </div>

            <div class="form-section">
              <div class="form-section-head">
                <h3>Database sources</h3>
                <div class="spacer" style="flex:1"></div>
                <button type="button" class="btn btn-sm" id="add-db">+ ${t("common.add")}</button>
              </div>
              <div class="form-section-body">
                <div id="db-list" class="flex-col" style="gap:10px"></div>
                <div id="db-empty" class="muted" style="font-size:12.5px;padding:8px 0">MySQL, MariaDB, PostgreSQL or SQLite.</div>
              </div>
            </div>
          </div>

          <div class="flex-col" style="gap:16px">
            <div class="form-section">
              <div class="form-section-head"><h3>${t("jobs.schedule")}</h3></div>
              <div class="form-section-body form-grid">
                <div class="field">
                  <label for="s-type">Schedule type</label>
                  <select id="s-type">${SCHEDULE_TYPES.map(([v, l]) => `<option value="${v}" ${sched.schedule_type === v ? "selected" : ""}>${l}</option>`).join("")}</select>
                </div>
                <div id="sched-dynamic" class="form-grid"></div>
                <div class="field">
                  <label for="s-tz">Timezone</label>
                  <input id="s-tz" value="${fmt.escape(sched.timezone || "UTC")}" placeholder="UTC">
                </div>
                <label class="checkbox"><input type="checkbox" id="s-paused" ${sched.paused ? "checked" : ""}>
                  <span>Pause this schedule</span></label>
              </div>
            </div>

            <div class="form-section">
              <div class="form-section-head"><h3>Archive</h3></div>
              <div class="form-section-body form-grid">
                <div class="form-row">
                  <div class="field">
                    <label for="j-comp">Compression</label>
                    <select id="j-comp">${COMPRESSION.map(([v, l]) => `<option value="${v}" ${(job ? job.compression : "tar.gz") === v ? "selected" : ""}>${l}</option>`).join("")}</select>
                  </div>
                  <div class="field">
                    <label for="j-level">Level (1–19)</label>
                    <input id="j-level" type="number" min="1" max="19" value="${job ? job.compression_level : 6}">
                  </div>
                </div>
                <div class="field">
                  <label for="j-excludes">Exclude patterns (comma separated)</label>
                  <input id="j-excludes" value="${fmt.escape((job ? job.exclude_patterns : []).join(", "))}" placeholder="*.log, .git, node_modules">
                </div>
                <label class="checkbox"><input type="checkbox" id="j-symlinks" ${job && job.follow_symlinks ? "checked" : ""}><span>Follow symbolic links</span></label>
                <label class="checkbox"><input type="checkbox" id="j-perms" ${!job || job.preserve_permissions ? "checked" : ""}><span>Preserve permissions</span></label>
              </div>
            </div>

            <div class="form-section">
              <div class="form-section-head"><h3>Destination &amp; retention</h3></div>
              <div class="form-section-body form-grid">
                <div class="field">
                  <label for="j-storage">Storage destination</label>
                  <select id="j-storage">
                    <option value="">Local backup directory</option>
                    ${storages.map((s) => `<option value="${s.id}" ${job && job.storage_destination_id === s.id ? "selected" : ""}>${fmt.escape(s.name)} (${s.storage_type})</option>`).join("")}
                  </select>
                </div>
                <div class="field">
                  <label for="j-telegram">Telegram destination</label>
                  <select id="j-telegram">
                    <option value="">${t("common.none")}</option>
                    ${telegrams.map((s) => `<option value="${s.id}" ${job && job.telegram_destination_id === s.id ? "selected" : ""}>${fmt.escape(s.name)}</option>`).join("")}
                  </select>
                </div>
                <label class="checkbox"><input type="checkbox" id="j-tg-upload" ${job && job.telegram_upload_enabled ? "checked" : ""}><span>Upload archive to Telegram</span></label>
                <div class="form-row">
                  <div class="field">
                    <label for="j-keep">Keep last N backups</label>
                    <input id="j-keep" type="number" min="0" value="${job && job.retention_keep_last != null ? job.retention_keep_last : 10}">
                  </div>
                  <div class="field">
                    <label for="j-days">Keep for N days</label>
                    <input id="j-days" type="number" min="0" value="${job && job.retention_days != null ? job.retention_days : ""}" placeholder="unlimited">
                  </div>
                </div>
              </div>
            </div>

            <div class="form-section">
              <div class="form-section-head"><h3>Encryption</h3></div>
              <div class="form-section-body form-grid">
                <label class="checkbox"><input type="checkbox" id="j-encrypt" ${job && job.encrypt_archive ? "checked" : ""}><span>Encrypt archive (AES-256-GCM)</span></label>
                <div class="field" id="enc-field">
                  <label for="j-encpass">Encryption password</label>
                  <input id="j-encpass" type="password" autocomplete="new-password" placeholder="${job && job.encrypt_archive ? "leave blank to keep current" : ""}">
                  <span class="hint">Required to verify and restore this archive. Store it safely.</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="flex mt-3" style="justify-content:flex-end;gap:10px">
          <a class="btn" href="/jobs">${t("common.cancel")}</a>
          <button class="btn btn-primary" type="submit" id="save-job">${t("common.save")}</button>
        </div>
      </form>`;

    /* ---------------- sources ---------------- */
    const sourceList = document.getElementById("source-list");
    const addSourceRow = (src = { name: "", path: "", enabled: true, exclude_patterns: [] }) => {
      const row = document.createElement("div");
      row.className = "card";
      row.style.padding = "10px";
      row.innerHTML = `
        <div class="form-row" style="gap:10px">
          <div class="field"><label>Name</label><input data-f="name" value="${fmt.escape(src.name)}" placeholder="e.g. Website files"></div>
          <div class="field"><label>Path *</label><input data-f="path" value="${fmt.escape(src.path)}" placeholder="/var/www"></div>
        </div>
        <div class="form-row" style="gap:10px;margin-top:8px">
          <div class="field"><label>Exclude patterns</label><input data-f="excludes" value="${fmt.escape((src.exclude_patterns || []).join(", "))}" placeholder="*.log, cache"></div>
          <div class="flex" style="align-items:flex-end;gap:8px;padding-bottom:1px">
            <label class="checkbox" style="margin-bottom:9px"><input type="checkbox" data-f="enabled" ${src.enabled ? "checked" : ""}><span>Enabled</span></label>
            <button type="button" class="btn btn-sm" data-browse style="margin-bottom:6px">Browse</button>
            <button type="button" class="btn btn-sm btn-ghost" data-remove style="margin-bottom:6px">✕</button>
          </div>
        </div>
        <div class="muted" data-status style="font-size:11.5px;margin-top:6px"></div>`;
      row.querySelector("[data-remove]").addEventListener("click", () => { row.remove(); updateEmpty(); });
      row.querySelector("[data-browse]").addEventListener("click", () => openBrowser((p) => {
        row.querySelector('[data-f="path"]').value = p;
        validateRow(row);
      }));
      row.querySelector('[data-f="path"]').addEventListener("change", () => validateRow(row));
      sourceList.appendChild(row);
      updateEmpty();
      if (src.path) validateRow(row);
    };
    const validateRow = async (row) => {
      const path = row.querySelector('[data-f="path"]').value.trim();
      const statusEl = row.querySelector("[data-status]");
      if (!path) { statusEl.textContent = ""; return; }
      try {
        const r = await api("/api/v1/sources/validate", { method: "POST", body: { path, name: "", exclude_patterns: [] } });
        if (!r.exists) statusEl.innerHTML = `<span class="text-critical">Path does not exist</span>`;
        else if (!r.readable) statusEl.innerHTML = `<span class="text-warning">Permission denied — the service user cannot read this path</span>`;
        else statusEl.innerHTML = `<span class="text-good">Readable</span> · ${fmt.bytes(r.size)}${r.is_dir ? " · directory" : " · file"}`;
      } catch (e) { statusEl.textContent = e.message; }
    };
    const updateEmpty = () => {
      document.getElementById("source-empty").style.display = sourceList.children.length ? "none" : "";
    };
    sources.forEach(addSourceRow);
    document.getElementById("add-source").addEventListener("click", () => addSourceRow());
    updateEmpty();

    /* ---------------- databases ---------------- */
    const dbList = document.getElementById("db-list");
    const addDbRow = (d = { name: "", db_type: "mysql", host: "localhost", port: 0, database_name: "", username: "", sqlite_path: "", enabled: true }) => {
      const row = document.createElement("div");
      row.className = "card";
      row.style.padding = "10px";
      row.innerHTML = `
        <div class="form-row" style="gap:10px">
          <div class="field"><label>Name</label><input data-f="name" value="${fmt.escape(d.name)}" placeholder="e.g. Shop DB"></div>
          <div class="field"><label>Type</label>
            <select data-f="db_type">
              ${["mysql", "mariadb", "postgresql", "sqlite"].map((v) => `<option value="${v}" ${d.db_type === v ? "selected" : ""}>${v}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="db-fields" style="margin-top:8px">
          <div class="form-row" style="gap:10px">
            <div class="field"><label>Host</label><input data-f="host" value="${fmt.escape(d.host)}"></div>
            <div class="field"><label>Port</label><input data-f="port" type="number" value="${d.port || ""}" placeholder="default"></div>
          </div>
          <div class="form-row" style="gap:10px;margin-top:8px">
            <div class="field"><label>Database</label><input data-f="database_name" value="${fmt.escape(d.database_name)}"></div>
            <div class="field"><label>Username</label><input data-f="username" value="${fmt.escape(d.username)}"></div>
          </div>
          <div class="field" style="margin-top:8px"><label>Password</label><input data-f="password" type="password" autocomplete="new-password" placeholder="leave blank to keep current"></div>
          <div class="field" style="margin-top:8px"><label>SQLite file path</label><input data-f="sqlite_path" value="${fmt.escape(d.sqlite_path)}" placeholder="/var/lib/app/app.db"></div>
        </div>
        <div class="flex" style="margin-top:8px;justify-content:space-between">
          <label class="checkbox"><input type="checkbox" data-f="enabled" ${d.enabled ? "checked" : ""}><span>Enabled</span></label>
          <button type="button" class="btn btn-sm btn-ghost" data-remove>✕ Remove</button>
        </div>`;
      row.querySelector("[data-remove]").addEventListener("click", () => { row.remove(); updateDbEmpty(); });
      dbList.appendChild(row);
      updateDbEmpty();
    };
    const updateDbEmpty = () => {
      document.getElementById("db-empty").style.display = dbList.children.length ? "none" : "";
    };
    dbs.forEach(addDbRow);
    document.getElementById("add-db").addEventListener("click", () => addDbRow());
    updateDbEmpty();

    /* ---------------- schedule ---------------- */
    const schedDynamic = document.getElementById("sched-dynamic");
    const renderScheduleFields = () => {
      const type = document.getElementById("s-type").value;
      const v = sched;
      let html = "";
      if (type === "minutes" || type === "hourly") {
        html += `<div class="field"><label>Interval</label><input id="s-interval" type="number" min="1" value="${v.interval_value || 1}"></div>`;
      }
      if (type === "hourly" || type === "daily" || type === "weekly" || type === "monthly") {
        html += `<div class="form-row">
          <div class="field"><label>Hour (0–23)</label><input id="s-hour" type="number" min="0" max="23" value="${v.hour}"></div>
          <div class="field"><label>Minute (0–59)</label><input id="s-minute" type="number" min="0" max="59" value="${v.minute}"></div>
        </div>`;
      }
      if (type === "weekly") {
        html += `<div class="field"><label>Day of week</label><select id="s-dow">${DOW.map((d, i) => `<option value="${i}" ${v.day_of_week === i ? "selected" : ""}>${d}</option>`).join("")}</select></div>`;
      }
      if (type === "monthly") {
        html += `<div class="field"><label>Day of month</label><input id="s-dom" type="number" min="1" max="31" value="${v.day_of_month}"></div>`;
      }
      if (type === "cron") {
        html += `<div class="field"><label>Cron expression</label><input id="s-cron" value="${fmt.escape(v.cron_expression || "")}" placeholder="0 3 * * *">
          <span class="hint">minute hour day-of-month month day-of-week</span></div>`;
      }
      if (type === "manual") {
        html += `<p class="muted" style="font-size:12.5px">This job only runs when started manually.</p>`;
      }
      schedDynamic.innerHTML = html;
    };
    document.getElementById("s-type").addEventListener("change", renderScheduleFields);
    renderScheduleFields();

    /* ---------------- encryption toggle ---------------- */
    const encToggle = () => {
      document.getElementById("enc-field").style.display = document.getElementById("j-encrypt").checked ? "" : "none";
    };
    document.getElementById("j-encrypt").addEventListener("change", encToggle);
    encToggle();

    /* ---------------- submit ---------------- */
    document.getElementById("job-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("save-job");
      const name = document.getElementById("j-name").value.trim();
      if (!name) { toast("Job name is required", "error"); return; }

      const srcPayload = [...sourceList.children].map((row) => ({
        name: row.querySelector('[data-f="name"]').value.trim(),
        path: row.querySelector('[data-f="path"]').value.trim(),
        enabled: row.querySelector('[data-f="enabled"]').checked,
        exclude_patterns: row.querySelector('[data-f="excludes"]').value.split(",").map((s) => s.trim()).filter(Boolean),
      })).filter((s) => s.path);

      const dbPayload = [...dbList.children].map((row) => ({
        name: row.querySelector('[data-f="name"]').value.trim(),
        db_type: row.querySelector('[data-f="db_type"]').value,
        host: row.querySelector('[data-f="host"]').value.trim() || "localhost",
        port: Number(row.querySelector('[data-f="port"]').value) || 0,
        database_name: row.querySelector('[data-f="database_name"]').value.trim(),
        username: row.querySelector('[data-f="username"]').value.trim(),
        password: row.querySelector('[data-f="password"]').value,
        sqlite_path: row.querySelector('[data-f="sqlite_path"]').value.trim(),
        enabled: row.querySelector('[data-f="enabled"]').checked,
      })).filter((d) => d.database_name || d.sqlite_path);

      if (!srcPayload.length && !dbPayload.length) {
        toast("Add at least one source or database", "error"); return;
      }

      const type = document.getElementById("s-type").value;
      const num = (id, fallback) => {
        const el = document.getElementById(id);
        return el ? Number(el.value) : fallback;
      };
      const schedule = {
        schedule_type: type,
        interval_value: num("s-interval", sched.interval_value || 1) || 1,
        hour: num("s-hour", sched.hour) || 0,
        minute: num("s-minute", sched.minute) || 0,
        day_of_week: num("s-dow", sched.day_of_week) || 0,
        day_of_month: num("s-dom", sched.day_of_month) || 1,
        cron_expression: (document.getElementById("s-cron") || {}).value || "",
        timezone: document.getElementById("s-tz").value.trim() || "UTC",
        paused: document.getElementById("s-paused").checked,
      };

      const payload = {
        name,
        description: document.getElementById("j-desc").value.trim(),
        enabled: document.getElementById("j-enabled").checked,
        compression: document.getElementById("j-comp").value,
        compression_level: Number(document.getElementById("j-level").value) || 6,
        backup_mode: "full",
        storage_destination_id: Number(document.getElementById("j-storage").value) || null,
        telegram_destination_id: Number(document.getElementById("j-telegram").value) || null,
        telegram_upload_enabled: document.getElementById("j-tg-upload").checked,
        retention_keep_last: document.getElementById("j-keep").value === "" ? null : Number(document.getElementById("j-keep").value),
        retention_days: document.getElementById("j-days").value === "" ? null : Number(document.getElementById("j-days").value),
        encrypt_archive: document.getElementById("j-encrypt").checked,
        encryption_password: document.getElementById("j-encpass").value,
        follow_symlinks: document.getElementById("j-symlinks").checked,
        preserve_permissions: document.getElementById("j-perms").checked,
        exclude_patterns: document.getElementById("j-excludes").value.split(",").map((s) => s.trim()).filter(Boolean),
        sources: srcPayload,
        database_sources: dbPayload,
        schedule,
      };

      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>';
      try {
        if (isEdit) await api(`/api/v1/jobs/${params.id}`, { method: "PUT", body: payload });
        else await api("/api/v1/jobs", { method: "POST", body: payload });
        toast(t("common.saved"), "success");
        navigate("/jobs");
      } catch (err) {
        toast(err.message, "error", "Save failed");
        btn.disabled = false;
        btn.textContent = t("common.save");
      }
    });
  },

  async sources(el) {
    const jobs = await api("/api/v1/jobs");
    const rows = [];
    jobs.forEach((j) => j.sources.forEach((s) => rows.push({ ...s, job: j })));

    el.innerHTML = `
      <div class="toolbar">
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input type="search" id="src-search" placeholder="${t("common.search")}">
        </div>
        <div class="spacer"></div>
        <a class="btn btn-primary" href="/jobs/new">${t("jobs.new")}</a>
      </div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>${t("common.name")}</th><th>Path</th><th>Job</th><th>${t("common.size")}</th>
          <th>${t("common.status")}</th><th>Excludes</th>
        </tr></thead><tbody id="src-body"></tbody></table>
      </div></div></div>`;

    const render = (filter = "") => {
      const body = document.getElementById("src-body");
      const list = rows.filter((r) => !filter || r.path.toLowerCase().includes(filter) || (r.name || "").toLowerCase().includes(filter));
      if (!list.length) {
        body.innerHTML = `<tr><td colspan="6">${emptyState("No sources", "Sources are defined inside each backup job.")}</td></tr>`;
        return;
      }
      body.innerHTML = list.map((s) => `
        <tr>
          <td class="primary">${fmt.escape(s.name || "—")}</td>
          <td class="mono truncate" style="max-width:320px">${fmt.escape(s.path)}</td>
          <td><a href="/jobs/${s.job.id}/edit">${fmt.escape(s.job.name)}</a></td>
          <td class="num">${s.estimated_size ? fmt.bytes(s.estimated_size) : "—"}</td>
          <td>${s.enabled ? '<span class="badge success">enabled</span>' : '<span class="badge disabled">disabled</span>'}</td>
          <td class="muted" style="font-size:11.5px">${fmt.escape((s.exclude_patterns || []).join(", ")) || "—"}</td>
        </tr>`).join("");
    };
    render();
    document.getElementById("src-search").addEventListener("input", debounce((e) => render(e.target.value.toLowerCase()), 200));
  },
});

/* ------------------------------------------------------------------ */
/* Directory browser modal                                             */
/* ------------------------------------------------------------------ */
function openBrowser(onPick) {
  let currentPath = "/";
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="flex mb-2" style="gap:8px">
      <button class="btn btn-sm" data-up>↑ Up</button>
      <input id="browse-path" class="mono" style="flex:1" value="/">
      <button class="btn btn-sm" data-go>Go</button>
    </div>
    <div id="browse-list" style="max-height:380px;overflow-y:auto;border:1px solid var(--border);border-radius:8px"></div>`;
  const m = openModal({
    title: "Select directory",
    body,
    size: "wide",
    footer: `<button class="btn" data-cancel>${t("common.cancel")}</button><button class="btn btn-primary" data-select>Select this directory</button>`,
  });
  const listEl = body.querySelector("#browse-list");
  const pathInput = body.querySelector("#browse-path");

  const load = async (path) => {
    listEl.innerHTML = `<div style="padding:20px;text-align:center"><span class="spinner"></span></div>`;
    try {
      const r = await api(`/api/v1/sources/browse?path=${encodeURIComponent(path)}`);
      currentPath = r.path;
      pathInput.value = r.path || "";
      // On Windows the root request returns the list of drives.
      const atDrives = r.drives === true;
      const selectBtn = m.el.querySelector("[data-select]");
      if (selectBtn) {
        selectBtn.disabled = atDrives;
        selectBtn.textContent = atDrives ? "Pick a drive first" : "Select this directory";
      }
      if (!r.entries.length) {
        listEl.innerHTML = `<div style="padding:20px" class="muted">${atDrives ? "No drives found" : "Empty directory"}</div>`;
        return;
      }
      listEl.innerHTML = r.entries.map((e) => `
        <div class="list-row" data-path="${fmt.escape(e.path)}" data-dir="${e.is_dir}" style="cursor:pointer">
          <span style="width:18px;color:var(--text-muted)">${atDrives ? "💾" : e.is_dir ? "📁" : "📄"}</span>
          <div class="grow"><div class="title">${fmt.escape(e.name)}</div></div>
          ${e.is_dir ? "" : `<span class="muted mono" style="font-size:11px">${fmt.bytes(e.size)}</span>`}
        </div>`).join("");
      listEl.querySelectorAll("[data-path]").forEach((row) => {
        row.addEventListener("click", () => {
          if (row.dataset.dir === "true") load(row.dataset.path);
          else { pathInput.value = row.dataset.path; }
        });
      });
    } catch (e) {
      listEl.innerHTML = `<div style="padding:20px" class="text-critical">${fmt.escape(e.message)}</div>`;
    }
  };

  body.querySelector("[data-up]").addEventListener("click", () => {
    if (!currentPath) return;                       // already at the drive list
    if (/^[A-Za-z]:\\?$/.test(currentPath)) { load("/"); return; }  // drive root → drives
    const parent = currentPath.replace(/[\\/]+$/, "").split(/[\\/]/).slice(0, -1).join("/") || "/";
    load(parent);
  });
  body.querySelector("[data-go]").addEventListener("click", () => load(pathInput.value.trim() || "/"));
  pathInput.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); load(pathInput.value.trim() || "/"); } });
  m.el.querySelector("[data-cancel]").addEventListener("click", () => m.close());
  m.el.querySelector("[data-select]").addEventListener("click", () => {
    if (!currentPath) { toast("Select a drive or directory first", "warning"); return; }
    onPick(currentPath);
    m.close();
  });

  load("/");
}
