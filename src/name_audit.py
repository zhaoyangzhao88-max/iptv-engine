import sys

sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import aiohttp
import re
from collections import defaultdict

import config

SOURCE_LIST = config.SOURCE_LIST
HEADERS = config.HEADERS


def parse_names(text: str) -> list[str]:
    """只提取频道名，不管URL"""
    names = []
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            m = re.search(r",(.+)$", line)
            if m:
                names.append(m.group(1).strip())
        elif "," in line and not line.startswith("#"):
            parts = line.split(",", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                url = parts[1].strip()
                if url.startswith("http") and name:
                    names.append(name)
        i += 1

    return names


async def fetch_all() -> str:
    async def fetch_one(session, url):
        try:
            timeout = aiohttp.ClientTimeout(total=90)
            async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
                if resp.status == 200:
                    return await resp.text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
        return ""

    connector = aiohttp.TCPConnector(limit=4, limit_per_host=2)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = []
        for i in range(0, len(SOURCE_LIST), 4):
            batch = SOURCE_LIST[i : i + 4]
            texts = await asyncio.gather(*[fetch_one(session, u) for u in batch])
            results.extend(texts)

        return "\n".join(t for t in results if t)


async def main():
    print("=== 第6课第一步：频道名变体侦察 ===\n")
    print("抓取中...")
    raw = await fetch_all()
    all_names = parse_names(raw)
    print(f"原始名称总数: {len(all_names):,}\n")

    # 按关键词分组，找出变体
    groups = {
        "CCTV系": [],
        "卫视系": [],
        "凤凰系": [],
        "TVB/香港系": [],
        "台湾系": [],
        "体育系": [],
        "新闻系": [],
    }

    for name in all_names:
        if "CCTV" in name or "央视" in name or "中央" in name:
            groups["CCTV系"].append(name)
        elif "卫视" in name:
            groups["卫视系"].append(name)
        elif "凤凰" in name:
            groups["凤凰系"].append(name)
        elif "TVB" in name or "翡翠" in name or "明珠" in name:
            groups["TVB/香港系"].append(name)
        elif "台视" in name or "中视" in name or "华视" in name or "民视" in name or "TVBS" in name:
            groups["台湾系"].append(name)
        elif "体育" in name or "足球" in name or "NBA" in name:
            groups["体育系"].append(name)
        elif "新闻" in name or "资讯" in name:
            groups["新闻系"].append(name)

    # 对每组去重并排序，展示变体
    for group_name, names in groups.items():
        unique = sorted(set(names))
        print(f"{'=' * 50}")
        print(f"【{group_name}】共 {len(unique)} 个变体名称")
        print(f"{'=' * 50}")
        for n in unique:
            print(f"  {n}")
        print()

    # 额外：找出所有包含数字1-17的CCTV变体
    print("=" * 50)
    print("【CCTV频道编号变体汇总】")
    print("=" * 50)
    for ch_num in range(1, 18):
        variants = set()
        for name in all_names:
            nu = name.upper().replace(" ", "").replace("-", "")
            if f"CCTV{ch_num}" in nu or f"央视{ch_num}" in nu or f"中央{ch_num}" in nu:
                variants.add(name)
        if variants:
            print(f"\n  CCTV{ch_num} ({len(variants)}个变体):")
            for v in sorted(variants):
                print(f"    · {v}")

    print("\n=== 侦察完毕 ===")


if __name__ == "__main__":
    asyncio.run(main())
