import sys
sys.stdout.reconfigure(encoding='utf-8')

import re
import asyncio
import aiohttp
import time

import config

from normalizer import normalize


def parse_m3u(text: str) -> list[dict]:
    """
    解析m3u/m3u8格式文本，返回频道列表。
    每个频道是一个dict：
    {
        "name":  频道名（清洗后）,
        "url":   播放地址,
        "group": group-title值（无则为"未分类"）,
        "raw_name": 原始名称（未清洗）
    }
    解析规则：
    1. 同时支持两种格式：
       格式A（标准m3u）：
       #EXTINF:-1 group-title="央视频道",CCTV-1
       http://xxx.xxx/stream.m3u8
       格式B（txt格式，逗号分隔）：
       CCTV-1,http://xxx.xxx/stream.m3u8
    2. 名称清洗（按顺序）：
       - 去除以下标签（不区分大小写）：
         [HD] [FHD] [4K] [SD] [CN] [Backup]
         HD FHD 4K SD （独立出现时）
         「 」『 』【 】
       - 去除多余空格，strip()
    3. URL过滤：
       - 必须以 http:// 或 https:// 或 rtmp:// 开头
       - 不含以下黑名单关键字（忽略大小写）：
         catvod, fongmi, epg.pw, ok.bkpcp.top
    4. 返回列表，保留所有字段
    """
    channels = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 格式A：#EXTINF行
        if line.startswith("#EXTINF"):
            name = ""
            group = "未分类"
            # 提取 group-title
            gm = re.search(r'group-title="([^"]*)"', line)
            if gm:
                group = gm.group(1).strip() or "未分类"
            # 提取频道名（逗号后面的部分）
            cm = re.search(r',(.+)$', line)
            if cm:
                name = cm.group(1).strip()
            # 下一行是URL
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                url = lines[i].strip()
                if _valid_url(url):
                    channels.append({
                        "name": normalize(_clean_name(name)),
                        "url": url,
                        "group": group,
                        "raw_name": name,
                    })
        # 格式B：name,url
        elif "," in line and not line.startswith("#"):
            parts = line.split(",", 1)
            if len(parts) == 2:
                name = parts[0].strip()
                url = parts[1].strip()
                if _valid_url(url) and name:
                    channels.append({
                        "name": normalize(_clean_name(name)),
                        "url": url,
                        "group": "未分类",
                        "raw_name": name,
                    })
        i += 1
    return channels


def _valid_url(url: str) -> bool:
    if not url:
        return False
    url_lower = url.lower()
    if not any(url_lower.startswith(p)
               for p in ["http://", "https://", "rtmp://"]):
        return False
    blacklist = ["catvod", "fongmi", "epg.pw", "ok.bkpcp.top"]
    return not any(b in url_lower for b in blacklist)


def _clean_name(name: str) -> str:
    # 去除方括号标签
    name = re.sub(
        r'\[(HD|FHD|4K|SD|CN|Backup|IPv6|ipv6)\]',
        '', name, flags=re.IGNORECASE)
    # 去除独立标签
    name = re.sub(
        r'\b(HD|FHD|4K|SD)\b', '', name, flags=re.IGNORECASE)
    # 去除中文括号
    name = re.sub(r'[「」『』【】［］]', '', name)
    # 合并多余空格
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def deduplicate(channels: list[dict]) -> dict:
    """
    去重逻辑：
    1. 按清洗后的 name 分组
    2. 每个name下的所有url去重（完全相同的url只保留一条）
    3. 返回 dict：{clean_name: [url1, url2, ...]}
    """
    result = {}
    for ch in channels:
        name = ch["name"]
        url = ch["url"]
        if not name:
            continue
        if name not in result:
            result[name] = []
        if url not in result[name]:
            result[name].append(url)
    return result


async def fetch_all() -> str:
    """抓取所有源，返回合并后的原始文本"""

    async def fetch_one(session, url):
        try:
            timeout = aiohttp.ClientTimeout(total=90)
            async with session.get(
                    url, timeout=timeout, headers=config.HEADERS) as resp:
                if resp.status == 200:
                    return await resp.text(
                        encoding='utf-8', errors='ignore')
        except Exception:
            pass
        return ""

    connector = aiohttp.TCPConnector(limit=4, limit_per_host=2)
    async with aiohttp.ClientSession(connector=connector) as session:
        BATCH = 4
        texts = []
        for i in range(0, len(config.SOURCE_LIST), BATCH):
            batch = config.SOURCE_LIST[i:i+BATCH]
            results = await asyncio.gather(
                *[fetch_one(session, u) for u in batch])
            texts.extend(results)
            print(f"  批次 {i//BATCH+1} 完成，"
                  f"本批成功 {sum(1 for r in results if r)}/{len(batch)}")
    return "\n".join(t for t in texts if t)


async def main():
    print("=== 第5课：m3u解析与去重统计 ===\n")
    t_start = time.time()

    print("【第一步】抓取24个源...")
    raw_text = await fetch_all()
    raw_lines = len(raw_text.splitlines())
    print(f"  原始合并行数: {raw_lines:,} 行\n")

    print("【第二步】解析m3u格式...")
    channels = parse_m3u(raw_text)
    print(f"  解析出频道条目: {len(channels):,} 条\n")

    print("【第三步】去重统计...")
    deduped = deduplicate(channels)
    total_unique = len(deduped)
    total_urls   = sum(len(v) for v in deduped.values())
    top20 = sorted(deduped.items(), key=lambda x: -len(x[1]))[:20]
    multi_url    = {k: v for k, v in deduped.items() if len(v) > 1}
    # 按URL数量排序，找出备用线路最多的频道
    top_multi = sorted(
        multi_url.items(), key=lambda x: -len(x[1]))[:20]
    # URL数量分布
    dist = {}
    for urls in deduped.values():
        n = len(urls)
        dist[n] = dist.get(n, 0) + 1

    t_elapsed = time.time() - t_start

    print(f"""
============ 第5课统计结果 ============
原始行数         : {raw_lines:,} 行
解析频道条目总数  : {len(channels):,} 条
去重后唯一频道数  : {total_unique:,} 个
去重后URL总数    : {total_urls:,} 条
有多条备用线路    : {len(multi_url):,} 个频道
URL数量分布：""")
    for n in sorted(dist.keys()):
        bar = "█" * min(n * 3, 30)
        print(f"  {n}条线路: {dist[n]:>5} 个频道  {bar}")

    print("""
============ 第6课标准化效果 ============
标准化前唯一频道数 : 4,091 个（parser.py第5课结果）
标准化后唯一频道数 : {total_unique:,} 个
合并减少频道数     : {reduced:,} 个
去重后URL总数      : {total_urls:,} 条
标准化后URL最多的TOP20频道：""".format(
        total_unique=total_unique,
        reduced=4091 - total_unique,
        total_urls=total_urls))
    for name, urls in top20:
        print(f"  [{len(urls):>4}条] {name}")
    print("=========================================")

    print("\n备用线路最多的TOP20频道：")
    for name, urls in top_multi:
        print(f"  [{len(urls)}条] {name}")
        for u in urls[:2]:  # 每个频道只展示前2条URL
            print(f"    {u[:80]}")
    print(f"\n总耗时: {t_elapsed:.1f} 秒")
    print("=======================================")


if __name__ == "__main__":
    asyncio.run(main())
