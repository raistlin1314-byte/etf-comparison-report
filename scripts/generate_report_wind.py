#!/usr/bin/env python3
"""
指数ETF滑动对比周报生成器 — Wind数据源版
==============================================
数据源：万得Wind MCP CLI（通过 subprocess 调用）
布局：与离线单文件HTML相同，仅替换数据源
依赖：python3, requests (仅用于下载Chart.js)
"""

import json, os, sys, re, subprocess, shutil
from datetime import datetime, date, timedelta

# ============================================================
# 配置
# ============================================================
WIND_SKILL_DIR = r"C:\Users\frank\.agents\skills\wind-mcp-skill"
OUTPUT_DIR = r"C:\Users\frank\.openclaw-tdxclaw\.openclaw\workspace-tdxclaw\reports"
SEED_HTML = os.path.join(OUTPUT_DIR, "index.html")  # 始终读最新的

# 6个板块 - windcode 用 Wind 标准代码
CATEGORIES_CONFIG = [
    {
        "cat_name": "上证50",
        "index_name": "上证50",
        "index_wind": "000016.SH",
        "etfs": [
            {"ts_code": "510050.SH", "windcode": "510050.SH", "name": "上证50ETF华夏", "mgr": "华夏基金"},
        ]
    },
    {
        "cat_name": "沪深300",
        "index_name": "沪深300",
        "index_wind": "000300.SH",
        "etfs": [
            {"ts_code": "510300.SH", "windcode": "510300.SH", "name": "沪深300ETF华泰柏瑞", "mgr": "华泰柏瑞基金"},
            {"ts_code": "510310.SH", "windcode": "510310.SH", "name": "沪深300ETF易方达", "mgr": "易方达基金"},
        ]
    },
    {
        "cat_name": "A500",
        "index_name": "中证A500",
        "index_wind": "000510.SH",
        "etfs": [
            {"ts_code": "563360.SH", "windcode": "563360.SH", "name": "A500ETF华泰柏瑞", "mgr": "华泰柏瑞基金"},
            {"ts_code": "159352.SZ", "windcode": "159352.SZ", "name": "A500ETF南方", "mgr": "南方基金"},
        ]
    },
    {
        "cat_name": "券商",
        "index_name": "证券公司",
        "index_wind": "399975.SZ",
        "etfs": [
            {"ts_code": "512000.SH", "windcode": "512000.SH", "name": "券商ETF华宝", "mgr": "华宝基金"},
            {"ts_code": "512880.SH", "windcode": "512880.SH", "name": "证券ETF国泰", "mgr": "国泰基金"},
        ]
    },
    {
        "cat_name": "创业板",
        "index_name": "创业板指",
        "index_wind": "399006.SZ",
        "etfs": [
            {"ts_code": "159915.SZ", "windcode": "159915.SZ", "name": "创业板ETF易方达", "mgr": "易方达基金"},
        ]
    },
    {
        "cat_name": "科创板",
        "index_name": "科创50",
        "index_wind": "000688.SH",
        "etfs": [
            {"ts_code": "588000.SH", "windcode": "588000.SH", "name": "科创50ETF华夏", "mgr": "华夏基金"},
            {"ts_code": "588080.SH", "windcode": "588080.SH", "name": "科创50ETF易方达", "mgr": "易方达基金"},
        ]
    },
]


# ============================================================
# Wind CLI 调用封装
# ============================================================
_WIND_CACHE = {}

def wind_call(server_type, tool_name, params_dict):
    """调用 Wind MCP CLI，返回解析后的 data 对象或 None"""
    cache_key = f"{server_type}/{tool_name}/{json.dumps(params_dict, ensure_ascii=False, sort_keys=True)}"
    if cache_key in _WIND_CACHE:
        return _WIND_CACHE[cache_key]

    params_json = json.dumps(params_dict, ensure_ascii=False)
    cmd = ["node", "scripts/cli.mjs", "call", server_type, tool_name, params_json]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                               encoding='utf-8', cwd=WIND_SKILL_DIR, timeout=30)
    except subprocess.TimeoutExpired:
        print(f"  [WARN] Wind call timeout: {server_type}/{tool_name}")
        return None

    if result.returncode != 0:
        print(f"  [WARN] Wind call failed ({result.returncode}): {result.stdout[:200]}")
        return None

    try:
        envelope = json.loads(result.stdout)
        text = envelope["content"][0]["text"]
        data = json.loads(text)
        _WIND_CACHE[cache_key] = data
        return data
    except Exception as e:
        print(f"  [WARN] Wind parse error: {e}")
        return None


