#!/usr/bin/env python3
"""
update_data.py
從 FRED 抓取最新的 核心PCE（YoY%）、那斯達克、HY OAS 數據，
直接寫回 pce-nasdaq.html 內建的資料區塊，供 GitHub Actions 每月自動執行。

前端不再呼叫 FRED、不再需要 API key、不再需要 CORS proxy。
GitHub Pages 永遠是最新資料。

需要環境變數 FRED_API_KEY（在 repo 的 Settings > Secrets 設定）。
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
HTML_PATH = os.path.join(os.path.dirname(__file__), "pce-nasdaq.html")

# FRED 序列設定
# - 核心PCE：PCEPILFE 是「指數」，必須用 units=pc1 轉成「較一年前變化%」才會是 YoY 年增率
# - 那斯達克：NASDAQCOM 是日資料，用 frequency=m + aggregation_method=avg 轉成月均
# - HY OAS：BAMLH0A0HYM2 是日資料（百分點），同樣轉月均
SERIES = {
    "pce": {"id": "PCEPILFE", "units": "pc1", "freq": "m", "agg": "avg", "round": 1},
    "ndx": {"id": "NASDAQCOM", "units": "lin", "freq": "m", "agg": "avg", "round": 0},
    "hy":  {"id": "BAMLH0A0HYM2", "units": "lin", "freq": "m", "agg": "avg", "round": 2},
}

START = "2015-01-01"


def fetch_series(cfg):
    """抓單一序列，回傳 {YYYY-MM: value} 字典。"""
    params = {
        "series_id": cfg["id"],
        "api_key": FRED_KEY,
        "file_type": "json",
        "observation_start": START,
        "units": cfg["units"],
        "frequency": cfg["freq"],
        "aggregation_method": cfg["agg"],
    }
    url = "https://api.stlouisfed.org/fred/series/observations?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "jc-dashboard-updater"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    out = {}
    for obs in data.get("observations", []):
        v = obs.get("value", ".")
        if v in (".", "", None):
            continue
        month = obs["date"][:7]  # YYYY-MM
        out[month] = float(v)
    if not out:
        raise RuntimeError(f"{cfg['id']} 回傳 0 筆有效資料")
    return out


def fmt(value, ndigits):
    """依精度格式化：整數不留小數點。"""
    if ndigits == 0:
        return str(int(round(value)))
    return f"{round(value, ndigits)}"


def build_js_array(name, values):
    """產生像 var NAME = [ ... ]; 的 JS 陣列，每行 12 筆方便閱讀。"""
    lines = []
    for i in range(0, len(values), 12):
        chunk = ",".join(values[i:i + 12])
        lines.append("  " + chunk + ("," if i + 12 < len(values) else ""))
    return "var " + name + " = [\n" + "\n".join(lines) + "\n];"


def build_labels_array(labels):
    lines = []
    for i in range(0, len(labels), 12):
        chunk = ",".join("'" + m + "'" for m in labels[i:i + 12])
        lines.append("  " + chunk + ("," if i + 12 < len(labels) else ""))
    return "var BUILTIN_LABELS = [\n" + "\n".join(lines) + "\n];"


def replace_block(html, var_name, new_block):
    """用正則把 var XXX = [ ... ]; 整段換掉。"""
    pattern = re.compile(
        r"var\s+" + re.escape(var_name) + r"\s*=\s*\[.*?\];",
        re.DOTALL,
    )
    if not pattern.search(html):
        raise RuntimeError(f"在 HTML 中找不到 {var_name} 區塊")
    return pattern.sub(lambda m: new_block, html, count=1)


def main():
    if not FRED_KEY:
        print("ERROR: 缺少 FRED_API_KEY 環境變數", file=sys.stderr)
        sys.exit(1)

    print("抓取 FRED 資料中…")
    pce = fetch_series(SERIES["pce"])
    ndx = fetch_series(SERIES["ndx"])
    hy = fetch_series(SERIES["hy"])

    # 只保留三個序列都有值的月份，並排序
    common = sorted(set(pce) & set(ndx) & set(hy))
    if not common:
        print("ERROR: 三序列無共同月份", file=sys.stderr)
        sys.exit(1)

    labels = common
    pce_vals = [fmt(pce[m], SERIES["pce"]["round"]) for m in labels]
    ndx_vals = [fmt(ndx[m], SERIES["ndx"]["round"]) for m in labels]
    hy_vals = [fmt(hy[m], SERIES["hy"]["round"]) for m in labels]

    print(f"  範圍：{labels[0]} ~ {labels[-1]}（{len(labels)} 個月）")
    print(f"  最新 PCE={pce_vals[-1]}%  NDX={ndx_vals[-1]}  HY={hy_vals[-1]}")

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    html = replace_block(html, "BUILTIN_LABELS", build_labels_array(labels))
    html = replace_block(html, "BUILTIN_PCE", build_js_array("BUILTIN_PCE", pce_vals))
    html = replace_block(html, "BUILTIN_NDX", build_js_array("BUILTIN_NDX", ndx_vals))
    html = replace_block(html, "BUILTIN_HY", build_js_array("BUILTIN_HY", hy_vals))

    # 更新前端顯示的「資料截止月份」字串
    html = re.sub(
        r"(var\s+BUILTIN_LAST\s*=\s*)'[^']*'",
        r"\g<1>'" + labels[-1] + "'",
        html,
    )

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"已更新 {HTML_PATH}")


if __name__ == "__main__":
    main()
