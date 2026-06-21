#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全国广电 CDN 自动化管理引擎 v2.0 (SMMD v1)
============================================
串联 cdn_explorer.py 全部功能，对全部省份的多维度进行地毯式扫描，
结果归集为 output/cdn_master.json。

用法：
  python src/cdn_manager.py                          # 全自动扫描全部省份全部维度
  python src/cdn_manager.py --province 浙江           # 只扫描指定省份
  python src/cdn_manager.py --method method_a_api     # 只使用指定维度
  python src/cdn_manager.py --workers 4               # 并行进程数（默认4）
  python src/cdn_manager.py --dry-run                 # 只打印任务计划，不执行
"""

import sys
import os
import json
import time
import argparse
import asyncio
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

# ── 路径锚定 ──────────────────────────────────
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC_DIR)

from config import HEADERS, OUTPUT_DIR, DATA_DIR

import cdn_explorer


# ── 单省扫描（子进程执行）──────────────────────

def scan_province(province_key: str, cdn_domains: dict, concurrency: int,
                  timeout_sec: int, method_filter: str = None) -> dict:
    """
    扫描单个省份的所有启用维度。
    在子进程中执行，每个进程独立 import cdn_explorer。

    返回：
    {
        "province": "浙江",
        "results": [{"name", "url", "method_type", "domain", "code"}],
        "stats": {"method_1_probe": 10, "method_a_api": 3, ...},
        "errors": []
    }
    """
    # 子进程中重新导入（Windows multiprocessing 需要）
    import importlib
    import cdn_explorer as explorer
    importlib.reload(explorer)

    cfg = cdn_domains[province_key]
    basic = cfg.get("basic", {})
    province_name = basic.get("province", cfg.get("province", province_key))
    enabled_methods = basic.get("enabled_methods", ["method_1_probe"])

    # 如果指定了 method 过滤
    if method_filter:
        if method_filter not in enabled_methods:
            return {
                "province": province_name,
                "results": [],
                "stats": {},
                "errors": [f"{province_name} 未启用 {method_filter}"]
            }
        active_methods = [method_filter]
    else:
        active_methods = enabled_methods

    all_results = []
    stats = {}
    errors = []

    for method in active_methods:
        method_cfg = cfg.get(method, {})
        # 检查维度是否启用
        if method != "method_1_probe":  # method_1 始终启用
            if not method_cfg.get("enabled", False):
                continue

        try:
            tasks = explorer.build_probe_tasks(
                {province_key: cfg},
                target_province=province_name,
                method=method
            )

            if not tasks:
                continue

            # 在子进程中运行 async 探测
            alive = asyncio.run(explorer.probe_all(tasks, concurrency, timeout_sec))

            for r in alive:
                r["province"] = province_name

            all_results.extend(alive)
            stats[method] = len(alive)

        except Exception as e:
            errors.append(f"{province_name}/{method}: {str(e)}")

    return {
        "province": province_name,
        "results": all_results,
        "stats": stats,
        "errors": errors,
    }


# ── 结果归集 ──────────────────────────────────

def merge_results(all_province_results: list[dict], elapsed_sec: float) -> dict:
    """合并所有省份的扫描结果，按 province 分组"""
    channels_by_province = defaultdict(list)
    total_alive = 0
    total_errors = []

    for prov_result in all_province_results:
        province = prov_result["province"]
        channels_by_province[province] = prov_result["results"]
        total_alive += len(prov_result["results"])
        total_errors.extend(prov_result.get("errors", []))

    return {
        "_meta": {
            "version": "2.0",
            "engine": "cdn_manager",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_seconds": round(elapsed_sec, 1),
            "total_alive": total_alive,
            "provinces_covered": len(channels_by_province),
            "errors": total_errors,
        },
        "channels": dict(channels_by_province),
    }


def merge_aggregator_results(output: dict) -> dict:
    """
    将 output/aggregator_results.json 中的频道按省份合并到 cdn_master.json。
    每个合并的频道标记 method_type="method_d_aggregator"。
    更新 _meta.total_alive 和 _meta.provinces_covered。
    """
    agg_path = os.path.join(OUTPUT_DIR, "aggregator_results.json")
    if not os.path.exists(agg_path):
        print("  ⚠️ aggregator_results.json 不存在，跳过合并")
        return output

    with open(agg_path, encoding="utf-8") as f:
        agg_data = json.load(f)

    agg_channels = agg_data.get("channels", [])
    if not agg_channels:
        print("  ⚠️ aggregator_results.json 中无频道数据，跳过合并")
        return output

    # 按省份归集
    existing_provinces = set(output.get("channels", {}).keys())
    merged_count = 0

    for ch in agg_channels:
        province = ch.get("province", "未知")
        # 构建合并后的频道条目
        merged_ch = {
            "name": ch.get("name", "未知频道"),
            "url": ch.get("url", ""),
            "tier": 1,  # 聚合站来源标记为 Tier1（官方源）
            "method_type": "method_d_aggregator",
            "source": ch.get("source", "aggregator"),
        }

        if province not in output["channels"]:
            output["channels"][province] = []
        output["channels"][province].append(merged_ch)
        merged_count += 1

    # 更新 meta
    meta = output["_meta"]
    old_total = meta.get("total_alive", 0)
    meta["total_alive"] = old_total + merged_count
    meta["provinces_covered"] = len(output["channels"])
    meta["aggregator_merged"] = merged_count
    meta["aggregator_source"] = "foodieguide.com"

    new_provinces = set(output["channels"].keys()) - existing_provinces
    print(f"\n  📦 聚合结果合并: +{merged_count} 个频道，新增 {len(new_provinces)} 个省份")
    if new_provinces:
        print(f"     新增省份: {', '.join(sorted(new_provinces))}")

    return output


def print_report(output: dict) -> None:
    meta = output["_meta"]
    channels = output["channels"]

    print(f"""
