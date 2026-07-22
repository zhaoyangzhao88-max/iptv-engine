"""
全国广电 CDN 探测引擎 v2.0 (SMMD v1)
=====================================
读取 src/data/cdn_domains.json 多维域名库，支持三种探测维度：
  - method_1_probe: 传统域名模板扫描（原有逻辑）
  - method_a_api: App 逆向 API 接口探测（含 Headers 防盗链）
  - method_b_sniffer: 运营商 CDN 边缘节点 IP 嗅探

探测策略：
  - 并发控制：asyncio.Semaphore(20)，防止被 CDN 防火墙封禁
  - 超时：5秒
  - 验证：HEAD 请求（method_1/method_b）或 GET 请求（method_a API）
  - 输出：扁平列表 [{"name": "频道名", "url": "...", "tier": 1, "method_type": "..."}]

用法：
  python src/cdn_explorer.py                                    # 探测全部省份（method_1）
  python src/cdn_explorer.py --province 浙江                     # 只探测指定省份
  python src/cdn_explorer.py --method method_1_probe             # 指定探测维度（默认）
  python src/cdn_explorer.py --method method_a_api --province 广东  # API 接口探测
  python src/cdn_explorer.py --method method_b_sniffer --province 北京 # IP 嗅探探测
  python src/cdn_explorer.py --concurrency 20                    # 自定义并发数
  python src/cdn_explorer.py --timeout 10                        # 自定义超时(秒)
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import asyncio
import aiohttp
import json
import time
import os
import argparse
import ipaddress
import socket

from config import HEADERS, OUTPUT_DIR, DATA_DIR

# ── 可选依赖：psutil 用于 NIC IP 提取 ──────
try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

# ── 配置常量 ──────────────────────────────────
DEFAULT_CONCURRENCY = 20
DEFAULT_TIMEOUT_SEC = 5
DATA_FILE = os.path.join(DATA_DIR, "cdn_domains.json")
OUTPUT_FILE = "cdn_explorer_results.json"


# ── 数据加载 ──────────────────────────────────

def load_cdn_domains() -> dict:
    """加载 CDN 域名库，过滤掉以 _ 开头的元数据键，返回完整多维结构"""
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _extract_json_path(data: dict, path: str):
    """从嵌套 JSON dict 中按点号路径提取值（容错：键缺失返回 None）"""
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


async def _validate_m3u8_url(session: aiohttp.ClientSession, url: str, timeout_sec: int = 5) -> bool:
    """验证 URL 是否为有效 M3U8 流（下载前 1024 字节校验 #EXTM3U）"""
    try:
        vtimeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with session.get(url, timeout=vtimeout, headers=HEADERS, allow_redirects=True, max_redirects=5) as resp:
            if 200 <= resp.status < 300:
                chunk = await resp.content.read(1024)
                try:
                    text = chunk.decode("utf-8", errors="ignore")
                    return "#EXTM3U" in text
                except Exception:
                    return False
    except Exception:
        return False


# ── 任务构建 ──────────────────────────────────

def build_probe_tasks(cdn_domains: dict, target_province: str = None,
                      method: str = "method_1_probe") -> list[dict]:
    """
    根据指定维度构建探测任务列表。

    参数：
      cdn_domains: 多维域名库
      target_province: 省份过滤（可选）
      method: 探测维度
        - method_1_probe: 域名模板扫描（原有逻辑）
        - method_a_api: App 逆向 API 接口探测
        - method_b_sniffer: 运营商 CDN 边缘节点 IP 嗅探

    返回任务列表，每个任务是一个 dict：
      method_1: {url, province, domain, code, channel_name, resolution, method_type, headers}
      method_a: {url, province, domain, code, channel_name, resolution, method_type, headers, response_path}
      method_b: {url, province, domain, code, channel_name, resolution, method_type, headers, cidr_source}
    """
    if method == "method_1_probe":
        return _build_method1_tasks(cdn_domains, target_province)
    elif method == "method_a_api":
        return _build_method_a_tasks(cdn_domains, target_province)
    elif method == "method_b_sniffer":
        return _build_method_b_tasks(cdn_domains, target_province)
    elif method == "method_c_social_hints":
        return _build_method_c_tasks(cdn_domains, target_province)
    elif method == "method_ipv6_probe":
        return _build_method_ipv6_tasks(cdn_domains, target_province)
    else:
        raise ValueError(f"未知探测维度: {method}，可选: method_1_probe, method_a_api, method_b_sniffer, method_c_social_hints, method_ipv6_probe")


