const SVG = "http://www.w3.org/2000/svg";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function fmtDeals(value) {
  if (value === null || value === undefined) return "无累计";
  return new Intl.NumberFormat("zh-CN").format(value) + " 套";
}

function fmtYoy(value) {
  if (value === null || value === undefined) return "—";
  const sign = Number(value) > 0 ? "+" : "";
  return sign + value + "%";
}

function fmtArea(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
}

async function loadJson(path) {
  const response = await fetch(new URL(path, document.baseURI));
  if (!response.ok) throw new Error(path + " 返回 " + response.status);
  return response.json();
}

function renderSummary(snapshot) {
  const host = document.getElementById("summary");
  host.replaceChildren();
  const banner = el("p", "banner-note");
  if (snapshot.ingest === "import") {
    banner.textContent = "这份最新快照是维护者录入的网签套数，不是这次自动抓取。";
  } else if (snapshot.writer === "huchai-feed") {
    banner.textContent = "这份最新快照由爬虫写入，来源是网上房地产的二手房昨日网签。";
  } else {
    banner.textContent = "最新快照仍是已核对的人工收录（" + snapshot.updated + "）。自动抓取成功之前，这里不会被空数据覆盖。";
  }
  host.append(banner);

  const mtd = snapshot.mtd || {};
  const months = snapshot.monthly || [];
  const complete = [...months].reverse().find((row) => !row.partial);
  const dailies = snapshot.daily || [];
  const latestDay = dailies[dailies.length - 1];
  const cards = [
    ["数据截至", snapshot.asOf || "—", "快照日 " + snapshot.updated],
    ["月内累计", fmtDeals(mtd.deals), "截至 " + (mtd.through || "—") + (mtd.partial ? " · 未完" : "")],
    ["最近完整月", complete ? complete.key : "—", complete ? fmtDeals(complete.deals) + " · 同比 " + fmtYoy(complete.yoy) : "还没有标成完整月"],
    ["最近收录单日", latestDay ? latestDay.key : "—", latestDay ? fmtDeals(latestDay.deals) : "—"],
  ];
  const grid = el("div", "cards");
  cards.forEach(([label, value, sub]) => {
    const card = el("article", "card");
    card.append(el("p", "label", label), el("p", "value", value), el("p", "sub", sub));
    grid.append(card);
  });
  host.append(grid);
  if (mtd.note) host.append(el("p", "note", mtd.note));
  host.append(el("p", "note", "来源注记：" + (snapshot.source || "网上房地产")));
}

function renderSignals(signals) {
  const host = document.getElementById("signal-list");
  host.replaceChildren();
  if (!signals || !signals.from) {
    host.append(el("p", "note", "还没有上一份快照，暂时没有对比。"));
    return;
  }
  host.append(el("p", "note", signals.from + " → " + signals.to));
  host.append(signalList(signals.items));
}

function signalList(items) {
  const list = el("div", "signal-list");
  if (!items || !items.length) {
    list.append(el("p", "note", "这两份快照之间没有新的成交变化。"));
    return list;
  }
  items.forEach((item) => {
    const card = el("article", "signal " + (item.tone || "info"));
    card.append(el("p", "tag", toneLabel(item.tone)));
    card.append(el("h3", null, item.title));
    if (item.detail) card.append(el("p", null, item.detail));
    list.append(card);
  });
  return list;
}

function toneLabel(tone) {
  if (tone === "up") return "放量";
  if (tone === "down") return "缩量";
  return "变动";
}

function renderCharts(snapshot) {
  const host = document.getElementById("charts");
  host.replaceChildren();
  host.append(chartPanel("月度成交（套）", (snapshot.monthly || []).map((row) => ({
    label: Number(row.key.slice(5)) + "月",
    value: row.deals,
    partial: Boolean(row.partial),
  }))));
  host.append(chartPanel("已收录单日（套）", (snapshot.daily || []).map((row) => ({
    label: row.key.slice(5),
    value: row.deals,
    partial: false,
  }))));
}

function chartPanel(title, rows) {
  const panel = el("div", "panel");
  panel.append(el("h3", null, title));
  const usable = rows.filter((row) => typeof row.value === "number");
  if (!usable.length) {
    panel.append(el("p", "note", "这一栏还没有可画的数字。"));
    return panel;
  }
  const max = Math.max(1, ...usable.map((row) => row.value));
  const barW = 36;
  const gap = 28;
  const height = 180;
  const width = Math.max(280, usable.length * (barW + gap) + gap);
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", title);
  svg.setAttribute("viewBox", "0 0 " + width + " " + height);
  svg.setAttribute("width", String(width));
  svg.setAttribute("height", String(height));
  usable.forEach((row, index) => {
    const barHeight = Math.max(2, Math.round((row.value / max) * 110));
    const x = gap + index * (barW + gap);
    const y = 128 - barHeight;
    const rect = document.createElementNS(SVG, "rect");
    rect.setAttribute("x", String(x));
    rect.setAttribute("y", String(y));
    rect.setAttribute("width", String(barW));
    rect.setAttribute("height", String(barHeight));
    rect.setAttribute("rx", "4");
    rect.setAttribute("fill", row.partial ? "#c4a484" : "#9f2d2d");
    svg.append(rect);
    const value = document.createElementNS(SVG, "text");
    value.setAttribute("x", String(x + barW / 2));
    value.setAttribute("y", String(y - 6));
    value.setAttribute("text-anchor", "middle");
    value.textContent = new Intl.NumberFormat("zh-CN").format(row.value);
    svg.append(value);
    const label = document.createElementNS(SVG, "text");
    label.setAttribute("class", "bar-label");
    label.setAttribute("x", String(x + barW / 2));
    label.setAttribute("y", "156");
    label.setAttribute("text-anchor", "middle");
    label.textContent = row.label;
    svg.append(label);
  });
  const scroller = el("div", "scroll");
  scroller.append(svg);
  panel.append(scroller);
  return panel;
}

