import json
import re
import sys
import asyncio
import aiohttp
import time

import config

HEADERS = config.HEADERS

# ── 第一步：提取所有 cztv/cztvcloud URL ──

# 匹配两种格式：
# 1. /channels/lantian/[CODE]/[RES].m3u8   (cztvcloud地方台)
# 2. /channels/lantian/channel[N]/[RES].m3u8 (cztv省级台)
CZTV_LOCAL_RE = re.compile(
    r"/channels/lantian/([A-Za-z0-9_]+)/(\d+p)\.m3u8", re.IGNORECASE
)
CZTV_PROV_RE = re.compile(
    r"/channels/lantian/(channel\d+)/(\d+p)\.m3u8", re.IGNORECASE
)


def load_channels():
    with open(config.output_path("channels_tiered.json"), encoding="utf-8") as f:
        return json.load(f)


def extract_cztv_codes(channels: list[dict]) -> tuple[dict, dict]:
    known_local = {}  # code → (频道名, url, 最高分辨率)
    known_prov = {}  # channel_N → (频道名, url)

    for ch in channels:
        name = ch["name"]
        for url in ch.get("urls", []):
            if "cztv" not in url.lower() and "cztvcloud" not in url.lower():
                continue

            m = CZTV_PROV_RE.search(url)
            if m:
                code = m.group(1)
                if code not in known_prov:
                    known_prov[code] = (name, url)
                continue

            m = CZTV_LOCAL_RE.search(url)
            if m:
                code = m.group(1)
                res = m.group(2)
                if code not in known_local:
                    known_local[code] = (name, url, res)
                continue

    return known_local, known_prov


def collect_hotel_ips(channels: list[dict]) -> set[str]:
    hotel_ips = set()

    for ch in channels:
        for url in ch.get("urls", []):
            m = re.match(r"http://(\d+\.\d+\.\d+\.\d+):(\d+)/hls/(\d+)/", url)
            if m:
                ip = m.group(1)
                port = m.group(2)
                hotel_ips.add(f"{ip}:{port}")

    return hotel_ips


# ── 第二步：构造探测列表 ──

# cztvcloud 地方台的代码规律：SX+城市拼音+数字
# 例如：SXyuyao1, SXsuichang1, SXyuyao2
# 我们从已知代码里提取前缀规律，然后猜测未收录的

# 浙江各地已知前缀 + 可能的变体
# 根据已有数据推断的探测列表
PROBE_LOCAL_CODES = [
    # 已知城市的备用线路
    "SXyuyao1",
    "SXyuyao2",
    "SXyuyao3",
    "SXsuichang1",
    "SXsuichang2",
    "SXqingtian1",
    "SXqingtian2",
    "SXshaoxing1",
    "SXshaoxing2",
    # 可能未收录的城市
    "SXhangzhou1",
    "SXhangzhou2",
    "SXningbo1",
    "SXningbo2",
    "SXwenzhou1",
    "SXwenzhou2",
    "SXjiaxing1",
    "SXjiaxing2",
    "SXhuzhou1",
    "SXhuzhou2",
    "SXzhoushan1",
    "SXzhoushan2",
    "SXtaizhou1",
    "SXtaizhou2",
    "SXlishui1",
    "SXlishui2",
    "SXjinhua1",
    "SXjinhua2",
    "SXquzhou1",
    # 县级市
    "SXcixi1",
    "SXcixi2",
    "SXyiwu1",
    "SXyiwu2",
    "SXdongyang1",
    "SXpujiang1",
    "SXlanxi1",
]

# 省级台探测（channel001 到 channel030）
PROBE_PROV_CODES = [f"channel{str(i).zfill(3)}" for i in range(1, 31)]
PROBE_PROV_CODES += [f"channel{i}" for i in range(1, 31)]

RES_LIST = ["1080p", "720p", "360p"]


async def probe_url(session, url, sem):
    async with sem:
        try:
            timeout = aiohttp.ClientTimeout(total=5)
            t = time.monotonic()
            async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
                if resp.status == 200:
                    delay = int((time.monotonic() - t) * 1000)
                    return (url, delay)
        except Exception:
            pass
    return (url, None)