def _build_method1_tasks(cdn_domains: dict, target_province: str = None) -> list[dict]:
    """method_1_probe: 传统域名模板扫描"""
    tasks = []
    for prov_name, cfg in cdn_domains.items():
        if target_province and target_province not in prov_name:
            continue

        basic = cfg.get("basic", {})
        m1 = cfg.get("method_1_probe", {})

        province = basic.get("province", cfg.get("province", ""))
        domains = m1.get("domains", [])
        pattern = m1.get("url_pattern", "")
        res_options = m1.get("res_options", ["1080p", "720p", "360p"])
        probe_codes = m1.get("probe_codes", [])
        code_map = m1.get("code_map", {})

        for domain in domains:
            for code in probe_codes:
                channel_name = code_map.get(code, code)
                for res in res_options:
                    url = pattern.replace("{domain}", domain)
                    url = url.replace("{code}", code)
                    url = url.replace("{res}", res)

                    tasks.append({
                        "url": url,
                        "province": province,
                        "domain": domain,
                        "code": code,
                        "channel_name": channel_name,
                        "resolution": res,
                        "method_type": "method_1_probe",
                        "headers": {},
                        "timeout_sec": 3,
                    })

    return tasks


def _build_method_a_tasks(cdn_domains: dict, target_province: str = None) -> list[dict]:
    """method_a_api: App 逆向 API 接口探测（含 Headers 防盗链 + probe_range 范围扫描）"""
    tasks = []
    for prov_name, cfg in cdn_domains.items():
        if target_province and target_province not in prov_name:
            continue

        basic = cfg.get("basic", {})
        api_cfg = cfg.get("method_a_api", {})

        if not api_cfg.get("enabled", False):
            continue

        province = basic.get("province", cfg.get("province", ""))
        endpoints = api_cfg.get("endpoints", [])
        m1 = cfg.get("method_1_probe", {})
        probe_codes = m1.get("probe_codes", [])
        code_map = m1.get("code_map", {})

        for ep in endpoints:
            api_url_template = ep.get("url", "")
            api_headers = ep.get("headers", {})
            api_name = ep.get("name", "unknown")
            response_path = ep.get("response_path", "")
            probe_range = ep.get("probe_range", None)

            # 支持 probe_range 动态生成 code 列表
            if probe_range and len(probe_range) == 2:
                range_start, range_end = probe_range[0], probe_range[1]
                pad_width = len(str(range_end))
                codes = [str(i).zfill(pad_width) for i in range(range_start, range_end + 1)]
            else:
                codes = probe_codes

            for code in codes:
                channel_name = code_map.get(code, code)
                # 替换 URL 模板中的占位符
                api_url = api_url_template.replace("{code}", code)
                # 替换 headers 中的占位符
                task_headers = {}
                for hk, hv in api_headers.items():
                    task_headers[hk] = hv.replace("{code}", code)

                # API 探测不需要分辨率维度（API 返回自适应码率）
                tasks.append({
                    "url": api_url,
                    "province": province,
                    "domain": api_url.split("/")[2] if "://" in api_url else api_url,
                    "code": code,
                    "channel_name": channel_name,
                    "resolution": "adaptive",
                    "method_type": "method_a_api",
                    "headers": task_headers,
                    "response_path": response_path,
                    "api_name": api_name,
                    "timeout_sec": 5,
                    "_probe_range": probe_range or [],
                })

    return tasks


