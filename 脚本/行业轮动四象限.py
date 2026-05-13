#!/usr/bin/env python3
"""
行业轮动四象限图 v1.0
====================
基于大周期股池 PE/PB 百分位数据，生成行业轮动四象限图。
X轴 = PE百分位（估值），Y轴 = PB百分位（资产价值）
四个象限映射经典美林时钟：
 [衰退] 复苏/价值区 (PE↓ PB↓)  → 低估值、低资产溢价
 [复苏] 扩张/成长区 (PE↓ PB↑)  → 低PE高PB，盈利驱动
 过热区   (PE↑ PB↑)  → 双高，警惕回调
 [滞胀] 衰退区   (PE↑ PB↓)  → PE虚高（盈利下滑），PB被压缩

用法:
 python3 行业轮动四象限.py         # 默认输出PNG
 python3 行业轮动四象限.py --html      # 输出交互式HTML
 python3 行业轮动四象限.py --window 10y   # 使用10年窗口
"""
import json, sys, webbrowser
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

BASE = Path(__file__).resolve().parent.parent
DATA_FILE = BASE / "数据/大周期股池_pepb_pct.json"
SECTORS_ORDER = ["石油石化","煤炭","有色金属","钢铁","化工","建材","工程机械","航运港口","金融","农牧"]

# ── 字体 ──
plt.rcParams["font.family"] = "Heiti TC"
plt.rcParams["axes.unicode_minus"] = False

# ── 颜色 ──
SECTOR_COLORS = {
  "石油石化": "#4A90D9", # 蓝色
  "煤炭":  "#333333",  # 深灰
  "有色金属": "#D4A017", # 金色
  "钢铁":  "#8B4513",  # 棕色
  "化工":  "#6B8E23",  # 橄榄绿
  "建材":  "#CD853F",  # 秘鲁色
  "工程机械": "#4682B4", # 钢蓝
  "航运港口": "#2E8B57", # 海洋绿
  "金融":  "#8B0000",  # 暗红
  "农牧":  "#228B22",  # 森林绿
}

def load_data():
  """加载估值数据，按行业聚合"""
  with open(DATA_FILE) as f:
    data = json.load(f)

  stocks = data.get("stocks", {})
  sector_stocks = defaultdict(list)
  for code, v in stocks.items():
    sector = v.get("sector", "其他")
    windows = v.get("windows", {})
    all_w = windows.get("all", {})
    sector_stocks[sector].append({
      "code": code,
      "name": v.get("name", ""),
      "pe_pct": all_w.get("pe_pct"),
      "pb_pct": all_w.get("pb_pct"),
      "pe": all_w.get("pe"),
      "pb": all_w.get("pb"),
    })

  return sector_stocks, data.get("update_date", ""), data.get("version", "")

def calc_sector_stats(sector_stocks):
  """计算行业级别的统计指标"""
  stats = {}
  for sector, stocks in sector_stocks.items():
    pe_pcts = [s["pe_pct"] for s in stocks if s["pe_pct"] is not None]
    pb_pcts = [s["pb_pct"] for s in stocks if s["pb_pct"] is not None]
    if not pe_pcts and not pb_pcts:
      continue
    stats[sector] = {
      "count": len(stocks),
      "pe_pct_median": np.median(pe_pcts) if pe_pcts else 50,
      "pb_pct_median": np.median(pb_pcts) if pb_pcts else 50,
      "pe_pct_mean": np.mean(pe_pcts) if pe_pcts else 50,
      "pb_pct_mean": np.mean(pb_pcts) if pb_pcts else 50,
    }
  return stats

