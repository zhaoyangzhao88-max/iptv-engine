import json
import re
import sys
import asyncio
import aiohttp
import time
from collections import defaultdict
from urllib.parse import urlparse

import config

HEADERS = config.HEADERS

# ── 第一步：提取PLTV频道ID映射 ──
# PLTV URL格式：
# http://[IP]/[可选域名前缀]/PLTV/[服务商码]/224/[频道ID]/[文件名]
PLTV_RE = re.compile(r"https?://[^/]+(?:/[^/]+)?/PLTV/(\d+)/224/(\d+)/\S+")


def load_channels():
    with open(config.output_path("channels_tested.json"), encoding="utf-8") as f:
        return json.load(f)


def extract_pltv_channels(channels: list[dict]):
    channel_ids = defaultdict(set)  # 频道名 → {(服务商码, 频道ID)}
    cdn_nodes = defaultdict(set)  # IP/节点 → {服务商码集合}
    service_codes = set()

    for ch in channels:
        name = ch["name"]
        for url in ch.get("urls", []):
            m = PLTV_RE.search(url)
            if m:
                service_code = m.group(1)
                channel_id = m.group(2)
                channel_ids[name].add((service_code, channel_id))
                service_codes.add(service_code)

                # 提取IP（含端口）
                parsed = urlparse(url)
                cdn_nodes[parsed.netloc].add(service_code)

    return channel_ids, cdn_nodes, service_codes


def print_channel_id_mapping(channel_ids):
    print("=== 频道ID映射（前30个）===")
    for name, ids in list(channel_ids.items())[:30]:
        for sc, cid in ids:
            print(f"  {name}: PLTV/{sc}/224/{cid}/")
    print()


async def probe_node(session, netloc, service_code, channel_id):
    """用一个已知的频道ID探测节点是否存活"""
    url = f"http://{netloc}/PLTV/{service_code}/224/{channel_id}/index.m3u8"
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        t = time.monotonic()
        async with session.get(url, timeout=timeout, headers=HEADERS) as resp:
            if resp.status in (200, 206):
                delay = int((time.monotonic() - t) * 1000)
                return (netloc, True, delay)
    except Exception:
        pass
    return (netloc, False, 0)


async def probe_all_nodes(channel_ids, cdn_nodes):
    alive_nodes = []
    dead_nodes = []

    # 为每个节点选一个探测用的频道ID
    probe_tasks = []
    for netloc, scodes in cdn_nodes.items():
        sc = next(iter(scodes))

        # 找一个该服务商码下的频道ID
        test_ch_id = None
        for name, ids in channel_ids.items():
            for scode, cid in ids:
                if scode == sc:
                    test_ch_id = (sc, cid)
                    break
            if test_ch_id:
                break

        if test_ch_id:
            probe_tasks.append((netloc, test_ch_id[0], test_ch_id[1]))

    print(f"共 {len(probe_tasks)} 个节点待探测...\n")
    sem = asyncio.Semaphore(50)

    async def probe_with_sem(session, netloc, sc, cid):
        async with sem:
            return await probe_node(session, netloc, sc, cid)

    connector = aiohttp.TCPConnector(limit=50)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = await asyncio.gather(
            *[probe_with_sem(session, n, s, c) for n, s, c in probe_tasks]
        )

    for netloc, alive, delay in results:
        if alive:
            alive_nodes.append((netloc, delay))
            print(f"  ✓ {netloc} ({delay}ms)")
        else:
            dead_nodes.append(netloc)

    print(f"\n存活节点: {len(alive_nodes)} 个")
    print(f"死亡节点: {len(dead_nodes)} 个")
    return alive_nodes


def generate_new_channels(channel_ids, cdn_nodes, alive_nodes):
    print("\n=== 生成新有效URL ===")
    new_channels = []
    alive_netlocs = [n for n, _ in sorted(alive_nodes, key=lambda x: x[1])]

    for name, ids in channel_ids.items():
        urls = []
        for sc, cid in ids:
            # 只用存活节点
            for netloc in alive_netlocs[:5]:  # 每频道最多5个节点
                if any(sc in scodes for node, scodes in cdn_nodes.items() if node == netloc):
                    url = f"http://{netloc}/PLTV/{sc}/224/{cid}/index.m3u8"
                    urls.append(url)
        if urls:
            new_channels.append(
                {
                    "name": name,
                    "urls": urls[:5],
                }
            )

    return new_channels


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    channels = load_channels()
    channel_ids, cdn_nodes, service_codes = extract_pltv_channels(channels)

    print(f"发现 PLTV 频道: {len(channel_ids)} 个")
    print(f"发现 CDN 节点: {len(cdn_nodes)} 个")
    print(f"服务商代码: {sorted(service_codes)}\n")

    print_channel_id_mapping(channel_ids)

    print("=== 探测CDN节点存活性 ===")
    alive_nodes = asyncio.run(probe_all_nodes(channel_ids, cdn_nodes))
    new_channels = generate_new_channels(channel_ids, cdn_nodes, alive_nodes)

    print(f"生成新频道数: {len(new_channels)} 个")
    print(f"生成新URL总数: {sum(len(c['urls']) for c in new_channels)} 条")

    # 保存
    output_path = config.output_path("cdn_channels.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(new_channels, f, ensure_ascii=False, indent=2)
    print(f"已保存到 {output_path}")

    # 输出示例
    print("\n前10个频道示例：")
    for ch in new_channels[:10]:
        print(f"  {ch['name']}: {len(ch['urls'])}条URL")
        for u in ch["urls"][:2]:
            print(f"    {u}")


if __name__ == "__main__":
    main()