def _build_method_b_tasks(cdn_domains: dict, target_province: str = None) -> list[dict]:
    """method_b_sniffer: 运营商 CDN 边缘节点 IP 嗅探"""
    tasks = []
    for prov_name, cfg in cdn_domains.items():
        if target_province and target_province not in prov_name:
            continue

        basic = cfg.get("basic", {})
        sniffer_cfg = cfg.get("method_b_sniffer", {})

        if not sniffer_cfg.get("enabled", False):
            continue

        province = basic.get("province", cfg.get("province", ""))
        cidr_ranges = sniffer_cfg.get("cidr_ranges", [])
        port_hints = sniffer_cfg.get("port_hints", [80, 443, 8080])
        path_patterns = sniffer_cfg.get("path_patterns", ["/live/{code}.m3u8"])
        m1 = cfg.get("method_1_probe", {})
        probe_codes = m1.get("probe_codes", [])
        code_map = m1.get("code_map", {})

        # 展开 CIDR → 采样 IP（每个 CIDR 取 .1 和 .100 作为代表性节点）
        sampled_ips = []
        for cidr in cidr_ranges:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
                hosts = list(network.hosts())
                if len(hosts) >= 1:
                    sampled_ips.append(str(hosts[0]))  # x.x.x.1
                if len(hosts) >= 100:
                    sampled_ips.append(str(hosts[99]))  # x.x.x.100
                # 大网段额外采样中间 IP
                if len(hosts) >= 2:
                    mid = len(hosts) // 2
                    sampled_ips.append(str(hosts[mid]))
            except ValueError:
                continue

        for ip in sampled_ips:
            for port in port_hints:
                for path_pattern in path_patterns:
                    for code in probe_codes:
                        channel_name = code_map.get(code, code)
                        path = path_pattern.replace("{code}", code)
                        # method_b 不探测分辨率维度（边缘节点通常自适应）
                        url = f"http://{ip}:{port}{path}"
                        tasks.append({
                            "url": url,
                            "province": province,
                            "domain": ip,
                            "code": code,
                            "channel_name": channel_name,
                            "resolution": "adaptive",
                            "method_type": "method_b_sniffer",
                            "headers": {},
                            "cidr_source": cidr,
                            "timeout_sec": 5,
                        })

    return tasks


def _build_method_c_tasks(cdn_domains: dict, target_province: str = None) -> list[dict]:
    """method_c_social_hints: 社交情报 URL 提取与探测

    从各省份的 method_c_social_hints.known_urls 中提取已知存活 URL，
    直接发送 GET 请求验证其存活状态（200 + #EXTM3U 内容校验）。

    若 known_urls 为空但有 github_patterns + method_1_probe 模板，
    则尝试组合生成候选 URL 进行探测。
    """
    tasks = []
    for prov_name, cfg in cdn_domains.items():
        if target_province and target_province not in prov_name:
            continue

        basic = cfg.get("basic", {})
        social_cfg = cfg.get("method_c_social_hints", {})

        if not social_cfg.get("enabled", False):
            continue

        province = basic.get("province", cfg.get("province", ""))
        known_urls = social_cfg.get("known_urls", [])
        github_patterns = social_cfg.get("github_patterns", [])

        # 直接探测 known_urls（优先路径）
        for url in known_urls:
            tasks.append({
                "url": url,
                "province": province,
                "domain": url.split("/")[2] if "://" in url else url,
                "code": "social",
                "channel_name": f"social_{prov_name}",
                "resolution": "adaptive",
                "method_type": "method_c_social_hints",
                "headers": {},
                "timeout_sec": 5,
            })

        # 若 known_urls 为空，尝试从 github_patterns + method_1_probe 模板合成
        if not known_urls and github_patterns:
            m1 = cfg.get("method_1_probe", {})
            domains = m1.get("domains", [])
            pattern = m1.get("url_pattern", "")
            probe_codes = m1.get("probe_codes", [])

            if domains and pattern and probe_codes:
                for domain in domains:
                    for code in probe_codes:
                        url = pattern.replace("{domain}", domain)
                        url = url.replace("{code}", code)
                        url = url.replace("{res}", "720p")
                        tasks.append({
                            "url": url,
                            "province": province,
                            "domain": domain,
                            "code": code,
                            "channel_name": f"{prov_name}_{code}",
                            "resolution": "720p",
                            "method_type": "method_c_social_hints",
                            "headers": {},
                            "timeout_sec": 5,
                        })

    return tasks


