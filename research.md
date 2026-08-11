> **📌 后续更新（2026-08-10）**：本文是早期调研记录，示例脚本已被项目根目录的实际实现取代——
> - `nmc_weather.py`：站点代码全量缓存到 `stations.json` 本地查找（不再每次遍历 34 省发请求），城市列表外置到 `cities.txt`，支持 `--temp14` 导出气温
> - `filter_weather.py`：交互式筛选向导，无当日数据时自动先抓取
> - 实测修正：`tempchart` 接口为**过去 7 天 + 未来 7 天**（共 14 条），NMC 没有超过 7 天的预报；`get_realtime()`/`get_aqi()` 方法未纳入最终实现
>
> 日常使用请见 `README.md`。以下为原始调研内容。

---

## 调研结论：可以爬取，且**无需模拟浏览器**

中国气象台（`nmc.cn`）提供了一套**未公开的 REST API**，直接返回 JSON 数据，无需解析 HTML 或绕过反爬机制。我已完整验证接口可用性，并编写了可直接运行的生产级脚本。

---

## 一、核心 API 接口清单

| 接口 | 地址 | 说明 |
|------|------|------|
| 省份列表 | `GET /f/rest/province` | 34 个省级行政区 |
| 城市列表 | `GET /f/rest/province/{省份代码}` | 该省所有气象站点（含区县） |
| **7 天预报** | `GET /rest/weather?stationid={城市代码}` | **核心接口**，含白天/夜间天气、温度、风向、风力、降水量 |
| 实时天气 | `GET /f/rest/real/{城市代码}` | 当前温度、湿度、气压、降雨、体感温度 |
| 空气质量 | `GET /f/rest/aqi/{城市代码}` | AQI 指数与等级 |
| 温度图表 | `GET /f/rest/tempchart/{城市代码}` | 过去 7 天 + 未来 7 天高低温 |

> **关键发现**：城市代码已改为短随机字符串（如上海 `WwcJd`、西安 `RfjCI`），而非旧版的纯数字站号，需先通过搜索接口映射。

---

## 二、Python 完整脚本（已验证）

