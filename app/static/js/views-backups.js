/* Backup history, backup detail, restore center, schedules. */
"use strict";

registerViews({
  async backups(el) {
    el.innerHTML = `
      <div class="toolbar">
        <div class="search-box">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>
          <input type="search" id="b-search" placeholder="${t("common.search")}">
        </div>
        <select id="b-status" style="width:auto">
          <option value="">${t("common.all")}</option>
          ${["success", "failed", "running", "pending", "cancelled"].map((s) => `<option value="${s}">${t("status." + s)}</option>`).join("")}
        </select>
        <input type="date" id="b-from" style="width:auto" title="From">
        <input type="date" id="b-to" style="width:auto" title="To">
        <div class="spacer"></div>
        <button class="btn" id="b-csv">CSV</button>
        <button class="btn" id="b-json">JSON</button>
      </div>
      <div class="card"><div class="card-body tight"><div class="table-wrap">
        <table class="data"><thead><tr>
          <th>#</th><th>${t("common.name")}</th><th>${t("common.status")}</th><th>${t("common.size")}</th>
          <th>${t("common.duration")}</th><th>${t("common.date")}</th><th>Telegram</th><th></th>
        </tr></thead><tbody id="b-body">${skeletonRows(6, 8)}</tbody></table>
      </div></div>
      <div class="flex" style="justify-content:space-between;padding:12px 16px;border-top:1px solid var(--border)">
        <span class="muted" id="b-total" style="font-size:12px"></span>
        <div class="flex" style="gap:6px">
          <button class="btn btn-sm" id="b-prev">←</button>
          <button class="btn btn-sm" id="b-next">→</button>
        </div>
      </div></div>`;

    let offset = 0;
    const limit = 50;

    const load = async () => {
      const params = new URLSearchParams({ limit, offset });
      const q = document.getElementById("b-search").value.trim();
      const status = document.getElementById("b-status").value;
      const from = document.getElementById("b-from").value;
      const to = document.getElementById("b-to").value;
      if (q) params.set("q", q);
      if (status) params.set("status", status);
      if (from) params.set("date_from", from);
      if (to) params.set("date_to", to + "T23:59:59");

      const data = await api(`/api/v1/backups?${params}`);
      document.getElementById("b-total").textContent = `${data.total} ${t("nav.history").toLowerCase()}`;
      const body = document.getElementById("b-body");
      if (!data.items.length) {
        body.innerHTML = `<tr><td colspan="8">${emptyState(t("backups.empty"), "Run a job to create your first backup.")}</td></tr>`;
        return;
      }
      body.innerHTML = data.items.map((b) => `
        <tr>
          <td class="muted num">${b.id}</td>
          <td class="primary"><a href="/backups/${b.id}" style="color:inherit">${fmt.escape(b.job_name)}</a></td>
          <td>${statusBadge(b.status)}</td>
          <td class="num">${fmt.bytes(b.archive_size)}</td>
          <td class="num">${fmt.duration(b.duration_seconds)}</td>
          <td class="num muted">${fmt.date(b.created_at)}</td>
          <td>${b.telegram_status ? `<span class="badge ${b.telegram_status === "sent" ? "success" : b.telegram_status === "partial" ? "partial" : "failed"}">${b.telegram_status}</span>` : "—"}</td>
          <td class="actions">
            <a class="btn btn-sm btn-ghost" href="/backups/${b.id}">${t("common.view")}</a>
            ${b.status === "running" ? `<button class="btn btn-sm btn-ghost" data-cancel="${b.id}">Cancel</button>` : ""}
          </td>
        </tr>`).join("");

      body.querySelectorAll("[data-cancel]").forEach((btn) => btn.addEventListener("click", async () => {
        try { await api(`/api/v1/backups/${btn.dataset.cancel}/cancel`, { method: "POST" }); toast("Cancellation requested", "info"); load(); }
        catch (e) { toast(e.message, "error"); }
      }));
    };

    document.getElementById("b-prev").addEventListener("click", () => { offset = Math.max(0, offset - limit); load(); });
    document.getElementById("b-next").addEventListener("click", () => { offset += limit; load(); });
    document.getElementById("b-search").addEventListener("input", debounce(() => { offset = 0; load(); }, 250));
    ["b-status", "b-from", "b-to"].forEach((id) => document.getElementById(id).addEventListener("change", () => { offset = 0; load(); }));
    document.getElementById("b-csv").addEventListener("click", () => downloadUrl("/api/v1/backups/export?format=csv"));
    document.getElementById("b-json").addEventListener("click", () => downloadUrl("/api/v1/backups/export?format=json"));

    await load();
    poll("backups", load, 10000);
  },

  async backupDetail(el, params) {
    const id = params.id;
    let b;
    try { b = await api(`/api/v1/backups/${id}`); }
    catch (e) { el.innerHTML = emptyState("Backup not found", e.message); return; }

    el.innerHTML = `
      <div class="flex mb-2" style="justify-content:space-between;flex-wrap:wrap;gap:10px">
        <div class="flex" style="gap:10px">
          <a class="btn btn-sm" href="/backups">← ${t("common.back")}</a>
          <h2 style="font-size:17px">${fmt.escape(b.job_name)} <span class="muted" style="font-weight:400">#${b.id}</span></h2>
          ${statusBadge(b.status)}
        </div>
        <div class="flex" style="gap:8px">
          ${b.archive_exists ? `<button class="btn btn-sm" id="verify-btn">${t("backups.verify")}</button>` : ""}
          ${b.archive_exists ? `<button class="btn btn-sm" id="download-btn">${t("common.download")}</button>` : ""}
          ${b.status === "success" || b.status === "partial" ? `<button class="btn btn-sm btn-primary" id="restore-btn">${t("backups.restore")}</button>` : ""}
          ${b.status === "running" ? `<button class="btn btn-sm btn-danger" id="cancel-btn">Cancel</button>` : ""}
          <button class="btn btn-sm btn-ghost" id="delete-btn">${t("common.delete")}</button>
        </div>
      </div>

      ${b.status === "running" ? `
        <div class="card mb-2"><div class="card-body">
          <div class="flex" style="justify-content:space-between;margin-bottom:8px">
            <span class="secondary">Backup in progress…</span><span class="mono" id="prog-pct">${b.progress}%</span>
          </div>
          <div class="progress"><div class="progress-bar" id="prog-bar" style="width:${b.progress}%"></div></div>
        </div></div>` : ""}

      ${b.error_message ? `<div class="alert error">${ICONS.alert}<span>${fmt.escape(b.error_message)}</span></div>` : ""}

      <div class="grid grid-2 mb-2" style="align-items:start">
        <div class="card"><div class="card-header"><h3>Summary</h3></div><div class="card-body">
          <dl class="kv">
            <dt>Job</dt><dd>${fmt.escape(b.job_name)}</dd>
            <dt>Trigger</dt><dd>${fmt.escape(b.trigger)}</dd>
            <dt>Mode</dt><dd>${fmt.escape(b.mode)}</dd>
            <dt>Started</dt><dd>${fmt.date(b.started_at)}</dd>
            <dt>Finished</dt><dd>${fmt.date(b.finished_at)}</dd>
            <dt>Duration</dt><dd>${fmt.duration(b.duration_seconds)}</dd>
            <dt>Archive</dt><dd class="mono">${fmt.escape(b.archive_name || "—")}</dd>
            <dt>Format</dt><dd>${fmt.escape(b.archive_format)}${b.encrypted ? " · encrypted" : ""}</dd>
            <dt>Archive size</dt><dd>${fmt.bytes(b.archive_size)}</dd>
            <dt>Source size</dt><dd>${fmt.bytes(b.source_size)}</dd>
            <dt>Compression ratio</dt><dd>${b.compression_ratio ? (b.compression_ratio * 100).toFixed(1) + "%" : "—"}</dd>
            <dt>Files</dt><dd>${fmt.num(b.file_count)}</dd>
            <dt>Verified</dt><dd>${b.verified ? '<span class="text-good">yes</span>' : '<span class="muted">no</span>'}</dd>
            <dt>Storage path</dt><dd class="mono" style="font-size:11.5px">${fmt.escape(b.storage_path || "—")}</dd>
            <dt>Telegram</dt><dd>${b.telegram_status ? `${fmt.escape(b.telegram_status)} (${b.telegram_parts_sent}/${b.telegram_parts})` : "—"}</dd>
          </dl>
        </div></div>

        <div class="card"><div class="card-header"><h3>${t("backups.archive")}</h3>
          <div class="spacer"></div>
          <button class="chart-table-toggle" id="toggle-files">Show file list</button>
        </div>
        <div class="card-body" id="archive-body"><span class="spinner"></span></div></div>
      </div>`;

    /* ---- archive contents ---- */
    const archiveBody = document.getElementById("archive-body");
    let showFiles = false;
    const loadArchive = async () => {
      archiveBody.innerHTML = `<div style="padding:20px;text-align:center"><span class="spinner"></span></div>`;
      try {
        if (showFiles) {
          const data = await api(`/api/v1/backups/${id}/files?limit=500`);
          if (!data.items.length) { archiveBody.innerHTML = `<p class="muted">No file metadata recorded.</p>`; return; }
          archiveBody.innerHTML = `<div class="muted mb-1" style="font-size:12px">${fmt.num(data.total)} files recorded</div>
            <div style="max-height:340px;overflow-y:auto"><table class="data" style="font-size:12px">
            <thead><tr><th>Path</th><th>Size</th></tr></thead><tbody>
            ${data.items.map((f) => `<tr><td class="mono truncate" style="max-width:340px">${fmt.escape(f.path)}</td><td class="num">${fmt.bytes(f.size)}</td></tr>`).join("")}
            </tbody></table></div>`;
          return;
        }
        if (!b.archive_exists) {
          archiveBody.innerHTML = `<p class="muted">The archive file is no longer on disk.</p>`;
          return;
        }
        const data = await api(`/api/v1/backups/${id}/archive?limit=1000`);
        archiveBody.innerHTML = `<div class="muted mb-1" style="font-size:12px">${fmt.num(data.total)} entries${data.truncated ? " (showing first 1000)" : ""}</div>
          <div style="max-height:340px;overflow-y:auto"><table class="data" style="font-size:12px">
          <thead><tr><th>Path</th><th>Size</th></tr></thead><tbody>
          ${data.items.map((f) => `<tr><td class="mono truncate" style="max-width:340px">${fmt.escape(f.path)}</td><td class="num">${f.is_dir ? "—" : fmt.bytes(f.size)}</td></tr>`).join("")}
          </tbody></table></div>`;
      } catch (e) {
        archiveBody.innerHTML = `<p class="text-critical" style="font-size:12.5px">${fmt.escape(e.message)}</p>`;
      }
    };
    document.getElementById("toggle-files").addEventListener("click", (e) => {
      showFiles = !showFiles;
      e.target.textContent = showFiles ? "Show archive contents" : "Show file list";
      loadArchive();
    });
    loadArchive();

    /* ---- actions ---- */
    const verifyBtn = document.getElementById("verify-btn");
    if (verifyBtn) verifyBtn.addEventListener("click", async () => {
      verifyBtn.disabled = true; verifyBtn.innerHTML = '<span class="spinner"></span>';
      try {
        const r = await api(`/api/v1/backups/${id}/verify`, { method: "POST" });
        toast(r.ok ? "Archive verified successfully" : r.message, r.ok ? "success" : "error");
      } catch (e) { toast(e.message, "error"); }
      verifyBtn.disabled = false; verifyBtn.textContent = t("backups.verify");
    });

    const dlBtn = document.getElementById("download-btn");
    if (dlBtn) dlBtn.addEventListener("click", () => downloadUrl(`/api/v1/backups/${id}/download`));

    const cancelBtn = document.getElementById("cancel-btn");
    if (cancelBtn) cancelBtn.addEventListener("click", async () => {
      try { await api(`/api/v1/backups/${id}/cancel`, { method: "POST" }); toast("Cancellation requested", "info"); }
      catch (e) { toast(e.message, "error"); }
    });

    document.getElementById("delete-btn").addEventListener("click", async () => {
      const ok = await confirmDialog({ title: "Delete backup", message: "The archive file will be permanently removed from disk.", confirmText: "Delete" });
      if (!ok) return;
      try { await api(`/api/v1/backups/${id}`, { method: "DELETE" }); toast(t("common.deleted"), "success"); navigate("/backups"); }
      catch (e) { toast(e.message, "error"); }
    });

    const restoreBtn = document.getElementById("restore-btn");
    if (restoreBtn) restoreBtn.addEventListener("click", () => openRestoreModal(b));

    if (b.status === "running") {
      poll("detail", async () => {
        const fresh = await api(`/api/v1/backups/${id}`);
        const bar = document.getElementById("prog-bar");
        const pct = document.getElementById("prog-pct");
        if (bar) bar.style.width = `${fresh.progress}%`;
        if (pct) pct.textContent = `${fresh.progress}%`;
        if (fresh.status !== "running") { stopPoll("detail"); navigate(`/backups/${id}`, false); }
      }, 3000);
    }
  },

  async restore(el) {
    const [backups, restores] = await Promise.all([
      api("/api/v1/backups?status=success&limit=200"),
      api("/api/v1/restores?limit=50"),
    ]);

    el.innerHTML = `
      <div class="grid grid-2 mb-2" style="align-items:start">
        <div class="card"><div class="card-header"><h3>${t("backups.restore")}</h3></div>
          <div class="card-body">
            <div class="field mb-2">
              <label for="r-backup">Backup</label>
              <select id="r-backup">
                <option value="">— select a backup —</option>
                ${backups.items.map((b) => `<option value="${b.id}">#${b.id} · ${fmt.escape(b.job_name)} · ${fmt.date(b.created_at)} · ${fmt.bytes(b.archive_size)}</option>`).join("")}
              </select>
            </div>
            <div id="r-detail" class="muted" style="font-size:12.5px">Select a backup to inspect its contents.</div>
            <div class="field mt-2">
              <label for="r-dest">${t("restore.destination")} *</label>
              <input id="r-dest" placeholder="/var/www/restore" class="mono">
            </div>
            <div class="field mt-2">
              <label for="r-paths">${t("restore.selectFiles")}</label>
              <textarea id="r-paths" placeholder="var/www/index.php&#10;etc/nginx/nginx.conf" class="mono" style="min-height:80px"></textarea>
            </div>
            <label class="checkbox mt-2"><input type="checkbox" id="r-overwrite"><span>${t("restore.overwrite")}</span></label>
            <label class="checkbox mt-1"><input type="checkbox" id="r-safety" checked><span>${t("restore.safety")}</span></label>
            <button class="btn btn-primary w-full mt-2" id="r-start">${t("restore.start")}</button>
          </div>
        </div>

        <div class="card"><div class="card-header"><h3>${t("restore.history")}</h3></div>
          <div class="card-body tight"><div class="table-wrap"><table class="data">
            <thead><tr><th>#</th><th>${t("common.status")}</th><th>Destination</th><th>Files</th><th>${t("common.date")}</th></tr></thead>
            <tbody id="r-history">${restores.length ? restores.map((r) => `
              <tr><td class="muted num">${r.id}</td><td>${statusBadge(r.status)}</td>
              <td class="mono truncate" style="max-width:220px">${fmt.escape(r.destination)}</td>
              <td class="num">${fmt.num(r.restored_files)}</td>
              <td class="num muted">${fmt.rel(r.finished_at || r.started_at)}</td></tr>`).join("")
              : `<tr><td colspan="5">${emptyState("No restores yet", "Restore operations will appear here.")}</td></tr>`}
            </tbody></table></div></div>
        </div>
      </div>`;

    document.getElementById("r-backup").addEventListener("change", async (e) => {
      const id = e.target.value;
      const detail = document.getElementById("r-detail");
      if (!id) { detail.textContent = "Select a backup to inspect its contents."; return; }
      detail.innerHTML = '<span class="spinner"></span>';
      try {
        const data = await api(`/api/v1/backups/${id}/archive?limit=40`);
        detail.innerHTML = `<div class="mb-1">${fmt.num(data.total)} entries in archive${data.truncated ? " (preview)" : ""}</div>
          <div class="code-block" style="max-height:160px;overflow-y:auto">${data.items.slice(0, 40).map((x) => fmt.escape(x.path)).join("\n")}</div>`;
      } catch (err) { detail.innerHTML = `<span class="text-critical">${fmt.escape(err.message)}</span>`; }
    });

    document.getElementById("r-start").addEventListener("click", async () => {
      const backupId = document.getElementById("r-backup").value;
      const destination = document.getElementById("r-dest").value.trim();
      if (!backupId) { toast("Select a backup first", "error"); return; }
      if (!destination) { toast("Destination path is required", "error"); return; }
      const paths = document.getElementById("r-paths").value.split("\n").map((s) => s.trim()).filter(Boolean);
      const ok = await confirmDialog({
        title: "Confirm restore",
        message: `Restore backup #${backupId} to ${destination}? ${paths.length ? paths.length + " selected path(s)." : "All files will be restored."}`,
        confirmText: "Start restore",
        danger: false,
      });
      if (!ok) return;
      try {
        const r = await api(`/api/v1/backups/${backupId}/restore`, {
          method: "POST",
          body: {
            destination,
            selected_paths: paths,
            overwrite: document.getElementById("r-overwrite").checked,
            create_safety_backup: document.getElementById("r-safety").checked,
            preserve_permissions: true,
          },
        });
        toast(`Restore #${r.restore_id} started`, "success");
        showRestoreProgress(r.restore_id);
        pollRestore(r.restore_id);
      } catch (e) { toast(e.message, "error"); }
    });

    const showRestoreProgress = (restoreId) => {
      let box = document.getElementById("restore-progress");
      if (!box) {
        box = document.createElement("div");
        box.id = "restore-progress";
        box.className = "card mt-2";
        box.innerHTML = `
          <div class="card-header"><h3>Restore in progress</h3>
            <div class="spacer"></div><span class="mono" id="rp-pct">0%</span></div>
          <div class="card-body">
            <div class="progress"><div class="progress-bar" id="rp-bar" style="width:0%"></div></div>
            <div class="muted mono mt-1" id="rp-path" style="font-size:11.5px;word-break:break-all"></div>
          </div>`;
        document.querySelector("#view .grid").before(box);
      }
      box.dataset.restoreId = String(restoreId);
      box.classList.remove("hidden");
    };

    const pollRestore = (restoreId) => {
      poll("restore", async () => {
        const r = await api(`/api/v1/restores/${restoreId}`);
        const bar = document.getElementById("rp-bar");
        const pct = document.getElementById("rp-pct");
        const pathEl = document.getElementById("rp-path");
        if (bar) bar.style.width = `${r.progress || 0}%`;
        if (pct) pct.textContent = `${r.progress || 0}%`;
        if (pathEl && r.current_path) pathEl.textContent = r.current_path;
        if (r.status === "success") {
          stopPoll("restore");
          toast(`Restored ${r.restored_files} files (${fmt.bytes(r.restored_bytes)})`, "success");
          navigate("/restore", false);
        } else if (r.status === "failed") {
          stopPoll("restore");
          toast(r.error_message || "Restore failed", "error");
        }
      }, 2000);
    };
  },

  async schedules(el) {
    const jobs = await api("/api/v1/jobs");
    const scheduled = jobs.filter((j) => j.schedule && j.schedule.schedule_type !== "manual");
    const manual = jobs.filter((j) => !j.schedule || j.schedule.schedule_type === "manual");

    el.innerHTML = `
      <div class="card mb-2"><div class="card-header"><h3>Scheduled jobs</h3>
        <div class="spacer"></div><span class="muted" style="font-size:12px">${scheduled.length} scheduled</span></div>
        <div class="card-body tight"><div class="table-wrap"><table class="data">
          <thead><tr><th>${t("common.name")}</th><th>Schedule</th><th>Timezone</th><th>${t("jobs.nextRun")}</th><th>${t("common.status")}</th><th></th></tr></thead>
          <tbody>${scheduled.length ? scheduled.map((j) => `
            <tr>
              <td class="primary"><a href="/jobs/${j.id}/edit" style="color:inherit">${fmt.escape(j.name)}</a></td>
              <td class="secondary" style="font-size:12.5px">${fmt.escape(j.schedule_description)}</td>
              <td class="mono muted">${fmt.escape(j.schedule.timezone)}</td>
              <td class="num">${j.next_run_at ? fmt.date(j.next_run_at) : "—"}</td>
              <td>${j.schedule.paused ? '<span class="badge paused">paused</span>' : j.enabled ? '<span class="badge success">active</span>' : '<span class="badge disabled">disabled</span>'}</td>
              <td class="actions">
                <button class="btn btn-sm btn-ghost" data-pause="${j.id}" data-paused="${j.schedule.paused}">${j.schedule.paused ? t("common.resume") : t("common.pause")}</button>
                <button class="btn btn-sm btn-ghost" data-run="${j.id}">${t("common.run")}</button>
              </td>
            </tr>`).join("") : `<tr><td colspan="6">${emptyState("No scheduled jobs", "Add a schedule to a job to see it here.")}</td></tr>`}
          </tbody></table></div></div>
      </div>
      <div class="card"><div class="card-header"><h3>Manual jobs</h3></div>
        <div class="card-body tight"><div class="table-wrap"><table class="data">
          <thead><tr><th>${t("common.name")}</th><th>${t("common.status")}</th><th>${t("jobs.lastRun")}</th><th></th></tr></thead>
          <tbody>${manual.length ? manual.map((j) => `
            <tr><td class="primary">${fmt.escape(j.name)}</td>
            <td>${j.enabled ? '<span class="badge success">enabled</span>' : '<span class="badge disabled">disabled</span>'}</td>
            <td class="num muted">${j.last_run_at ? fmt.rel(j.last_run_at) : t("common.never")}</td>
            <td class="actions"><button class="btn btn-sm btn-ghost" data-run="${j.id}">${t("common.run")}</button></td></tr>`).join("")
            : `<tr><td colspan="4">${emptyState("No manual-only jobs", "")}</td></tr>`}
          </tbody></table></div></div>
      </div>`;

    el.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", async () => {
      try { const r = await api(`/api/v1/jobs/${b.dataset.run}/run`, { method: "POST" }); toast("Backup started", "success"); navigate(`/backups/${r.backup_id}`); }
      catch (e) { toast(e.message, "error"); }
    }));
    el.querySelectorAll("[data-pause]").forEach((b) => b.addEventListener("click", async () => {
      const paused = b.dataset.paused === "true";
      try {
        await api(`/api/v1/jobs/${b.dataset.pause}/${paused ? "resume" : "pause"}`, { method: "POST" });
        toast(paused ? "Schedule resumed" : "Schedule paused", "success");
        navigate("/schedules", false);
      } catch (e) { toast(e.message, "error"); }
    }));
  },
});

