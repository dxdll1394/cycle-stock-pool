# AGENTS.md — 大周期股池 v3.0

**当前版本**: v3.0（100只，10行业，按成交额自动排名更新）

## 目录结构

| 路径 | 用途 |
|------|------|
| `脚本/update_pool.py` | **核心更新脚本** — 从东方财富拉取板块成分股，成交额排序取前10 |
| `脚本/query_valuation.py` | 估值百分位查询 — akshare 拉历史 PE/PB，输出 JSON/MD/HTML 报告 |
| `脚本/行业轮动四象限.py` | 基于估值数据生成美林时钟四象限图（PNG / HTML） |
| `数据/大周期股池.json` | **核心股池** — {行业→[{code, name}]} 格式 |
| `数据/大周期股池_pepb_pct.json` | query_valuation.py 的输出，行业轮动四象限的输入 |
| `数据/估值缓存/` | 各股票历史 PE/PB 缓存文件（{code}.json） |
| `v1.0/` `v2.0/` `v3.0/` | 历史版本备份（各自有独立的脚本和数据） |

## 关键命令

```bash
python3 脚本/update_pool.py                         # 更新股池（拉取最新成交额排序）
python3 脚本/update_pool.py --dry-run               # 预览变更，不写入
python3 脚本/update_pool.py --force-refresh          # 强制重试（API限流时有用）

python3 脚本/query_valuation.py                     # 更新估值百分位（默认 all 窗口）
python3 脚本/query_valuation.py --read               # 只读缓存，不联网
python3 脚本/query_valuation.py --sort composite     # 按综合得分排序
python3 脚本/query_valuation.py --force              # 强制刷新所有缓存

python3 脚本/行业轮动四象限.py                        # 输出 PNG
python3 脚本/行业轮动四象限.py --html                 # 输出交互式 HTML
python3 脚本/行业轮动四象限.py --window 10y           # 使用 10 年窗口
```

## 数据流

```
update_pool.py ──→ 数据/大周期股池.json
                        ↓
               query_valuation.py ──→ 数据/大周期股池_pepb_pct.json
                        ↓                          ↓
               数据/估值缓存/*.json       行业轮动四象限.py ──→ PNG / HTML
```

## 10 个行业

石油石化 · 煤炭 · 有色金属 · 钢铁 · 化工 · 建材 · 工程机械 · 航运港口 · 金融 · 农牧

每个行业取成交额 TOP10 = 100 只成分股。

## 注意

- `update_pool.py` 依赖东方财富 `push2.eastmoney.com` — API 经常限流（返回空），此时保留当前池不变
- `query_valuation.py` 依赖 `akshare` 的 `stock_value_em` 接口
- 历史版本目录（`v1.0/` `v2.0/` `v3.0/`）各自有"副本"脚本和数据，改主目录脚本注意区分
- 缓存文件（`数据/估值缓存/*.json`）可手动删除，下次查询自动重建
- 改进构想见 `notes.md`：行业自动发现、淘汰机制、多级池、日均成交额