def _build_method_ipv6_tasks(cdn_domains: dict, target_province: str = None) -> list[dict]:
    """method_ipv6_probe: IPv6 单播源探测（固定探针优先策略）

    使用 CCTV 通用频道 ID 作为探针，探测各省 IPv6 节点存活。
    URL 模板中的 {code} 占位符在构建时被替换为具体频道 ID。
    """
    tasks = []
    for prov_name, cfg in cdn_domains.items():
        if target_province and target_province not in prov_name:
            continue

        basic = cfg.get("basic", {})
        ipv6_cfg = cfg.get("method_ipv6_probe", {})

        if not ipv6_cfg.get("enabled", False):
            continue

        province = basic.get("province", cfg.get("province", ""))
        ipv6_templates = ipv6_cfg.get("ipv6_templates", [])
        probe_codes = ipv6_cfg.get("probe_codes", [])
        code_map = ipv6_cfg.get("code_map", {})

        for template in ipv6_templates:
            url_pattern = template.get("url_pattern", "")
            isp = template.get("isp", "unknown")
            cidr = template.get("cidr_segment", "")

            for code in probe_codes:
                channel_name = code_map.get(code, f"IPv6_{code}")
                # 替换 URL 模板中的 {code} 占位符
                url = url_pattern.replace("{code}", code)

                tasks.append({
                    "url": url,
                    "province": province,
                    "domain": f"[{cidr}]",
                    "code": code,
                    "channel_name": channel_name,
                    "resolution": "adaptive",
                    "method_type": "method_ipv6_probe",
                    "headers": {},
                    "isp": isp,
                    "cidr_segment": cidr,
                    "timeout_sec": 5,
                })

    return tasks


# ── NIC 接口绑定工具 ─────────────────────────

def _is_ipv6_url(url: str) -> bool:
    """判断 URL 是否为 IPv6 地址格式（检测方括号包裹的 IPv6 地址）"""
    return "[" in url


def get_interface_ips(interface_name: str) -> tuple[str | None, str | None]:
    """
    根据网卡名称获取其 IPv4 地址和全球单播公网 IPv6 地址。

    提取优先级：
      1. 主路径：psutil（迭代所有 NIC，大小写不敏感部分匹配）
      2. 降级路径：socket.getaddrinfo（psutil 缺失时回退）

    过滤规则：
      IPv4：排除 127.0.0.1 等环回地址，取第一个非环回地址
      IPv6：排除 fe80:: 链路本地和 ::1 环回，只保留全球单播地址

    返回 (ipv4_str | None, ipv6_str | None)
    """
    try:
        if _HAS_PSUTIL:
            return _get_ips_via_psutil(interface_name)
        return _get_ips_via_socket()
    except Exception as exc:
        print(f"[NIC] 获取接口 IP 失败: {interface_name}，错误: {exc}，返回 (None, None)")
        return (None, None)


def _get_ips_via_psutil(interface_name: str) -> tuple[str | None, str | None]:
    """psutil 主路径：枚举 NIC 地址并匹配接口名（大小写不敏感，部分匹配）"""
    ipv4_addr = None
    ipv6_addr = None

    try:
        all_interfaces = psutil.net_if_addrs()
    except Exception:
        return (None, None)

    for iface, addrs in all_interfaces.items():
        if interface_name.lower() not in iface.lower():
            continue

        for addr in addrs:
            if addr.family == socket.AF_INET:
                ip = addr.address
                if ipv4_addr is None and not ip.startswith("127."):
                    ipv4_addr = ip
            elif addr.family == socket.AF_INET6:
                ip = addr.address
                if "%" in ip:
                    ip = ip.split("%")[0]

                if (
                    ipv6_addr is None
                    and ip != "::1"
                    and not ip.startswith("fe80:")
                    and ip.startswith(("2408:", "2409:", "240e:", "2001:"))
                ):
                    ipv6_addr = ip

        if ipv4_addr is not None and ipv6_addr is not None:
            break

    return (ipv4_addr, ipv6_addr)


