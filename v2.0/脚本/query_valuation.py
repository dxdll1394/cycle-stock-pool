#!/usr/bin/env python3
"""
大周期股池 PE/PB 估值百分位查询工具 v2.0
================================================================
功能：
  - 多窗口并行输出（all / 10y / 5y / 3y）
  - 百分位趋势方向（↑ ↓ →）
  - 行业估值汇总
  - 多种排序方式
  - 只读模式（--read 跳过网络请求）
  - HTML 可排序表格 + Markdown 报告

用法：
  python3 query_valuation.py                    # 默认 all 窗口
  python3 query_valuation.py --read              # 只读缓存，不联网
  python3 query_valuation.py --sort composite    # 按综合得分排序
  python3 query_valuation.py --force             # 强制刷新缓存
  python3 query_valuation.py --no-cache          # 不使用缓存
================================================================
"""
import json, sys, time, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
POOL_FILE = BASE / "数据/大周期股池.json"
CACHE_DIR = BASE / "数据/估值缓存"
OUTPUT_JSON = BASE / "数据/大周期股池_pepb_pct.json"
OUTPUT_MD = BASE / "数据/大周期股池_估值报告.md"
OUTPUT_HTML = BASE / "数据/大周期股池_估值报告.html"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

WINDOWS = {"all": None, "10y": 10, "5y": 5, "3y": 3}
WINDOW_ORDER = ["all", "10y", "5y", "3y"]
SECTORS_ORDER = ["石油石化","煤炭","有色金属","钢铁","化工","建材","工程机械","航运港口","金融","农牧"]
TREND_LOOKBACK = 42

# ── 股票池 ──

def load_pool():
    with open(POOL_FILE) as f:
        sectors = json.load(f)
    stocks = []
    for sector, items in sectors.items():
        for item in items:
            stocks.append({**item, "sector": sector})
    return stocks

# ── 缓存 ──

def cache_path(code):
    return CACHE_DIR / f"{code}.json"

def load_cache(code):
    p = cache_path(code)
    if p.exists():
        return json.loads(p.read_text())
    return None

def save_cache(code, data):
    cache_path(code).write_text(json.dumps(data, ensure_ascii=False))

# ── 网络请求 ──

def fetch_stock(code, name):
    cache = load_cache(code)
    today = datetime.now().strftime("%Y-%m-%d")
    if cache and len(cache) > 1 and cache[-1]["date"] == today:
        return code, cache

    import akshare as ak
    try:
        df = ak.stock_value_em(symbol=code)
    except Exception as e:
        print(f"  {name}({code}) 请求失败: {e}", file=sys.stderr)
        return code, cache or []

    if df is None or df.empty:
        print(f"  {name}({code}) 数据为空", file=sys.stderr)
        return code, cache or []

    rows = []
    for _, row in df.iterrows():
        date_val = str(row.iloc[0])[:10]
        pe = row.get("PE(TTM)")
        pb = row.get("市净率")
        if pe is None:
            pe = row.get("PE(静)")
        rows.append({
            "date": date_val,
            "pe": round(float(pe), 4) if pd.notna(pe) else None,
            "pb": round(float(pb), 4) if pd.notna(pb) else None,
        })

    rows.sort(key=lambda x: x["date"])
    save_cache(code, rows)
    return code, rows

# ── 百分位计算 ──

def calc_pct(values):
    vals = np.array([v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))])
    if len(vals) < 30:
        return None, None
    latest = float(vals[-1])
    pct = float((vals <= latest).mean() * 100)
    return round(latest, 2), round(pct, 2)

def window_filter(rows, years):
    if years is None:
        return rows
    cutoff = (datetime.now() - timedelta(days=years * 365.25)).strftime("%Y-%m-%d")
    return [r for r in rows if r["date"] >= cutoff]