╔══════════════════════════════════════════════════╗
║         全国广电 CDN 自动化管理引擎 v2.0          ║
╚══════════════════════════════════════════════════╝

  总耗时        : {meta['elapsed_seconds']:.1f} 秒
  存活URL总数   : {meta['total_alive']:,}
  覆盖省份数    : {meta['provinces_covered']}
""")

    if meta.get("errors"):
        print(f"  错误数       : {len(meta['errors'])}")
        for err in meta["errors"][:5]:
            print(f"    ! {err}")

    print("\n  ── 各省存活 URL 统计 ──")
    for prov, chs in sorted(channels.items(), key=lambda x: -len(x[1])):
        print(f"  {prov}: {len(chs)} 条")

    print(f"\n  归集完成，共 {meta['total_alive']} 条存活 URL")


def print_heatmap(output: dict, cdn_domains: dict) -> None:
    """打印中国广电 CDN 覆盖热力图

    根据扫描结果和域名库，按省份维度输出覆盖状态：
      ✅ 绿色: 有存活源
      ⚠️ 黄色: 有域名但暂无存活
      ❌ 红色: 无域名库

    CCTV 作为国家级条目单独展示。
    """
    channels = output.get("channels", {})

    # 分离 CCTV 与省级条目
    province_keys = [k for k in cdn_domains.keys() if not k.startswith("_") and k != "央视CCTV"]
    has_cctv = "央视CCTV" in cdn_domains

    green = []   # (prov, count)
    yellow = []  # prov
    red = []     # prov (理论上不会出现，因域名库已覆盖)

    for key in province_keys:
        cfg = cdn_domains[key]
        basic = cfg.get("basic", {})
        pname = basic.get("province", cfg.get("province", key))
        alive_count = len(channels.get(pname, []))
        if alive_count > 0:
            green.append((pname, alive_count))
        else:
            yellow.append(pname)

    # 按存活数降序排列
    green.sort(key=lambda x: -x[1])

    # 统计
    green_count = len(green)
    yellow_count = len(yellow)
    red_count = len(red)

    # ANSI 颜色码
    C_GREEN = "\033[92m"
    C_YELLOW = "\033[93m"
    C_RED = "\033[91m"
    C_RESET = "\033[0m"
    C_BOLD = "\033[1m"
    C_CYAN = "\033[96m"

    print(f"""
