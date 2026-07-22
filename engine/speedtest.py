# 设计原则
# - 每个频道最多保留20条存活URL，达到即停止测该频道
# - 测速指标：首包延迟（ms），不下载完整流
# - 超时：3秒
# - 并发：100线程（测速是纯IO，不下载内容）
# - 输出：方案C格式，每条URL带延迟标注

import sys

sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import aiohttp
import time
import json
import os
import re
from collections import defaultdict

import config

from normalizer import normalize
from parser import _valid_url, _clean_name

MAX_URLS_PER_CHANNEL = 20  # 每频道最多保留存活URL数
TIMEOUT_SEC = 3  # 测速超时
CONCURRENCY = 100  # 并发数


def parse_m3u(text: str) -> list[dict]:
    channels = []
    lines = text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            name, group = "", "未分类"
            gm = re.search(r'group-title="([^"]*)"', line)
            if gm:
                group = gm.group(1).strip() or "未分类"
            cm = re.search(r",(.+)$", line)
            if cm:
                name = cm.group(1).strip()

            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                url = lines[i].strip()
                if _valid_url(url):
                    channels.append(
                        {
                            "name": normalize(_clean_name(name)),
                            "url": url,
                            "group": group,
                        }
                    )
        elif "," in line and not line.startswith("#"):
            parts = line.split(",", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                url = parts[1].strip()
                if _valid_url(url) and name:
                    channels.append(
                        {
                            "name": normalize(_clean_name(name)),
                            "url": url,
                            "group": "未分类",
                        }
                    )
        i += 1
    return channels


async def fetch_all() -> str:
    async def fetch_one(session, url):
        try:
            timeout = aiohttp.ClientTimeout(total=90)
            async with session.get(url, timeout=timeout, headers=config.HEADERS) as resp:
                if resp.status == 200:
                    return await resp.text(encoding="utf-8", errors="ignore")
        except Exception:
            pass
        return ""

    connector = aiohttp.TCPConnector(limit=4, limit_per_host=2)
    async with aiohttp.ClientSession(connector=connector) as session:
        results = []
        for i in range(0, len(config.SOURCE_LIST), 4):
            batch = config.SOURCE_LIST[i : i + 4]
            texts = await asyncio.gather(*[fetch_one(session, u) for u in batch])
            results.extend(texts)
        return "\n".join(t for t in results if t)


async def test_url(session: aiohttp.ClientSession, url: str) -> float | None:
    """
    四步检测：

    - 步骤1：跳过非HTTP协议
    - 步骤2：发请求，allow_redirects=True（跟随重定向）
    - 步骤3：检查最终落地URL是否命中黑名单
    - 步骤4：读取前128字节，检查内容是否命中内容黑名单
    - 全部通过才返回延迟，任何一步失败返回None
    """
    # 步骤1：跳过组播/RTSP协议
    if url.startswith(("rtp://", "udp://", "rtsp://")):
        return None

    # URL黑名单（这些域名出现在最终落地URL里，判定为假台）
    URL_BLACKLIST = [
        "epg.pw",
        "freetv.fun",
        "catvod",
        "fongmi",
        "ok.bkpcp.top",
        "livednow.com",
        "diyp.tv",
        "zhuomiantv.cn",
        "hitv.com",
        "bdp.tv",
    ]

    # 内容黑名单（出现在响应体前128字节里，判定为假台）
    # 这些是广告/错误页面的特征字符串
    CONTENT_BLACKLIST = [
        b"<html",
        b"<!DOCTYPE",
        b"Access Denied",
        b"403 Forbidden",
        b"Not Found",
        b"epg.pw",
        b"freetv",
    ]

    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC, connect=TIMEOUT_SEC)
        t = time.monotonic()
        async with session.get(
            url,
            timeout=timeout,
            headers=config.HEADERS,
            allow_redirects=True,  # 跟随302重定向
            max_redirects=5,  # 最多跟5跳
        ) as resp:
            # 步骤2：状态码必须是200或206
            if resp.status not in (200, 206):
                return None

            # 步骤3：检查最终落地URL
            final_url = str(resp.url).lower()
            for bad in URL_BLACKLIST:
                if bad in final_url:
                    return None  # 落地到黑名单域名，判定假台

            # 步骤4：读取前128字节检查内容
            chunk = await resp.content.read(128)
            for bad_bytes in CONTENT_BLACKLIST:
                if bad_bytes in chunk:
                    return None  # 内容是HTML/错误页，判定假台

            # 全部通过，记录延迟
            delay = round((time.monotonic() - t) * 1000, 1)
            return delay
    except Exception:
        return None


