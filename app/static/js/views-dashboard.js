/* Dashboard and Server Monitoring views. */
"use strict";

registerViews({
  async dashboard(el) {
    el.innerHTML = `
      <div class="grid grid-4 mb-2" id="stat-grid">
        ${Array.from({ length: 4 }).map(() => `<div class="stat"><div class="skeleton" style="height:56px"></div></div>`).join("")}
      </div>
      <div class="grid grid-2 mb-2">
        <div class="card chart-card">
          <div class="card-header">
            <h3>${t("dash.activity")}</h3>
            <span class="hint muted" style="font-size:11.5px">${t("dash.activitySub")}</span>
            <div class="spacer"></div>
            <button class="chart-table-toggle" id="act-table">Show data table</button>
          </div>
          <div id="chart-activity"></div>
        </div>
        <div class="card chart-card">
          <div class="card-header">
            <h3>${t("dash.storage")}</h3>
            <div class="spacer"></div>
            <button class="chart-table-toggle" id="disk-table">Show data table</button>
          </div>
          <div id="chart-disk"></div>
        </div>
      </div>
      <div class="grid grid-2 mb-2">
        <div class="card chart-card">
          <div class="card-header">
            <h3>${t("dash.sizeHistory")}</h3>
            <div class="spacer"></div>
            <button class="chart-table-toggle" id="size-table">Show data table</button>
          </div>
          <div id="chart-size"></div>
        </div>
        <div class="card">
          <div class="card-header"><h3>${t("dash.systemHealth")}</h3></div>
          <div class="card-body" id="health-body"><span class="spinner"></span></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <h3>${t("dash.recent")}</h3>
          <div class="spacer"></div>
          <a class="btn btn-sm" href="/backups">${t("nav.history")}</a>
        </div>
        <div class="card-body tight"><div class="table-wrap">
          <table class="data"><thead><tr>
            <th>${t("common.name")}</th><th>${t("common.status")}</th><th>${t("common.size")}</th>
            <th>${t("common.duration")}</th><th>${t("common.date")}</th><th></th>
          </tr></thead><tbody id="recent-body">${skeletonRows(4, 6)}</tbody></table>
        </div></div>
      </div>`;

    const load = async () => {
      const d = await api("/api/v1/dashboard");
      renderStats(d);
      renderCharts(d);
      renderHealth(d);
      renderRecent(d.recent_backups);
    };

    const renderStats = (d) => {
      const s = d.stats;
      const disk = d.disk;
      const tiles = [
        { label: t("dash.totalJobs"), value: fmt.num(s.total_jobs), foot: `${s.enabled_jobs} ${t("common.enabled").toLowerCase()}`, icon: "layers", tone: "" },
        { label: t("dash.successful"), value: fmt.num(s.successful_backups), foot: `${t("dash.successRate")}: ${fmt.pct(s.backup_success_rate)}`, icon: "check", tone: "good" },
        { label: t("dash.failed"), value: fmt.num(s.failed_backups), foot: `${s.running_backups} ${t("status.running").toLowerCase()}`, icon: "x", tone: s.failed_backups ? "critical" : "" },
        { label: t("dash.totalSize"), value: fmt.bytes(s.total_backup_size), foot: `${t("dash.freeSpace")}: ${fmt.bytes(disk.free)}`, icon: "database", tone: "info" },
      ];
      document.getElementById("stat-grid").innerHTML = tiles.map((x) => `
        <div class="stat">
          <div class="stat-label">${fmt.escape(x.label)}</div>
          <div class="stat-value">${fmt.escape(x.value)}</div>
          <div class="stat-foot">${fmt.escape(x.foot)}</div>
          <div class="stat-icon ${x.tone}">${icon(x.icon)}</div>
        </div>`).join("") + `
        <div class="stat">
          <div class="stat-label">${t("dash.lastBackup")}</div>
          <div class="stat-value sm">${d.last_backup ? fmt.rel(d.last_backup.finished_at) : t("common.never")}</div>
          <div class="stat-foot truncate">${d.last_backup ? fmt.escape(d.last_backup.job_name) : "—"}</div>
          <div class="stat-icon info">${icon("archive")}</div>
        </div>
        <div class="stat">
          <div class="stat-label">${t("dash.nextBackup")}</div>
          <div class="stat-value sm">${d.next_backup ? fmt.rel(d.next_backup.next_run_at) : t("common.none")}</div>
          <div class="stat-foot truncate">${d.next_backup ? fmt.escape(d.next_backup.job_name) : "—"}</div>
          <div class="stat-icon">${icon("clock")}</div>
        </div>
        <div class="stat">
          <div class="stat-label">${t("dash.uptime")}</div>
          <div class="stat-value sm">${fmt.uptime(d.system.uptime_seconds)}</div>
          <div class="stat-foot truncate">${fmt.escape(d.system.hostname)}</div>
          <div class="stat-icon good">${icon("activity")}</div>
        </div>
        <div class="stat">
          <div class="stat-label">${t("dash.freeSpace")}</div>
          <div class="stat-value sm">${fmt.bytes(disk.free)}</div>
          <div class="stat-foot">${fmt.pct(disk.percent)} ${t("common.size").toLowerCase()} · ${fmt.bytes(disk.total)}</div>
          <div class="stat-icon ${disk.level === "ok" ? "good" : disk.level === "warning" ? "warning" : "critical"}">${icon("database")}</div>
        </div>`;
      // grid-4 only fits 4; switch to auto grid for 8 tiles
      document.getElementById("stat-grid").className = "grid grid-4 mb-2";
    };

    const renderCharts = (d) => {
      const series = d.activity_series;
      const labels = series.map((x) => x.date.slice(5));
      const actEl = document.getElementById("chart-activity");
      Charts.barChart(actEl, {
        labels,
        series: [
          { name: t("status.success"), data: series.map((x) => x.success), color: cssVar("--series-3") },
          { name: t("status.failed"), data: series.map((x) => x.failed), color: cssVar("--series-8") },
        ],
        height: 210,
      });
      Charts.attachTableToggle(actEl, document.getElementById("act-table"));

      const diskEl = document.getElementById("chart-disk");
      Charts.donut(diskEl, {
        segments: [
          { name: "Used", value: d.disk.used, color: cssVar("--series-1") },
          { name: "Free", value: d.disk.free, color: cssVar("--surface-3") },
        ],
        centerValue: fmt.pct(d.disk.percent),
        centerLabel: "used",
        height: 210,
      });
      Charts.attachTableToggle(diskEl, document.getElementById("disk-table"));

      const sizeEl = document.getElementById("chart-size");
      Charts.lineChart(sizeEl, {
        labels,
        series: [{ name: t("common.size"), data: series.map((x) => x.size), color: cssVar("--series-1") }],
        height: 210,
        area: true,
        yFormat: (v) => fmt.bytes(v),
        valueFormat: (v) => fmt.bytes(v),
      });
      Charts.attachTableToggle(sizeEl, document.getElementById("size-table"));
    };

    const renderHealth = (d) => {
      const rows = [
        { label: t("dash.cpu"), value: d.system.cpu_percent, tone: d.system.cpu_percent > 85 ? "critical" : d.system.cpu_percent > 65 ? "warning" : "" },
        { label: t("dash.memory"), value: d.system.memory_percent, tone: d.system.memory_percent > 85 ? "critical" : d.system.memory_percent > 65 ? "warning" : "" },
        { label: t("dash.disk"), value: d.disk.percent, tone: d.disk.level === "ok" ? "" : d.disk.level },
      ];
      document.getElementById("health-body").innerHTML = rows.map((r) => `
        <div style="margin-bottom:16px">
          <div class="flex" style="justify-content:space-between;margin-bottom:6px">
            <span class="secondary" style="font-size:12.5px">${fmt.escape(r.label)}</span>
            <span class="mono" style="color:var(--text-primary)">${fmt.pct(r.value)}</span>
          </div>
          <div class="progress"><div class="progress-bar ${r.tone}" style="width:${Math.min(100, r.value)}%"></div></div>
        </div>`).join("") + `
        <div class="flex" style="justify-content:space-between;margin-top:18px;padding-top:14px;border-top:1px solid var(--border)">
          <span class="muted" style="font-size:12px">${t("nav.monitoring")}</span>
          <a class="btn btn-sm" href="/monitoring">${t("common.view")}</a>
        </div>`;
    };

    const renderRecent = (items) => {
      const body = document.getElementById("recent-body");
      if (!items || !items.length) {
        body.innerHTML = `<tr><td colspan="6">${emptyState(t("backups.empty"), "Run a job to see history here.")}</td></tr>`;
        return;
      }
      body.innerHTML = items.map((b) => `
        <tr>
          <td class="primary">${fmt.escape(b.job_name)}</td>
          <td>${statusBadge(b.status)}</td>
          <td class="num">${fmt.bytes(b.archive_size)}</td>
          <td class="num">${fmt.duration(b.duration_seconds)}</td>
          <td class="num muted">${fmt.rel(b.created_at)}</td>
          <td class="actions"><a class="btn btn-sm btn-ghost" href="/backups/${b.id}">${t("common.view")}</a></td>
        </tr>`).join("");
    };

    await load();
    poll("dashboard", load, 15000);
  },

  async monitoring(el) {
    el.innerHTML = `
      <div class="grid grid-4 mb-2" id="mon-stats"></div>
      <div class="grid grid-2 mb-2">
        <div class="card"><div class="card-header"><h3>CPU &amp; Memory</h3></div><div class="card-body" id="mon-gauges"><span class="spinner"></span></div></div>
        <div class="card"><div class="card-header"><h3>Disk &amp; Network</h3></div><div class="card-body" id="mon-io"><span class="spinner"></span></div></div>
      </div>
      <div class="card">
        <div class="card-header"><h3>System Information</h3></div>
        <div class="card-body"><dl class="kv" id="mon-info"></dl></div>
      </div>`;

    const load = async () => {
      const m = await api("/api/v1/monitoring");
      document.getElementById("mon-stats").innerHTML = [
        { label: "CPU", value: fmt.pct(m.cpu.percent), foot: `${m.cpu.cores} cores`, tone: m.cpu.percent > 85 ? "critical" : "" },
        { label: "Memory", value: fmt.pct(m.memory.percent), foot: `${fmt.bytes(m.memory.used)} / ${fmt.bytes(m.memory.total)}`, tone: m.memory.percent > 85 ? "critical" : "" },
        { label: "Disk", value: fmt.pct(m.disk.percent), foot: `${fmt.bytes(m.disk.free)} free`, tone: m.disk_health.level === "ok" ? "" : m.disk_health.level },
        { label: "Uptime", value: fmt.uptime(m.uptime_seconds), foot: `${fmt.num(m.processes)} processes`, tone: "good" },
      ].map((x) => `<div class="stat"><div class="stat-label">${x.label}</div><div class="stat-value">${x.value}</div><div class="stat-foot">${x.foot}</div></div>`).join("");

      document.getElementById("mon-gauges").innerHTML = `
        <div style="margin-bottom:18px">
          <div class="flex" style="justify-content:space-between;margin-bottom:6px"><span class="secondary">CPU</span><span class="mono">${fmt.pct(m.cpu.percent)}</span></div>
          <div class="progress"><div class="progress-bar ${m.cpu.percent > 85 ? "critical" : m.cpu.percent > 65 ? "warning" : "good"}" style="width:${m.cpu.percent}%"></div></div>
        </div>
        <div style="margin-bottom:18px">
          <div class="flex" style="justify-content:space-between;margin-bottom:6px"><span class="secondary">Memory</span><span class="mono">${fmt.bytes(m.memory.used)} / ${fmt.bytes(m.memory.total)}</span></div>
          <div class="progress"><div class="progress-bar ${m.memory.percent > 85 ? "critical" : m.memory.percent > 65 ? "warning" : "good"}" style="width:${m.memory.percent}%"></div></div>
        </div>
        <div>
          <div class="flex" style="justify-content:space-between;margin-bottom:6px"><span class="secondary">Swap</span><span class="mono">${fmt.bytes(m.memory.swap_used)} / ${fmt.bytes(m.memory.swap_total)}</span></div>
          <div class="progress"><div class="progress-bar" style="width:${m.memory.swap_percent}%"></div></div>
        </div>`;

      document.getElementById("mon-io").innerHTML = `
        <dl class="kv">
          <dt>Backup volume</dt><dd>${fmt.escape(m.disk_health.path)}</dd>
          <dt>Used</dt><dd>${fmt.bytes(m.disk_health.used)} / ${fmt.bytes(m.disk_health.total)}</dd>
          <dt>Free</dt><dd class="${m.disk_health.level === "ok" ? "text-good" : "text-critical"}">${fmt.bytes(m.disk_health.free)}</dd>
          <dt>Network RX</dt><dd>${fmt.bytes(m.network.rx_bytes_per_sec)}/s</dd>
          <dt>Network TX</dt><dd>${fmt.bytes(m.network.tx_bytes_per_sec)}/s</dd>
          <dt>Disk read</dt><dd>${fmt.bytes(m.disk_io.read_bytes || 0)}</dd>
          <dt>Disk write</dt><dd>${fmt.bytes(m.disk_io.write_bytes || 0)}</dd>
        </dl>`;

      document.getElementById("mon-info").innerHTML = `
        <dt>Hostname</dt><dd>${fmt.escape(m.hostname)}</dd>
        <dt>Platform</dt><dd>${fmt.escape(m.platform)}</dd>
        <dt>Python</dt><dd>${fmt.escape(m.python)}</dd>
        <dt>Load average</dt><dd>${(m.cpu.load_avg || []).join(" / ") || "n/a"}</dd>
        <dt>Scheduler</dt><dd>${m.scheduler.running ? '<span class="badge success">running</span>' : '<span class="badge idle">stopped</span>'} · tick ${m.scheduler.tick_seconds}s</dd>
        <dt>Backup service</dt><dd><span class="badge success">${m.backup_service.status}</span> · max ${m.backup_service.max_concurrent} concurrent</dd>
        <dt>Last tick</dt><dd>${m.scheduler.last_tick ? fmt.rel(m.scheduler.last_tick) : "—"}</dd>`;
    };

    await load();
    poll("monitoring", load, 8000);
  },
});