def get_result_sets(data):
    """从Wind返回数据中提取结果集列表"""
    if data is None:
        return []
    inner = data.get("data", {})
    if isinstance(inner, dict):
        datasets = inner.get("data", [])
        if isinstance(datasets, list):
            return datasets
    return []


# ============================================================
# 数据获取
# ============================================================
def fetch_index_kline_wind(index_wind, start_date, end_date):
    """
    从Wind获取指数日K线
    返回: {date_str: close_price}
    Wind get_index_kline 返回平铺格式：data.{columns, rows}
    (注意：不是标准的result-sets格式)
    """
    data = wind_call("index_data", "get_index_kline", {
        "windcode": index_wind,
        "begin_date": start_date.replace("-", ""),
        "end_date": end_date.replace("-", ""),
        "period": "10"  # 日K
    })
    
    result = {}
    if data is None:
        return result

    inner = data.get("data", {})
    if isinstance(inner, dict):
        rows = inner.get("rows", [])
        cols = [c["name"] for c in inner.get("columns", [])]
        # 找到DATE和MATCH的列索引
        date_idx = next((i for i, n in enumerate(cols) if n in ("_DATE", "DATE")), -1)
        close_idx = next((i for i, n in enumerate(cols) if n == "MATCH"), -1)
        
        for row in rows:
            if date_idx >= 0 and close_idx >= 0 and len(row) > max(date_idx, close_idx):
                date_str = str(row[date_idx])
                close = float(row[close_idx])
                # date_str 可能是 "20260518" 或 "2026-05-18T00:00:00..."
                if len(date_str) >= 8 and date_str[:8].isdigit():
                    result[date_str[:8]] = close
    
    return result


def fetch_etf_shares_weekly(windcode):
    """
    从Wind获取ETF近52周周度份额（万份）
    处理多种列格式：
      Format A: [code, name, shares, date_str, ...]
      Format B: [year, week, shares, reits_shares, reits_unissued, ...]
    返回: {date_str: shares_wanfen}
    """
    data = wind_call("fund_data", "get_fund_performance", {
        "question": f"{windcode}近一年每周基金份额",
        "lang": "中文"
    })
    
    result = {}
    for ds in get_result_sets(data):
        cols = [c["name"] for c in ds.get("columns", [])]
        is_format_b = ("年份" in cols and "周数" in cols)
        
        for row in ds.get("rows", []):
            shares = None
            date_str = None

            if is_format_b:
                # Format B: [year, week, shares, ...]
                if len(row) >= 3 and row[2] is not None:
                    shares = float(row[2])
                if len(row) >= 2:
                    try:
                        year = int(row[0]) if row[0] is not None else 0
                        week = int(row[1]) if row[1] is not None else 0
                        if year > 2000 and week > 0:
                            # 从year+week推算日期（周结束=周日）
                            from datetime import datetime as _dt
                            iso_date = _dt.strptime(f"{year}-W{week:02d}-7", "%G-W%V-%u")
                            date_str = iso_date.strftime("%Y%m%d")
                    except (ValueError, TypeError):
                        pass
            else:
                # Format A: [code, name, shares, date_str, ...]
                # 找出数值列（份额）和日期列
                shares_col = date_col = None
                for i, c in enumerate(cols):
                    cn = c.replace("_支持历史", "")
                    if "份额" in cn and "REITS" not in cn and "未流通" not in cn:
                        shares_col = i
                    if "时间" in cn:
                        date_col = i
                # 回退到位置推断
                if shares_col is None:
                    shares_col = 2 if len(row) > 2 else -1
                if date_col is None:
                    date_col = 3 if len(row) > 3 else -1
                
                if shares_col >= 0 and shares_col < len(row):
                    try:
                        shares = float(row[shares_col]) if row[shares_col] is not None else None
                    except (ValueError, TypeError):
                        shares = None
                if date_col >= 0 and date_col < len(row):
                    date_str = str(row[date_col]) if row[date_col] is not None else None
            
            if shares is not None and date_str and re.match(r"^\d{8}$", date_str):
                result[date_str] = shares
    
    if not result:
        print(f"  [警告] {windcode} 每周份额解析为0行，尝试回退方案...")
        # 回退：用analytics_data拿最新一份快照
        data2 = wind_call("analytics_data", "get_financial_data", {
            "question": f"{windcode}最新基金份额",
            "lang": "CNS"
        })
        for ds in get_result_sets(data2):
            for row in ds.get("rows", []):
                if len(row) >= 3 and row[2]:
                    shares = float(row[2])
                    today = date.today().strftime("%Y%m%d")
                    result[today] = shares
                    print(f"    回退方案: 最新份额={shares:.0f}万份 (日期={today})")
                    break
    
    return result


