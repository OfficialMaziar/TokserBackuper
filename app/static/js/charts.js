/* Tokser Backup Manager — dependency-free SVG charts.
   Implements the data-viz rules: thin marks, recessive grid, legend for >=2
   series, crosshair tooltip, and a table view for accessibility. */
"use strict";

const Charts = (() => {
  const SERIES = ["--series-1", "--series-2", "--series-3", "--series-4",
                  "--series-5", "--series-6", "--series-7", "--series-8"];

  function seriesColor(index) {
    return cssVar(SERIES[index % SERIES.length]) || "#3987e5";
  }

  function niceMax(value) {
    if (!value || value <= 0) return 1;
    const exp = Math.floor(Math.log10(value));
    const base = Math.pow(10, exp);
    const norm = value / base;
    const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
    return step * base;
  }

  function svgEl(tag, attrs = {}) {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  }

  function buildTooltip(container) {
    let tip = container.querySelector(".chart-tooltip");
    if (!tip) {
      tip = document.createElement("div");
      tip.className = "chart-tooltip";
      container.appendChild(tip);
    }
    return tip;
  }

  function positionTooltip(tip, container, x, y) {
    const cw = container.clientWidth;
    const tw = tip.offsetWidth || 140;
    let left = x + 14;
    if (left + tw > cw - 8) left = x - tw - 14;
    if (left < 4) left = 4;
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(4, y - 12)}px`;
    tip.classList.add("visible");
  }

  function renderLegend(container, series) {
    if (series.length < 2) return;
    const legend = document.createElement("div");
    legend.className = "chart-legend";
    legend.innerHTML = series.map((s, i) =>
      `<span class="legend-item"><span class="legend-swatch" style="background:${s.color || seriesColor(i)}"></span>${fmt.escape(s.name)}</span>`
    ).join("");
    container.appendChild(legend);
  }

  /* ---------------------------------------------------------------- */
  /* Line / area chart                                                 */
  /* ---------------------------------------------------------------- */
  function lineChart(container, { labels, series, height = 220, yFormat = (v) => fmt.num(v),
                                  area = false, valueFormat = (v) => fmt.num(v) }) {
    container.innerHTML = "";
    container.classList.add("chart-body");
    if (!labels || !labels.length || !series.length) {
      container.innerHTML = `<div class="chart-empty">${t("common.noData")}</div>`;
      return;
    }
    const width = Math.max(320, container.clientWidth || 640);
    const pad = { top: 12, right: 14, bottom: 26, left: 46 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    let maxVal = 0;
    series.forEach((s) => s.data.forEach((v) => { if (v > maxVal) maxVal = v; }));
    const yMax = niceMax(maxVal);
    const n = labels.length;
    const xAt = (i) => pad.left + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
    const yAt = (v) => pad.top + innerH - (v / yMax) * innerH;

    const svg = svgEl("svg", { class: "chart-svg", viewBox: `0 0 ${width} ${height}`, height, role: "img" });

    // Gridlines + y labels
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const v = (yMax / ticks) * i;
      const y = yAt(v);
      svg.appendChild(svgEl("line", {
        x1: pad.left, x2: width - pad.right, y1: y, y2: y,
        stroke: cssVar("--grid"), "stroke-width": 1,
      }));
      const label = svgEl("text", {
        x: pad.left - 8, y: y + 4, "text-anchor": "end",
        fill: cssVar("--text-muted"), "font-size": 10.5,
        "font-variant-numeric": "tabular-nums",
      });
      label.textContent = yFormat(v);
      svg.appendChild(label);
    }

    // X labels (thinned)
    const maxLabels = Math.max(2, Math.floor(innerW / 70));
    const step = Math.ceil(n / maxLabels);
    labels.forEach((lab, i) => {
      if (i % step !== 0 && i !== n - 1) return;
      const txt = svgEl("text", {
        x: xAt(i), y: height - 8, "text-anchor": "middle",
        fill: cssVar("--text-muted"), "font-size": 10.5,
      });
      txt.textContent = lab;
      svg.appendChild(txt);
    });

    // Series
    series.forEach((s, si) => {
      const color = s.color || seriesColor(si);
      const pts = s.data.map((v, i) => [xAt(i), yAt(v)]);
      const path = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      if (area) {
        const areaPath = `${path} L${pts[pts.length - 1][0]},${pad.top + innerH} L${pts[0][0]},${pad.top + innerH} Z`;
        svg.appendChild(svgEl("path", {
          d: areaPath, fill: hexA(color, 0.14), stroke: "none",
        }));
      }
      svg.appendChild(svgEl("path", {
        d: path, fill: "none", stroke: color, "stroke-width": 2,
        "stroke-linejoin": "round", "stroke-linecap": "round",
      }));
    });

    // Crosshair layer
    const crosshair = svgEl("line", {
      y1: pad.top, y2: pad.top + innerH, stroke: cssVar("--axis"),
      "stroke-width": 1, "stroke-dasharray": "3 3", opacity: 0,
    });
    svg.appendChild(crosshair);
    const dots = series.map((s, si) => {
      const c = svgEl("circle", {
        r: 4, fill: s.color || seriesColor(si), stroke: cssVar("--chart-surface"),
        "stroke-width": 2, opacity: 0,
      });
      svg.appendChild(c);
      return c;
    });

    const overlay = svgEl("rect", {
      x: pad.left, y: pad.top, width: innerW, height: innerH,
      fill: "transparent", style: "cursor:crosshair",
    });
    svg.appendChild(overlay);
    container.appendChild(svg);

    const tip = buildTooltip(container);

    const showAt = (i) => {
      const x = xAt(i);
      crosshair.setAttribute("x1", x);
      crosshair.setAttribute("x2", x);
      crosshair.setAttribute("opacity", 1);
      series.forEach((s, si) => {
        dots[si].setAttribute("cx", x);
        dots[si].setAttribute("cy", yAt(s.data[i]));
        dots[si].setAttribute("opacity", 1);
      });
      const rows = series.map((s, si) =>
        `<div class="tt-row"><span class="tt-dot" style="background:${s.color || seriesColor(si)}"></span>${fmt.escape(s.name)}<b>${valueFormat(s.data[i])}</b></div>`
      ).join("");
      tip.innerHTML = `<div class="tt-title">${fmt.escape(labels[i])}</div>${rows}`;
      const rect = container.getBoundingClientRect();
      positionTooltip(tip, container, x + (container.clientWidth - width) / 2, pad.top + 8);
    };
    const hide = () => {
      crosshair.setAttribute("opacity", 0);
      dots.forEach((d) => d.setAttribute("opacity", 0));
      tip.classList.remove("visible");
    };

    overlay.addEventListener("mousemove", (e) => {
      const rect = svg.getBoundingClientRect();
      const scale = width / rect.width;
      const localX = (e.clientX - rect.left) * scale;
      const ratio = (localX - pad.left) / innerW;
      const i = Math.max(0, Math.min(n - 1, Math.round(ratio * (n - 1))));
      showAt(i);
    });
    overlay.addEventListener("mouseleave", hide);
    overlay.addEventListener("touchstart", (e) => {
      const rect = svg.getBoundingClientRect();
      const t0 = e.touches[0];
      const scale = width / rect.width;
      const localX = (t0.clientX - rect.left) * scale;
      const i = Math.max(0, Math.min(n - 1, Math.round(((localX - pad.left) / innerW) * (n - 1))));
      showAt(i);
    }, { passive: true });

    container.appendChild(buildTable(labels, series, valueFormat));
  }

  /* ---------------------------------------------------------------- */
  /* Bar chart (grouped)                                               */
  /* ---------------------------------------------------------------- */
  function barChart(container, { labels, series, height = 220, stacked = false,
                                 yFormat = (v) => fmt.num(v), valueFormat = (v) => fmt.num(v) }) {
    container.innerHTML = "";
    container.classList.add("chart-body");
    if (!labels || !labels.length || !series.length) {
      container.innerHTML = `<div class="chart-empty">${t("common.noData")}</div>`;
      return;
    }
    const width = Math.max(320, container.clientWidth || 640);
    const pad = { top: 12, right: 14, bottom: 26, left: 46 };
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;

    let maxVal = 0;
    if (stacked) {
      labels.forEach((_, i) => {
        const total = series.reduce((acc, s) => acc + (s.data[i] || 0), 0);
        if (total > maxVal) maxVal = total;
      });
    } else {
      series.forEach((s) => s.data.forEach((v) => { if (v > maxVal) maxVal = v; }));
    }
    const yMax = niceMax(maxVal);
    const n = labels.length;
    const slot = innerW / n;
    const groupW = Math.min(slot * 0.68, 46);
    const barW = stacked ? groupW : Math.max(2, (groupW - (series.length - 1) * 2) / series.length);

    const svg = svgEl("svg", { class: "chart-svg", viewBox: `0 0 ${width} ${height}`, height, role: "img" });
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) {
      const v = (yMax / ticks) * i;
      const y = pad.top + innerH - (v / yMax) * innerH;
      svg.appendChild(svgEl("line", { x1: pad.left, x2: width - pad.right, y1: y, y2: y, stroke: cssVar("--grid") }));
      const label = svgEl("text", { x: pad.left - 8, y: y + 4, "text-anchor": "end", fill: cssVar("--text-muted"), "font-size": 10.5 });
      label.textContent = yFormat(v);
      svg.appendChild(label);
    }

    const maxLabels = Math.max(2, Math.floor(innerW / 62));
    const step = Math.ceil(n / maxLabels);
    labels.forEach((lab, i) => {
      if (i % step !== 0 && i !== n - 1) return;
      const x = pad.left + slot * i + slot / 2;
      const txt = svgEl("text", { x, y: height - 8, "text-anchor": "middle", fill: cssVar("--text-muted"), "font-size": 10.5 });
      txt.textContent = lab;
      svg.appendChild(txt);
    });

    const tip = buildTooltip(container);
    const bars = [];

    labels.forEach((lab, i) => {
      const cx = pad.left + slot * i + slot / 2;
      let stackY = pad.top + innerH;
      series.forEach((s, si) => {
        const color = s.color || seriesColor(si);
        const v = s.data[i] || 0;
        const h = (v / yMax) * innerH;
        let x, y;
        if (stacked) {
          x = cx - groupW / 2;
          y = stackY - h;
          stackY = y;
        } else {
          x = cx - groupW / 2 + si * (barW + 2);
          y = pad.top + innerH - h;
        }
        if (h > 0.5) {
          const rect = svgEl("rect", {
            x: x.toFixed(1), y: y.toFixed(1), width: barW.toFixed(1),
            height: Math.max(1, h).toFixed(1), rx: Math.min(4, barW / 2),
            fill: color, style: "cursor:pointer",
          });
          svg.appendChild(rect);
          bars.push({ rect, i });
        }
      });
    });

    container.appendChild(svg);

    const showBar = (i) => {
      const rows = series.map((s, si) =>
        `<div class="tt-row"><span class="tt-dot" style="background:${s.color || seriesColor(si)}"></span>${fmt.escape(s.name)}<b>${valueFormat(s.data[i])}</b></div>`
      ).join("");
      tip.innerHTML = `<div class="tt-title">${fmt.escape(labels[i])}</div>${rows}`;
      const x = pad.left + slot * i + slot / 2;
      positionTooltip(tip, container, x, pad.top + 10);
    };
    bars.forEach(({ rect, i }) => {
      rect.addEventListener("mouseenter", () => showBar(i));
      rect.addEventListener("mouseleave", () => tip.classList.remove("visible"));
    });

    container.appendChild(buildTable(labels, series, valueFormat));
  }

  /* ---------------------------------------------------------------- */
  /* Donut / ring                                                      */
  /* ---------------------------------------------------------------- */
  function donut(container, { segments, height = 200, centerLabel = "", centerValue = "" }) {
    container.innerHTML = "";
    container.classList.add("chart-body");
    const total = segments.reduce((a, s) => a + (s.value || 0), 0);
    if (!total) {
      container.innerHTML = `<div class="chart-empty">${t("common.noData")}</div>`;
      return;
    }
    const size = Math.min(height, 200);
    const r = size / 2 - 12;
    const cx = size / 2, cy = size / 2;
    const thickness = 18;
    const circ = 2 * Math.PI * r;
    let offset = 0;

    const svg = svgEl("svg", { class: "chart-svg", viewBox: `0 0 ${size} ${size}`, height: size, width: size, style: "max-width:200px;margin:0 auto", role: "img" });
    svg.appendChild(svgEl("circle", { cx, cy, r, fill: "none", stroke: cssVar("--surface-3"), "stroke-width": thickness }));

    segments.forEach((seg, i) => {
      const frac = seg.value / total;
      if (frac <= 0) return;
      const dash = Math.max(0, frac * circ - 2); // 2px surface gap between segments
      const arc = svgEl("circle", {
        cx, cy, r, fill: "none",
        stroke: seg.color || seriesColor(i),
        "stroke-width": thickness,
        "stroke-dasharray": `${dash} ${circ - dash}`,
        "stroke-dashoffset": -offset,
        transform: `rotate(-90 ${cx} ${cy})`,
        "stroke-linecap": "butt",
      });
      svg.appendChild(arc);
      offset += frac * circ;
    });

    if (centerValue !== "") {
      const v = svgEl("text", { x: cx, y: cy - 2, "text-anchor": "middle", fill: cssVar("--text-primary"), "font-size": 19, "font-weight": 680 });
      v.textContent = centerValue;
      svg.appendChild(v);
      if (centerLabel) {
        const l = svgEl("text", { x: cx, y: cy + 15, "text-anchor": "middle", fill: cssVar("--text-muted"), "font-size": 10.5 });
        l.textContent = centerLabel;
        svg.appendChild(l);
      }
    }
    container.appendChild(svg);

    const legend = document.createElement("div");
    legend.className = "chart-legend";
    legend.style.padding = "10px 0 0";
    legend.style.justifyContent = "center";
    legend.innerHTML = segments.map((s, i) =>
      `<span class="legend-item"><span class="legend-swatch" style="background:${s.color || seriesColor(i)}"></span>${fmt.escape(s.name)} <b style="color:var(--text-primary);font-variant-numeric:tabular-nums">${fmt.num(s.value)}</b></span>`
    ).join("");
    container.appendChild(legend);

    // Table view so the values stay readable for low-contrast fills.
    const tableRows = segments.map((s) =>
      `<tr><td>${fmt.escape(s.name)}</td><td>${fmt.num(s.value)}</td><td>${((s.value / total) * 100).toFixed(1)}%</td></tr>`
    ).join("");
    const table = document.createElement("div");
    table.className = "chart-data-table hidden";
    table.innerHTML = `<table><thead><tr><th>Segment</th><th>Value</th><th>Share</th></tr></thead><tbody>${tableRows}</tbody></table>`;
    container.appendChild(table);
  }

  /* ---------------------------------------------------------------- */
  /* Table view (accessibility / relief for low-contrast colors)       */
  /* ---------------------------------------------------------------- */
  function buildTable(labels, series, valueFormat) {
    const wrap = document.createElement("div");
    wrap.className = "chart-data-table hidden";
    const head = `<tr><th>${fmt.escape(t("common.date"))}</th>${series.map(s => `<th>${fmt.escape(s.name)}</th>`).join("")}</tr>`;
    const rows = labels.map((lab, i) =>
      `<tr><td>${fmt.escape(lab)}</td>${series.map(s => `<td>${fmt.escape(valueFormat(s.data[i] || 0))}</td>`).join("")}</tr>`
    ).join("");
    wrap.innerHTML = `<table><thead>${head}</thead><tbody>${rows}</tbody></table>`;
    return wrap;
  }

  function attachTableToggle(container, button) {
    button.addEventListener("click", () => {
      const table = container.querySelector(".chart-data-table");
      if (!table) return;
      table.classList.toggle("hidden");
      button.textContent = table.classList.contains("hidden") ? "Show data table" : "Hide data table";
    });
  }

  return { lineChart, barChart, donut, seriesColor, attachTableToggle, buildTable };
})();
