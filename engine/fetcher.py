# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 设计原则：
# - 直连GitHub，不用镜像（本机直连1-2秒可达）
# - 串行分批抓取，每批4个，批间无间隔
# - 单个超时90秒（最大文件3.6MB约需60秒）
# - 7个已确认死链不再尝试
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import sys
sys.stdout.reconfigure(encoding='utf-8')

import asyncio
import aiohttp
import time

import config


async def fetch_one(session: aiohttp.ClientSession, url: str, idx: int, total: int) -> tuple[str, str | None]:
    short = url.split("githubusercontent.com/")[1]
    t = time.time()
    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with session.get(url, timeout=timeout, headers=config.HEADERS) as resp:
            if resp.status == 200:
                text = await resp.text(encoding='utf-8', errors='ignore')
                elapsed = int((time.time() - t) * 1000)
                size = len(text.encode())
                print(f"[{idx:02d}/{total}] ✓ {elapsed}ms | {size:,}字节 | {short}")
                return (url, text)
            else:
                elapsed = int((time.time() - t) * 1000)
                print(f"[{idx:02d}/{total}] ✗ HTTP {resp.status} | {elapsed}ms | {short}")
                return (url, None)
    except Exception as e:
        elapsed = int((time.time() - t) * 1000)
        print(f"[{idx:02d}/{total}] ✗ {type(e).__name__} | {elapsed}ms | {short}")
        return (url, None)


async def main():
    print("=== IPTV源抓取开始（直连，批量4并发，90秒超时）===")
    print(f"共 {len(config.SOURCE_LIST)} 个源\n")

    # 分批：每批最多4个并发
    BATCH_SIZE = 4
    all_results = []
    connector = aiohttp.TCPConnector(limit=4, limit_per_host=2)
    async with aiohttp.ClientSession(connector=connector) as session:
        for batch_start in range(0, len(config.SOURCE_LIST), BATCH_SIZE):
            batch = config.SOURCE_LIST[batch_start:batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            total_batches = (len(config.SOURCE_LIST) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"--- 第 {batch_num}/{total_batches} 批（{len(batch)}个）---")
            tasks = [
                fetch_one(session, url, batch_start + i + 1, len(config.SOURCE_LIST))
                for i, url in enumerate(batch)
            ]
            batch_results = await asyncio.gather(*tasks)
            all_results.extend(batch_results)

    # 统计
    success = [(url, text) for url, text in all_results if text]
    failed  = [url for url, text in all_results if not text]
    raw_text = "\n".join(text for _, text in success)
    total_lines = len(raw_text.splitlines())
    total_size  = sum(len(t.encode()) for _, t in success)

    print(f"""
============ 最终运行结果 ============
抓取成功 : {len(success)} / 共 {len(config.SOURCE_LIST)}
合并行数 : {total_lines:,} 行
合并大小 : {total_size:,} 字节 ({total_size/1024/1024:.1f} MB)
失败的源：""")
    for url in failed:
        print(f"  ✗ {url.split('githubusercontent.com/')[1]}")
    print(f"""
前10行内容预览：""")
    for i, line in enumerate(raw_text.splitlines()[:10], 1):
        print(f"  {i}: {line}")
    print("=====================================")


if __name__ == "__main__":
    asyncio.run(main())
