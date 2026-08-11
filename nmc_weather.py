#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国气象台 (nmc.cn) 天气批量导出工具

用法:
    python3 nmc_weather.py refresh   # 首次/站点代码失效时, 重建 stations.json 缓存
    python3 nmc_weather.py           # 读取 cities.txt, 导出未来7天预报 CSV
    python3 nmc_weather.py --temp14  # 额外导出 近7天+未来7天 气温 CSV
    python3 nmc_weather.py --json data.json  # 导出网页版兜底快照 (GitHub Actions 用)
    python3 nmc_weather.py --json <路径>  # 导出网页版兜底快照 data.json (预报+实况+气温)

依赖: pip install requests
数据版权: 国家气象中心, 仅供个人学习使用
"""

import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://www.nmc.cn"
STATIONS_FILE = Path(__file__).parent / "stations.json"
CITIES_FILE = Path(__file__).parent / "cities.txt"
DELAY = 0.3  # 请求间隔(秒)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.nmc.cn/",
}


def get(path: str, params: dict = None):
    resp = requests.get(f"{BASE_URL}{path}", params=params,
                        headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(DELAY)
    return resp.json()


def refresh_stations():
    """抓取全部省份与站点, 写入 stations.json 本地缓存"""
    stations = {}
    provinces = get("/f/rest/province")
    for i, prov in enumerate(provinces, 1):
        cities = get(f"/f/rest/province/{prov['code']}")
        for c in cities:
            stations[c["city"]] = {
                "code": c["code"],
                "province": c["province"],
                "city": c["city"],
            }
        print(f"\r[{i}/{len(provinces)}] {prov['name']}... 已收录 {len(stations)} 站",
              end="", flush=True)
    STATIONS_FILE.write_text(json.dumps(stations, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    print(f"\n✅ 缓存已保存: {STATIONS_FILE} (共 {len(stations)} 站)")


def load_stations() -> dict:
    if not STATIONS_FILE.exists():
        sys.exit("⚠️ 未找到 stations.json, 请先运行: python3 nmc_weather.py refresh")
    return json.loads(STATIONS_FILE.read_text(encoding="utf-8"))


def find_station(stations: dict, name: str):
    """精确匹配优先, 其次前缀匹配(如 '南京' 命中 '南京')"""
    if name in stations:
        return stations[name]
    for city, info in stations.items():
        if city.startswith(name) or name.startswith(city):
            return info
    return None


def forecast_from_data(data: dict) -> tuple:
    """从 /rest/weather 响应中提取 未来7天逐日预报"""
    predict = data["predict"]
    rows = []
    for d in predict["detail"]:
        rows.append({
            "日期": d["date"],
            "白天天气": d["day"]["weather"]["info"],
            "白天温度": d["day"]["weather"]["temperature"],
            "白天风向": d["day"]["wind"]["direct"],
            "白天风力": d["day"]["wind"]["power"],
            "夜间天气": d["night"]["weather"]["info"],
            "夜间温度": d["night"]["weather"]["temperature"],
            "夜间风向": d["night"]["wind"]["direct"],
            "夜间风力": d["night"]["wind"]["power"],
            "降水量(mm)": d.get("precipitation") or 0,
        })
    return predict["publish_time"], rows


def fetch_forecast(code: str) -> list:
    """未来7天逐日预报"""
    data = get("/rest/weather", params={"stationid": code})
    return forecast_from_data(data["data"])


def fetch_temp14(code: str) -> list:
    """近7天 + 未来7天 高低温(tempchart 接口)"""
    data = get(f"/f/rest/tempchart/{code}")
    today = datetime.now().date()
    rows = []
    for d in data:
        date = datetime.strptime(d["time"], "%Y/%m/%d").date()
        # 历史日期的天气字段为 "9999"(无数据), 仅未来日期有效
        day_text = d.get("day_text") or ""
        night_text = d.get("night_text") or ""
        rows.append({
            "日期": date.isoformat(),
            "类型": "实况" if date <= today else "预报",
            "白天天气": "" if day_text == "9999" else day_text,
            "夜间天气": "" if night_text == "9999" else night_text,
            "最高气温": d["max_temp"],
            "最低气温": d["min_temp"],
        })
    return rows


def save_csv(rows: list, fieldnames: list, filename: str):
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"💾 已保存: {filename} ({len(rows)} 行)")


def export_data_json(path: str):
    """导出网页版兜底快照: 每城市完整 /rest/weather 响应 (网页直连失败时回退使用)"""
    city_names = [line.strip() for line in
                  CITIES_FILE.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
    stations = load_stations()
    out, failed = [], []
    for name in dict.fromkeys(city_names):
        st = find_station(stations, name)
        if not st:
            print(f"❌ 未找到城市: {name}")
            failed.append(name)
            continue
        try:
            data = get("/rest/weather", params={"stationid": st["code"]})
            out.append({"city": st["city"], "province": st["province"],
                        "station_code": st["code"], "data": data["data"]})
            print(f"✅ {st['province']} {st['city']}")
        except Exception as e:
            print(f"❌ {st['city']} 获取失败: {e}")
            failed.append(name)
    payload = {"fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "cities": out}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"💾 已保存: {path} ({len(out)} 城)")
    if failed:
        print(f"\n⚠️ 失败城市: {', '.join(failed)}")
        sys.exit(1)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "refresh":
        refresh_stations()
        return
    if "--json" in sys.argv:
        i = sys.argv.index("--json")
        path = sys.argv[i + 1] if i + 1 < len(sys.argv) else "data.json"
        export_data_json(path)
        return

    with_temp14 = "--temp14" in sys.argv
    json_out = None
    if "--json" in sys.argv:  # 网页版兜底快照: 导出原始响应供 index.html 回退使用
        i = sys.argv.index("--json")
        if i + 1 >= len(sys.argv):
            sys.exit("⚠️ --json 需要指定输出路径, 如: python3 nmc_weather.py --json data.json")
        json_out = sys.argv[i + 1]
    if not CITIES_FILE.exists():
        sys.exit(f"⚠️ 未找到 {CITIES_FILE}, 请创建并每行填写一个城市名")

    city_names = [line.strip() for line in
                  CITIES_FILE.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")]
    # 去重(保持原有顺序), 重复项提醒后跳过
    seen, unique_names, duplicates = set(), [], []
    for name in city_names:
        if name in seen:
            duplicates.append(name)
        else:
            seen.add(name)
            unique_names.append(name)
    if duplicates:
        print(f"⚠️ 城市列表存在重复项, 已自动跳过: {', '.join(duplicates)}")
    city_names = unique_names

    stations = load_stations()

    forecast_rows, temp14_rows, failed = [], [], []
    snapshot = {}  # --json 模式: 城市 -> 原始响应数据
    for name in city_names:
        st = find_station(stations, name)
        if not st:
            print(f"❌ 未找到城市: {name} (可尝试运行 refresh 更新缓存)")
            failed.append(name)
            continue
        try:
            if json_out:
                # 快照模式只取原始数据, 不生成 CSV 行
                data = get("/rest/weather", params={"stationid": st["code"]})["data"]
                snapshot[st["city"]] = {
                    "province": st["province"], "code": st["code"], "data": data,
                }
                print(f"✅ {st['province']} {st['city']}: 快照已收录 "
                      f"(发布于 {data['predict']['publish_time']})")
                continue
            publish_time, rows = fetch_forecast(st["code"])
            for r in rows:
                forecast_rows.append({"城市": st["city"], "省份": st["province"],
                                      "发布时刻": publish_time, **r})
            print(f"✅ {st['province']} {st['city']}: {len(rows)} 天预报 "
                  f"(发布于 {publish_time})")
            if with_temp14:
                for r in fetch_temp14(st["code"]):
                    temp14_rows.append({"城市": st["city"], "省份": st["province"], **r})
        except Exception as e:
            print(f"❌ {st['city']} 获取失败: {e}")
            failed.append(name)

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    if json_out:
        out = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
               "cities": snapshot}
        Path(json_out).write_text(json.dumps(out, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"💾 已保存: {json_out} ({len(snapshot)} 城市)")
    if forecast_rows:
        save_csv(forecast_rows, list(forecast_rows[0].keys()),
                 f"weather_forecast_{stamp}.csv")
    if temp14_rows:
        save_csv(temp14_rows, list(temp14_rows[0].keys()),
                 f"weather_temp14_{stamp}.csv")

    if failed:
        print(f"\n⚠️ 失败城市: {', '.join(failed)}")
        sys.exit(1)
    print("\n🎉 全部完成")


if __name__ == "__main__":
    main()
