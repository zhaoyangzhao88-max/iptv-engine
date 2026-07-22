#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三方情报聚合爬虫 v1.1
=======================
从多个 IPTV 情报源抓取现成 M3U8 地址，按省份分类归集。

数据源（按优先级）:
  1. https://foodieguide.com/iptv/hotlist.php (主入口，需 curl_cffi 绕过 Cloudflare)
  2. https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u (GitHub 镜像，稳定)

反爬策略:
  - curl_cffi 模拟 Chrome TLS 指纹
  - 随机 UA + Referer
  - 请求间隔 1-2s 随机抖动
  - 失败重试 3 次
  - 源1失败时自动降级到源2

用法:
  python src/aggregator_crawler.py                    # 爬取全部
  python src/aggregator_crawler.py --province 四川     # 只爬指定省份
  python src/aggregator_crawler.py --source foodieguide # 指定源
  python src/aggregator_crawler.py --source iptv-org   # 指定源
  python src/aggregator_crawler.py --output my.json    # 自定义输出文件
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
import re
import json
import time
import random
import argparse
from datetime import datetime

from config import OUTPUT_DIR

# ── 依赖检查 ──────────────────────────────────
import requests  # 用于 iptv-org 等普通 HTTP 源
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    print("  ⚠️ curl_cffi 未安装，降级为 requests")

# ── 配置常量 ──────────────────────────────────
BASE_URL = "https://foodieguide.com/iptv/hotlist.php"
BASE_DOMAIN = "https://foodieguide.com"
OUTPUT_FILE = "aggregator_results.json"

# 省份关键词映射（用于从 URL/文本中识别省份）
PROVINCE_KEYWORDS = {
    "四川": ["四川", "sc", "sichuan", "成都", "cd"],
    "重庆": ["重庆", "cq", "chongqing"],
    "广东": ["广东", "gd", "guangdong", "广州", "深圳", "gz", "sz"],
    "浙江": ["浙江", "zj", "zhejiang", "杭州", "hz"],
    "江苏": ["江苏", "js", "jiangsu", "南京", "nj"],
    "山东": ["山东", "sd", "shandong", "济南", "jn"],
    "河南": ["河南", "hn", "henan", "郑州", "zz"],
    "湖北": ["湖北", "hb", "hubei", "武汉", "wh"],
    "湖南": ["湖南", "hunan", "长沙", "cs"],
    "福建": ["福建", "fj", "fujian", "厦门", "xm"],
    "安徽": ["安徽", "ah", "anhui", "合肥", "hf"],
    "江西": ["江西", "jx", "jiangxi", "南昌", "nc"],
    "广西": ["广西", "gx", "guangxi", "南宁", "nn"],
    "云南": ["云南", "yn", "yunnan", "昆明", "km"],
    "贵州": ["贵州", "gz", "guizhou", "贵阳", "gy"],
    "陕西": ["陕西", "shaanxi", "西安", "xa"],
    "山西": ["山西", "shanxi", "太原", "ty"],
    "河北": ["河北", "hebei", "石家庄", "sjz"],
    "北京": ["北京", "bj", "beijing"],
    "天津": ["天津", "tj", "tianjin"],
    "上海": ["上海", "sh", "shanghai"],
    "海南": ["海南", "hainan", "海口", "三亚"],
    "甘肃": ["甘肃", "gansu", "兰州", "lz"],
    "宁夏": ["宁夏", "ningxia", "银川", "yc"],
    "青海": ["青海", "qinghai", "西宁", "xn"],
    "内蒙古": ["内蒙古", "neimenggu", "呼和浩特", "hhht"],
    "新疆": ["新疆", "xinjiang", "乌鲁木齐", "wlmq"],
    "西藏": ["西藏", "xizang", "拉萨", "ls"],
    "辽宁": ["辽宁", "ln", "liaoning", "沈阳", "sy"],
    "吉林": ["吉林", "jl", "jilin", "长春", "cc"],
    "黑龙江": ["黑龙江", "hlj", "heilongjiang", "哈尔滨", "hrb"],
    "央视": ["央视", "CCTV", "cctv", "中央"],
}