function renderTables(snapshot) {
  const host = document.getElementById("tables");
  host.replaceChildren();
  host.append(monthTable(snapshot.monthly || []));
  host.append(dailyTable(snapshot.daily || []));
}

function monthTable(rows) {
  const panel = el("div", "panel");
  panel.append(el("h3", null, "月度"));
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["月份", "套数", "同比", "说明"].forEach((name, index) => {
    head.append(el("th", index === 1 || index === 2 ? "num" : null, name));
  });
  table.append(head);
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    const month = el("td", null, row.key);
    if (row.partial) month.append(el("span", "badge", "未完月"));
    tr.append(month);
    tr.append(el("td", "num", fmtDeals(row.deals)));
    tr.append(el("td", "num", fmtYoy(row.yoy)));
    tr.append(el("td", null, row.note || ""));
    table.append(tr);
  });
  panel.append(table);
  return panel;
}

function dailyTable(rows) {
  const panel = el("div", "panel");
  panel.append(el("h3", null, "单日"));
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["日期", "套数", "面积㎡", "说明"].forEach((name, index) => {
    head.append(el("th", index === 1 || index === 2 ? "num" : null, name));
  });
  table.append(head);
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.append(el("td", null, row.key));
    tr.append(el("td", "num", fmtDeals(row.deals)));
    tr.append(el("td", "num", fmtArea(row.area)));
    tr.append(el("td", null, row.note || ""));
    table.append(tr);
  });
  panel.append(table);
  return panel;
}

function renderHistory(index) {
  const host = document.getElementById("history");
  host.replaceChildren();
  const panel = el("div", "panel");
  const table = document.createElement("table");
  const head = document.createElement("tr");
  ["快照日", "截至", "月内累计", "收录单日"].forEach((name, index) => {
    head.append(el("th", index === 2 ? "num" : null, name));
  });
  table.append(head);
  (index.snapshots || []).forEach((row) => {
    const tr = document.createElement("tr");
    const link = document.createElement("a");
    link.href = row.path;
    link.textContent = row.updated;
    const cell = el("td");
    cell.append(link);
    tr.append(cell);
    tr.append(el("td", null, row.asOf));
    tr.append(el("td", "num", fmtDeals(row.mtdDeals)));
    const days = row.days || [];
    tr.append(el("td", null, days.length > 6 ? days.length + " 天" : days.join("、")));
    table.append(tr);
  });
  panel.append(table);
  host.append(panel);
}

function renderEarlier(signals) {
  const host = document.getElementById("earlier");
  host.replaceChildren();
  const pairs = (signals && signals.earlier) || [];
  if (!pairs.length) {
    host.append(el("p", "note", "没有更早的对比。"));
    return;
  }
  pairs.forEach((pair) => {
    const details = document.createElement("details");
    details.append(el("summary", null, pair.from + " → " + pair.to));
    details.append(signalList(pair.items));
    host.append(details);
  });
}

function showError(error) {
  const host = document.getElementById("summary");
  host.replaceChildren();
  host.append(el("p", "banner-note", "快照没有载入：" + error.message + "。请从站点根目录打开这个页面，而不是直接双击文件。"));
}

async function main() {
  try {
    const [snapshot, signals, index] = await Promise.all([
      loadJson("fangdi.json"),
      loadJson("signals.json"),
      loadJson("snapshots/index.json"),
    ]);
    renderSummary(snapshot);
    renderSignals(signals);
    renderCharts(snapshot);
    renderTables(snapshot);
    renderHistory(index);
    renderEarlier(signals);
    if (snapshot.updated && index.snapshots && index.snapshots.length) {
      const newest = index.snapshots[index.snapshots.length - 1].updated;
      if (newest !== snapshot.updated) {
        document.getElementById("summary").append(
          el("p", "note", "注意：最新文件 fangdi.json 的快照日是 " + snapshot.updated + "，目录里最新一份是 " + newest + "。")
        );
      }
    }
  } catch (error) {
    showError(error);
  }
}

main();