async def probe_cztv():
    # 构造所有探测URL

    probe_urls = []

    # 地方台
    bases = [
        "http://l.cztvcloud.com/channels/lantian/",
        "http://ali-m-l.cztv.com/channels/lantian/",
    ]

    for code in PROBE_LOCAL_CODES:
        for res in RES_LIST:
            for base in bases:
                probe_urls.append(f"{base}{code}/{res}.m3u8")

    # 省级台
    prov_bases = [
        "http://ali-m-l.cztv.com/channels/lantian/",
        "https://ali-m-l.cztv.com/channels/lantian/",
    ]

    for code in PROBE_PROV_CODES:
        for res in RES_LIST:
            for base in prov_bases:
                probe_urls.append(f"{base}{code}/{res}.m3u8")

    print(f"探测URL总数: {len(probe_urls)}")

    sem = asyncio.Semaphore(50)
    connector = aiohttp.TCPConnector(limit=50)
    results = []

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [probe_url(session, u, sem) for u in probe_urls]
        raw = await asyncio.gather(*tasks)

    results = [(u, d) for u, d in raw if d is not None]

    print(f"发现存活URL: {len(results)} 个")
    for url, delay in sorted(results, key=lambda x: x[1]):
        print(f"  ✓ {delay}ms  {url}")

    return results


# ── 第三步：探测酒店IPTV频道列表 ──


async def probe_hotel(hotel_ip):
    """探测酒店IPTV系统的频道列表，最多测试hls/1到hls/100"""
    results = []

    sem = asyncio.Semaphore(30)
    connector = aiohttp.TCPConnector(limit=30)

    async def test_ch(session, ch_id):
        url = f"http://{hotel_ip}/hls/{ch_id}/index.m3u8"
        async with sem:
            try:
                timeout = aiohttp.ClientTimeout(total=3)
                async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
                    if resp.status == 200:
                        return (ch_id, url)
            except Exception:
                pass
        return None

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [test_ch(session, i) for i in range(1, 101)]
        raw = await asyncio.gather(*tasks)

    results = [r for r in raw if r]
    return results


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    start_time = time.monotonic()

    channels = load_channels()
    known_local, known_prov = extract_cztv_codes(channels)

    print("=== 第一步：提取浙江广电CDN频道代码 ===\n")
    print(f"已知地方台代码（cztvcloud格式）: {len(known_local)} 个")
    for code, (name, url, res) in sorted(known_local.items()):
        print(f"  {code:<20} → {name} ({res})")

    print(f"\n已知省级台代码（cztv格式）: {len(known_prov)} 个")
    for code, (name, url) in sorted(known_prov.items()):
        print(f"  {code:<15} → {name}")

    print("\n=== 第二步：探测未收录的cztvcloud频道 ===")
    cztv_results = await probe_cztv()

    print("\n=== 第三步：探测酒店IPTV系统 ===")
    hotel_ips = collect_hotel_ips(channels)
    print(f"发现酒店IPTV系统: {len(hotel_ips)} 个")
    for h in sorted(hotel_ips):
        print(f"  {h}")

    print("\n--- 酒店IPTV探测 ---")
    hotel_results = {}

    for hotel_ip in sorted(hotel_ips):
        print(f"\n探测 {hotel_ip} 的频道列表...")
        hotel_chs = await probe_hotel(hotel_ip)
        hotel_results[hotel_ip] = hotel_chs
        print(f"  发现 {len(hotel_chs)} 个存活频道:")
        for ch_id, url in hotel_chs[:20]:
            print(f"    hls/{ch_id}: {url}")

    elapsed = int((time.monotonic() - start_time) * 1000)
    print(f"\n=== 完成，总耗时: {elapsed}ms ===")

    output = {
        "known_local": {
            code: {"name": name, "url": url, "res": res}
            for code, (name, url, res) in sorted(known_local.items())
        },
        "known_prov": {
            code: {"name": name, "url": url}
            for code, (name, url) in sorted(known_prov.items())
        },
        "cztv_results": [
            {"url": url, "delay_ms": delay} for url, delay in sorted(cztv_results, key=lambda x: x[1])
        ],
        "hotel_ips": sorted(hotel_ips),
        "hotel_results": {
            ip: [
                {"ch_id": ch_id, "url": url}
                for ch_id, url in sorted(hotel_chs, key=lambda x: x[0])
            ]
            for ip, hotel_chs in hotel_results.items()
        },
        "hotel_counts": {ip: len(hotel_chs) for ip, hotel_chs in hotel_results.items()},
        "elapsed_ms": elapsed,
    }

    output_path = config.output_path("cztv_explorer_results.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"已保存结果: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
