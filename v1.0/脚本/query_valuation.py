#!/usr/bin/env python3
"""
大周期股池 PE/PB 估值百分位查询工具

用法:
  python3 query_valuation.py                  # 上市以来百分位
  python3 query_valuation.py 10y              # 近10年
  python3 query_valuation.py 5y               # 近5年
  python3 query_valuation.py 3y               # 近3年
  python3 query_valuation.py all --force      # 强制刷新缓存
  python3 query_valuation.py all --no-cache   # 不使用缓存

数据源: 东方财富（akshare stock_value_em）
输出:   JSON + Markdown
"""
import json, sys, time
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

WINDOW_OPTIONS = {"all": None, "10y": 10, "5y": 5, "3y": 3}
SECTORS_ORDER = ["石油石化", "煤炭", "有色金属", "钢铁", "化工", "建材", "工程机械", "航运港口", "金融", "农牧"]

def load_pool():
    with open(POOL_FILE) as f:
        sectors = json.load(f)
    stocks = []
    for sector, items in sectors.items():
        for item in items:
            stocks.append({**item, "sector": sector})
    return stocks

def cache_path(code):
    return CACHE_DIR / f"{code}.json"

def load_cache(code):
    p = cache_path(code)
    if p.exists():
        return json.loads(p.read_text())
    return None

def save_cache(code, data):
    cache_path(code).write_text(json.dumps(data, ensure_ascii=False))

def fetch_stock(code, name):
    cache = load_cache(code)
    today = datetime.now().strftime("%Y-%m-%d")
    if cache and len(cache) > 1:
        last_date = cache[-1]["date"]
        if last_date == today:
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
            "pe": float(pe) if pd.notna(pe) else None,
            "pb": float(pb) if pd.notna(pb) else None,
        })

    rows.sort(key=lambda x: x["date"])
    save_cache(code, rows)
    return code, rows

def calc_pct(values):
    vals = np.array([v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))])
    if len(vals) < 30:
        return None, None
    latest = vals[-1]
    pct = float((vals <= latest).mean() * 100)
    return round(float(latest), 2), round(pct, 2)

def window_filter(rows, years):
    if years is None:
        return rows
    cutoff = (datetime.now() - timedelta(days=years * 365.25)).strftime("%Y-%m-%d")
    return [r for r in rows if r["date"] >= cutoff]

def label(pct):
    if pct is None: return "——"
    if pct >= 90: return "🔥 极高"
    if pct >= 80: return "⚠️ 偏高"
    if pct >= 70: return "偏高"
    if pct >= 30: return "合理"
    if pct >= 20: return "偏低"
    if pct >= 10: return "📈 偏低"
    return "💰 极低"

def fmt(v, decimals=1):
    if v is None: return "-"
    return f"{v:.{decimals}f}"

def generate_markdown(results, window_key, update_date, stocks):
    lines = []
    lines.append(f"# 大周期股池估值百分位报告")
    lines.append(f"")
    lines.append(f"**更新日期**: {update_date}  **数据窗口**: {window_key}")
    lines.append(f"")
    lines.append(f"| 行业 | 代码 | 名称 | PE | PB | PE% | PE判断 | PB% | PB判断 | 数据天数 |")
    lines.append(f"|------|------|------|----|----|----|--------|----|--------|---------|")

    row_codes = {s["code"]: s for s in stocks}
    for sector in SECTORS_ORDER:
        sector_stocks = [s for s in stocks if s["sector"] == sector]
        first = True
        for s in sector_stocks:
            code = s["code"]
            v = results.get(code, {})
            sector_cell = sector if first else ""
            first = False
            pe_s = fmt(v.get("pe"), 1)
            pb_s = fmt(v.get("pb"), 2)
            pep_s = f"{v['pe_pct']:.1f}" if v.get("pe_pct") is not None else "-"
            pbp_s = f"{v['pb_pct']:.1f}" if v.get("pb_pct") is not None else "-"
            days = v.get("data_days", 0)
            lines.append(f"| {sector_cell} | {code} | {s['name']} | {pe_s} | {pb_s} | {pep_s} | {v.get('pe_label', '')} | {pbp_s} | {v.get('pb_label', '')} | {days} |")

    return "\n".join(lines)

def stock_url(code):
    if code.startswith(("600","601","603","605","688")):
        return f"https://quote.eastmoney.com/sh{code}.html"
    return f"https://quote.eastmoney.com/sz{code}.html"