def _get_ips_via_socket() -> tuple[str | None, str | None]:
    """
    psutil 降级路径：通过 socket.getaddrinfo 获取本机 IP。

    该路径无法精确定位指定 NIC，仅提供基础 IP 绑定能力。
    """
    hostname = socket.gethostname()
    try:
        addrinfo_list = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror:
        return (None, None)

    ipv4_addr = None
    ipv6_addr = None

    for info in addrinfo_list:
        family, _, _, _, sockaddr = info
        ip = sockaddr[0]

        if family == socket.AF_INET:
            if ipv4_addr is None and not ip.startswith("127."):
                ipv4_addr = ip
        elif family == socket.AF_INET6:
            if "%" in ip:
                ip = ip.split("%")[0]

            if (
                ipv6_addr is None
                and ip != "::1"
                and not ip.startswith("fe80:")
                and ip.startswith(("2408:", "2409:", "240e:", "2001:"))
            ):
                ipv6_addr = ip

    return (ipv4_addr, ipv6_addr)


# ── 探测核心 ──────────────────────────────────

async def probe_single(
    session: aiohttp.ClientSession,
    task: dict,
    semaphore: asyncio.Semaphore,
    timeout_sec: int,
) -> dict | None:
    """
    探测单个 URL。
    - method_1 / method_b: HEAD 请求，200 = 存活
    - method_a: GET 请求（API 通常不支持 HEAD），200 = 存活
    - method_c_social_hints: GET 请求 + #EXTM3U 内容校验（社交情报 URL）

    返回 None = 死亡
    返回 dict = 存活
    """
    url = task["url"]
    method_type = task.get("method_type", "method_1_probe")
    task_headers = task.get("headers", {})

    # 合并 headers：task headers 覆盖全局 HEADERS
    merged_headers = {**HEADERS, **task_headers}

    async with semaphore:
        try:
            # 动态超时：任务级 timeout_sec 覆盖全局默认值
            effective_timeout = task.get("timeout_sec", timeout_sec)
            timeout = aiohttp.ClientTimeout(total=effective_timeout)

            if method_type == "method_a_api":
                # API 接口用 GET 请求 + 深度解析 + 二次流验证
                try:
                    async with session.get(
                        url,
                        timeout=timeout,
                        headers=merged_headers,
                        allow_redirects=True,
                        max_redirects=5,
                    ) as resp:
                        if resp.status in (401, 403):
                            print(f"  [API防盗链] {url} → HTTP {resp.status} (api={task.get('api_name','')}, code={task.get('code','')})")
                            return None
                        if 200 <= resp.status < 300:
                            response_path = task.get("response_path", "")
                            if response_path:
                                try:
                                    body = await resp.text()
                                    json_data = json.loads(body)
                                    stream_url = _extract_json_path(json_data, response_path)
                                    if stream_url and isinstance(stream_url, str) and stream_url.startswith("http"):
                                        is_valid = await _validate_m3u8_url(session, stream_url, timeout_sec=task.get("timeout_sec", 5))
                                        if is_valid:
                                            return {
                                                "name": task["channel_name"],
                                                "url": stream_url,
                                                "province": task["province"],
                                                "domain": task["domain"],
                                                "method_type": method_type,
                                                "api_name": task.get("api_name", ""),
                                            }
                                        else:
                                            print(f"  [流验证失败] {stream_url} (api={task.get('api_name','')}, code={task.get('code','')})")
                                            return None
                                    else:
                                        print(f"  [JSON解析失败] path={response_path} 未提取到URL (api={task.get('api_name','')}, code={task.get('code','')})")
                                        return None
                                except (json.JSONDecodeError, ValueError) as json_err:
                                    print(f"  [JSON解析错误] {url} → {json_err}")
                                    return None
                            else:
                                # 无 response_path，回退到 API URL
                                return {
                                    "name": task["channel_name"],
                                    "url": url,
                                    "province": task["province"],
                                    "domain": task["domain"],
                                    "method_type": method_type,
                                    "api_name": task.get("api_name", ""),
                                }
                        # 其他非200状态码（如404、500）→ 判死，不输出
                except Exception as exc:
                    print(f"  [API探测异常] {url} → {type(exc).__name__}: {exc}")
                    return None
            elif method_type == "method_ipv6_probe":
                # IPv6 单播源：直接使用 GET + #EXTM3U 内容校验
                try:
                    async with session.get(
                        url,
                        timeout=timeout,
                        headers=merged_headers,
                        allow_redirects=True,
                        max_redirects=5,
                    ) as resp:
                        if 200 <= resp.status < 300:
                            chunk = await resp.content.read(1024)
                            try:
                                text = chunk.decode("utf-8", errors="ignore")
                                if "#EXTM3U" not in text:
                                    return None  # 非有效 M3U8
                            except Exception:
                                pass
                            result = {
                                "name": task["channel_name"],
                                "url": url,
                                "province": task["province"],
                                "domain": task["domain"],
                                "method_type": method_type,
                            }
                            if task.get("isp"):
                                result["isp"] = task["isp"]
                            return result
                except Exception:
                    pass
            else:
                # method_1 / method_b: 先尝试 HEAD，405/403 时降级为 GET
                _head_ok = False
                try:
                    async with session.head(
                        url,
                        timeout=timeout,
                        headers=merged_headers,
                        allow_redirects=True,
                        max_redirects=5,
                    ) as resp:
                        if resp.status == 200:
                            # method_c 需要额外校验 M3U8 内容（HEAD 无法验证）
                            if method_type == "method_c_social_hints":
                                _head_ok = True  # 强制降级 GET 以校验内容
                            else:
                                return {
                                    "name": task["channel_name"],
                                    "url": url,
                                    "province": task["province"],
                                    "domain": task["domain"],
                                    "method_type": method_type,
                                }
                        elif resp.status in (405, 403):
                            _head_ok = True  # 需要降级 GET
                        # 其他状态码 → 直接判死（_head_ok 保持 False）
                except Exception:
                    return None

                if _head_ok:
                    # HEAD 返回 405/403 → 降级为 GET（仅读前 1024 字节）
                    try:
                        async with session.get(
                            url,
                            timeout=timeout,
                            headers=merged_headers,
                            allow_redirects=True,
                            max_redirects=5,
                        ) as resp:
                            if 200 <= resp.status < 300:
                                # 对 method_1 / method_c 额外校验 M3U8 内容
                                if method_type in ("method_1_probe", "method_c_social_hints"):
                                    chunk = await resp.content.read(1024)
                                    try:
                                        text = chunk.decode("utf-8", errors="ignore")
                                        if "#EXTM3U" not in text:
                                            return None  # 非有效 M3U8
                                    except Exception:
                                        pass
                                return {
                                    "name": task["channel_name"],
                                    "url": url,
                                    "province": task["province"],
                                    "domain": task["domain"],
                                    "method_type": method_type,
                                }
                    except Exception:
                        pass
        except Exception:
            pass
    return None


