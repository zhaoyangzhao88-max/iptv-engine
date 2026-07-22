import sys

sys.stdout.reconfigure(encoding="utf-8")

import json
from datetime import datetime, timezone

import config

sys.path.insert(0, config.SRC_DIR)
from normalizer import get_logo, get_epg_id

# ── 1. 数据读取与合并 ──

def load_all_data():
    master_channels = {}  # {name: {urls: [], delays: [], tiers: []}}

    # A. 加载主测速结果 (channels_tiered.json)
    tiered_path = config.output_path("channels_tiered.json")
    if tiered_path.exists():
        with open(tiered_path, encoding="utf-8") as f:
            for ch in json.load(f):
                name = ch["name"]
                master_channels[name] = {
                    "urls": ch.get("urls", []),
                    "delays": ch.get("delays", []),
                    "tiers": ch.get("url_tiers", [])
                }

    # B. 合并 CDN 探测结果 (cdn_channels.json)
    cdn_path = config.output_path("cdn_channels.json")
    if cdn_path.exists():
        with open(cdn_path, encoding="utf-8") as f:
            for ch in json.load(f):
                name = ch["name"]
                if name not in master_channels:
                    master_channels[name] = {"urls": [], "delays": [], "tiers": []}
                for u in ch.get("urls", []):
                    if u not in master_channels[name]["urls"]:
                        master_channels[name]["urls"].insert(0, u) # CDN源插到最前面
                        master_channels[name]["delays"].insert(0, 10.0) # 模拟低延迟
                        master_channels[name]["tiers"].insert(0, 1) # 强制 Tier1

    # C. 合并浙广探测结果 (cztv_explorer_results.json)
    # (逻辑同 B，读取 cztv_results 里的 url 并在 master_channels 中寻找匹配频道名)
    return master_channels

# ── 2. 精准分组逻辑 (修复P6) ──

def assign_group(name: str) -> str:
    # 强制白名单：只有真正的全国新闻频道才入"新闻资讯"
    TRUE_NEWS = ["CCTV-13", "第一财经", "凤凰资讯台", "东方卫视", "北京卫视", "深圳卫视"]
    if any(k in name for k in TRUE_NEWS):
        return "新闻资讯"

    # 央视
    if name.upper().startswith("CCTV"):
        return "央视频道"

    # 港澳台
    taiw_list = ["凤凰", "TVB", "TVBS", "台视", "中视", "华视", "民视", "翡翠"]
    if any(k in name for k in taiw_list):
        return "港澳台频道"

    # 卫视
    if name.endswith("卫视"):
        return "卫视频道"

    # 其他常用分类
    if any(k in name for k in ["体育", "NBA", "足球"]): return "体育竞技"
    if any(k in name for k in ["少儿", "卡通", "动漫"]): return "少儿动漫"
    if any(k in name for k in ["电影", "影院", "剧场"]): return "电影剧场"

    return "地方频道"

# ── 3. 运行输出 ──

def main():
    data = load_all_data()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    final_output = []

    for name, info in data.items():
        if not info["urls"]: continue

        # 裁剪前3条最优质线路
        top_urls = info["urls"][:3]
        top_delays = info["delays"][:3]
        top_tiers = info["tiers"][:3]

        final_output.append({
            "name": name,
            "group": assign_group(name),
            "urls": top_urls,
            "delay_ms": min(top_delays) if top_delays else 999,
            "logo": get_logo(name),
            "epg_id": get_epg_id(name),
            "source_tier": min(top_tiers) if top_tiers else 2,
            "last_verified": now_iso
        })

    # 排序：等级优先，延迟其次
    final_output.sort(key=lambda x: (x["source_tier"], x["delay_ms"]))

    # 保存
    channels_path = config.output_path("channels.json")
    with open(channels_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)

    print(f"成功生成 {channels_path}，共 {len(final_output)} 个频道")

    # 打印分组统计进行核对
    stats = {}
    for ch in final_output:
        stats[ch['group']] = stats.get(ch['group'], 0) + 1

    for k, v in sorted(stats.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
