#!/usr/bin/env python3
"""
构建 A 股股票名称→代码映射数据库 v2
数据源：东方财富 API (80.push2.eastmoney.com)
每个请求最多 100 条，需分页
"""

import json
import os
import time
import urllib.request

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_names.json")


def fetch_page(fs: str, pn: int = 1) -> tuple:
    """抓取一页股票数据，返回 (items, total)"""
    url = (
        f"http://80.push2.eastmoney.com/api/qt/clist/get"
        f"?pn={pn}&pz=100&po=0&np=1&fields=f12,f14&fid=f12&fs={fs}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = data.get("data", {}).get("diff", [])
    total = data.get("data", {}).get("total", 0)
    return items, total


def fetch_all() -> list:
    """循环抓取所有 A 股（仅主板+中小板）"""
    all_stocks = []
    seen_codes = set()

    market_segments = [
        "m:0+t:6",     # 沪市A股 (600xxx)
        "m:1+t:2",     # 深市A股 (000xxx)
        "m:1+t:23",    # 中小板 (002xxx)
    ]

    for fs in market_segments:
        pn = 1
        while True:
            try:
                items, total = fetch_page(fs, pn)
                if not items:
                    print(f"  {fs} page {pn}: empty, done", flush=True)
                    break
                for item in items:
                    code = item["f12"]
                    name = item["f14"].replace(" ", "").replace("*", "")
                    # 排除创业板(3xxxx)、科创板(688/689)、北交所(8/9)、三板(4)
                    if code.startswith(("3", "688", "689", "8", "9", "4")):
                        continue
                    if code not in seen_codes:
                        seen_codes.add(code)
                        all_stocks.append({"code": code, "name": name})
                print(f"  {fs} page {pn}: {len(items)} items (total {len(all_stocks)})", flush=True)
                if len(items) < 100 or pn * 100 >= total:
                    break
                pn += 1
                time.sleep(0.2)
            except Exception as e:
                print(f"  {fs} page {pn} error: {e}", flush=True)
                break

    return all_stocks


def deduplicate(stocks: list) -> dict:
    """按名称去重，优先保留主板代码"""
    name_to_code = {}
    for s in stocks:
        name = s["name"]
        code = s["code"]
        if name not in name_to_code:
            name_to_code[name] = code
        else:
            existing = name_to_code[name]
            priority = {"6": 0, "00": 1, "002": 2}
            new_p = next((v for k, v in priority.items() if code.startswith(k)), 3)
            old_p = next((v for k, v in priority.items() if existing.startswith(k)), 3)
            if new_p < old_p:
                name_to_code[name] = code
    return name_to_code


def main():
    print("📦 正在抓取 A 股股票列表...", flush=True)
    stocks = fetch_all()
    print(f"\n✅ 共获取 {len(stocks)} 条记录", flush=True)

    mapping = deduplicate(stocks)
    print(f"✅ 去重后 {len(mapping)} 只唯一股票", flush=True)

    # 验证关键股票
    checks = ["紫光国微", "中国巨石", "龙佰集团", "贵州茅台", "中国平安",
              "招商银行", "宁德时代", "中兴通讯", "中信证券", "美的集团",
              "三六零", "科大讯飞", "比亚迪", "紫金矿业", "药明康德"]
    for name in checks:
        code = mapping.get(name, "NOT FOUND")
        print(f"  {name} -> {code}", flush=True)

    output = {
        "version": 5,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "total": len(mapping),
        "stocks": mapping
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"\n💾 已保存到 {OUTPUT_PATH} ({size_kb:.1f} KB)", flush=True)


if __name__ == "__main__":
    main()