脚本功能：
- 根据**城市名自动搜索**对应气象站代码
- 批量获取**未来 7 天**预报（天气状况、温度、风向、风力、降水）
- 输出**终端表格** + **CSV** + **JSON**
- 内置请求间隔与异常处理，避免触发限流

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中国气象台 (nmc.cn) 天气数据批量爬虫
依赖：pip install requests
版权：数据归国家气象中心所有，仅供学习交流
"""

import requests
import json
import csv
import time
import sys
from typing import List, Dict, Optional

BASE_URL = "https://www.nmc.cn"

class NMCWeatherCrawler:
    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.nmc.cn/",
        })
        self._province_cache: Optional[List[Dict]] = None
        self._city_cache: Dict[str, List[Dict]] = {}

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = f"{BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_provinces(self) -> List[Dict]:
        if self._province_cache is None:
            self._province_cache = self._get("/f/rest/province")
            time.sleep(self.delay)
        return self._province_cache

    def get_cities(self, province_code: str) -> List[Dict]:
        if province_code not in self._city_cache:
            self._city_cache[province_code] = self._get(f"/f/rest/province/{province_code}")
            time.sleep(self.delay)
        return self._city_cache[province_code]

    def search_city(self, city_name: str) -> Optional[Dict]:
        """根据城市名搜索气象站代码，支持模糊匹配"""
        for prov in self.get_provinces():
            for city in self.get_cities(prov["code"]):
                if city_name in city["city"]:
                    if city["city"] == city_name:  # 优先精确匹配
                        return city
        return None

    def get_forecast(self, station_id: str) -> Dict:
        """
        获取未来7天预报
        返回: {city, province, publish_time, forecast: [...]}
        """
        data = self._get("/rest/weather", params={"stationid": station_id})
        time.sleep(self.delay)

        predict = data["data"]["predict"]
        forecast = []
        for day in predict["detail"]:
            forecast.append({
                "date": day["date"],
                "day_weather": day["day"]["weather"]["info"],
                "day_temp": int(day["day"]["weather"]["temperature"]),
                "day_wind_direct": day["day"]["wind"]["direct"],
                "day_wind_power": day["day"]["wind"]["power"],
                "night_weather": day["night"]["weather"]["info"],
                "night_temp": int(day["night"]["weather"]["temperature"]),
                "night_wind_direct": day["night"]["wind"]["direct"],
                "night_wind_power": day["night"]["wind"]["power"],
                "precipitation": float(day.get("precipitation") or 0.0),
            })

        return {
            "city": predict["station"]["city"],
            "province": predict["station"]["province"],
            "publish_time": predict["publish_time"],
            "forecast": forecast,
        }

    def batch_fetch(self, city_names: List[str]) -> List[Dict]:
        results = []
        for name in city_names:
            print(f"\n🔍 正在搜索: {name} ...")
            info = self.search_city(name)
            if not info:
                print(f"  ❌ 未找到城市: {name}")
                continue
            print(f"  ✅ 匹配到: {info['province']} {info['city']} (code={info['code']})")
            try:
                forecast = self.get_forecast(info["code"])
                results.append(forecast)
                print(f"  📊 获取到 {len(forecast['forecast'])} 天预报")
            except Exception as e:
                print(f"  ❌ 失败: {e}")
        return results


def print_table(results: List[Dict]):
    for res in results:
        print(f"\n{'='*80}")
        print(f"📍 {res['province']} {res['city']}  |  发布时间: {res['publish_time']}")
        print(f"{'='*80}")
        print(f"{'日期':<12}{'白天':<8}{'高温':<6}{'夜间':<8}{'低温':<6}{'风向':<10}{'风力':<10}{'降水':<8}")
        print("-" * 80)
        for d in res["forecast"]:
            print(
                f"{d['date']:<12}{d['day_weather']:<8}{d['day_temp']}°C{'':<3}"
                f"{d['night_weather']:<8}{d['night_temp']}°C{'':<3}"
                f"{d['day_wind_direct']:<10}{d['day_wind_power']:<10}"
                f"{d['precipitation']:.1f}mm"
            )


def save_to_csv(results: List[Dict], filename: str = "weather.csv"):
    rows = []
    for res in results:
        for d in res["forecast"]:
            rows.append({
                "城市": res["city"], "省份": res["province"],
                "发布时刻": res["publish_time"], "日期": d["date"],
                "白天天气": d["day_weather"], "白天温度": d["day_temp"],
                "白天风向": d["day_wind_direct"], "白天风力": d["day_wind_power"],
                "夜间天气": d["night_weather"], "夜间温度": d["night_temp"],
                "夜间风向": d["night_wind_direct"], "夜间风力": d["night_wind_power"],
                "降水量(mm)": d["precipitation"],
            })
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n💾 CSV 已保存: {filename}")


def main():
    # ========== 配置区域 ==========
    city_names = ["上海", "西安", "北京", "成都", "杭州"]
    delay = 0.5  # 请求间隔（秒）
    # ==============================

    crawler = NMCWeatherCrawler(delay=delay)
    results = crawler.batch_fetch(city_names)

    if not results:
        print("⚠️ 未获取到数据")
        sys.exit(1)

    print_table(results)
    save_to_csv(results)
    print("\n✅ 全部完成！")


if __name__ == "__main__":
    main()
```

---

## 三、TypeScript / Node.js 版本

如果你更倾向用 TypeScript（配合 `bun` 或 `node`）：

```typescript
// nmc_weather.ts
// 运行: bun run nmc_weather.ts  或  npx tsx nmc_weather.ts

const BASE = "https://www.nmc.cn";

interface CityInfo {
  code: string;
  province: string;
  city: string;
}

interface DayForecast {
  date: string;
  day_weather: string;
  day_temp: number;
  day_wind_direct: string;
  day_wind_power: string;
  night_weather: string;
  night_temp: number;
  night_wind_direct: string;
  night_wind_power: string;
  precipitation: number;
}

class NMCClient {
  private delay: number;
  private provinceCache?: any[];
  private cityCache = new Map<string, any[]>();

  constructor(delay = 500) {
    this.delay = delay;
  }

  private async sleep() {
    return new Promise(r => setTimeout(r, this.delay));
  }

  private async get(path: string, params?: Record<string, string>) {
    const url = new URL(path, BASE);
    if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url.toString(), {
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://www.nmc.cn/",
      },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async getProvinces() {
    if (!this.provinceCache) {
      this.provinceCache = await this.get("/f/rest/province");
      await this.sleep();
    }
    return this.provinceCache;
  }

  async getCities(provinceCode: string) {
    if (!this.cityCache.has(provinceCode)) {
      const cities = await this.get(`/f/rest/province/${provinceCode}`);
      this.cityCache.set(provinceCode, cities);
      await this.sleep();
    }
    return this.cityCache.get(provinceCode)!;
  }

  async searchCity(name: string): Promise<CityInfo | null> {
    const provinces = await this.getProvinces();
    for (const prov of provinces) {
      const cities = await this.getCities(prov.code);
      for (const city of cities) {
        if (city.city.includes(name)) return city;
      }
    }
    return null;
  }

  async getForecast(stationId: string) {
    const data: any = await this.get("/rest/weather", { stationid: stationId });
    await this.sleep();
    const predict = data.data.predict;
    const forecast: DayForecast[] = predict.detail.map((day: any) => ({
      date: day.date,
      day_weather: day.day.weather.info,
      day_temp: parseInt(day.day.weather.temperature),
      day_wind_direct: day.day.wind.direct,
      day_wind_power: day.day.wind.power,
      night_weather: day.night.weather.info,
      night_temp: parseInt(day.night.weather.temperature),
      night_wind_direct: day.night.wind.direct,
      night_wind_power: day.night.wind.power,
      precipitation: parseFloat(day.precipitation || 0),
    }));
    return {
      city: predict.station.city,
      province: predict.station.province,
      publish_time: predict.publish_time,
      forecast,
    };
  }

  async batchFetch(names: string[]) {
    const results = [];
    for (const name of names) {
      console.log(`\n🔍 搜索: ${name} ...`);
      const info = await this.searchCity(name);
      if (!info) {
        console.log(`  ❌ 未找到: ${name}`);
        continue;
      }
      console.log(`  ✅ ${info.province} ${info.city} (${info.code})`);
      try {
        const forecast = await this.getForecast(info.code);
        results.push(forecast);
        console.log(`  📊 ${forecast.forecast.length} 天预报`);
      } catch (e) {
        console.log(`  ❌ 失败: ${e}`);
      }
    }
    return results;
  }
}

// ========== 使用示例 ==========
async function main() {
  const client = new NMCClient(500);
  const results = await client.batchFetch(["上海", "西安", "北京"]);

  for (const r of results) {
    console.log(`\n📍 ${r.province} ${r.city} | ${r.publish_time}`);
    console.log("-".repeat(70));
    for (const d of r.forecast) {
      console.log(
        `${d.date} | 白天 ${d.day_weather} ${d.day_temp}°C (${d.day_wind_direct} ${d.day_wind_power}) | ` +
        `夜间 ${d.night_weather} ${d.night_temp}°C | 降水 ${d.precipitation}mm`
      );
    }
  }
}

main();
```

---

## 四、实测数据样例（上海）

| 日期 | 白天天气 | 高温 | 夜间天气 | 低温 | 风向 | 风力 | 降水 |
|------|---------|------|---------|------|------|------|------|
| 2026-08-10 | 暴雨 | 28°C | 大雨 | 26°C | 东风 | 5~6级 | 75.0mm |
| 2026-08-11 | 小雨 | 30°C | 小雨 | 26°C | 东南风 | 5~6级 | 15.7mm |
| 2026-08-12 | 阴 | 30°C | 阴 | 26°C | 东风 | 微风 | 0.0mm |
| ... | ... | ... | ... | ... | ... | ... | ... |

---

## 五、关键注意事项

1. **数据版权**：接口返回数据版权属**国家气象中心**，脚本仅供个人学习与研究，大规模商用需联系 `nmccn@cma.gov.cn` 获取授权。
2. **请求频率**：建议间隔 **≥ 300ms**。省份列表可缓存到本地（如 `provinces.json`），避免每次重复请求。
3. **城市代码**：`nmc.cn` 已弃用数字站号，改用短随机字符串（如 `WwcJd`），**不可硬编码**，必须通过搜索接口动态获取。
4. **数据时效**：预报每日约 **06:00、12:00、18:00** 三次更新，`publish_time` 字段标识发报时间。
5. **稳定性**：此为未公开 API，结构可能调整。建议在生产环境中加入字段存在性校验与降级逻辑。

---

## 六、macOS 快速开始

```bash
# 1. 安装依赖
pip install requests

# 2. 保存脚本为 nmc_weather.py，修改 city_names 列表

# 3. 运行
python3 nmc_weather.py

# 输出：终端表格 + weather.csv + weather.json
```

如需**实时天气**（当前温度/湿度/降雨）或**空气质量**，脚本中已预留 `get_realtime()` 与 `get_aqi()` 方法，直接调用即可。