async def probe_all(
    tasks: list[dict],
    concurrency: int,
    timeout_sec: int,
    interface_name: str | None = None,
) -> list[dict]:
    """
    并发探测所有任务，返回存活结果列表。

    当 interface_name 为 None 时：使用默认路由的单会话模式（原有逻辑）
    当 interface_name 指定时：按 IPv4/IPv6 分流绑定指定物理网卡
    """
    semaphore = asyncio.Semaphore(concurrency)

    if interface_name is None:
        connector = aiohttp.TCPConnector(
            limit=concurrency,
            limit_per_host=5,
            enable_cleanup_closed=True,
        )

        async with aiohttp.ClientSession(connector=connector) as session:
            return await _run_probes(tasks, session, None, semaphore, timeout_sec)

    local_ipv4, local_ipv6 = get_interface_ips(interface_name)

    if local_ipv4:
        v4_status = local_ipv4
    else:
        v4_status = "未检测到 IPv4"

    if local_ipv6:
        v6_status = f"已绑定物理 IPv6: {local_ipv6}"
    else:
        v6_status = "未检测到公网 IPv6 地址（IPv6 探测通道将自动安全退避）"

    print(f"[{interface_name} 状态自检] 已绑定物理 IPv4: {v4_status} | {v6_status}")

    connector_v4 = None
    session_v4 = None
    session_v6 = None

    if local_ipv4:
        connector_v4 = aiohttp.TCPConnector(
            limit=concurrency,
            limit_per_host=5,
            enable_cleanup_closed=True,
            local_addr=(local_ipv4, 0),
        )
        session_v4 = aiohttp.ClientSession(connector=connector_v4)

    if local_ipv6:
        connector_v6 = aiohttp.TCPConnector(
            limit=concurrency,
            limit_per_host=5,
            enable_cleanup_closed=True,
            family=socket.AF_INET6,
            local_addr=(local_ipv6, 0),
        )
        session_v6 = aiohttp.ClientSession(connector=connector_v6)

    if session_v4 is None:
        print(f"[{interface_name} 状态自检] 未检测到可用 IPv4，IPv4 探测通道将自动安全退避")
        return []

    try:
        return await _run_probes(tasks, session_v4, session_v6, semaphore, timeout_sec)
    finally:
        await session_v4.close()
        if session_v6 is not None:
            await session_v6.close()


