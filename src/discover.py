import sys
sys.stdout.reconfigure(encoding='utf-8')

import urllib.request
import urllib.parse
import json
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/vnd.github.v3+json",
}

# 12组搜索词（仓库搜索）
REPO_QUERIES = [
    "iptv m3u 直播 中国",
    "iptv live m3u8 cctv china",
    "直播源 m3u 卫视 更新",
    "iptv 直播 央视 卫视 地方台",
    "china iptv live stream m3u playlist",
    "电视直播源 自动更新",
    "iptv源 每日更新 m3u",
    "直播 m3u8 cctv 卫视 ipv6",
    "tvbox iptv 直播源",
    "iptv-sources china live",
    "m3u playlist china television",
    "cniptv live channels m3u",
]

# Code Search词（搜索文件内容）
CODE_QUERIES = [
    "EXTM3U EXTINF CCTV filename:.m3u",
    "EXTM3U 卫视 filename:.m3u",
    "EXTM3U 央视 filename:.m3u8",
]

KNOWN_REPOS = {
    "Guovin/TV", "CCSH/IPTV", "best-fan/iptv-sources",
    "fanmingming/live", "yuanzl77/IPTV", "suxuang/myIPTV",
    "joevess/IPTV", "FHWWC/FCLiveTool", "hexinchuang/iptv",
    "followheart/IPTV2", "YueChan/Live", "iptv-org/iptv",
    "hujingguang/ChinaIPTV", "Ftindy/IPTV-URL",
    "billy21/Tvlist-awesome-m3u-m3u8", "vbskycn/iptv",
    "jia070310/4K-IPTV-M3U", "2010dainifei/IPTV",
    "Rivens7/Livelist", "xisohi/CHINA-IPTV",
    "herbertwangh/IPTV-2025",
}


def api_get(url: str) -> tuple:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            # 检查限速
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            data = json.loads(resp.read().decode())
            return data, remaining
    except Exception as e:
        print(f"    ⚠ 请求失败: {e}")
        return None, "?"


def get_m3u_files(owner: str, repo: str) -> list[str]:
    """
    检查五个位置：
    1. 根目录
    2. /output/ 子目录
    3. /tv/ 子目录
    4. /live/ 子目录
    5. /src/ 子目录
    返回所有 .m3u/.m3u8/.txt 的 raw URL
    """
    raw_urls = []
    for path in ["", "output", "tv", "live", "src"]:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        data, _ = api_get(url)
        if not data or not isinstance(data, list):
            continue
        for item in data:
            name = item.get("name", "").lower()
            if any(name.endswith(ext) for ext in [".m3u", ".m3u8"]):
                raw = item.get("download_url", "")
                if raw:
                    raw_urls.append(raw)
            # .txt 只要名字包含 iptv/live/tv/直播
            elif name.endswith(".txt"):
                keywords = ["iptv", "live", "tv", "直播", "频道", "channel"]
                if any(k in name for k in keywords):
                    raw = item.get("download_url", "")
                    if raw:
                        raw_urls.append(raw)
        time.sleep(0.5)
    return raw_urls