╔══════════════════════════════════════════════════╗
║         中国广电 CDN 覆盖热力图                    ║
╚══════════════════════════════════════════════════╝
""")

    # ── 31 省网格 ──
    if green:
        print(f"  {C_GREEN}{C_BOLD}✅ 已覆盖 ({green_count} 省):{C_RESET}")
        for prov, count in green:
            print(f"    {C_GREEN}✅ {prov}: {count} 条存活{C_RESET}")

    if yellow:
        print(f"\n  {C_YELLOW}{C_BOLD}⚠️ 有域名无存活 ({yellow_count} 省):{C_RESET}")
        # 每行显示多个，节省空间
        line = "    "
        for i, prov in enumerate(yellow):
            line += f"{C_YELLOW}⚠️ {prov}{C_RESET}"
            if (i + 1) % 4 == 0:
                print(line)
                line = "    "
        if line.strip():
            print(line)

    if red:
        print(f"\n  {C_RED}{C_BOLD}❌ 无域名库 ({red_count} 省):{C_RESET}")
        line = "    "
        for i, prov in enumerate(red):
            line += f"{C_RED}❌ {prov}{C_RESET}"
            if (i + 1) % 4 == 0:
                print(line)
                line = "    "
        if line.strip():
            print(line)

    # ── CCTV 国家级单独展示 ──
    if has_cctv:
        cctv_cfg = cdn_domains["央视CCTV"]
        cctv_name = cctv_cfg.get("basic", {}).get("province", "央视")
        cctv_alive = len(channels.get(cctv_name, []))
        cctv_domains = cctv_cfg.get("method_1_probe", {}).get("domains", [])
        cctv_codes = cctv_cfg.get("method_1_probe", {}).get("probe_codes", [])
        cctv_known = cctv_cfg.get("method_c_social_hints", {}).get("known_urls", [])

        if cctv_alive > 0:
            cctv_status = f"{C_GREEN}✅{C_RESET}"
            cctv_detail = f"{cctv_alive} 条存活"
        elif cctv_domains or cctv_known:
            cctv_status = f"{C_YELLOW}⚠️{C_RESET}"
            cctv_detail = f"有 {len(cctv_domains)} 域名 + {len(cctv_known)} 社交URL 但暂无存活"
        else:
            cctv_status = f"{C_RED}❌{C_RESET}"
            cctv_detail = "无域名库"

        print(f"\n  {C_CYAN}{C_BOLD}📺 国家级 — 央视CCTV{C_RESET}")
        print(f"    {cctv_status} {cctv_name}: {cctv_detail}")
        if cctv_domains:
            print(f"    {C_CYAN}域名: {', '.join(cctv_domains)}{C_RESET}")
        if cctv_codes:
            print(f"    {C_CYAN}频道: {', '.join(cctv_codes)}{C_RESET}")

    # ── 汇总统计 ──
    total_provinces = green_count + yellow_count + red_count
    print(f"\n  {'─' * 40}")
    print(f"  {C_BOLD}统计: {C_GREEN}✅ {green_count} 省{C_RESET}  |  "
          f"{C_YELLOW}⚠️ {yellow_count} 省{C_RESET}  |  "
          f"{C_RED}❌ {red_count} 省{C_RESET}  |  "
          f"共 {total_provinces} 省")
    if has_cctv:
        print(f"  {C_CYAN}另含央视CCTV 国家级条目{C_RESET}")
    print()


# ── 主入口 ──────────────────────────────────

def main():
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="全国广电 CDN 自动化管理引擎 v2.0")
    parser.add_argument("--province", type=str, default=None, help="只扫描指定省份")
    parser.add_argument("--method", type=str, default=None,
                        choices=["method_1_probe", "method_a_api", "method_b_sniffer", "method_ipv6_probe"],
                        help="只使用指定维度")
    parser.add_argument("--workers", type=int, default=4, help="并行进程数（默认4）")
    parser.add_argument("--concurrency", type=int, default=20, help="每省并发数（默认20）")
    parser.add_argument("--timeout", type=int, default=5, help="超时秒数（默认5）")
    parser.add_argument("--dry-run", action="store_true", help="只打印任务计划，不执行探测")
    parser.add_argument("--merge-aggregator", action="store_true",
                        help="将 aggregator_results.json 并入 cdn_master.json（按省份归集，标记 method_d_aggregator）")
    parser.add_argument("--output", type=str, default="cdn_master.json", help="输出文件名")
    args = parser.parse_args()

    print("=" * 60)
    print("  全国广电 CDN 自动化管理引擎 v2.0 (SMMD v1)")
    print("=" * 60)

    # 加载域名库
    cdn_domains = cdn_explorer.load_cdn_domains()
    print(f"  已加载 {len(cdn_domains)} 个省份配置")

    # 确定要扫描的省份
    target_provinces = {}
    for key, cfg in cdn_domains.items():
        basic = cfg.get("basic", {})
        province_name = basic.get("province", cfg.get("province", key))
        if args.province and args.province not in key and args.province != province_name:
            continue
        target_provinces[key] = cfg

    print(f"  目标省份: {len(target_provinces)} 个")
    print(f"  并行进程: {args.workers}")
    print(f"  每省并发: {args.concurrency}")
    print()

    if args.dry_run:
        print("── DRY RUN 模式（只打印任务计划）──")
        for key, cfg in target_provinces.items():
            basic = cfg.get("basic", {})
            pname = basic.get("province", key)
            methods = basic.get("enabled_methods", ["method_1_probe"])
            if args.method:
                methods = [args.method] if args.method in methods else []
            print(f"  {pname}: {methods}")
            for method in methods:
                try:
                    tasks = cdn_explorer.build_probe_tasks(
                        {key: cfg}, target_province=pname, method=method
                    )
                    task_info = f"{len(tasks)} 个任务"
                    if method == "method_ipv6_probe" and tasks:
                        isps = set(t.get("isp", "?") for t in tasks)
                        task_info += f" (ISP: {', '.join(sorted(isps))})"
                    print(f"    {method}: {task_info}")
                except Exception as e:
                    print(f"    {method}: 错误 - {e}")
        # 即使 dry-run 也展示热力图（基于域名库）
        print_heatmap({"_meta": {}, "channels": {}}, cdn_domains)
        print("\nDRY RUN 完成，未执行实际探测。")
        return

    # 开始扫描
    print("── 开始多维度地毯式扫描 ──")
    t_start = time.monotonic()

    all_results = []

    # 省间并行
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for key, cfg in target_provinces.items():
            basic = cfg.get("basic", {})
            pname = basic.get("province", key)
            future = executor.submit(
                scan_province,
                key, cdn_domains, args.concurrency, args.timeout, args.method
            )
            futures[future] = pname

        completed = 0
        for future in as_completed(futures):
            pname = futures[future]
            completed += 1
            try:
                result = future.result()
                all_results.append(result)
                total = len(result["results"])
                stats_str = ", ".join(f"{m}:{c}" for m, c in result["stats"].items())
                print(f"  [{completed}/{len(target_provinces)}] {pname}: {total} 条存活 ({stats_str})")
            except Exception as e:
                print(f"  [{completed}/{len(target_provinces)}] {pname}: 扫描失败 - {e}")
                all_results.append({"province": pname, "results": [], "stats": {}, "errors": [str(e)]})

    elapsed = time.monotonic() - t_start

    # 归集结果
    output = merge_results(all_results, elapsed)

    # 合并聚合爬虫结果（如果启用）
    if args.merge_aggregator:
        output = merge_aggregator_results(output)

    # 打印报告
    print_report(output)

    # 打印覆盖热力图
    print_heatmap(output, cdn_domains)

    # 保存结果
    out_path = os.path.join(OUTPUT_DIR, args.output)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {out_path}")
    print(f"文件大小: {os.path.getsize(out_path):,} 字节")
    print("\n扫描完成。")


if __name__ == "__main__":
    main()
