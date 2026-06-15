#!/usr/bin/env python3
"""
update_data.py
從 FRED 抓取最新數據，直接寫回 pce-nasdaq.html 內建的資料區塊，
供 GitHub Actions 每月自動執行。前端不需 API key / proxy。

監控指標（原文 2022 重演 5 條件中可量化者）：
  1. 核心PCE 年增率   PCEPILFE (units=pc1)         > 4% 警戒
  2. Fed 目標利率上限 DFEDTARU                      連升 3 次以上
  4. 實質工資年增率   CES0500000003 - CPIAUCSL(pc1) 轉負為警訊
  5. 高收益債利差     BAMLH0A0HYM2                  > 4% 觀察
（第3項 EPS 下修無免費自動來源，未納入）

需要環境變數 FRED_API_KEY。
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()
HTML_PATH = os.path.join(os.path.dirname(__file__), "pce-nasdaq.html")

START = "2015-01-01"

SERIES = {
    "pce": {"id": "PCEPILFE",     "units": "pc1", "freq": "m", "agg": "avg", "round": 1},
    "ndx": {"id": "NASDAQCOM",    "units": "lin", "freq": "m", "agg": "avg", "round": 0},
    "hy":  {"id": "BAMLH0A0HYM2", "units": "lin", "freq": "m", "agg": "avg", "round": 2},
    "fed": {"id": "DFEDTARU",     "units": "lin", "freq": "m", "agg": "eop", "round": 2},
    "wage_nom": {"id": "CES0500000003", "units": "pc1", "freq": "m", "agg": "avg"},
    "cpi":      {"id": "CPIAUCSL",       "units": "pc1", "freq": "m", "agg": "avg"},
}


def fetch_series(cfg):
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
        out[obs["date"][:7]] = float(v)
    if not out:
        raise RuntimeError(f"{cfg['id']} 回傳 0 筆有效資料")
    return out


def month_range(start_ym, end_ym):
    sy, sm = map(int, start_ym.split("-"))
    ey, em = map(int, end_ym.split("-"))
    out = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def align(series_dict, labels):
    """依 labels 對齊；缺漏用前值 forward-fill，開頭缺用第一個有效值。"""
    out = []
    last = None
    first_valid = next((series_dict[m] for m in labels if m in series_dict), None)
    for m in labels:
        if m in series_dict:
            last = series_dict[m]
        out.append(last if last is not None else first_valid)
    return out


def fmt(value, ndigits):
    if ndigits == 0:
        return str(int(round(value)))
    return f"{round(value, ndigits)}"


def build_js_array(name, values):
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
    pattern = re.compile(r"var\s+" + re.escape(var_name) + r"\s*=\s*\[.*?\];", re.DOTALL)
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
    fed = fetch_series(SERIES["fed"])
    wage_nom = fetch_series(SERIES["wage_nom"])
    cpi = fetch_series(SERIES["cpi"])

    real_wage = {}
    for m in set(wage_nom) & set(cpi):
        real_wage[m] = wage_nom[m] - cpi[m]

    pce_months = sorted(pce)
    labels = month_range(pce_months[0], pce_months[-1])
    labels = [m for m in labels if m >= "2015-01"]

    pce_vals = [fmt(v, SERIES["pce"]["round"]) for v in align(pce, labels)]
    ndx_vals = [fmt(v, SERIES["ndx"]["round"]) for v in align(ndx, labels)]
    hy_vals = [fmt(v, SERIES["hy"]["round"]) for v in align(hy, labels)]
    fed_vals = [fmt(v, SERIES["fed"]["round"]) for v in align(fed, labels)]
    wage_vals = [fmt(v, 1) for v in align(real_wage, labels)]

    print(f"  範圍：{labels[0]} ~ {labels[-1]}（{len(labels)} 個月）")
    print(f"  最新 PCE={pce_vals[-1]}%  NDX={ndx_vals[-1]}  HY={hy_vals[-1]}%"
          f"  Fed={fed_vals[-1]}%  實質工資={wage_vals[-1]}%")

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    html = replace_block(html, "BUILTIN_LABELS", build_labels_array(labels))
    html = replace_block(html, "BUILTIN_PCE", build_js_array("BUILTIN_PCE", pce_vals))
    html = replace_block(html, "BUILTIN_NDX", build_js_array("BUILTIN_NDX", ndx_vals))
    html = replace_block(html, "BUILTIN_HY", build_js_array("BUILTIN_HY", hy_vals))
    html = replace_block(html, "BUILTIN_FED", build_js_array("BUILTIN_FED", fed_vals))
    html = replace_block(html, "BUILTIN_WAGE", build_js_array("BUILTIN_WAGE", wage_vals))

    html = re.sub(r"(var\s+BUILTIN_LAST\s*=\s*)'[^']*'",
                  r"\g<1>'" + labels[-1] + "'", html)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"已更新 {HTML_PATH}")


if __name__ == "__main__":
    main()