def compute_trend(rows):
    """计算趋势：对比当前百分位与 TREND_LOOKBACK 个交易日前"""
    if len(rows) < TREND_LOOKBACK + 30:
        return None, None

    def _pct(arr):
        vals = np.array([v for v in arr if v is not None and not (np.isnan(v) if isinstance(v, float) else False)])
        if len(vals) < 30:
            return None
        return float((vals <= vals[-1]).mean() * 100)

    pe_all = [r["pe"] for r in rows]
    pb_all = [r["pb"] for r in rows]

    pe_current_vals = pe_all[-(TREND_LOOKBACK+1):]
    pb_current_vals = pb_all[-(TREND_LOOKBACK+1):]
    pe_past_vals = pe_all[:-(TREND_LOOKBACK+1)] + pe_all[-(TREND_LOOKBACK+1):-1]
    pb_past_vals = pb_all[:-(TREND_LOOKBACK+1)] + pb_all[-(TREND_LOOKBACK+1):-1]

    pe_pct_now = _pct(pe_current_vals)
    pe_pct_before = _pct(pe_past_vals)
    pb_pct_now = _pct(pb_current_vals)
    pb_pct_before = _pct(pb_past_vals)

    return (pe_pct_now, pe_pct_before, pb_pct_now, pb_pct_before)

def trend_arrow(now, before):
    if now is None or before is None:
        return "→"
    diff = now - before
    if diff > 5: return "↑"
    if diff < -5: return "↓"
    return "→"

# ── 标签 ──

def label(pct):
    if pct is None: return "——"
    if pct >= 90: return "🔥极高"
    if pct >= 80: return "⚠️偏高"
    if pct >= 70: return "偏高"
    if pct >= 30: return "合理"
    if pct >= 20: return "偏低"
    if pct >= 10: return "📈偏低"
    return "💰极低"

def label_short(pct):
    if pct is None: return "--"
    if pct >= 90: return "极高"
    if pct >= 80: return "偏高"
    if pct >= 70: return "偏高"
    if pct >= 30: return "合理"
    if pct >= 10: return "偏低"
    return "极低"

def fmt(v, d=1):
    if v is None: return "-"
    return f"{v:.{d}f}"

# ── 排序 ──

def sort_key(stock_items, method):
    method = method or "code"
    if method == "code":
        return sorted(stock_items, key=lambda x: x[0])
    if method == "name":
        return sorted(stock_items, key=lambda x: x[1]["name"])
    if method == "pe_pct":
        return sorted(stock_items, key=lambda x: x[1].get("windows", {}).get("all", {}).get("pe_pct") or 999)
    if method == "pb_pct":
        return sorted(stock_items, key=lambda x: x[1].get("windows", {}).get("all", {}).get("pb_pct") or 999)
    if method == "composite":
        def _composite(item):
            w = item[1].get("windows", {}).get("all", {})
            pe = w.get("pe_pct")
            pb = w.get("pb_pct")
            if pe is None and pb is None:
                return 999
            if pe is None: return pb or 999
            if pb is None: return pe or 999
            return (pe + pb) / 2
        return sorted(stock_items, key=_composite)
    return sorted(stock_items, key=lambda x: x[0])

# ── 输出生成 ──

def gen_markdown(all_results, sector_summary, update_date):
    lines = [
        f"# 大周期股池估值百分位报告 v2.0",
        f"",
        f"**更新日期**: {update_date}  **覆盖**: {len(all_results)} 只股票  **数据天数**: ≥30 日",
        f"",
        f"## 一、个股估值",
        f"",
    ]

    header = "| 行业 | 代码 | 名称 | PE | PB | PE%_all | PE判断 | PB%_all | PB判断 | PE%_10y | PB%_10y | PE%_5y | PB%_5y | PE%_3y | PB%_3y | PE趋 | PB趋 | 天数 |"
    sep = "|------|------|------|----|----|---------|--------|---------|--------|---------|---------|--------|--------|--------|--------|------|------|------|"
    lines.append(header)
    lines.append(sep)

    for sector in SECTORS_ORDER:
        sector_stocks = sorted(
            [(k, v) for k, v in all_results.items() if v.get("sector") == sector],
            key=lambda x: x[1]["name"]
        )
        first = True
        for code, v in sector_stocks:
            sc = sector if first else ""
            first = False
            w = v.get("windows", {})
            tr = v.get("trend", {})
            pe_pct = w.get('all',{}).get('pe_pct')
            pb_pct = w.get('all',{}).get('pb_pct')
            lines.append(
                f"| {sc} | {code} | {v['name']} "
                f"| {fmt(w.get('all',{}).get('pe'))} | {fmt(w.get('all',{}).get('pb'),2)} "
                f"| {fmt(pe_pct)} | {label_short(pe_pct)} | {fmt(pb_pct)} | {label_short(pb_pct)} "
                f"| {fmt(w.get('10y',{}).get('pe_pct'))} | {fmt(w.get('10y',{}).get('pb_pct'))} "
                f"| {fmt(w.get('5y',{}).get('pe_pct'))} | {fmt(w.get('5y',{}).get('pb_pct'))} "
                f"| {fmt(w.get('3y',{}).get('pe_pct'))} | {fmt(w.get('3y',{}).get('pb_pct'))} "
                f"| {tr.get('pe_arrow','→')} | {tr.get('pb_arrow','→')} "
                f"| {w.get('all',{}).get('days','')} |"
            )

    lines.append("")
    lines.append("## 二、行业估值汇总")
    lines.append("")
    lines.append("| 行业 | 家数 | PE%_all中位 | PB%_all中位 | PE趋中位 | PB趋中位 | PE%_all均值 | PB%_all均值 |")
    lines.append("|------|------|-------------|-------------|----------|----------|-------------|-------------|")
    for sector in SECTORS_ORDER:
        s = sector_summary.get(sector)
        if not s:
            continue
        lines.append(
            f"| {sector} | {s['count']} "
            f"| {fmt(s.get('pe_pct_median'))} | {fmt(s.get('pb_pct_median'))} "
            f"| {s.get('pe_trend','→')} | {s.get('pb_trend','→')} "
            f"| {fmt(s.get('pe_pct_mean'))} | {fmt(s.get('pb_pct_mean'))} |"
        )

    lines.append("")
    lines.append(f"*趋势说明: ↑=估值上升(变贵)  ↓=估值下降(变便宜)  →=稳定  对比基准: 42个交易日前*")
    return "\n".join(lines)

