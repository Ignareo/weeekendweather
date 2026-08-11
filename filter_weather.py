#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather_forecast CSV 交互式筛选向导 (旅游决策版)

用法:
    python3 filter_weather.py            # 向导模式: 逐项提问筛选条件, 回车=不限
    python3 filter_weather.py <csv文件>  # 指定数据文件 (默认用当日最新的, 没有则自动抓取)

按城市聚合所选日期范围内的天气, 输出"每城市一行"的行程决策汇总:
逐日雨况 / 达标天数 / 综合雨况(最差一天) / 温度区间 / 总降水
"""

import csv
import glob
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

RAIN_LABELS = ["☀️ 无雨", "🌦 小雨", "🌧 中雨", "⛈ 大到暴雨"]
RAIN_ICONS = ["☀️", "🌦", "🌧", "⛈"]


def list_forecast_files() -> list:
    """全部预报 CSV(不含筛选/汇总导出件), 按修改时间从新到旧"""
    files = [f for f in glob.glob("weather_forecast_*.csv")
             if not f.endswith(("_filtered.csv", "_summary.csv"))]
    return sorted(files, key=os.path.getmtime, reverse=True)


def pick_file() -> Path:
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if not p.exists():
            sys.exit(f"⚠️ 文件不存在: {p}")
        return p

    # 优先使用当日数据; 当日没有则先调用 nmc_weather.py 抓取
    today = datetime.now().strftime("%Y%m%d")
    if not any(f"weather_forecast_{today}_" in f for f in list_forecast_files()):
        print(f"🔄 未检测到当日 ({today}) 数据, 先运行 nmc_weather.py 抓取...\n")
        ret = subprocess.run([sys.executable, str(Path(__file__).parent / "nmc_weather.py")]).returncode
        print()
        if ret != 0 and not list_forecast_files():
            sys.exit("⚠️ 抓取失败且无任何历史 CSV 可用")

    files = list_forecast_files()
    if not files:
        sys.exit("⚠️ 当前目录没有 weather_forecast_*.csv, 请先运行 nmc_weather.py")
    return Path(files[0])


def ask(prompt: str, hint: str = "") -> str:
    suffix = f" ({hint})" if hint else ""
    return input(f"{prompt}{suffix}: ").strip()


def ask_valid(prompt: str, hint: str, parser):
    """提问并校验, 输入非法时提示重问; 回车返回 None 表示不限"""
    while True:
        raw = ask(prompt, hint)
        if not raw:
            return None
        value = parser(raw)
        if value is not None:
            return value
        print(f"  ⚠️ 无法识别 '{raw}', 请检查格式后重新输入 (回车=不限)")


def make_date_parser(default_year: int):
    """接受 8-16 / 08-16 / 8/16 / 2026-08-16 等写法, 统一返回 ISO 日期串"""
    def parse(raw: str):
        m = re.fullmatch(r"(?:(\d{4})[-/.)]?)?(\d{1,2})[-/.](\d{1,2})", raw.strip())
        if not m:
            return None
        year = int(m.group(1)) if m.group(1) else default_year
        try:
            return date(year, int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return parse


def parse_number(raw: str):
    try:
        return float(raw.strip().rstrip("°Cc"))
    except ValueError:
        return None


def parse_tier(raw: str):
    """雨天接受度: 1~4, 返回可容忍的最高雨况档位 (0~3)"""
    if raw in ("1", "2", "3", "4"):
        return int(raw) - 1
    return None


def text_rain_tier(weather: str) -> int:
    """按天气文字判定雨况档位"""
    if any(k in weather for k in ("大暴雨", "暴雨", "大雨", "大雪", "暴雪")):
        return 3
    if any(k in weather for k in ("中雨", "中雪", "雷阵雨")):
        return 2
    if any(k in weather for k in ("小雨", "小雪", "阵雨", "雨", "雪")):
        return 1
    return 0


def mm_rain_tier(mm: float) -> int:
    """按 24h 降水量判定雨况档位 (气象标准)"""
    if mm <= 0:
        return 0
    if mm < 10:
        return 1
    if mm < 25:
        return 2
    return 3


def row_rain_tier(r) -> int:
    """整行雨况: 白天/夜间文字与降水量三者取最严重 (昼夜都算)"""
    mm = float(r["降水量(mm)"] or 0)
    return max(text_rain_tier(r["白天天气"]),
               text_rain_tier(r["夜间天气"]),
               mm_rain_tier(mm))


def main():
    csv_file = pick_file()
    with open(csv_file, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit("⚠️ CSV 中没有数据")

    dates = sorted(r["日期"] for r in rows)
    cities = sorted({r["城市"] for r in rows})
    default_year = int(dates[0][:4])
    date_parser = make_date_parser(default_year)

    def parse_city(raw: str):
        if raw in cities:
            return raw
        matched = [c for c in cities if raw in c]
        if len(matched) == 1:
            return matched[0]
        return None

    print(f"\n📁 数据文件: {csv_file} (共 {len(rows)} 行, {dates[0]} ~ {dates[-1]})")
    print(f"🏙  包含城市: {'、'.join(cities)}")
    print("   逐项设置筛选条件, 直接回车 = 不限\n")

    date_from = ask_valid("📅 开始日期", f"{dates[0][5:]} ~ {dates[-1][5:]}, 如 08-15", date_parser)
    date_to = ask_valid("📅 结束日期", "如 08-16", date_parser)
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
        print(f"  ℹ️ 开始日期晚于结束日期, 已自动互换为 {date_from} ~ {date_to}")

    print("🌧  雨天接受度 (综合白天/夜间天气与降水量, 取较严重者):")
    print("     1. 只接受无雨    2. 小雨可以(带伞能玩)    3. 中雨也行    4. 不限")
    max_rain = ask_valid("   请选择", "1~4, 回车=不限", parse_tier)

    max_day = ask_valid("🌡  白天温度上限 °C", "如 30", parse_number)
    min_night = ask_valid("🌡  夜间温度下限 °C", "如 20", parse_number)
    city = ask_valid("🏙  只看城市", "如 上海", parse_city)

    # 选定日期范围内的天数, 决定"至少几天达标"的提问与默认值
    days = sorted({r["日期"] for r in rows
                   if (not date_from or r["日期"] >= date_from)
                   and (not date_to or r["日期"] <= date_to)})
    n_days = len(days)
    need = n_days
    if n_days > 1:
        def parse_need(raw: str):
            if raw.isdigit() and 1 <= int(raw) <= n_days:
                return int(raw)
            return None
        need = ask_valid("📆 至少几天达标", f"1~{n_days}, 回车={n_days}(全部达标)",
                         parse_need) or n_days

    def day_ok(r) -> bool:
        if max_rain is not None and row_rain_tier(r) > max_rain:
            return False
        if max_day is not None and float(r["白天温度"]) > max_day:
            return False
        if min_night is not None and float(r["夜间温度"]) < min_night:
            return False
        return True

    # 按城市聚合
    by_city = defaultdict(dict)  # 城市 -> {日期: 行}
    for r in rows:
        if r["日期"] in days and (not city or r["城市"] == city):
            by_city[r["城市"]][r["日期"]] = r

    summaries = []
    for c, daymap in by_city.items():
        ok_days = [d for d in days if d in daymap and day_ok(daymap[d])]
        if len(ok_days) < need:
            continue
        present = [daymap[d] for d in days if d in daymap]
        worst = max(row_rain_tier(r) for r in present)
        summaries.append({
            "城市": c,
            "省份": present[0]["省份"],
            "达标": len(ok_days),
            "逐日": {d: (RAIN_ICONS[row_rain_tier(daymap[d])] if d in daymap else "—",
                        day_ok(daymap[d]) if d in daymap else False)
                    for d in days},
            "综合档": worst,
            "白天温度": (min(float(r["白天温度"]) for r in present),
                        max(float(r["白天温度"]) for r in present)),
            "夜间温度": (min(float(r["夜间温度"]) for r in present),
                        max(float(r["夜间温度"]) for r in present)),
            "总降水": sum(float(r["降水量(mm)"] or 0) for r in present),
        })

    # 达标天数多→少, 综合雨况好→差, 白天最高温低→高
    summaries.sort(key=lambda s: (-s["达标"], s["综合档"], s["白天温度"][1]))

    def fmt_days(s) -> str:
        parts = []
        for d in days:
            icon, ok = s["逐日"][d]
            parts.append(f"{d[8:10]}{icon}" if ok else f"{d[8:10]}{icon}✗")
        return " ".join(parts)

    print(f"\n{'='*100}")
    print(f"✅ 符合条件: {len(summaries)} / {len(by_city)} 个城市 "
          f"({days[0][5:]}~{days[-1][5:]}, 至少 {need}/{n_days} 天达标)")
    print(f"{'='*100}")
    if summaries:
        print("{:<6}{:<7}{:<20}{:<12}{:<11}{:<11}{:<10}".format(
            "城市", "达标", "逐日雨况(✗=不达标)", "综合雨况", "白天温度", "夜间温度", "总降水"))
        print("-" * 100)
        for s in summaries:
            d_lo, d_hi = s["白天温度"]
            n_lo, n_hi = s["夜间温度"]
            print("{:<7}{:<8}{:<23}{:<14}{:<13}{:<13}{:<10}".format(
                s["城市"], f"{s['达标']}/{n_days}", fmt_days(s),
                RAIN_LABELS[s["综合档"]],
                f"{d_lo:.0f}~{d_hi:.0f}°C", f"{n_lo:.0f}~{n_hi:.0f}°C",
                f"{s['总降水']:.1f}mm"))
    else:
        print("(无符合城市, 可放宽接受度或降低达标天数重试)")

    if summaries and ask("\n💾 导出汇总为 CSV?", "y/N").lower() == "y":
        out = csv_file.with_name(csv_file.stem + "_summary.csv")
        with open(out, "w", newline="", encoding="utf-8-sig") as f:
            fieldnames = ["城市", "省份", "达标天数", "综合雨况", "逐日雨况",
                          "白天温度范围", "夜间温度范围", "总降水量(mm)"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for s in summaries:
                d_lo, d_hi = s["白天温度"]
                n_lo, n_hi = s["夜间温度"]
                writer.writerow({
                    "城市": s["城市"], "省份": s["省份"],
                    "达标天数": f"{s['达标']}/{n_days}",
                    "综合雨况": RAIN_LABELS[s["综合档"]],
                    "逐日雨况": "; ".join(
                        f"{d}: {RAIN_LABELS[row_rain_tier(r)] if (r := by_city[s['城市']].get(d)) else '无数据'}"
                        f"{'(不达标)' if r and not day_ok(r) else ''}"
                        for d in days),
                    "白天温度范围": f"{d_lo:.0f}~{d_hi:.0f}°C",
                    "夜间温度范围": f"{n_lo:.0f}~{n_hi:.0f}°C",
                    "总降水量(mm)": round(s["总降水"], 1),
                })
        print(f"💾 已保存: {out}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n已取消")