async def verify_ts_slice(session: aiohttp.ClientSession, m3u8_url: str) -> bool:
    """
    TS切片深度验证：

    1. 下载M3U8内容
    2. 提取第一个媒体切片URL（.ts 或无扩展名的切片）
    3. 请求该切片前10KB，验证真实可播

    返回 True=真实可播 / False=假台或无法验证

    特殊处理：
    - 如果M3U8内容里第一个非注释行是另一个.m3u8（多级M3U8），
      则递归获取该子M3U8，再提取切片
    - 递归最多1层（防止死循环）
    - 超时10秒
    - 失败一律返回True（宁可放行，不误杀）

    原因：TS验证是加分项，不是硬性门槛
    """

    async def _get_first_segment(url: str, depth: int = 0):
        if depth > 1:
            return None

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.get(url, timeout=timeout, headers=config.HEADERS) as resp:
                if resp.status != 200:
                    return None

                text = await resp.text(errors="ignore")

            base = url.rsplit("/", 1)[0] + "/"
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # 构造完整URL
                seg_url = line if line.startswith("http") else base + line

                # 如果是子M3U8，递归处理
                if ".m3u8" in seg_url.lower():
                    return await _get_first_segment(seg_url, depth + 1)

                # 是媒体切片
                return seg_url
        except Exception:
            return None

        return None

    try:
        seg_url = await _get_first_segment(m3u8_url)
        if not seg_url:
            return True  # 找不到切片，放行（不误杀）

        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(seg_url, timeout=timeout, headers=config.HEADERS) as resp:
            if resp.status == 200:
                await resp.content.read(10240)  # 读10KB验证
                return True
            elif resp.status in (403, 401):
                return False  # 明确拒绝，判定假台
            else:
                return True  # 其他状态码，放行
    except Exception:
        return True  # 异常放行，不误杀


async def test_channel(
    session: aiohttp.ClientSession,
    name: str,
    urls: list[str],
    semaphore: asyncio.Semaphore,
) -> tuple[str, list[dict]]:
    """
    对一个频道的所有URL并发测速。

    返回 (频道名, [{url, delay_ms}, ...])
    结果按延迟从低到高排序，最多保留 MAX_URLS_PER_CHANNEL 条存活URL。
    """

    async def test_one(url):
        async with semaphore:
            delay = await test_url(session, url)
            return {"url": url, "delay_ms": delay}

    results = await asyncio.gather(*[test_one(u) for u in urls])
    alive = [r for r in results if r["delay_ms"] is not None]

    # TS切片深度验证（过滤403假台）
    verified = []
    for r in alive:
        ts_ok = await verify_ts_slice(session, r["url"])
        if ts_ok:
            verified.append(r)
    alive = verified

    alive.sort(key=lambda x: x["delay_ms"])
    return name, alive[:MAX_URLS_PER_CHANNEL]