def fetch_etf_latest_info(windcode):
    """
    从Wind获取ETF最新规模/净值信息
    返回: {shares_wanfen, scale_yi, nav, name}
    """
    # 方式1：get_fund_info 拿档案（含规模和净值）
    data = wind_call("fund_data", "get_fund_info", {
        "question": f"{windcode}基金档案",
        "lang": "中文"
    })
    info = {}
    for ds in get_result_sets(data):
        for row in ds.get("rows", []):
            cols = [c["name"] for c in ds.get("columns", [])]
            if "基金规模合计" in cols:
                idx_scale = cols.index("基金规模合计")
                scale_yi = float(row[idx_scale]) if row[idx_scale] else 0
                info["scale_yi"] = scale_yi
            if "单位净值" in cols:
                idx_nav = cols.index("单位净值")
                nav = float(row[idx_nav]) if row[idx_nav] else 0
                info["nav"] = nav
            if len(row) >= 2:
                info["name"] = str(row[1])

    # 方式2：analytics_data 拿最新份额（万份）
    data2 = wind_call("analytics_data", "get_financial_data", {
        "question": f"{windcode}最新基金份额",
        "lang": "CNS"
    })
    for ds in get_result_sets(data2):
        for row in ds.get("rows", []):
            if len(row) >= 3 and row[2]:
                info["shares"] = float(row[2])  # 已在万份单位
    
    return info


def nearest_weekly_share(weekly_data, target_date):
    """
    找到 target_date 前最近的周度份额数据
    """
    dates = sorted(weekly_data.keys(), reverse=True)
    for d in dates:
        if d <= target_date:
            return weekly_data[d]
    return list(weekly_data.values())[-1] if weekly_data else None


# ============================================================
# 数据处理
# ============================================================
def parse_seed_html(html_path):
    """从现有HTML提取 REPORT_DATA"""
    if not os.path.exists(html_path):
        print(f"[ERROR] 种子文件不存在: {html_path}")
        return None
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
    idx = content.find("window.REPORT_DATA=")
    if idx < 0:
        print("[ERROR] HTML中找不到 REPORT_DATA")
        return None
    start = idx + len("window.REPORT_DATA=")
    end = content.find("</script>", start)
    json_str = content[start:end].strip().rstrip(";")
    return json.loads(json_str)