async def _run_probes(
    tasks: list[dict],
    session_v4: aiohttp.ClientSession,
    session_v6: aiohttp.ClientSession | None,
    semaphore: asyncio.Semaphore,
    timeout_sec: int,
) -> list[dict]:
    """
    实际执行探测的协程。
    保持分批处理与进度报告，并按目标 URL 的协议栈选择会话。
    """
    alive_results = []
    total = len(tasks)
    completed = 0
    last_report = 0
    skipped_ipv6 = 0

    BATCH = 200
    for batch_start in range(0, total, BATCH):
        batch = tasks[batch_start : batch_start + BATCH]

        async def _dispatch(task: dict) -> dict | None:
            nonlocal skipped_ipv6

            if _is_ipv6_url(task["url"]):
                if session_v6 is None:
                    skipped_ipv6 += 1
                    return None
                return await probe_single(session_v6, task, semaphore, timeout_sec)

            return await probe_single(session_v4, task, semaphore, timeout_sec)

        batch_results = await asyncio.gather(*[
            _dispatch(task)
            for task in batch
        ])

        for result in batch_results:
            completed += 1
            if result is not None:
                alive_results.append(result)

        progress = completed / total * 100
        if progress - last_report >= 10 or completed == total:
            last_report = progress
            print(f"  进度: {completed}/{total} ({progress:.0f}%) | 存活: {len(alive_results)}")

    if skipped_ipv6 > 0:
        print(f"  [IPv6 退避] 已跳过 {skipped_ipv6} 个 IPv6 任务（未检测到有效 IPv6 通道）")

    return alive_results


# ── 结果输出 ──────────────────────────────────

def build_output(alive_results: list[dict], elapsed_sec: float,
                 total_tasks: int, method: str) -> dict:
    """构建最终输出结构"""
    from collections import Counter
    prov_channel_count = Counter(r["province"] for r in alive_results)

    channels = []
    for r in alive_results:
        ch = {
            "name": r["name"],
            "url": r["url"],
            "tier": 1,
            "method_type": r.get("method_type", method),
        }
        if r.get("api_name"):
            ch["api_name"] = r["api_name"]
        channels.append(ch)

    return {
        "_meta": {
            "version": "2.0",
            "method": method,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_seconds": round(elapsed_sec, 1),
            "total_probe_tasks": total_tasks,
            "alive_urls": len(alive_results),
            "provinces_covered": len(prov_channel_count),
            "province_stats": dict(prov_channel_count),
        },
        "channels": channels,
    }


def print_report(output: dict) -> None:
    meta = output["_meta"]
    province_stats = meta["province_stats"]
    method = meta.get("method", "method_1_probe")

    method_labels = {
        "method_1_probe": "域名模板扫描",
        "method_a_api": "API 接口探测",
        "method_b_sniffer": "IP 边缘嗅探",
        "method_ipv6_probe": "IPv6 单播探测",
    }
    method_label = method_labels.get(method, method)

    print(f"""
╔══════════════════════════════════════════════════╗
║         全国广电 CDN 探测引擎 v2.0 报告           ║
║         探测维度: {method_label:<12}              ║
╚══════════════════════════════════════════════════╝

  总耗时        : {meta['elapsed_seconds']:.1f} 秒
  探测任务总数  : {meta['total_probe_tasks']:,}
  存活URL数     : {meta['alive_urls']:,}
  覆盖省份数    : {meta['provinces_covered']}
""")

    print("  ── 各省探测汇总 ──")
    for prov, count in sorted(province_stats.items(), key=lambda x: -x[1]):
        print(f"  {prov} 发现 {count} 个频道")

    print(f"\n  探测完成，共发现 {meta['alive_urls']} 个存活频道")