/* ------------------------------------------------------------------ */
/* Restore modal (from backup detail)                                  */
/* ------------------------------------------------------------------ */
function openRestoreModal(backup) {
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="alert info">${ICONS.info}<span>Restoring from <b>${fmt.escape(backup.job_name)}</b> (#${backup.id}, ${fmt.bytes(backup.archive_size)}).</span></div>
    <div class="field mb-2">
      <label>${t("restore.destination")} *</label>
      <input id="m-dest" class="mono" placeholder="/var/www/restore">
    </div>
    <div class="field mb-2">
      <label>${t("restore.selectFiles")}</label>
      <textarea id="m-paths" class="mono" style="min-height:70px" placeholder="var/www/index.php"></textarea>
    </div>
    <label class="checkbox"><input type="checkbox" id="m-overwrite"><span>${t("restore.overwrite")}</span></label>
    <label class="checkbox mt-1"><input type="checkbox" id="m-safety" checked><span>${t("restore.safety")}</span></label>`;
  const m = openModal({
    title: t("backups.restore"),
    body,
    footer: `<button class="btn" data-cancel>${t("common.cancel")}</button><button class="btn btn-primary" data-go>${t("restore.start")}</button>`,
  });
  m.el.querySelector("[data-cancel]").addEventListener("click", () => m.close());
  m.el.querySelector("[data-go]").addEventListener("click", async () => {
    const destination = body.querySelector("#m-dest").value.trim();
    if (!destination) { toast("Destination path is required", "error"); return; }
    const paths = body.querySelector("#m-paths").value.split("\n").map((s) => s.trim()).filter(Boolean);
    try {
      const r = await api(`/api/v1/backups/${backup.id}/restore`, {
        method: "POST",
        body: {
          destination, selected_paths: paths,
          overwrite: body.querySelector("#m-overwrite").checked,
          create_safety_backup: body.querySelector("#m-safety").checked,
          preserve_permissions: true,
        },
      });
      m.close();
      toast(`Restore #${r.restore_id} started — track it in the Restore Center`, "success");
    } catch (e) { toast(e.message, "error"); }
  });
}