def merge_data_with_wind(seed_data):
    """
    通过Wind补充最新数据到种子数据中。
    策略：对每个板块：
      1. 从Wind获取指数日K线（最近一个月）
      2. 从Wind获取ETF周度份额（最近一年）
      3. 合并新交易日到种子数据中，用最近的周度份额填充
    """
    today = date.today()
    today_str = today.strftime("%Y%m%d")
    
    # 对每个ETF预取周度份额
    etf_weekly_cache = {}
    print("\n  预取ETF周度份额数据...")
    for cat_cfg in CATEGORIES_CONFIG:
        for etf_cfg in cat_cfg["etfs"]:
            if etf_cfg["windcode"] not in etf_weekly_cache:
                print(f"    {etf_cfg['name']}...", end=" ")
                weekly = fetch_etf_shares_weekly(etf_cfg["windcode"])
                etf_weekly_cache[etf_cfg["windcode"]] = weekly
                print(f"{len(weekly)}周")

    print()
    for cat_cfg in CATEGORIES_CONFIG:
        cat_name = cat_cfg["cat_name"]
        seed_cat = seed_data["categories"].get(cat_name)
        if not seed_cat:
            print(f"[{cat_name}] 跳过 - 种子数据中不存在")
            continue

        rows = seed_cat["rows"]
        last_seed_date = rows[-1]["date"]
        n_etfs = len(seed_cat["etfs"])

        print(f"[{cat_name}] 种子最后日期: {last_seed_date}")

        # 计算需要获取的时间范围
        fetch_start = datetime.strptime(last_seed_date, "%Y%m%d") - timedelta(days=5)
        fetch_start_str = fetch_start.strftime("%Y%m%d")
        fetch_end = today
        
        # 获取Wind指数K线
        index_daily = fetch_index_kline_wind(
            cat_cfg["index_wind"], 
            fetch_start.strftime("%Y-%m-%d"),
            fetch_end.strftime("%Y-%m-%d")
        )
        if not index_daily:
            print(f"  [跳过] 无法获取K线数据")
            continue

        # 筛选新交易日（从种子最后日期之后）
        new_dates = sorted([d for d in index_daily if d > last_seed_date])
        if not new_dates:
            print(f"  [无需更新]")
            continue

        print(f"  新增交易日: {len(new_dates)}天 ({new_dates[0]} ~ {new_dates[-1]})")

        # 获取每个ETF的最新周度份额
        latest_shares = []
        for etf_cfg in cat_cfg["etfs"]:
            weekly = etf_weekly_cache.get(etf_cfg["windcode"], {})
            # 使用最后一个新日期之前的周度份额
            last_new = new_dates[-1]
            share = nearest_weekly_share(weekly, last_new)
            if share is None:
                # 回退到种子最后值
                idx = [e["ts_code"] for e in cat_cfg["etfs"]].index(etf_cfg["ts_code"])
                share = rows[-1]["etfs"][idx] if idx < len(rows[-1]["etfs"]) else 0
                print(f"  [回退] {etf_cfg['name']}: 使用种子值 {share:.0f}万份")
            else:
                print(f"  {etf_cfg['name']}: {share:.0f}万份")
            latest_shares.append(share)

        # 追加新行
        added = 0
        for dt in new_dates:
            idx_close = index_daily.get(dt)
            if idx_close is None:
                continue
            
            # 使用该日期前最近的份额数据
            etf_shares = []
            for i, etf_cfg in enumerate(cat_cfg["etfs"]):
                weekly = etf_weekly_cache.get(etf_cfg["windcode"], {})
                share = nearest_weekly_share(weekly, dt)
                etf_shares.append(share if share else latest_shares[i])

            new_row = {
                "date": dt,
                "date_label": f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}",
                "index": round(idx_close, 2),
                "etfs": [round(s, 2) for s in etf_shares]
            }
            rows.append(new_row)
            added += 1

        print(f"  新增 {added} 行 ✓")

    # 更新全局日期范围
    all_dates = []
    for cat_cfg in CATEGORIES_CONFIG:
        cat = seed_data["categories"].get(cat_cfg["cat_name"])
        if cat and cat["rows"]:
            all_dates.append(cat["rows"][0]["date"])
            all_dates.append(cat["rows"][-1]["date"])
    if all_dates:
        seed_data["start"] = min(all_dates)
        seed_data["end"] = max(all_dates)

    # 更新ETF最新share_yi信息
    print("\n  更新ETF最新份额摘要...")
    for cat_cfg in CATEGORIES_CONFIG:
        seed_cat = seed_data["categories"].get(cat_cfg["cat_name"])
        if not seed_cat:
            continue
        for i, etf_cfg in enumerate(cat_cfg["etfs"]):
            info = fetch_etf_latest_info(etf_cfg["windcode"])
            if info.get("shares"):
                # shares 是万份 -> 转亿份
                seed_cat["etfs"][i]["share_yi"] = round(info["shares"] / 10000, 2)
            if info.get("scale_yi"):
                seed_cat["etfs"][i]["size_yi"] = round(info["scale_yi"], 2)

    return seed_data