def plot_quadrant_png(sector_stats, update_date):
  """生成行业轮动四象限图（PNG）"""
  fig, ax = plt.subplots(figsize=(14, 12))
  fig.patch.set_facecolor("#F8F9FA")
  ax.set_facecolor("#F8F9FA")

  # ── 四分界线 ──
  ax.axhline(y=50, color="#999999", linestyle="--", linewidth=1.2, alpha=0.6)
  ax.axvline(x=50, color="#999999", linestyle="--", linewidth=1.2, alpha=0.6)

  # ── 象限背景色 ──
  ax.axhspan(0, 50, xmin=0, xmax=0.5, facecolor="#E3F2FD", alpha=0.15) # 复苏
  ax.axhspan(50, 100, xmin=0, xmax=0.5, facecolor="#E8F5E9", alpha=0.15) # 扩张
  ax.axhspan(50, 100, xmin=0.5, xmax=1, facecolor="#FFF3E0", alpha=0.15) # 过热
  ax.axhspan(0, 50, xmin=0.5, xmax=1, facecolor="#FFEBEE", alpha=0.15)  # 衰退

  # ── 象限标签 ──
  ax.text(15, 92, "复苏/价值区\n低PE·低PB\n估值修复+资产低估",
      fontsize=11, color="#1565C0", alpha=0.7, ha="center", va="center")
  ax.text(85, 92, "过热区\n高PE·高PB\n警惕估值泡沫+回调风险",
      fontsize=11, color="#E65100", alpha=0.7, ha="center", va="center")
  ax.text(15, 8, "衰退区\n低PE·低PB\n盈利见底+资产廉价",
      fontsize=11, color="#1B5E20", alpha=0.7, ha="center", va="center")
  ax.text(85, 8, "滞胀区\n高PE·低PB\n盈利下滑+资产折价",
      fontsize=11, color="#C62828", alpha=0.7, ha="center", va="center")

  # ── 绘制行业散点 ──
  for sector in SECTORS_ORDER:
    if sector not in sector_stats:
      continue
    s = sector_stats[sector]
    x = s["pe_pct_median"]
    y = s["pb_pct_median"]
    size = s["count"] * 50 # 气泡大小按成分股数
    color = SECTOR_COLORS.get(sector, "#666666")

    ax.scatter(x, y, s=size, c=color, alpha=0.75, edgecolors="white",
          linewidth=2, zorder=5)

    # 标签
    offset_x = 2.5
    offset_y = 2.5
    # 调整标签位置避免重叠
    for other in SECTORS_ORDER:
      if other == sector or other not in sector_stats:
        continue
      ox = sector_stats[other]["pe_pct_median"]
      oy = sector_stats[other]["pb_pct_median"]
      if abs(x - ox) < 6 and abs(y - oy) < 6:
        offset_y = -7.5
        break

    ax.annotate(f"{sector}\n({s['count']}只)",
          (x, y),
          xytext=(offset_x, offset_y),
          textcoords="offset points",
          fontsize=10,
          fontweight="bold",
          color=color,
          ha="left",
          va="bottom",
          zorder=6)

  # ── 坐标轴 ──
  ax.set_xlim(-3, 103)
  ax.set_ylim(-3, 103)
  ax.set_xlabel("PE百分位 (估值便宜→贵) ------>", fontsize=13, fontweight="bold", color="#333")
  ax.set_ylabel("PB百分位 (资产廉价→溢价) ------>", fontsize=13, fontweight="bold", color="#333")
  ax.set_title(f"大周期股池行业轮动四象限图\n{update_date} | 中位PE% vs 中位PB% | 气泡大小=成分股数",
         fontsize=15, fontweight="bold", color="#1a1a2e", pad=18)

  # ── 刻度 ──
  ax.set_xticks([0, 25, 50, 75, 100])
  ax.set_yticks([0, 25, 50, 75, 100])
  ax.tick_params(labelsize=11)

  # ── 网格 ──
  ax.grid(True, alpha=0.3, linestyle=":", color="#888")

  # ── 统计信息 ──
  total_stocks = sum(v["count"] for v in sector_stats.values())
  stats_text = (
    f"数据源: 大周期股池 v3.0\n"
    f"覆盖: {len(sector_stats)} 个行业 / {total_stocks} 只股票\n"
    f"窗口: 上市以来 | 趋势对比: 42个交易日\n"
    f"分类: PE↑PB↑=过热  PE↑PB↓=滞胀  PE↓PB↓=复苏  PE↓PB↑=扩张"
  )
  ax.text(0.98, 0.02, stats_text, transform=ax.transAxes,
      fontsize=9, color="#888", ha="right", va="bottom",
      bbox=dict(boxstyle="round,pad=0.5", facecolor="white", alpha=0.8))

  plt.tight_layout()
  out_path = BASE / "数据/行业轮动四象限图.png"
  fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=fig.get_facecolor())
  plt.close(fig)
  print(f"✅ PNG: {out_path}", file=sys.stderr)
  return out_path