def generate_html(md_content, results):
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大周期股池估值百分位报告</title>
<style>
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; color: #333; }
  h1 { color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
  th { background: #1a1a2e; color: #fff; padding: 10px 8px; font-size: 13px; text-align: center; }
  td { padding: 8px; text-align: center; border-bottom: 1px solid #eee; font-size: 13px; }
  tr:hover { background: #f0f0ff; }
  .sector-cell { background: #e8e8f0; font-weight: bold; color: #555; }
  .sector-first { border-top: 2px solid #ccc; }
  a.stock-link { color: #1a73e8; text-decoration: none; font-weight: 500; }
  a.stock-link:hover { text-decoration: underline; color: #e94560; }
</style>
</head>
<body>
"""
    import re
    table_match = re.search(r'\|.*\|.*\|.*\|', md_content)
    if table_match:
        start = md_content.index("| 行业")
        table_text = md_content[start:]
        lines = table_text.strip().split("\n")
        header = [c.strip() for c in lines[0].split("|")[1:-1]]
        html += f"<h1>大周期股池估值百分位报告</h1>\n"
        html += f"<p><strong>更新日期:</strong> {datetime.now().strftime('%Y-%m-%d')}</p>\n"
        html += "<table><thead><tr>"
        for h in header:
            html += f"<th>{h}</th>"
        html += "</tr></thead><tbody>\n"

        for line in lines[2:]:
            if not line.strip() or "|---" in line:
                continue
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if not cols:
                continue
            is_sector = bool(cols[0])
            row_class = ' class="sector-first"' if is_sector else ""
            html += f"<tr{row_class}>"
            for i, c in enumerate(cols):
                if i == 0 and is_sector:
                    html += f'<td class="sector-cell">{c}</td>'
                elif i == 1:
                    url = stock_url(c)
                    html += f'<td><a class="stock-link" href="{url}" target="_blank">{c}</a></td>'
                else:
                    html += f"<td>{c}</td>"
            html += "</tr>\n"
        html += "</tbody></table>\n"

    html += """<p style="color:#999;font-size:12px;margin-top:20px;text-align:center;">数据来源: 东方财富 · 生成时间: {}</p>""".format(datetime.now().strftime("%Y-%m-%d %H:%M"))
    html += "\n</body>\n</html>"
    return html

def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = set(a for a in sys.argv[1:] if a.startswith("--"))

    window_key = argv[0] if argv and argv[0] in WINDOW_OPTIONS else "all"
    years = WINDOW_OPTIONS[window_key]
    force = "--force" in opts
    no_cache = "--no-cache" in opts

    stocks = load_pool()
    need_fetch = []
    for s in stocks:
        code = s["code"]
        if force or no_cache:
            need_fetch.append(s)
            continue
        cache = load_cache(code)
        if cache:
            last_date = cache[-1]["date"]
            today = datetime.now().strftime("%Y-%m-%d")
            if last_date == today and len(cache) > 1:
                continue
        need_fetch.append(s)

    if need_fetch:
        print(f"📡 正在获取 {len(need_fetch)} 只股票估值数据...", file=sys.stderr)
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(fetch_stock, s["code"], s["name"]): s for s in need_fetch}
            done = 0
            for f in as_completed(futures):
                done += 1
                code, _ = f.result()
                s = futures[f]
                elapsed = time.time() - t0
                print(f"  [{done}/{len(need_fetch)}] {s['name']}({code})  {elapsed:.0f}s", file=sys.stderr)
        print(f"  ⏱ 耗时 {time.time()-t0:.0f}s", file=sys.stderr)

    update_date = datetime.now().strftime("%Y-%m-%d")
    results = {}
    for s in stocks:
        code = s["code"]
        cache = load_cache(code) or []
        rows = window_filter(cache, years)

        pe_vals = [r["pe"] for r in rows]
        pb_vals = [r["pb"] for r in rows]

        pe, pe_pct = calc_pct(pe_vals)
        pb, pb_pct = calc_pct(pb_vals)

        results[code] = {
            "name": s["name"],
            "sector": s["sector"],
            "pe": pe,
            "pb": pb,
            "pe_pct": pe_pct,
            "pb_pct": pb_pct,
            "pe_label": label(pe_pct),
            "pb_label": label(pb_pct),
            "data_days": len(rows),
        }

    # JSON
    output = {"update_date": update_date, "window": window_key, "stocks": results}
    OUTPUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown
    md = generate_markdown(results, window_key, update_date, stocks)
    OUTPUT_MD.write_text(md, encoding="utf-8")

    # HTML
    html = generate_html(md, results)
    OUTPUT_HTML.write_text(html, encoding="utf-8")

    total = len(results)
    ok = sum(1 for v in results.values() if v["pe_pct"] is not None)
    print(f"\n📊 共 {total} 只, 有数据 {ok} 只, 窗口: {window_key}", file=sys.stderr)
    print(f"📄 JSON: {OUTPUT_JSON}", file=sys.stderr)
    print(f"📄 MD:   {OUTPUT_MD}", file=sys.stderr)
    print(f"📄 HTML: {OUTPUT_HTML}", file=sys.stderr)

    # 终端表格
    print()
    header = f"{'代码':>6} {'名称':8s} {'行业':6s} {'PE':>7} {'PB':>7} {'PE%':>6} {'判断':8s} {'PB%':>6} {'判断':8s}"
    sep = "  " + "-" * 77
    print(header)
    print(sep)
    for code, v in sorted(results.items(), key=lambda x: x[0]):
        print(f"{code:>6} {v['name']:8s} {v['sector']:6s} {fmt(v['pe']):>7} {fmt(v['pb'],2):>7} {fmt(v['pe_pct']):>6} {v['pe_label']:8s} {fmt(v['pb_pct']):>6} {v['pb_label']:8s}")

if __name__ == "__main__":
    main()