# 27 个零存活省份（优先回血目标）
ZERO_PROVINCES = [
    "四川", "重庆", "江苏", "山东", "河南", "湖北", "福建", "安徽",
    "江西", "广西", "云南", "贵州", "陕西", "山西", "河北", "天津",
    "海南", "甘肃", "宁夏", "青海", "内蒙古", "新疆", "西藏",
    "辽宁", "吉林", "黑龙江",
]

# UA 池
UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


# ── HTTP 请求 ──────────────────────────────────

def fetch_page(url: str, retries: int = 3, timeout: int = 15) -> str | None:
    """
    获取页面 HTML。
    优先使用 curl_cffi 模拟 Chrome TLS 指纹，失败时降级为 requests。
    """
    headers = {
        "User-Agent": random.choice(UA_POOL),
        "Referer": BASE_DOMAIN + "/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    for attempt in range(retries):
        try:
            if HAS_CURL_CFFI:
                resp = curl_requests.get(
                    url,
                    headers=headers,
                    timeout=timeout,
                    impersonate="chrome",
                )
            else:
                resp = requests.get(url, headers=headers, timeout=timeout)

            if resp.status_code == 200:
                return resp.text
            elif resp.status_code == 403:
                print(f"    ⚠️ 403 Forbidden (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(random.uniform(2, 4))
            else:
                print(f"    ⚠️ HTTP {resp.status_code} (attempt {attempt + 1}/{retries})")
        except Exception as e:
            print(f"    ⚠️ 请求异常: {e} (attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(random.uniform(1, 3))

    return None


# ── HTML 解析 ──────────────────────────────────

# 匹配 m3u8 URL 的正则
M3U8_RE = re.compile(
    r'https?://[^\s<>"\']+?\.m3u8[^\s<>"\']*',
    re.IGNORECASE,
)

# 匹配分支页面链接
LINK_RE = re.compile(
    r'href=["\']([^"\']*?(?:province|iptv|live|channel)[^"\']*)["\']',
    re.IGNORECASE,
)


def extract_m3u8_urls(html: str) -> list[dict]:
    """
    从 HTML 中提取所有 m3u8 URL 及其上下文。
    返回 [{"url": ..., "context": ...}] 列表。
    """
    results = []
    seen_urls = set()

    for match in M3U8_RE.finditer(html):
        url = match.group(0).rstrip("',\"")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # 提取 URL 前后的文本作为频道名线索
        start = max(0, match.start() - 200)
        end = min(len(html), match.end() + 200)
        context = html[start:end]

        # 尝试从上下文中提取频道名
        name = extract_channel_name(context, url)

        results.append({
            "url": url,
            "name": name,
            "context": context[:300],
        })

    return results


def extract_channel_name(context: str, url: str) -> str:
    """从 URL 上下文中尝试提取频道名"""
    # 方法1: 查找附近的中文标签
    # 匹配 >频道名< 或 "频道名" 或 '频道名'
    name_patterns = [
        r'>([^<]{2,20}台)<',
        r'>([^<]{2,20}频道)<',
        r'>([^<]{2,20}卫视)<',
        r'>([^<]{2,20}综合)<',
        r'>([^<]{2,20}新闻)<',
        r'>([^<]{2,20}公共)<',
        r'>([^<]{2,20}影视)<',
        r'>([^<]{2,20}体育)<',
        r'>([^<]{2,20}都市)<',
        r'title["\s]*[:=]["\s]*([^"\'<]{2,30})',
        r'alt["\s]*[:=]["\s]*([^"\'<]{2,30})',
    ]

    for pat in name_patterns:
        m = re.search(pat, context, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            if len(name) >= 2:
                return name

    # 方法2: 从 URL 路径中提取
    try:
        from urllib.parse import urlparse
        path = urlparse(url).path
        # 取路径最后一段（不含扩展名）
        parts = [p for p in path.split("/") if p and p != "index.m3u8"]
        if parts:
            last = parts[-1].replace(".m3u8", "").replace("-", " ").replace("_", " ")
            if len(last) >= 2 and not last.replace(".", "").isdigit():
                return last
    except Exception:
        pass

    return "未知频道"


def extract_subpage_links(html: str, base_url: str) -> list[str]:
    """从 HTML 中提取分支页面链接"""
    links = set()
    for match in LINK_RE.finditer(html):
        href = match.group(1)
        # 补全相对 URL
        if href.startswith("/"):
            href = BASE_DOMAIN + href
        elif not href.startswith("http"):
            href = BASE_DOMAIN + "/" + href
        # 只保留同域名
        if BASE_DOMAIN in href:
            links.add(href)
    return list(links)


# ── 省份分类 ──────────────────────────────────

def classify_by_province(url: str, name: str, context: str) -> str | None:
    """
    根据 URL、频道名、上下文判断所属省份。
    返回省份名 or None。
    """
    # 合并所有文本用于匹配
    text = f"{url} {name} {context}".lower()

    for province, keywords in PROVINCE_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text:
                return province

    return None


# ── 主爬虫流程 ──────────────────────────────────

def crawl_all(target_province: str = None) -> list[dict]:
    """
    主爬虫流程：
    1. 抓取 hotlist.php 主页面
    2. 提取分支页面链接
    3. 并发抓取分支页面
    4. 汇总去重，按省份分类
    """
    all_channels = []
    seen_urls = set()

    print(f"\n{'=' * 60}")
    print(f"  第三方情报聚合爬虫 v1.0")
    print(f"  目标站点: {BASE_URL}")
    print(f"  反爬策略: {'curl_cffi (Chrome TLS)' if HAS_CURL_CFFI else 'requests (降级)'}")
    print(f"{'=' * 60}\n")

    # Step 1: 抓取主页面
    print(f"[1/3] 抓取主页面: {BASE_URL}")
    main_html = fetch_page(BASE_URL)
    if not main_html:
        print("  ❌ 主页面抓取失败，尝试备用方案...")
        # 备用：直接构造各省页面 URL
        main_html = ""

    main_results = []
    if main_html:
        main_results = extract_m3u8_urls(main_html)
        print(f"  主页面提取到 {len(main_results)} 个 m3u8 URL")

    # Step 2: 提取分支页面
    subpage_links = []
    if main_html:
        subpage_links = extract_subpage_links(main_html, BASE_URL)
        print(f"  发现 {len(subpage_links)} 个分支页面链接")

    # Step 3: 抓取分支页面
    print(f"\n[2/3] 抓取分支页面...")
    subpage_results = []
    for i, link in enumerate(subpage_links):
        print(f"  [{i + 1}/{len(subpage_links)}] {link}")
        time.sleep(random.uniform(0.5, 1.5))  # 随机间隔
        html = fetch_page(link)
        if html:
            results = extract_m3u8_urls(html)
            subpage_results.extend(results)
            print(f"    -> 提取到 {len(results)} 个 m3u8 URL")
        else:
            print(f"    -> 抓取失败，跳过")

    # Step 4: 汇总去重 + 省份分类
    print(f"\n[3/3] 汇总去重 + 省份分类...")
    all_raw = main_results + subpage_results

    province_channels = {}  # province -> [channel, ...]
    unclassified = 0

    for item in all_raw:
        url = item["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        name = item["name"]
        context = item.get("context", "")

        province = classify_by_province(url, name, context)

        if target_province and province != target_province:
            continue

        channel = {
            "province": province or "未知",
            "name": name,
            "url": url,
            "source": "aggregator",
        }

        if province:
            if province not in province_channels:
                province_channels[province] = []
            province_channels[province].append(channel)
        else:
            unclassified += 1

        all_channels.append(channel)

    # 打印统计
    print(f"\n{'─' * 40}")
    print(f"  爬取统计:")
    print(f"  原始 URL 总数: {len(all_raw)}")
    print(f"  去重后 URL 数: {len(all_channels)}")
    print(f"  已分类 URL 数: {len(all_channels) - unclassified}")
    print(f"  未分类 URL 数: {unclassified}")
    print(f"  覆盖省份数: {len(province_channels)}")

    if province_channels:
        print(f"\n  ── 各省频道统计 ──")
        for prov, chs in sorted(province_channels.items(), key=lambda x: -len(x[1])):
            marker = "🎯" if prov in ZERO_PROVINCES else "  "
            print(f"  {marker} {prov}: {len(chs)} 个频道")

    # 回血统计
    recovered = [p for p in ZERO_PROVINCES if p in province_channels and len(province_channels[p]) > 0]
    if recovered:
        print(f"\n  🎉 回血成功省份 ({len(recovered)}/{len(ZERO_PROVINCES)}):")
        for p in recovered:
            print(f"    ✅ {p}: {len(province_channels[p])} 个频道")

    return all_channels


# ── 结果输出 ──────────────────────────────────

def save_results(channels: list[dict], output_file: str) -> str:
    """保存结果到 output/aggregator_results.json"""
    # 按省份统计
    province_count = {}
    for ch in channels:
        p = ch.get("province", "未知")
        province_count[p] = province_count.get(p, 0) + 1

    output = {
        "_meta": {
            "source": "foodieguide.com",
            "crawl_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total_channels": len(channels),
            "provinces_covered": len(province_count),
            "province_stats": province_count,
            "crawler": "aggregator_crawler v1.0",
            "anti_bot": "curl_cffi (Chrome TLS)" if HAS_CURL_CFFI else "requests (fallback)",
        },
        "channels": channels,
    }

    out_path = os.path.join(OUTPUT_DIR, output_file)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return out_path


# ── 主入口 ──────────────────────────────────

def crawl_iptv_org(target_province: str = None) -> list[dict]:
    """
    从 iptv-org GitHub 仓库抓取中国频道列表。
    这是 foodieguide.com 不可用时的稳定备用源。
    """
    url = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u"
    print(f"\n[iptv-org] 抓取: {url}")

    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": random.choice(UA_POOL)})
        if resp.status_code != 200:
            print(f"  ❌ HTTP {resp.status_code}")
            return []
        content = resp.text
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return []

    # 解析 M3U
    channels_list = []
    current_name = None
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("#EXTINF:"):
            m = re.search(r",(.+)$", line)
            if m:
                current_name = m.group(1).strip()
        elif line and not line.startswith("#") and current_name:
            channels_list.append({"name": current_name, "url": line})
            current_name = None

    print(f"  解析到 {len(channels_list)} 个频道")

    # 省份分类
    output_channels = []
    seen_urls = set()
    for ch in channels_list:
        text = f"{ch['name']} {ch['url']}".lower()
        for prov, kws in PROVINCE_KEYWORDS.items():
            for kw in kws:
                if kw.lower() in text:
                    if ch["url"] not in seen_urls:
                        seen_urls.add(ch["url"])
                        if target_province and prov != target_province:
                            break
                        output_channels.append({
                            "province": prov,
                            "name": ch["name"],
                            "url": ch["url"],
                            "source": "aggregator",
                        })
                    break
            else:
                continue
            break

    print(f"  分类后: {len(output_channels)} 个频道")
    return output_channels


def main():
    parser = argparse.ArgumentParser(description="第三方情报聚合爬虫 v1.1")
    parser.add_argument("--province", type=str, default=None, help="只爬取指定省份")
    parser.add_argument("--source", type=str, default="auto",
                        choices=["auto", "foodieguide", "iptv-org"],
                        help="数据源：auto(自动降级) | foodieguide | iptv-org")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE, help=f"输出文件名（默认{OUTPUT_FILE}）")
    args = parser.parse_args()

    t_start = time.monotonic()
    channels = []

    if args.source in ("auto", "foodieguide"):
        channels = crawl_all(target_province=args.province)
        if not channels and args.source == "auto":
            print("\n  foodieguide.com 无数据，降级到 iptv-org...")
            channels = crawl_iptv_org(target_province=args.province)
    elif args.source == "iptv-org":
        channels = crawl_iptv_org(target_province=args.province)

    if channels:
        out_path = save_results(channels, args.output)
        elapsed = time.monotonic() - t_start
        print(f"\n结果已保存: {out_path}")
        print(f"文件大小: {os.path.getsize(out_path):,} 字节")
        print(f"总耗时: {elapsed:.1f} 秒")
    else:
        print("\n未抓取到任何频道，请检查网络或目标站点是否可访问。")

    print("\n爬取完成。")


if __name__ == "__main__":
    main()