def gen_html(md_content):
    html = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大周期股池估值百分位报告 v2.0</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; max-width: 1400px; margin: 0 auto; padding: 20px; background: #f5f5f5; color: #333; }
  h1 { color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 10px; font-size: 22px; }
  h2 { color: #1a1a2e; font-size: 18px; margin-top: 28px; }
  .meta { color: #666; font-size: 13px; margin-bottom: 16px; }
  .controls { margin-bottom: 14px; font-size: 13px; }
  .controls button { background: #1a1a2e; color: #fff; border: none; padding: 5px 12px; border-radius: 4px; cursor: pointer; margin-right: 4px; font-size: 12px; }
  .controls button:hover { background: #e94560; }
  .controls input { padding: 5px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; width: 120px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; font-size: 12px; }
  th { background: #1a1a2e; color: #fff; padding: 8px 5px; text-align: center; cursor: pointer; user-select: none; white-space: nowrap; }
  th:hover { background: #2a2a4e; }
  th .sort-icon { opacity: 0.4; margin-left: 2px; }
  th.sorted .sort-icon { opacity: 1; }
  td { padding: 6px 5px; text-align: center; border-bottom: 1px solid #eee; white-space: nowrap; }
  tr:hover { background: #f0f0ff; }
  .sector-row td { background: #e8e8f0; font-weight: bold; color: #555; border-top: 2px solid #ccc; }
  .sector-row:hover td { background: #dddde8; }
  .summary-row td { background: #fff8e8; font-weight: bold; border-top: 2px solid #f0c040; }
  .summary-row:hover td { background: #fff0d0; }
  .val-verylow { color: #2e7d32; font-weight: bold; }
  .val-low { color: #558b2f; }
  .val-mid { color: #333; }
  .val-high { color: #e65100; }
  .val-veryhigh { color: #c62828; font-weight: bold; }
  .trend-up { color: #c62828; } .trend-down { color: #2e7d32; } .trend-flat { color: #999; }
  a.stock-link { color: #1565c0; text-decoration: none; font-weight: 500; }
  a.stock-link:hover { text-decoration: underline; color: #e94560; }
  .sticky-header th { position: sticky; top: 0; z-index: 10; }
  .footer { text-align: center; color: #999; font-size: 11px; margin-top: 20px; }
  .judge-extreme { background: #c8e6c9; color: #1b5e20; font-weight: bold; border-radius: 3px; padding: 2px 0; }
  .judge-low { background: #e8f5e9; color: #2e7d32; }
  .judge-mid { background: #f5f5f5; color: #555; }
  .judge-high { background: #fff3e0; color: #e65100; }
  .judge-veryhigh { background: #ffebee; color: #c62828; font-weight: bold; }
  .judge-none { color: #999; }
</style>
</head>
<body>
<script>
function sortTable(col, tableId) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr:not(.summary-row)'));
  const isNum = col >= 2;
  const ascending = table.querySelectorAll('th')[col].classList.toggle('asc');
  rows.sort((a, b) => {
    const va = a.cells[col]?.textContent.trim() || '';
    const vb = b.cells[col]?.textContent.trim() || '';
    if (isNum) {
      const na = parseFloat(va.replace(/[^0-9.\-]/g,'')) || 0;
      const nb = parseFloat(vb.replace(/[^0-9.\-]/g,'')) || 0;
      return ascending ? na - nb : nb - na;
    }
    return ascending ? va.localeCompare(vb) : vb.localeCompare(va);
  });
  rows.forEach(r => tbody.appendChild(r));
  table.querySelectorAll('th').forEach((th,i) => {
    th.classList.toggle('sorted', i === col);
  });
}
function filterTable(inputId, tableId) {
  const q = document.getElementById(inputId).value.toLowerCase();
  document.querySelectorAll(`#${tableId} tbody tr`).forEach(r => {
    if (r.classList.contains('summary-row')) return;
    r.style.display = r.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
}
</script>
<h1>📊 大周期股池估值百分位报告</h1>
"""
    html += f"<p class=\"meta\">更新日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>\n"

    # Extract table data from markdown
    parts = md_content.split("## ")
    table_section = parts[1] if len(parts) > 1 else ""
    summary_section = parts[2] if len(parts) > 2 else ""

    # ---- Stock table ----
    table_lines = [l for l in table_section.split("\n") if l.strip() and "|" in l and "---" not in l]
    html += """
<div class="controls">
  <span>排序: </span>
  <button onclick="sortTable(0,'stock-table')">行业</button>
  <button onclick="sortTable(1,'stock-table')">代码</button>
  <button onclick="sortTable(2,'stock-table')">名称</button>
  <button onclick="sortTable(5,'stock-table')">PE%_all</button>
  <button onclick="sortTable(6,'stock-table')">PB%_all</button>
  <button onclick="sortTable(7,'stock-table')">PE%_10y</button>
  <button onclick="sortTable(9,'stock-table')">PE%_5y</button>
  <button onclick="sortTable(11,'stock-table')">PE%_3y</button>
  <span style="margin-left:16px;">🔍 <input id="stock-filter" oninput="filterTable('stock-filter','stock-table')" placeholder="搜索代码/名称"></span>
</div>
<table id="stock-table"><thead><tr class="sticky-header">
"""
    cols_raw = ["行业","代码","名称","PE","PB","PE%_全","PE判断","PB%_全","PB判断","PE%_10y","PB%_10y","PE%_5y","PB%_5y","PE%_3y","PB%_3y","PE趋","PB趋","天数"]
    for c in cols_raw:
        html += f"<th onclick=\"sortTable({cols_raw.index(c)},'stock-table')\">{c}</th>\n"
    html += "</tr></thead><tbody>\n"

    for line in table_lines[1:]:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 18:
            continue
        is_sector = bool(cells[0])
        if is_sector:
            html += f'<tr class="sector-row">'
        else:
            html += "<tr>"
        for i, c in enumerate(cells):
            if i == 0 and is_sector:
                html += f"<td>{c}</td>"
            elif i == 1:
                html += f'<td><a class="stock-link" href="https://quote.eastmoney.com/{"sh" if c[:1]=="6" else "sz"}{c}.html" target="_blank">{c}</a></td>'
            elif i in (15, 16):
                val_class = "trend-up" if "↑" in c else ("trend-down" if "↓" in c else "trend-flat")
                html += f'<td class="{val_class}">{c}</td>'
            elif i in (6, 8):
                jcls = "judge-extreme" if "极低" in c else ("judge-low" if "偏低" in c else ("judge-mid" if "合理" in c else ("judge-high" if "偏高" in c else ("judge-veryhigh" if "极高" in c else "judge-none"))))
                html += f'<td class="{jcls}">{c}</td>'
            else:
                raw = c
                val_class = ""
                pct_match = re.search(r'[\d.]+', c)
                if pct_match and i >= 4:
                    pv = float(pct_match.group())
                    val_class = "val-verylow" if pv < 5 else ("val-low" if pv < 20 else ("val-mid" if pv <= 70 else ("val-high" if pv <= 90 else "val-veryhigh")))
                html += f'<td class="{val_class}">{c}</td>'
        html += "</tr>\n"
    html += "</tbody></table>\n"

    # ---- Summary table ----
    summary_lines = [l for l in summary_section.split("\n") if l.strip() and "|" in l and "---" not in l]
    if summary_lines:
        html += "<h2>行业估值汇总</h2>\n<table id=\"summary-table\"><thead><tr class=\"sticky-header\">"
        summary_headers = [c.strip() for c in summary_lines[0].split("|")[1:-1]]
        for h in summary_headers:
            html += f"<th>{h}</th>"
        html += "</tr></thead><tbody>\n"
        for line in summary_lines[2:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not cells:
                continue
            html += "<tr class=\"summary-row\">"
            for i, c in enumerate(cells):
                val_class = ""
                pct_match = re.search(r'[\d.]+', c)
                if pct_match and i >= 2:
                    pv = float(pct_match.group())
                    val_class = "val-verylow" if pv < 5 else ("val-low" if pv < 20 else ("val-mid" if pv <= 70 else ("val-high" if pv <= 90 else "val-veryhigh")))
                html += f'<td class="{val_class}">{c}</td>'
            html += "</tr>\n"
        html += "</tbody></table>\n"

    html += """<div class="footer">
🔥极高(≥90%)  ⚠️偏高(80-90%)  偏高(70-80%)  合理(30-70%)  偏低(10-30%)  📈偏低(10-20%)  💰极低(<10%)<br>
趋势: ↑估值上升(变贵)  ↓估值下降(变便宜)  →稳定  基准: 42个交易日前<br>
数据来源: 东方财富 stock_value_em · 生成时间: {}
</div>""".format(datetime.now().strftime("%Y-%m-%d %H:%M"))
    html += "\n</body>\n</html>"
    return html

# ── 主流程 ──

def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = set(a for a in sys.argv[1:] if a.startswith("--"))

    force = "--force" in opts
    no_cache = "--no-cache" in opts
    read_only = "--read" in opts
    sort_method = None
    for a in sys.argv[1:]:
        if a.startswith("--sort="):
            sort_method = a.split("=", 1)[1]

    stocks = load_pool()
    update_date = datetime.now().strftime("%Y-%m-%d")
    all_results = {}

    # ── 获取数据 ──
    if not read_only:
        need_fetch = []
        for s in stocks:
            code = s["code"]
            if force or no_cache:
                need_fetch.append(s)
                continue
            cache = load_cache(code)
            if cache and len(cache) > 1 and cache[-1]["date"] == update_date:
                continue
            need_fetch.append(s)

        if need_fetch:
            print(f"📡 正在获取 {len(need_fetch)} 只...", file=sys.stderr)
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(fetch_stock, s["code"], s["name"]): s for s in need_fetch}
                done = 0
                for f in as_completed(futures):
                    done += 1
                    code, _ = f.result()
                    s = futures[f]
                    print(f"  [{done}/{len(need_fetch)}] {s['name']}({code}) {time.time()-t0:.0f}s", file=sys.stderr)
            print(f"  ⏱ {time.time()-t0:.0f}s", file=sys.stderr)
    else:
        print(f"📖 只读模式，使用缓存数据...", file=sys.stderr)

    # ── 计算 ──
    for s in stocks:
        code = s["code"]
        cache = load_cache(code) or []
        windows = {}
        trend_info = {"pe_arrow": "→", "pb_arrow": "→"}

        for wk in WINDOW_ORDER:
            years = WINDOWS[wk]
            rows = window_filter(cache, years)
            pe_vals = [r["pe"] for r in rows]
            pb_vals = [r["pb"] for r in rows]
            pe, pe_pct = calc_pct(pe_vals)
            pb, pb_pct = calc_pct(pb_vals)
            windows[wk] = {"pe": pe, "pb": pb, "pe_pct": pe_pct, "pb_pct": pb_pct, "days": len(rows)}

        # 趋势（用全量数据）
        if len(cache) >= TREND_LOOKBACK + 30:
            trend_result = compute_trend(cache)
            if trend_result[0] is not None:
                pe_t, pe_b, pb_t, pb_b = trend_result
                trend_info = {
                    "pe_trend_now": round(pe_t, 1) if pe_t else None,
                    "pe_trend_before": round(pe_b, 1) if pe_b else None,
                    "pb_trend_now": round(pb_t, 1) if pb_t else None,
                    "pb_trend_before": round(pb_b, 1) if pb_b else None,
                    "pe_arrow": trend_arrow(pe_t, pe_b),
                    "pb_arrow": trend_arrow(pb_t, pb_b),
                }

        all_results[code] = {
            "name": s["name"],
            "sector": s["sector"],
            "windows": windows,
            "trend": trend_info,
        }

    # ── 行业汇总 ──
    sector_summary = {}
    for sector in SECTORS_ORDER:
        sec_stocks = {k: v for k, v in all_results.items() if v.get("sector") == sector}
        if not sec_stocks:
            continue
        pe_pcts = [v["windows"].get("all", {}).get("pe_pct") for v in sec_stocks.values() if v["windows"].get("all", {}).get("pe_pct") is not None]
        pb_pcts = [v["windows"].get("all", {}).get("pb_pct") for v in sec_stocks.values() if v["windows"].get("all", {}).get("pb_pct") is not None]
        if not pe_pcts and not pb_pcts:
            continue
        pe_median = round(float(np.median(pe_pcts)), 1) if pe_pcts else None
        pe_mean = round(float(np.mean(pe_pcts)), 1) if pe_pcts else None
        pb_median = round(float(np.median(pb_pcts)), 1) if pb_pcts else None
        pb_mean = round(float(np.mean(pb_pcts)), 1) if pb_pcts else None

        pe_arrows = [v["trend"]["pe_arrow"] for v in sec_stocks.values() if v["trend"]["pe_arrow"] != "→"]
        pb_arrows = [v["trend"]["pb_arrow"] for v in sec_stocks.values() if v["trend"]["pb_arrow"] != "→"]
        pe_trend = "↑" if pe_arrows.count("↑") > pe_arrows.count("↓") else ("↓" if pe_arrows.count("↓") > pe_arrows.count("↑") else "→")
        pb_trend = "↑" if pb_arrows.count("↑") > pb_arrows.count("↓") else ("↓" if pb_arrows.count("↓") > pb_arrows.count("↑") else "→")

        sector_summary[sector] = {
            "count": len(sec_stocks),
            "pe_pct_median": pe_median,
            "pe_pct_mean": pe_mean,
            "pb_pct_median": pb_median,
            "pb_pct_mean": pb_mean,
            "pe_trend": pe_trend,
            "pb_trend": pb_trend,
        }

    # ── 保存 JSON ──
    output = {
        "update_date": update_date,
        "version": "2.0",
        "windows_available": WINDOW_ORDER,
        "total": len(all_results),
        "stocks": all_results,
        "sector_summary": sector_summary,
    }
    OUTPUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 生成报告 ──
    md = gen_markdown(all_results, sector_summary, update_date)
    OUTPUT_MD.write_text(md, encoding="utf-8")
    html = gen_html(md)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    ok = sum(1 for v in all_results.values() if v["windows"].get("all", {}).get("pe_pct") is not None)
    print(f"\n📊 共 {len(all_results)} 只, 有数据 {ok} 只", file=sys.stderr)
    print(f"📄 JSON: {OUTPUT_JSON}", file=sys.stderr)
    print(f"📄 MD:   {OUTPUT_MD}", file=sys.stderr)
    print(f"📄 HTML: {OUTPUT_HTML}", file=sys.stderr)

    # ── 终端表格 ──
    sorted_items = sort_key(list(all_results.items()), sort_method)
    print(f"\n{'代码':>6} {'名称':8s} {'行业':6s} {'PE':>7} {'PB':>7} {'PE%_a':>6} {'PB%_a':>6} {'PE%_10':>6} {'PB%_10':>6} {'PE趋':>4} {'PB趋':>4} {'PE判断':>8} {'PB判断':>8}")
    print("  " + "-" * 88)
    for code, v in sorted_items:
        w = v["windows"]
        tr = v["trend"]
        pe_s = fmt(w["all"]["pe"])
        pb_s = fmt(w["all"]["pb"], 2)
        pea = fmt(w["all"]["pe_pct"])
        pba = fmt(w["all"]["pb_pct"])
        pe10 = fmt(w["10y"]["pe_pct"])
        pb10 = fmt(w["10y"]["pb_pct"])
        pe_lab = label_short(w["all"]["pe_pct"])
        pb_lab = label_short(w["all"]["pb_pct"])
        print(f"{code:>6} {v['name']:8s} {v['sector']:6s} {pe_s:>7} {pb_s:>7} {pea:>6} {pba:>6} {pe10:>6} {pb10:>6} {tr['pe_arrow']:>4} {tr['pb_arrow']:>4} {pe_lab:>8} {pb_lab:>8}")

if __name__ == "__main__":
    main()