def plot_quadrant_html(sector_stats, update_date):
  """生成交互式HTML版本（基于ECharts）"""
  import json as _json

  series_data = []
  for sector in SECTORS_ORDER:
    if sector not in sector_stats:
      continue
    s = sector_stats[sector]
    series_data.append({
      "name": sector,
      "value": [round(s["pe_pct_median"], 1), round(s["pb_pct_median"], 1),
           s["count"], SECTOR_COLORS.get(sector, "#666")],
      "symbolSize": 15 + s["count"] * 3,
    })

  html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大周期股池行业轮动四象限图</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
 * {{ margin: 0; padding: 0; box-sizing: border-box; }}
 body {{ background: #f5f5f5; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; }}
 .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
 h1 {{ font-size: 22px; color: #1a1a2e; margin-bottom: 6px; }}
 .meta {{ color: #888; font-size: 13px; margin-bottom: 14px; }}
 #chart {{ width: 100%; height: 800px; background: #fff; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
 .legend {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 16px 0; font-size: 12px; }}
 .legend-item {{ display: flex; align-items: center; gap: 4px; padding: 4px 10px; border-radius: 4px; background: #fff; }}
 .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
 .footer {{ text-align: center; color: #aaa; font-size: 11px; margin-top: 16px; }}
</style>
</head>
<body>
<div class="container">
 <h1>📊 大周期股池 · 行业轮动四象限图</h1>
 <div class="meta">{update_date} | 中位PE% × 中位PB% | 气泡大小 = 成分股数 | 窗口: 上市以来</div>
 <div id="chart"></div>
 <div class="legend">
  <span class="legend-item"><span class="legend-dot" style="background:#E3F2FD;"></span>复苏/价值区 PE↓PB↓</span>
  <span class="legend-item"><span class="legend-dot" style="background:#E8F5E9;"></span>扩张/成长区 PE↓PB↑</span>
  <span class="legend-item"><span class="legend-dot" style="background:#FFF3E0;"></span>过热区 PE↑PB↑</span>
  <span class="legend-item"><span class="legend-dot" style="background:#FFEBEE;"></span>滞胀区 PE↑PB↓</span>
 </div>
 <div class="footer">数据源: 东方财富(akshare) | 气泡大小为各行业成分股数</div>
</div>
<script>
const chart = echarts.init(document.getElementById('chart'));
const option = {{
 tooltip: {{
  formatter: function(params) {{
   if (!params.value) return '';
   const [pe, pb, count, color] = params.value;
   const quad = pe >= 50 ? (pb >= 50 ? '🔥过热区' : '滞胀区') : (pb >= 50 ? '扩张区' : '复苏区');
   return `<strong>${{params.name}}</strong><br/>
       PE中位百分位: ${{pe}}%<br/>
       PB中位百分位: ${{pb}}%<br/>
       成分股: ${{count}} 只<br/>
       象限: ${{quad}}`;
  }}
 }},
 xAxis: {{
  name: 'PE百分位 (估值)',
  nameLocation: 'center',
  nameGap: 40,
  min: -5, max: 105,
  splitLine: {{ show: true, lineStyle: {{ type: 'dashed', color: '#ccc' }} }},
  axisLine: {{ show: true }},
 }},
 yAxis: {{
  name: 'PB百分位 (资产溢价)',
  nameLocation: 'center',
  nameGap: 45,
  min: -5, max: 105,
  splitLine: {{ show: true, lineStyle: {{ type: 'dashed', color: '#ccc' }} }},
  axisLine: {{ show: true }},
 }},
 series: [{{
  type: 'scatter',
  data: {_json.dumps(series_data, ensure_ascii=False)},
  itemStyle: {{
   opacity: 0.8,
   borderColor: '#fff',
   borderWidth: 2,
  }},
  label: {{
   show: true,
   formatter: function(p) {{ return p.name; }},
   fontSize: 12,
   fontWeight: 'bold',
   position: 'right',
  }},
  emphasis: {{
   itemStyle: {{ opacity: 1, borderColor: '#333', borderWidth: 3 }},
   label: {{ fontSize: 14 }},
  }},
  markArea: {{
   silent: true,
   data: [
    [{{ xAxis: 50, yAxis: 50 }}, {{ xAxis: 105, yAxis: 105, itemStyle: {{ color: '#FFF3E0', opacity: 0.2 }} }}],
    [{{ xAxis: -5, yAxis: 50 }}, {{ xAxis: 50, yAxis: 105, itemStyle: {{ color: '#E8F5E9', opacity: 0.2 }} }}],
    [{{ xAxis: 50, yAxis: -5 }}, {{ xAxis: 105, yAxis: 50, itemStyle: {{ color: '#FFEBEE', opacity: 0.2 }} }}],
    [{{ xAxis: -5, yAxis: -5 }}, {{ xAxis: 50, yAxis: 50, itemStyle: {{ color: '#E3F2FD', opacity: 0.2 }} }}],
   ]
  }},
 }}],
 grid: {{ top: 60, bottom: 60, left: 70, right: 50 }},
}};

chart.setOption(option);
window.addEventListener('resize', () => chart.resize());
</script>
</body>
</html>"""
  out_path = BASE / "数据/行业轮动四象限图.html"
  out_path.write_text(html, encoding="utf-8")
  print(f"✅ HTML: {out_path}", file=sys.stderr)
  return out_path

def main():
  sector_stocks, update_date, version = load_data()
  stats = calc_sector_stats(sector_stocks)

  print(f"📊 大周期股池 v{version} | 更新: {update_date}", file=sys.stderr)
  print(f"📈 共 {len(stats)} 个行业", file=sys.stderr)

  # 终端输出
  print(f"\n{'行业':8s} {'家数':>4s} {'PE%中位':>8s} {'PB%中位':>8s} {'PE%均值':>8s} {'PB%均值':>8s} {'象限':>10s}")
  print(" " + "-" * 62)
  for sector in SECTORS_ORDER:
    s = stats.get(sector)
    if not s:
      continue
    pe = s["pe_pct_median"]
    pb = s["pb_pct_median"]
    if pe >= 50 and pb >= 50:
      quad = "🔥过热"
    elif pe >= 50 and pb < 50:
      quad = "滞胀"
    elif pe < 50 and pb >= 50:
      quad = "扩张"
    else:
      quad = "复苏"
    print(f"{sector:8s} {s['count']:4d} {pe:8.1f} {pb:8.1f} {s['pe_pct_mean']:8.1f} {s['pb_pct_mean']:8.1f} {quad:>10s}")

  make_html = "--html" in sys.argv

  if make_html:
    plot_quadrant_html(stats, update_date)
  else:
    plot_quadrant_png(stats, update_date)

if __name__ == "__main__":
  main()