# ── 主入口 ──────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="全国广电 CDN 探测引擎 v2.0 (SMMD v1)")
    parser.add_argument("--province", type=str, default=None, help="只探测指定省份（如：浙江）")
    parser.add_argument("--method", type=str, default="method_1_probe",
                        choices=["method_1_probe", "method_a_api", "method_b_sniffer", "method_c_social_hints", "method_ipv6_probe"],
                        help="探测维度：method_1_probe(域名模板) | method_a_api(API接口) | method_b_sniffer(IP嗅探) | method_c_social_hints(社交情报) | method_ipv6_probe(IPv6单播)")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"并发数（默认{DEFAULT_CONCURRENCY}）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SEC, help=f"超时秒数（默认{DEFAULT_TIMEOUT_SEC}）")
    parser.add_argument("--output", type=str, default=OUTPUT_FILE, help=f"输出文件名（默认{OUTPUT_FILE}）")
    parser.add_argument("--interface", type=str, default=None,
                        help="绑定物理网卡接口名（如：WLAN、Ethernet），未指定则使用系统默认路由")
    args = parser.parse_args()

    method_labels = {
        "method_1_probe": "域名模板扫描",
        "method_a_api": "API 接口探测",
        "method_b_sniffer": "IP 边缘嗅探",
        "method_c_social_hints": "社交情报提取",
        "method_ipv6_probe": "IPv6 单播探测",
    }

    print("=" * 60)
    print("  全国广电 CDN 探测引擎 v2.0 (SMMD v1)")
    print("=" * 60)
    print(f"  数据文件: {DATA_FILE}")
    print(f"  输出目录: {OUTPUT_DIR}")
    print(f"  探测维度: {method_labels.get(args.method, args.method)}")
    print()

    cdn_domains = load_cdn_domains()
    print(f"已加载 {len(cdn_domains)} 个省份的 CDN 配置（SMMD v1 多维结构）")

    # 构建探测任务
    tasks = build_probe_tasks(cdn_domains, args.province, args.method)
    print(f"探测任务总数: {len(tasks):,}")
    print(f"并发数: {args.concurrency}（Semaphore 限制）  |  超时: {args.timeout}s")

    if args.method == "method_a_api":
        print(f"验证方式: GET 请求（API 接口），200 = 存活")
    elif args.method == "method_c_social_hints":
        print(f"验证方式: GET 请求 + #EXTM3U 内容校验（社交情报 URL）")
    elif args.method == "method_ipv6_probe":
        print(f"验证方式: GET 请求 + #EXTM3U 内容校验（IPv6 单播源）")
    else:
        print(f"验证方式: HEAD 请求，200 = 存活")
    print()

    if not tasks:
        print("没有匹配的探测任务，请检查 --province 或 --method 参数")
        print("提示：method_a_api 需要目标省份的 method_a_api.enabled=true")
        print("      method_b_sniffer 需要目标省份的 method_b_sniffer.enabled=true")
        print("      method_ipv6_probe 需要目标省份的 method_ipv6_probe.enabled=true")
        return

    # 开始探测
    print("── 开始探测 ──")
    t_start = time.monotonic()
    alive_results = await probe_all(tasks, args.concurrency, args.timeout, args.interface)
    elapsed = time.monotonic() - t_start

    # 构建输出
    output = build_output(alive_results, elapsed, len(tasks), args.method)

    # 打印报告
    print_report(output)

    # 保存结果
    out_path = os.path.join(OUTPUT_DIR, args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
    print(f"文件大小: {os.path.getsize(out_path):,} 字节")
    print("\n探测完成。")


if __name__ == "__main__":
    asyncio.run(main())