# ============================================================
# HTML生成（与原来完全一致）
# ============================================================
def generate_html(data, output_path):
    """生成更新后的HTML，保持原布局和展现方式"""
    if not os.path.exists(SEED_HTML):
        print(f"[ERROR] 种子HTML不存在: {SEED_HTML}")
        return False

    with open(SEED_HTML, "r", encoding="utf-8") as f:
        template = f.read()

    # 替换 REPORT_DATA
    old_start = template.find("window.REPORT_DATA=")
    old_end = template.find("</script>", old_start)
    json_str = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new_content = (template[:old_start]
                   + f"window.REPORT_DATA={json_str}"
                   + template[old_end:])

    # 更新时间戳
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_content = re.sub(
        r"更新 \d{4}-\d{2}-\d{2} \d{2}:\d{2}",
        f"更新 {now_str}",
        new_content
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"\n{'='*60}")
    print(f"✅ 报告已生成: {output_path}")
    print(f"📅 数据范围: {data['start']} ~ {data['end']}")
    total = sum(len(c["rows"]) for c in data["categories"].values())
    print(f"📊 总数据行: {total}")
    print(f"📡 数据来源: 万得 Wind 金融数据")
    return True


def git_push_to_github(repo_dir, commit_msg):
    """将报告提交并推送到GitHub"""
    try:
        # 检查是否有变更
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=repo_dir, timeout=10
        )
        if not result.stdout.strip():
            print("  [Git] 没有变更需要提交")
            return True
        
        # git add (stderr可能含非UTF-8，丢弃)
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, timeout=15, 
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # git commit (stderr可能含非UTF-8)
        subprocess.run(["git", "commit", "-m", commit_msg], 
                      capture_output=True, text=True, 
                      cwd=repo_dir, timeout=15)
        
        # git push - 用二进制模式避免GBK编码异常
        push_result = subprocess.run(
            ["git", "push", "origin", "main"],
            capture_output=True, text=False, cwd=repo_dir, timeout=60
        )
        out = (push_result.stdout or b"").decode("utf-8", errors="replace")
        err = (push_result.stderr or b"").decode("utf-8", errors="replace")
        
        if push_result.returncode == 0:
            print(f"  [Git] ✅ 已推送到GitHub: {out[:100]}{err[:100]}")
            return True
        else:
            print(f"  [Git] ⚠️ push失败(code={push_result.returncode}): {err[:200]}")
            return False
    except Exception as e:
        print(f"  [Git] ❌ 自动推送失败: {e}")
        print(f"  请手动: cd {repo_dir} && git add -A && git commit -m \"{commit_msg}\" && git push")
        return False


# ============================================================
# 主流程
# ============================================================
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("  指数ETF滑动对比周报生成器（Wind数据源版）")
    print(f"  {'='*56}")
    print(f"  运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 加载种子数据
    print("\n[1/3] 加载种子数据...")
    seed_data = parse_seed_html(SEED_HTML)
    if not seed_data:
        sys.exit(1)
    print(f"  数据区间: {seed_data['start']} ~ {seed_data['end']}")
    print(f"  板块: {', '.join(seed_data['categories'].keys())}")

    # 2. 合并新数据（Wind）
    print("\n[2/3] 通过Wind获取最新数据...")
    updated_data = merge_data_with_wind(seed_data)

    # 3. 生成HTML
    print("\n[3/3] 生成报告...")
    output_filename = f"etf_report_{datetime.now().strftime('%Y%m%d')}.html"
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    if not generate_html(updated_data, output_path):
        sys.exit(1)

    # 同步到 index.html
    index_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(output_path, "rb") as f:
        content = f.read()
    with open(index_path, "wb") as f:
        f.write(content)
    print(f"  同步: {index_path}")

    # 4. GitHub自动推送
    GITHUB_REPO_DIR = os.path.join(os.path.dirname(OUTPUT_DIR), "report-repo")
    if os.path.exists(os.path.join(GITHUB_REPO_DIR, ".git")):
        print(f"\n[4/4] 部署到GitHub...")
        # 复制index.html到report-repo
        shutil.copy2(index_path, os.path.join(GITHUB_REPO_DIR, "index.html"))
        commit_msg = f"ETF周报自动更新 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        git_push_to_github(GITHUB_REPO_DIR, commit_msg)
    else:
        print(f"\n[4/4] 跳过 - 未找到report-repo")


if __name__ == "__main__":
    main()
