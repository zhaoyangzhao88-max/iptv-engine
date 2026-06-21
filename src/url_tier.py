import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import config

TIER1_PATTERNS = [
    r"cztv\.com",
    r"cztvcloud\.com",  # 浙江广电
    r"jlntv\.cn",  # 吉林广电
    r"cnr\.cn",  # 中央人民广播
    r"hrbtv\.net",  # 哈尔滨广电
    r"hntv\.tv",  # 湖南广电
    r"nntv\.cn",  # 南宁广电
    r"lytv\.tv",  # 洛阳广电
    r"ahbztv\.com",  # 安徽广电
    r"yangshipin\.cn",  # 央视频官方
    r"yicai\.com",  # 第一财经
    r"qingting\.fm",  # 蜻蜓FM官方
    r"shaoxing\.com\.cn",  # 绍兴广电
    r"hfmt\.net",  # 合肥广电
    r"ybcxjd\.com",  # 宜宾广电
    r"bdstatic\.com",  # 百度CDN（稳定）
    r"myalicdn\.com",  # 阿里CDN（稳定）
    r"cloudfront\.net",  # AWS CDN
    r"kwimgs\.com",  # 快手官方
]

TIER2_PATTERNS = [
    r"ottiptv\.cc",
    r"kankanlive\.com",
    r"quklive\.com",
    r"juyun\.tv",
    r"thmz\.com",
    r"hugd\.com",
]

TIER3_PATTERNS = [
    r"061899\.xyz",
    r"264788\.xyz",
    r"ddzb\.fun",
    r"qqff\.top",
    r"serv00\.net",
]

TIER_NAMES = {
    1: "Tier1 官方广电CDN（极稳定）",
    2: "Tier2 平台/未知域名（较稳定）",
    3: "Tier3 个人域名（不稳定）",
    4: "Tier4 IP直连/IPv6（最不稳定）",
}


def is_ip_direct(host: str) -> bool:
    # IPv4 直连
    if re.match(r"^\d+\.\d+\.\d+\.\d+(:\d+)?$", host):
        return True
    # IPv6 直连（方括号包裹的 IPv6 地址）
    if re.match(r"^\[.*\]", host):
        return True
    return False


def classify_url(url: str) -> int:
    host = urlparse(url).netloc
    if is_ip_direct(host):
        return 4

    for pat in TIER1_PATTERNS:
        if re.search(pat, url, re.IGNORECASE):
            return 1

    for pat in TIER2_PATTERNS:
        if re.search(pat, url, re.IGNORECASE):
            return 2

    for pat in TIER3_PATTERNS:
        if re.search(pat, url, re.IGNORECASE):
            return 3

    return 2


def tier_name(tier: int) -> str:
    return TIER_NAMES[tier]


def summarize_tiers(channels: list[dict]) -> dict[int, dict[str, int]]:
    tier_counts = defaultdict(int)
    tier_channels = defaultdict(set)

    for ch in channels:
        for url in ch.get("urls", []):
            tier = classify_url(url)
            tier_counts[tier] += 1
            tier_channels[tier].add(ch["name"])

    total = sum(tier_counts.values())

    summary = {}
    for tier in [1, 2, 3, 4]:
        count = tier_counts[tier]
        channel_count = len(tier_channels[tier])
        pct = count / total * 100 if total else 0
        summary[tier] = {
            "url_count": count,
            "channel_count": channel_count,
            "percent": pct,
        }

    return summary


def sort_channel_urls(ch: dict) -> dict:
    urls = ch.get("urls", [])
    delays = ch.get("delays", [])

    paired = list(zip(urls, delays)) if delays else [(u, 999) for u in urls]
    paired.sort(key=lambda x: (classify_url(x[0]), x[1]))

    sorted_urls = [p[0] for p in paired]
    sorted_delays = [p[1] for p in paired]

    return {
        "name": ch["name"],
        "urls": sorted_urls,
        "delays": sorted_delays,
        "min_delay_ms": min(sorted_delays) if sorted_delays else 999,
        "url_tiers": [classify_url(u) for u in sorted_urls],
    }


def process_channels(input_path: str | Path, output_path: str | Path) -> list[dict]:
    with open(input_path, encoding="utf-8") as f:
        channels = json.load(f)

    new_channels = [sort_channel_urls(ch) for ch in channels]
    new_channels.sort(key=lambda x: x["min_delay_ms"])

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(new_channels, f, ensure_ascii=False, indent=2)

    return new_channels


def print_summary(channels: list[dict]) -> None:
    summary = summarize_tiers(channels)

    print("=== URL稳定性分层统计 ===\n")

    for tier in [1, 2, 3, 4]:
        info = summary[tier]
        print(f"  {tier_name(tier)}")
        print(
            f"    URL数: {info['url_count']:>5}条 ({info['percent']:.1f}%)  |  涵盖频道: {info['channel_count']}个"
        )
        print()


def print_samples(channels: list[dict]) -> None:
    print("\n=== Tier1官方CDN频道样本（前20个）===")

    tier1_chs = [ch for ch in channels if any(t == 1 for t in ch.get("url_tiers", []))]

    print(f"含Tier1 URL的频道共: {len(tier1_chs)} 个\n")

    for ch in tier1_chs[:20]:
        tier1_urls = [u for u, t in zip(ch["urls"], ch["url_tiers"]) if t == 1]
        print(f"  {ch['name']}: {len(tier1_urls)}条Tier1 URL")
        for u in tier1_urls[:1]:
            print(f"    {u[:90]}")

    only_tier4 = [
        ch
        for ch in channels
        if ch.get("urls") and all(t == 4 for t in ch.get("url_tiers", []))
    ]

    print(f"\n=== 仅有Tier4 IP直连的频道（最脆弱）===")
    print(f"仅IP直连的频道: {len(only_tier4)} 个")
    for ch in only_tier4[:10]:
        print(f"  {ch['name']}: {ch['urls'][0][:80]}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    input_path = config.output_path("channels_tested.json")
    output_file = config.output_path("channels_tiered.json")

    print("=== 重排URL顺序：Tier越低排越前 ===")
    print(f"输入: {input_path}")
    print(f"输出: {output_file}")

    new_channels = process_channels(input_path, output_file)

    print_summary(new_channels)
    print(f"=== 重排后输出 {output_file} ===")
    print(f"  已保存 {len(new_channels)} 个频道")
    print(f"  文件: {output_file}")

    print_samples(new_channels)


if __name__ == "__main__":
    main()