def write_scheme_c_m3u(path: str, alive_channels: dict[str, list[dict]]) -> None:
    """
    输出方案C格式：每条URL带延迟标注。
    格式示例：
    #EXTINF:-1 group-title="CCTV-1",CCTV-1 $123.4ms
    http://example.com/live.m3u8
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, urls in alive_channels.items():
            for item in urls:
                delay = item["delay_ms"]
                url = item["url"]
                f.write(f'#EXTINF:-1 group-title="{name}",{name} ${delay:.0f}ms\n')
                f.write(f"{url}\n")


async def main():
    print("=== 第7课：并发测速 ===\n")

    # 第一步：抓取并解析
    print("【第一步】抓取24个源...")
    t0 = time.monotonic()
    raw = await fetch_all()
    print(f"  抓取完成，用时 {time.monotonic() - t0:.1f}s\n")

    print("【第二步】解析并标准化...")
    channels = parse_m3u(raw)

    # 按频道名分组
    grouped: dict[str, list[str]] = defaultdict(list)
    for ch in channels:
        url = ch["url"]
        name = ch["name"]
        if url not in grouped[name]:
            grouped[name].append(url)

    total_channels = len(grouped)
    total_urls = sum(len(v) for v in grouped.values())
    print(f"  唯一频道数: {total_channels:,}")
    print(f"  待测URL总数: {total_urls:,}\n")

    # 第三步：并发测速
    print(f"【第三步】并发测速（{CONCURRENCY}并发，{TIMEOUT_SEC}秒超时）...")
    t1 = time.monotonic()
    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=5)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            test_channel(session, name, urls, semaphore)
            for name, urls in grouped.items()
        ]

        # 分批执行，每批200个频道，打印进度
        BATCH = 200
        all_results = {}
        for i in range(0, len(tasks), BATCH):
            batch = tasks[i : i + BATCH]
            batch_results = await asyncio.gather(*batch)
            for name, alive in batch_results:
                all_results[name] = alive
            done = min(i + BATCH, len(tasks))
            elapsed = time.monotonic() - t1
            print(f"  进度: {done}/{len(tasks)} 频道 | 用时 {elapsed:.0f}s")

    elapsed_total = time.monotonic() - t1

    # 第四步：统计
    alive_channels = {k: v for k, v in all_results.items() if v}
    dead_channels = {k: v for k, v in all_results.items() if not v}
    total_alive_urls = sum(len(v) for v in alive_channels.values())

    # 延迟分布
    all_delays = [r["delay_ms"] for v in alive_channels.values() for r in v]
    avg_delay = sum(all_delays) / len(all_delays) if all_delays else 0
    fast = sum(1 for d in all_delays if d < 500)
    medium = sum(1 for d in all_delays if 500 <= d < 1500)
    slow = sum(1 for d in all_delays if d >= 1500)

    # 存活URL最多的TOP20
    top20 = sorted(alive_channels.items(), key=lambda x: -len(x[1]))[:20]

    print(
        f"""

============ 第7课测速结果 ============
测速用时        : {elapsed_total:.0f} 秒
待测频道总数    : {total_channels:,} 个
存活频道数      : {len(alive_channels):,} 个
全死频道数      : {len(dead_channels):,} 个
存活URL总数     : {total_alive_urls:,} 条
平均延迟        : {avg_delay:.0f} ms
延迟分布：
<500ms（快）  : {fast:,} 条
500-1500ms（中）: {medium:,} 条
>1500ms（慢） : {slow:,} 条
存活URL最多的TOP20频道："""
    )

    for name, urls in top20:
        delays = [u["delay_ms"] for u in urls]
        min_d = min(delays)
        print(f"  [{len(urls):>3}条 | 最低{min_d:.0f}ms] {name}")

    print(
        f"""

全死频道数量    : {len(dead_channels):,} 个
全死频道示例（前10个）："""
    )
    for name in list(dead_channels.keys())[:10]:
        print(f"  ✗ {name}")

    # 保存结果到 JSON
    output = []
    for name, urls in alive_channels.items():
        output.append(
            {
                "name": name,
                "urls": [u["url"] for u in urls],
                "delays": [u["delay_ms"] for u in urls],
                "min_delay_ms": min(u["delay_ms"] for u in urls),
            }
        )
    output.sort(key=lambda x: x["min_delay_ms"])

    out_path = config.output_path("channels_tested.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # 同时保存方案C格式M3U：每条URL带延迟标注
    scheme_c_path = config.output_path("channels_tested.m3u")
    write_scheme_c_m3u(scheme_c_path, alive_channels)

    print(
        f"""

已保存到: {out_path}
文件大小: {os.path.getsize(out_path):,} 字节
方案C输出: {scheme_c_path}
=========================================="""
    )


if __name__ == "__main__":
    asyncio.run(main())