def main():
    print("=== GitHub IPTV仓库自动发现（升级版）===\n")
    start_time = time.time()

    discovered = {}

    # ── 第一阶段：仓库搜索 ──
    print("【第一阶段】仓库关键词搜索（12组）")
    for i, query in enumerate(REPO_QUERIES, 1):
        print(f"  [{i:02d}/{len(REPO_QUERIES)}] {query}")
        encoded = urllib.parse.quote(query)
        url = (f"https://api.github.com/search/repositories"
               f"?q={encoded}+fork:false"
               f"&sort=updated&order=desc&per_page=15")
        data, remaining = api_get(url)
        if not data:
            time.sleep(7)
            continue
        items = data.get("items", [])
        new_count = 0
        for repo in items:
            full_name = repo.get("full_name", "")
            stars = repo.get("stargazers_count", 0)
            updated = repo.get("updated_at", "")[:10]
            description = (repo.get("description") or "")[:80]

            if full_name in KNOWN_REPOS:
                continue
            if stars < 2:
                continue
            if updated < "2022-01-01":
                continue

            desc_lower = description.lower()
            name_lower = full_name.lower()
            keywords = ["iptv", "m3u", "直播", "live", "tv", "频道", "电视", "channel"]
            if not any(k in desc_lower + name_lower for k in keywords):
                continue

            if full_name not in discovered:
                discovered[full_name] = {
                    "stars": stars,
                    "updated": updated,
                    "description": description,
                    "files": [],
                    "source": "repo_search",
                }
                new_count += 1

        print(f"      → 本组新增 {new_count} 个，API剩余配额: {remaining}")
        time.sleep(7)

    # ── 第二阶段：Code Search ──
    print(f"\n【第二阶段】Code Search（文件内容搜索，3组）")
    for i, query in enumerate(CODE_QUERIES, 1):
        print(f"  [{i}/{len(CODE_QUERIES)}] {query}")
        encoded = urllib.parse.quote(query)
        url = (f"https://api.github.com/search/code"
               f"?q={encoded}&per_page=20")
        data, remaining = api_get(url)
        if not data:
            time.sleep(7)
            continue
        items = data.get("items", [])
        new_count = 0
        for item in items:
            repo_info = item.get("repository", {})
            full_name = repo_info.get("full_name", "")

            if full_name in KNOWN_REPOS:
                continue

            if full_name in discovered:
                # 直接记录文件URL
                raw_url = item.get("html_url", "").replace(
                    "github.com", "raw.githubusercontent.com"
                ).replace("/blob/", "/")
                if raw_url not in discovered[full_name]["files"]:
                    discovered[full_name]["files"].append(raw_url)
                continue

            stars = repo_info.get("stargazers_count", 0)
            description = (repo_info.get("description") or "")[:80]

            # Code Search结果直接记录文件URL
            raw_url = item.get("html_url", "").replace(
                "github.com", "raw.githubusercontent.com"
            ).replace("/blob/", "/")

            discovered[full_name] = {
                "stars": stars,
                "updated": "unknown",
                "description": description,
                "files": [raw_url] if raw_url else [],
                "source": "code_search",
            }
            new_count += 1

        print(f"      → 本组新增 {new_count} 个，API剩余配额: {remaining}")
        time.sleep(7)

    # ── 第三阶段：获取文件列表 ──
    print(f"\n【第三阶段】获取 {len(discovered)} 个新仓库的文件列表...")
    for full_name, info in discovered.items():
        if info["files"]:  # code search已有文件，跳过
            continue
        owner, repo = full_name.split("/", 1)
        files = get_m3u_files(owner, repo)
        info["files"] = files
        print(f"  {full_name}: 找到 {len(files)} 个文件")

    elapsed = time.time() - start_time

    # ── 输出结果 ──
    has_files = {k: v for k, v in discovered.items() if v["files"]}
    no_files = {k: v for k, v in discovered.items() if not v["files"]}

    print(f"""
============ 发现结果 ============
搜索方式    : 仓库搜索(12组) + Code Search(3组)
新发现仓库  : {len(discovered)} 个
有m3u文件   : {len(has_files)} 个
无m3u文件   : {len(no_files)} 个
""")

    print(f"【有文件的仓库】按Star排序：\n")
    for full_name, info in sorted(
            has_files.items(), key=lambda x: -x[1]["stars"]):
        print(f"  ★{info['stars']:,} | {info['updated']} "
              f"| [{info['source']}] {full_name}")
        print(f"  描述: {info['description']}")
        for f in info["files"]:
            print(f"  → {f}")
        print()

    print(f"【无文件仓库】（共{len(no_files)}个）：")
    for full_name, info in sorted(
            no_files.items(), key=lambda x: -x[1]["stars"]):
        print(f"  ★{info['stars']:,} | {full_name} | {info['description'][:50]}")

    print("\n=================================")
    print(f"\n总耗时: {elapsed:.1f} 秒")


if __name__ == "__main__":
    main()
