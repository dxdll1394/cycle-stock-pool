#!/usr/bin/env python3
"""
大周期股池自动更新工具 v1.0

按各行业成分股的成交额排序，取前10名更新 大周期股池.json

用法:
  python3 update_pool.py                    # 更新股票池
  python3 update_pool.py --dry-run          # 预览不写入
  python3 update_pool.py --force-refresh    # 强制重试API（限流时有用）

数据源: 东方财富 push2.eastmoney.com
        API被限流时，保留当前池不动（通常几小时后恢复）

其他改进构想（记录在 notes.md）:
  2. 行业自动发现
  3. 淘汰机制（连续N月跌出前15）
  4. 多级池（核心池+观察池）
"""
import json, sys, time, re
from pathlib import Path
from collections import OrderedDict
import requests

BASE = Path(__file__).resolve().parent.parent
POOL_FILE = BASE / "数据/大周期股池.json"
BAK_FILE = BASE / "数据/大周期股池_更新前备份.json"
NOTES_FILE = BASE / "notes.md"

SECTOR_BOARD_KEYWORDS = OrderedDict([
    ("石油石化",   ["石油加工", "石油石化", "油气开采"]),
    ("煤炭",      ["煤炭"]),
    ("有色金属",   ["有色金属", "黄金", "工业金属", "小金属"]),
    ("钢铁",      ["钢铁"]),
    ("化工",      ["化工", "化学制品", "化学原料", "化学纤维"]),
    ("建材",      ["建筑材料", "水泥", "玻璃"]),
    ("工程机械",   ["工程机械", "专用设备"]),
    ("航运港口",   ["航运", "港口"]),
    ("金融",      ["银行", "证券", "保险"]),
    ("农牧",      ["农牧饲渔", "养殖业", "饲料"]),
])

def api_get(url, params):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": "https://quote.eastmoney.com/",
    }
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers,
                             timeout=15, proxies={"http": "", "https": ""})
            if r.status_code == 200:
                data = r.json()
                if data and data.get("data", {}).get("diff") is not None:
                    return data
        except requests.ConnectionError:
            if attempt < 2:
                time.sleep(3)
        except Exception:
            if attempt < 2:
                time.sleep(1)
    return None

def get_all_boards():
    result = api_get("https://push2.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": 500, "po": 0, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": "m:90+t:2+f:!50",
        "fields": "f12,f14",
    })
    if not result:
        return None
    boards = {}
    for item in result["data"]["diff"]:
        code = item.get("f12", "")
        name = item.get("f14", "")
        if code and name:
            boards[name] = code
    return boards

def match_board(keywords, boards):
    for kw in keywords:
        for name, code in boards.items():
            if kw in name:
                return code, name
    return None, None

def get_board_stocks(board_code):
    result = api_get("https://push2.eastmoney.com/api/qt/clist/get", {
        "pn": 1, "pz": 200, "po": 0, "np": 1,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3",
        "fs": f"b:{board_code}+f:!50",
        "fields": "f12,f14,f20,f62",
    })
    if not result:
        return []
    stocks = []
    for item in result["data"]["diff"]:
        stocks.append({
            "code": str(item.get("f12", "")),
            "name": item.get("f14", ""),
            "amount": float(item.get("f62", 0) or 0),
            "market_cap": float(item.get("f20", 0) or 0),
        })
    return stocks

def fmt_amount(v):
    if v >= 1e8:
        return f"{v/1e8:.1f}亿"
    if v >= 1e4:
        return f"{v/1e4:.0f}万"
    return f"{v:.0f}"

def save_notes():
    NOTES_FILE.write_text("""# 大周期股池改进构想

记录于 2026-05-12，当前已实现 v3.0（100只，10行业，按成交额自动排名更新）。

## 待实现方案

### 2. 行业自动发现
用 `stock_board_industry_name_em()` 获取东方财富全部分类（约496个板块），
自动筛选出周期属性强的板块纳入股池，替代手动维护行业列表。

### 3. 淘汰机制
每次更新时对比新旧池：
- 连续3个月跌出行业成交额前15的 -> 标记建议剔除
- 新晋前10的 -> 标记建议加入
- 生成差异报告供人工确认

### 4. 多级池
- 核心池（当前100只）：月度成交额排名 + 人工确认
- 观察池（行业11-20名）：自动跟踪，随时可调入

### 5. 日均成交额代替单日成交额
当前用当日成交额排序，波动较大。
改用近20日日均成交额更稳定。（需20次API调用/股，成本较高）
""", encoding="utf-8")

def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force-refresh" in sys.argv

    # 记录改进方案
    save_notes()

    # 加载当前池
    if not POOL_FILE.exists():
        print(f"❌ 未找到 {POOL_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(POOL_FILE) as f:
        old_pool = json.load(f)

    # 备份
    BAK_FILE.write_text(json.dumps(old_pool, ensure_ascii=False, indent=2), encoding="utf-8")

    # 获取板块列表
    print("📡 获取行业板块列表...", file=sys.stderr)
    boards = get_all_boards()

    if not boards:
        print("⚠️  push2.eastmoney.com 暂时无法访问（可能限流），保留当前池不变", file=sys.stderr)
        print("   稍后重试: python3 update_pool.py --force-refresh", file=sys.stderr)

        # 预览模式下展示当前池统计
        if dry_run:
            total = sum(len(v) for v in old_pool.values())
            print(f"\n当前池: {total} 只, {len(old_pool)} 个行业", file=sys.stderr)
            for sec, stks in old_pool.items():
                print(f"  {sec}: {len(stks)} 只", file=sys.stderr)
        return

    new_pool = OrderedDict()
    changes = []

    for sector, keywords in SECTOR_BOARD_KEYWORDS.items():
        board_code, board_name = match_board(keywords, boards)
        if not board_code:
            print(f"⚠️  未找到 {sector} 对应的板块，跳过", file=sys.stderr)
            continue

        stocks = get_board_stocks(board_code)
        if not stocks:
            print(f"⚠️  {sector} 板块无成分股数据", file=sys.stderr)
            continue

        stocks.sort(key=lambda x: x["amount"], reverse=True)
        top10 = stocks[:10]
        new_pool[sector] = [{"code": s["code"], "name": s["name"]} for s in top10]

        old_codes = {s["code"] for s in old_pool.get(sector, [])}
        new_codes = {s["code"] for s in top10}
        added = new_codes - old_codes
        removed = old_codes - new_codes

        if added or removed:
            parts = []
            if added:
                items = [s for s in top10 if s["code"] in added]
                parts.append("+" + ",".join(s["name"] + "(" + s["code"] + ")" for s in items))
            if removed:
                items = [s for s in stocks if s["code"] in removed]
                parts.append("-" + ",".join(s["name"] + "(" + s["code"] + ")" for s in items))
            changes.append("  " + sector + ": " + "; ".join(parts))

        print(f"\n📊 {sector} → {board_name}({board_code})", file=sys.stderr)
        for i, s in enumerate(top10, 1):
            tag = " NEW" if s["code"] in added else (" ✓" if s["code"] in old_codes else "  ")
            print(f"  {i:2d}. {s['name']:8s} {s['code']:>6s}  {fmt_amount(s['amount']):>8s}{tag}", file=sys.stderr)

    if changes:
        print(f"\n📋 变更:", file=sys.stderr)
        for c in changes:
            print(c, file=sys.stderr)

    if dry_run:
        print("\n🧪 预览模式，未写入", file=sys.stderr)
        return

    POOL_FILE.write_text(json.dumps(new_pool, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 已更新 {POOL_FILE}", file=sys.stderr)

if __name__ == "__main__":
    main()
