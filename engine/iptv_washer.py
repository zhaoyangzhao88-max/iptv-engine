"""
IPTV Washer v4.0 — 双轨制流验证器（挽救 500+ 连续媒体流）
================================================
从国内 IPv4 黄金源拉取 → 三级验证 → 频道标准化 → 分类输出

流程：
  Stage 1: 并发拉取九源 → M3U/TXT 解析 → MD5 去重
  Stage 2: Phase1(HEAD+#EXTM3U) → Phase2(双轨制：HLS分片 / FLV-TS连续流)
  Stage 3: 频道名标准化 → 央视/卫视/地方台/其他 → M3U+JSON 输出

用法：
  python src/iptv_washer.py
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import aiohttp
import hashlib
import json
import os
import re
import time
from collections import defaultdict

from config import HEADERS, OUTPUT_DIR
from normalizer import pre_clean, normalize, get_logo, get_epg_id
from normalizer import SATELLITE_ALIASES
from parser import parse_m3u


# ── 配置常量 ──────────────────────────────────

FETCH_SEMAPHORE = asyncio.Semaphore(10)     # 源拉取并发
VALIDATE_SEMAPHORE = asyncio.Semaphore(50)  # 验证并发

FETCH_TIMEOUT = aiohttp.ClientTimeout(total=10)    # 源列表拉取
HEAD_TIMEOUT = aiohttp.ClientTimeout(total=5)      # HEAD 验证
GET_TIMEOUT = aiohttp.ClientTimeout(total=5)       # GET 验证(前1024字节)
TS_SLICE_TIMEOUT = aiohttp.ClientTimeout(total=4)  # TS 切片下载(前10KB)

MAX_M3U_BYTES = 1024    # #EXTM3U 校验读取量
MAX_TS_BYTES = 10240    # TS 切片验证读取量

BATCH_SIZE = 100        # 分批处理大小

# ── 指数退避重试配置 ──────────────────────────
RETRY_MAX_ATTEMPTS = 3          # 最大尝试次数（首次 + 最多2次重试）
RETRY_BACKOFF_DELAYS = [1.5, 3.0]  # 第1次失败后等1.5s，第2次失败后等3s
RETRY_CONNECT_TIMEOUT = aiohttp.ClientTimeout(total=3)  # 单次连接+读取超时3秒

# ── 双轨验证常量 ────────────────────────────────
FLV_MAGIC = b'FLV'           # FLV 文件头魔数 (0x46 0x4C 0x56)
TS_SYNC_BYTE = 0x47          # MPEG-TS 同步字节
M3U8_MAGIC = b'#EXTM3U'      # M3U8/HLS 标识


# ── 公开订阅源池 ──────────────────────────────

SOURCES = [
    # ══════════════════════════════════════════════
    # 第一批：五大黄金 IPv4 源（已验证，v2.0 核心）
    # ══════════════════════════════════════════════
    # ── Guovin 日更验证 IPv4（酒店源/组播源筛选，100% 存活超清）──
    {
        "name": "Guovin/iptv-api",
        "url": "https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv4/result.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv4/result.m3u",
    },
    # ── suxuang 典藏卫视 IPv4 专线（全覆盖省级卫视高清）──
    {
        "name": "suxuang/myIPTV",
        "url": "https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u",
    },
    # ── vbskycn 极速可用 IPv4 源（数千频道，全套央视+卫视）──
    {
        "name": "vbskycn/iptv",
        "url": "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.txt",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.txt",
    },
    # ── frankwuzp 中国移动专用 IPv4 源（移动宽带深度优化）──
    {
        "name": "frankwuzp/iptv-cn",
        "url": "https://raw.githubusercontent.com/frankwuzp/iptv-cn/main/tv-ipv4-cmcc.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/frankwuzp/iptv-cn/main/tv-ipv4-cmcc.m3u",
    },
    # ── BurningC4 纯 IPv4 央视卫视 ──
    {
        "name": "BurningC4/Chinese-IPTV",
        "url": "https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/BurningC4/Chinese-IPTV/master/TV-IPV4.m3u",
    },
    # ══════════════════════════════════════════════
    # 第二批：四大超级 IPv4 混合源（v3.0 新增）
    # ══════════════════════════════════════════════
    # ── yuanzl77 每天自动更新双栈源（日更级去重筛选极速 IPv4 节目流）──
    {
        "name": "yuanzl77/IPTV",
        "url": "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    },
    # ── joevess 高质量 IPv4 专线（家用网络优化，完整台标和 EPG）──
    {
        "name": "joevess/IPTV",
        "url": "https://raw.githubusercontent.com/joevess/IPTV/main/m3u/iptv.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/joevess/IPTV/main/m3u/iptv.m3u",
    },
    # ── YanG-1989 Gather 国内高速直连聚合大片源（数百市县级地方台+卫视）──
    {
        "name": "YanG-1989/Gather",
        "url": "https://tv.iill.top/m3u/Gather",
        # 国内直连域名，无需 gh-proxy 兜底
    },
    # ── Kimentanm APTV 官方推荐 IPv4 源（APTV 播放器官方精选纯净源）──
    {
        "name": "Kimentanm/aptv",
        "url": "https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
        "url_fallback": "https://gh-proxy.com/https://raw.githubusercontent.com/Kimentanm/aptv/master/m3u/iptv.m3u",
    },
]


# ── Stage 1: 拉取与解析引擎 ──────────────────────

async def fetch_one_source(session: aiohttp.ClientSession, src: dict) -> str:
    """拉取单个订阅源，支持 gh-proxy 代理兜底，失败返回空串（不阻断其他源）"""
    name = src["name"]
    urls_to_try = [src["url"]]
    if src.get("url_fallback"):
        urls_to_try.append(src["url_fallback"])

    for try_url in urls_to_try:
        try:
            async with session.get(try_url, timeout=FETCH_TIMEOUT, headers=HEADERS,
                                   allow_redirects=True, max_redirects=5) as resp:
                if 200 <= resp.status < 300:
                    text = await resp.text(errors="ignore")
                    if len(text) > 100:  # 过滤空响应
                        if try_url != src["url"]:
                            print(f"  [代理兜底] {name} 通过 gh-proxy 成功拉取")
                        return text
        except asyncio.TimeoutError:
            if try_url == urls_to_try[-1]:
                print(f"  [源超时] {name}")
            continue
        except Exception as exc:
            if try_url == urls_to_try[-1]:
                print(f"  [源失败] {name} → {type(exc).__name__}")
            continue
    return ""


async def fetch_and_parse_sources() -> list[dict]:
    """
    并发拉取所有订阅源 → M3U/TXT 解析 → MD5 去重
    返回: [{"name": raw_name, "url": stream_url}, ...]
    """
    big_source_names = ["yuanzl77/IPTV"]
    normal_sources = [s for s in SOURCES if s["name"] not in big_source_names]
    big_sources = [s for s in SOURCES if s["name"] in big_source_names]

    raw_texts = [None] * len(SOURCES)
    
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=5, enable_cleanup_closed=True)
    async with aiohttp.ClientSession(connector=connector, headers=HEADERS) as session:
        # Step 1: 并发拉取普通源
        normal_tasks = []
        for i, src in enumerate(SOURCES):
            if src["name"] not in big_source_names:
                normal_tasks.append((i, fetch_one_source(session, src)))
        
        if normal_tasks:
            indices, tasks = zip(*normal_tasks)
            results = await asyncio.gather(*tasks)
            for idx, res in zip(indices, results):
                raw_texts[idx] = res

        # Step 2: 序列化或延迟拉取大数据源 (yuanzl77)
        for i, src in enumerate(SOURCES):
            if src["name"] in big_source_names:
                print(f"  [核心拉取] {src['name']} (大数据源, 正在加载...)...")
                raw_texts[i] = await fetch_one_source(session, src)

    # 解析每个源的文本
    all_channels = []
    for i, text in enumerate(raw_texts):
        if not text:
            continue
        src_name = SOURCES[i]["name"]
        try:
            parsed = parse_m3u(text)
            if parsed:
                print(f"  [解析成功] {src_name}: {len(parsed)} 个频道")
                all_channels.extend(parsed)
            else:
                print(f"  [解析为空] {src_name}")
        except Exception as exc:
            print(f"  [解析错误] {src_name} → {exc}")

    # MD5 去重（基于 URL）
    seen_hashes = set()
    unique = []
    for ch in all_channels:
        url = ch.get("url", "")
        if not url:
            continue
        url_hash = hashlib.md5(url.encode()).hexdigest()
        if url_hash not in seen_hashes:
            seen_hashes.add(url_hash)
            unique.append({"name": ch.get("raw_name", ch.get("name", "")), "url": url})

    return unique


# ── Stage 2: 三级验证引擎 ────────────────────────

def _is_retryable(exc: Exception) -> bool:
    """判断异常是否属于网络瞬时抖动，值得重试。

    可重试：TimeoutError、ClientConnectorError（DNS/连接拒绝）、
            ServerDisconnectedError、ClientPayloadError、OSError。
    不可重试：SSLError、CertificateError（证书问题不会因重试消失）、
            NonHttpUrlClientError（URL 格式错误）。
    """
    # SSL 证书错误 → 不可重试
    if isinstance(exc, (aiohttp.ClientConnectorSSLError,
                        aiohttp.ClientConnectorCertificateError)):
        return False
    # URL 格式错误 → 不可重试
    if isinstance(exc, aiohttp.NonHttpUrlClientError):
        return False
    # 超时 → 可重试
    if isinstance(exc, asyncio.TimeoutError):
        return True
    # 连接级错误（DNS 失败、连接拒绝等）→ 可重试
    if isinstance(exc, aiohttp.ClientConnectorError):
        return True
    # 服务器断开连接 → 可重试
    if isinstance(exc, aiohttp.ServerDisconnectedError):
        return True
    # 其他 aiohttp 客户端错误（如 ClientPayloadError）→ 可重试
    if isinstance(exc, aiohttp.ClientError):
        return True
    # 系统级 OSError → 可重试
    if isinstance(exc, OSError):
        return True
    return False


async def validate_basic(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                          channel: dict) -> dict | None:
    """
    第一层 + 第二层验证（含指数退避重试）：
    1. HEAD 请求（200/405/403 通过，其余判死）
    2. GET 前 1024 字节 → 检查 #EXTM3U
    网络瞬时抖动（TimeoutError/ClientConnectorError/OSError）触发退避重试。
    """
    url = channel["url"]
    ch_name = channel.get("name", "")[:20]
    async with sem:
        # ── Step 1: HEAD（含退避重试）──
        head_ok = False
        last_exc = None
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                async with session.head(url, timeout=RETRY_CONNECT_TIMEOUT, headers=HEADERS,
                                        allow_redirects=True, max_redirects=5) as resp:
                    if resp.status not in (200, 405, 403):
                        return None  # 明确拒绝，不重试
                    head_ok = True
                    break  # HEAD 通过，进入 Step 2
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc):
                    return None  # 不可重试异常，直接判死
                if attempt < RETRY_MAX_ATTEMPTS - 1:
                    delay = RETRY_BACKOFF_DELAYS[attempt]
                    print(f"  [重试 {attempt + 1}/{RETRY_MAX_ATTEMPTS}] {ch_name} HEAD → "
                          f"{type(exc).__name__}, {delay}s后重试")
                    await asyncio.sleep(delay)
        if not head_ok:
            return None  # 重试耗尽

        # ── Step 2: GET first 1024 bytes → #EXTM3U（含退避重试）──
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                async with session.get(url, timeout=RETRY_CONNECT_TIMEOUT, headers=HEADERS,
                                       allow_redirects=True, max_redirects=5) as resp:
                    if resp.status in (404, 401, 403):
                        return None  # 明确拒绝，不重试
                    if 200 <= resp.status < 300:
                        chunk = await resp.content.read(MAX_M3U_BYTES)
                        text = chunk.decode("utf-8", errors="ignore")
                        if "#EXTM3U" in text:
                            if attempt > 0:
                                print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功")
                            return channel
                        return None  # 无 #EXTM3U，判死
                    # 其他状态码，宽容处理
                    if attempt > 0:
                        print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功")
                    return channel
            except Exception as exc:
                if not _is_retryable(exc):
                    pass  # 不可重试异常，宽容放行
                    break
                if attempt < RETRY_MAX_ATTEMPTS - 1:
                    delay = RETRY_BACKOFF_DELAYS[attempt]
                    print(f"  [重试 {attempt + 1}/{RETRY_MAX_ATTEMPTS}] {ch_name} GET → "
                          f"{type(exc).__name__}, {delay}s后重试")
                    await asyncio.sleep(delay)
                else:
                    # 重试耗尽，宽容放行
                    break
        # 宽容放行（原逻辑保持）
        return channel


async def _get_first_segment(session: aiohttp.ClientSession, url: str,
                              depth: int = 0) -> str | None:
    """递归1层获取 M3U8 中第一个媒体切片 URL"""
    if depth > 1:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with session.get(url, timeout=timeout, headers=HEADERS,
                               allow_redirects=True, max_redirects=5) as resp:
            if resp.status != 200:
                return None
            text = await resp.text(errors="ignore")

        base = url.rsplit("/", 1)[0] + "/"
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            seg = line if line.startswith("http") else base + line
            if ".m3u8" in seg.lower():
                return await _get_first_segment(session, seg, depth + 1)
            return seg
    except Exception:
        return None
    return None


async def _validate_continuous_stream(
        session: aiohttp.ClientSession, sem: asyncio.Semaphore,
        channel: dict) -> dict | None:
    """
    轨道 2：连续/直达流验证（含指数退避重试）
    直接对主 URL 发起 GET，读取前 10KB，通过头部特征识别流类型：
    - FLV: 前 3 字节 == b'FLV'
    - TS:  第 1 字节 == 0x47（MPEG-TS 同步字）
    - M3U8: 包含 b'#EXTM3U'（伪装成 m3u8 的直达流）
    网络瞬时抖动触发退避重试，403/401 直接判死。
    """
    url = channel["url"]
    ch_name = channel.get("name", "")[:20]
    async with sem:
        for attempt in range(RETRY_MAX_ATTEMPTS):
            try:
                async with session.get(url, timeout=RETRY_CONNECT_TIMEOUT, headers=HEADERS,
                                       allow_redirects=True, max_redirects=5) as resp:
                    if resp.status in (403, 401, 404):
                        return None  # 明确拒绝，不重试
                    if 200 <= resp.status < 300:
                        chunk = await resp.content.read(MAX_TS_BYTES)
                        if len(chunk) < 100:
                            return None  # 数据过少，判死

                        # 特征匹配
                        if chunk[:3] == FLV_MAGIC:
                            if attempt > 0:
                                print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(FLV)")
                            return channel  # FLV 连续流 ✓
                        if chunk[0] == TS_SYNC_BYTE:
                            if attempt > 0:
                                print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(TS)")
                            return channel  # TS 连续流 ✓
                        if M3U8_MAGIC in chunk[:512]:
                            if attempt > 0:
                                print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(M3U8)")
                            return channel  # M3U8/HLS 直达流 ✓

                        # 未知格式，宽容放行
                        if attempt > 0:
                            print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(未知格式)")
                        return channel
                    # 其他状态码，宽容放行
                    if attempt > 0:
                        print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(状态{resp.status})")
                    return channel
            except Exception as exc:
                if not _is_retryable(exc):
                    # 不可重试异常，宽容放行（原逻辑）
                    return channel
                if attempt < RETRY_MAX_ATTEMPTS - 1:
                    delay = RETRY_BACKOFF_DELAYS[attempt]
                    print(f"  [重试 {attempt + 1}/{RETRY_MAX_ATTEMPTS}] {ch_name} 连续流 → "
                          f"{type(exc).__name__}, {delay}s后重试")
                    await asyncio.sleep(delay)
                else:
                    # 重试耗尽，宽容放行
                    return channel
    return None


async def validate_deep(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                         channel: dict) -> dict | None:
    """
    第三层深度验证 — 双轨制流验证器（含指数退避重试）
    轨道 1: 标准 HLS/M3U8 → 解析子切片 → 下载首个 .ts 切片 10KB
    轨道 2: 连续流（FLV/TS/直达）→ 直接 GET 主 URL → 读取 10KB → 特征匹配
    网络瞬时抖动触发退避重试，403/401/404 直接判死，其他异常宽容放行（不误杀）
    """
    url = channel["url"]
    url_lower = url.lower()
    ch_name = channel.get("name", "")[:20]

    # ── 快速判断：URL 后缀直接暴露流类型 ──
    is_direct_stream = (
        url_lower.endswith('.flv') or
        (url_lower.endswith('.ts') and '.m3u8' not in url_lower)
    )

    if is_direct_stream:
        # URL 明显是连续流，直接进入轨道 2（内部已含重试）
        return await _validate_continuous_stream(session, sem, channel)

    # ── 对整体验证流程施加退避重试（轨道1 → 降级轨道2）──
    for attempt in range(RETRY_MAX_ATTEMPTS):
        rescued = False
        async with sem:
            # ── 尝试轨道 1：标准 M3U8 分片验证 ──
            try:
                seg_url = await _get_first_segment(session, url)
                if seg_url is not None:
                    try:
                        async with session.get(seg_url, timeout=RETRY_CONNECT_TIMEOUT,
                                               headers=HEADERS) as resp:
                            if resp.status == 200:
                                await resp.content.read(MAX_TS_BYTES)
                                if attempt > 0:
                                    print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(HLS切片)")
                                return channel
                            elif resp.status in (403, 401, 404):
                                return None  # 明确拒绝
                            else:
                                if attempt > 0:
                                    print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(HLS状态{resp.status})")
                                return channel
                    except Exception as exc:
                        if not _is_retryable(exc):
                            # 不可重试异常，宽容放行
                            return channel
                        # 可重试异常，记录后走退避
                        rescued = True
                        if attempt < RETRY_MAX_ATTEMPTS - 1:
                            delay = RETRY_BACKOFF_DELAYS[attempt]
                            print(f"  [重试 {attempt + 1}/{RETRY_MAX_ATTEMPTS}] {ch_name} HLS切片 → "
                                  f"{type(exc).__name__}, {delay}s后重试")
                        # 降级到轨道 2
                else:
                    # 无子切片，降级轨道 2
                    pass

            except Exception as exc:
                # _get_first_segment 本身失败
                if not _is_retryable(exc):
                    pass  # 不可重试，降级轨道 2
                else:
                    rescued = True
                    if attempt < RETRY_MAX_ATTEMPTS - 1:
                        delay = RETRY_BACKOFF_DELAYS[attempt]
                        print(f"  [重试 {attempt + 1}/{RETRY_MAX_ATTEMPTS}] {ch_name} M3U8解析 → "
                              f"{type(exc).__name__}, {delay}s后重试")

            # ── 轨道 1 失败（无子切片/切片下载失败）→ 降级到轨道 2：连续流验证 ──
            # _validate_continuous_stream 内部已有重试，此处直接调用
            result = await _validate_continuous_stream(session, sem, channel)
            if result is not None:
                if attempt > 0 and not rescued:
                    print(f"  [获救 ✓] {ch_name} → 第{attempt + 1}次重试成功(降级连续流)")
                return result
            # 轨道 2 也返回 None（明确拒绝），不重试
            return None

        # 可重试且还有剩余次数 → 执行退避 sleep（在 sem 外释放并发槽）
        if rescued and attempt < RETRY_MAX_ATTEMPTS - 1:
            await asyncio.sleep(RETRY_BACKOFF_DELAYS[attempt])

    return None


async def run_validation(channels: list[dict]) -> list[dict]:
    """
    两阶段验证流水线：
    Phase 1: validate_basic (HEAD + #EXTM3U)
    Phase 2: validate_deep  (TS 切片 10KB)
    返回: [{"name", "url", "category"}, ...]
    """
    sem = VALIDATE_SEMAPHORE
    connector = aiohttp.TCPConnector(limit=50, limit_per_host=3, enable_cleanup_closed=True)

    async with aiohttp.ClientSession(connector=connector, headers=HEADERS) as session:
        total = len(channels)

        # ── Phase 1: Basic validation ──
        print(f"\n  [Phase 1] HEAD + #EXTM3U 验证: {total} 个频道...")
        t1 = time.monotonic()
        phase1_alive = []

        for i in range(0, total, BATCH_SIZE):
            batch = channels[i:i + BATCH_SIZE]
            results = await asyncio.gather(
                *[validate_basic(session, sem, ch) for ch in batch]
            )
            phase1_alive.extend([r for r in results if r is not None])
            cur = min(i + BATCH_SIZE, total)
            print(f"    进度: {cur}/{total} | 存活: {len(phase1_alive)}")

        t1_elapsed = time.monotonic() - t1
        print(f"  [Phase 1] 完成: {len(phase1_alive)}/{total} 通过 ({t1_elapsed:.1f}s)")

        if not phase1_alive:
            return []

        # ── Phase 2: Deep validation ──
        p1_total = len(phase1_alive)
        print(f"\n  [Phase 2] 双轨制流验证（HLS分片 + FLV/TS连续流）: {p1_total} 个频道...")
        t2 = time.monotonic()
        verified_alive = []

        for i in range(0, p1_total, BATCH_SIZE):
            batch = phase1_alive[i:i + BATCH_SIZE]
            results = await asyncio.gather(
                *[validate_deep(session, sem, ch) for ch in batch]
            )
            verified_alive.extend([r for r in results if r is not None])
            cur = min(i + BATCH_SIZE, p1_total)
            print(f"    进度: {cur}/{p1_total} | 验证通过: {len(verified_alive)}")

        t2_elapsed = time.monotonic() - t2
        print(f"  [Phase 2] 完成: {len(verified_alive)}/{p1_total} 验证通过 ({t2_elapsed:.1f}s)")

    # ── 分类 ──
    final = []
    for ch in verified_alive:
        category = classify_channel(ch["name"])
        cleaned_name = normalize(pre_clean(ch["name"]))
        final.append({
            "name": cleaned_name,
            "raw_name": ch["name"],
            "url": ch["url"],
            "category": category,
        })

    return final


# ── Stage 3: 频道分类 ──────────────────────────

# 从 normalizer 导入卫视标准名集合
_SATELLITE_NAMES = set(SATELLITE_ALIASES.keys())

# 省市名正则（用于地方台识别）
_PROVINCE_RE = re.compile(
    r"北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|"
    r"江西|山东|河南|湖北|湖南|广东|四川|贵州|云南|陕西|甘肃|青海|内蒙古|"
    r"广西|西藏|宁夏|新疆|海南"
)

# 地方台特征关键词
_LOCAL_KWS = ["频道", "电视台", "电视", "影视", "新闻", "综合", "都市",
              "公共", "少儿", "教育", "经济", "生活", "导视", "文体", "法治"]


def classify_channel(name: str) -> str:
    """
    将频道名分类为：央视 / 卫视 / 地方台 / 其他
    使用 normalizer.normalize() 进行标准化后判断
    """
    std = normalize(name)

    # 央视：标准化后以 CCTV 开头
    if std.upper().startswith("CCTV"):
        return "央视"

    # 卫视：在卫视别名表中，或以"卫视"结尾
    if std in _SATELLITE_NAMES or std.endswith("卫视"):
        return "卫视"

    # 地方台：包含省市名或地方台特征词
    if _PROVINCE_RE.search(name):
        return "地方台"
    if any(kw in name for kw in _LOCAL_KWS):
        return "地方台"

    return "其他"


# ── Stage 4: 输出 ──────────────────────────────

def write_m3u_output(channels: list[dict], filepath: str):
    """输出标准 M3U 文件，按分类分组"""
    category_order = ["央视", "卫视", "地方台", "其他"]
    grouped = defaultdict(list)
    for ch in channels:
        grouped[ch["category"]].append(ch)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for cat in category_order:
            if not grouped.get(cat):
                continue
            f.write(f"\n# === {cat} ===\n\n")
            for ch in sorted(grouped[cat], key=lambda x: x["name"]):
                logo = get_logo(ch["name"])
                epg = get_epg_id(ch["name"])
                f.write(f'#EXTINF:-1 tvg-logo="{logo}" tvg-id="{epg}" '
                        f'group-title="{cat}",{ch["name"]}\n')
                f.write(f'{ch["url"]}\n')

    return os.path.getsize(filepath)


def write_json_output(channels: list[dict], filepath: str):
    """输出 JSON 数据文件"""
    from collections import Counter
    category_counts = Counter(ch["category"] for ch in channels)

    output = {
        "_meta": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_channels": len(channels),
            "category_stats": dict(category_counts),
            "generator": "IPTV Washer v4.0",
            "pipeline": "fetch→parse→dedup→HEAD+#EXTM3U→dual-track(FLV/TS/HLS)→classify",
        },
        "channels": [
            {
                "name": ch["name"],
                "url": ch["url"],
                "category": ch["category"],
                "logo": get_logo(ch["name"]),
                "epg_id": get_epg_id(ch["name"]),
            }
            for ch in channels
        ],
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return os.path.getsize(filepath)


# ── 主入口 ──────────────────────────────────────

async def main():
    print("=" * 60)
    print("  IPTV Washer v4.0 — 双轨制流验证器（挽救 500+ 连续媒体流）")
    print("=" * 60)
    t_start = time.monotonic()

    # ── Stage 1: 拉取与解析 ──
    print(f"\n[Stage 1] 拉取 {len(SOURCES)} 个订阅源...")
    t_fetch = time.monotonic()
    channels = await fetch_and_parse_sources()
    t_fetch_elapsed = time.monotonic() - t_fetch
    print(f"  解析完成: {len(channels)} 个唯一频道 (去重后) | 耗时 {t_fetch_elapsed:.1f}s")

    if not channels:
        print("\n未获取到任何频道，请检查网络或源地址。")
        return

    # ── Stage 2: 验证 ──
    print(f"\n[Stage 2] 三级验证流水线...")
    verified = await run_validation(channels)

    if not verified:
        print("\n无存活频道通过验证。")
        return

    # ── Stage 3: 输出 ──
    print(f"\n[Stage 3] 生成输出文件...")
    m3u_path = os.path.join(OUTPUT_DIR, "cleaned_iptv_list.m3u")
    json_path = os.path.join(OUTPUT_DIR, "cleaned_channels.json")

    m3u_size = write_m3u_output(verified, m3u_path)
    json_size = write_json_output(verified, json_path)

    print(f"  M3U:  {m3u_path} ({m3u_size:,} bytes)")
    print(f"  JSON: {json_path} ({json_size:,} bytes)")

    # ── 最终统计 ──
    from collections import Counter
    cat_counts = Counter(ch["category"] for ch in verified)
    t_total = time.monotonic() - t_start

    print(f"\n{'=' * 60}")
    print(f"  总耗时: {t_total:.1f}s")
    print(f"  源数量: {len(SOURCES)}")
    print(f"  解析频道: {len(channels)}")
    print(f"  验证存活: {len(verified)}")
    print(f"  ── 分类统计 ──")
    for cat in ["央视", "卫视", "地方台", "其他"]:
        cnt = cat_counts.get(cat, 0)
        if cnt > 0:
            print(f"    {cat}: {cnt} 个")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
