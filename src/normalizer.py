import sys

sys.stdout.reconfigure(encoding="utf-8")

import re

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第一步：预清洗（去除画质后缀和噪音）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def pre_clean(name: str) -> str:
    """
    去除以下噪音，返回干净名称：

    1. 括号内画质标注：(1080p) (720p) (576p) (576i) (540p)
       (480p) (360p) (2160p) (4K) (SD) (HD)
    2. 方括号内分辨率：[960*540] [1280*720] [786*576] 等
    3. [Not 24/7] [Geo-blocked] 等英文标注
    4. tvg-id= tvg-name= tvg-logo= group-title= 等m3u属性
       （有些源把属性写进了名字里）
    5. 多余空格，首尾strip
    """
    # 去除 tvg-*/group-title 属性污染（取最后一个逗号后的内容）
    if "tvg-" in name or "group-title=" in name:
        if "," in name:
            name = name.split(",")[-1].strip()

    # 去除括号内内容（画质/状态标注）
    name = re.sub(
        r"\s*\([^)]*(?:p|i|K|HD|SD|not|geo)[^)]*\)",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # 去除方括号内容（分辨率/状态标注）
    name = re.sub(r"\s*\[[^\]]*\]", "", name)

    # 去除 backup 标注
    name = re.sub(r"\s*backup\s*", "", name, flags=re.IGNORECASE)

    # 去除独立画质/状态后缀：1080P、720p、1080p、2160p 等
    name = re.sub(
        r"\s+(?:1080|720|576|540|480|360|2160)\s*(?:p|i)?\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # 去除 4K/8K/HD/FHD/SD/HDR 独立后缀（前有空格时）
    name = re.sub(
        r"\s+(4K|8K|HD|FHD|SD|HDR)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # 兼容“频道名4K”这种无空格后缀；但保留 CCTV-4K/CCTV-8K 这类频道本体
    if name.endswith(("4K", "8K", "HD", "FHD", "SD", "HDR")) and not re.match(r"^CCTV[-\s]?\d", name, flags=re.IGNORECASE):
        name = re.sub(r"(4K|8K|HD|FHD|SD|HDR)\s*$", "", name, flags=re.IGNORECASE).strip()

    # 合并空格
    name = re.sub(r"\s+", " ", name).strip()
    return name


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第二步：CCTV标准化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# CCTV数字频道标准名称映射
# key: 标准名  value: 该频道所有别名的识别规则（正则）
CCTV_CHANNELS = {
    "CCTV-1": r"^(cctv-?1|cctv-?1综合|中央1台|央视1套)$",
    "CCTV-2": r"^(cctv-?2|中央2台|央视2套|cctv-?2财经)$",
    "CCTV-3": r"^(cctv-?3|中央3台|cctv-?3综艺)$",
    "CCTV-4": r"^(cctv-?4|中央4台|cctv-?4中文国际|cctv-?4(国际)?(欧洲|美洲|asia)?)$",
    "CCTV-5": r"^(cctv-?5|中央5台|cctv-?5体育)$",
    "CCTV-5+": r"^(cctv-?5\+|cctv-?5\+(体育赛事|赛事台)?)$",
    "CCTV-6": r"^(cctv-?6|中央6台|cctv-?6电影)$",
    "CCTV-7": r"^(cctv-?7|中央7台|cctv-?7(国防军事)?)$",
    "CCTV-8": r"^(cctv-?8|中央8台|cctv-?8电视剧)$",
    "CCTV-9": r"^(cctv-?9|中央9台|cctv-?9纪录)$",
    "CCTV-10": r"^(cctv-?10|中央10台|cctv-?10科教)$",
    "CCTV-11": r"^(cctv-?11|中央11台|cctv-?11戏曲)$",
    "CCTV-12": r"^(cctv-?12|中央12台|cctv-?12社会与法)$",
    "CCTV-13": r"^(cctv-?13|中央13台|cctv-?13新闻)$",
    "CCTV-14": r"^(cctv-?14|中央14台|cctv-?14少儿)$",
    "CCTV-15": r"^(cctv-?15|中央15台|cctv-?15音乐)$",
    "CCTV-16": r"^(cctv-?16|中央16台|cctv-?16(奥林匹克)?)$",
    "CCTV-17": r"^(cctv-?17|中央17台|cctv-?17农业农村)$",
    # 特殊：4K和8K是独立频道，不归入CCTV-4/CCTV-8
    "CCTV-4K": r"^(cctv-?4k(真4k|超高清)?|cctv4k(真4k|超高清)?)$",
    "CCTV-8K": r"^(cctv-?8k(超高清)?|cctv8k(超高清)?)$",
}


def normalize_cctv(name: str) -> str | None:
    """
    若 name 匹配某个CCTV频道，返回标准名，否则返回None。

    匹配前先转小写，去除所有空格。
    """
    n = name.lower().replace(" ", "").replace("_", "")
    for std_name, pattern in CCTV_CHANNELS.items():
        if re.match(pattern, n):
            return std_name
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第三步：卫视标准化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 卫视别名映射：{标准名: [别名列表]}
SATELLITE_ALIASES = {
    "北京卫视": ["BRTV北京卫视", "BRTV 北京卫视", "北京卫视"],
    "东方卫视": ["东方卫视", "上海卫视"],
    "湖南卫视": ["湖南卫视"],
    "江苏卫视": ["江苏卫视"],
    "浙江卫视": ["浙江卫视"],
    "深圳卫视": ["深圳卫视"],
    "广东卫视": ["广东卫视"],
    "安徽卫视": ["安徽卫视"],
    "辽宁卫视": ["辽宁卫视"],
    "湖北卫视": ["湖北卫视"],
    "山东卫视": ["山东卫视"],
    "四川卫视": ["四川卫视"],
    "重庆卫视": ["重庆卫视"],
    "黑龙江卫视": ["黑龙江卫视", "黑龙卫视"],
    "天津卫视": ["天津卫视"],
    "河南卫视": ["河南卫视"],
    "河北卫视": ["河北卫视"],
    "陕西卫视": ["陕西卫视"],
    "江西卫视": ["江西卫视"],
    "广西卫视": ["广西卫视"],
    "贵州卫视": ["贵州卫视"],
    "云南卫视": ["云南卫视"],
    "内蒙古卫视": ["内蒙古卫视"],
    "吉林卫视": ["吉林卫视"],
    "新疆卫视": ["新疆卫视"],
    "西藏卫视": ["西藏卫视"],
    "青海卫视": ["青海卫视"],
    "宁夏卫视": ["宁夏卫视"],
    "甘肃卫视": ["甘肃卫视"],
    "海南卫视": ["海南卫视"],
    "山西卫视": ["山西卫视"],
    "福建卫视": ["东南卫视", "福建海峡卫视", "海峡卫视"],
    "三沙卫视": ["三沙卫视"],
    "厦门卫视": ["厦门卫视"],
    "延边卫视": ["延边卫视"],
    "康巴卫视": ["康巴卫视"],
}

# 构建反向查找表
_SAT_LOOKUP: dict[str, str] = {}
for std, aliases in SATELLITE_ALIASES.items():
    for alias in aliases:
        _SAT_LOOKUP[alias.replace(" ", "")] = std


def normalize_satellite(name: str) -> str | None:
    """
    若 name 匹配某卫视频道，返回标准名，否则返回None。

    匹配逻辑：
    1. 去空格后精确匹配别名表
    2. 若名称以"卫视"结尾且包含已知省市名，直接返回"XX卫视"
    """
    key = name.replace(" ", "")
    if key in _SAT_LOOKUP:
        return _SAT_LOOKUP[key]

    # 模糊：以"卫视"结尾，去掉4K/HD后缀后返回
    cleaned = re.sub(r"(4K|HD|FHD|高清)$", "", key).strip()
    if cleaned.endswith("卫视") and len(cleaned) >= 4:
        return cleaned
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 第四步：凤凰、TVB、台湾系标准化
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MISC_ALIASES = {
    "凤凰中文台": ["凤凰中文", "凤凰中文台", "凤凰中文高清"],
    "凤凰资讯台": ["凤凰资讯", "凤凰资讯台", "凤凰资讯高清"],
    "凤凰香港台": ["凤凰香港", "凤凰香港台", "凤凰香港高清"],
    "TVB翡翠台": ["TVB翡翠台", "翡翠台", "无线翡翠", "华丽翡翠台"],
    "TVB明珠台": ["TVB明珠台", "明珠台", "无线明珠", "TVBPearl"],
    "TVB星河台": ["TVB星河", "TVB无线星河", "TVBPlus", "TVB Plus"],
    "TVBS亚洲台": ["TVBS亚洲", "TVBS Asia"],
    "TVBS新闻台": ["TVBS新闻", "TVBS新闻台"],
    "TVBS欢乐台": ["TVBS欢乐", "TVBS欢乐台"],
    "台视": ["台视"],
    "中视": ["中视"],
    "华视": ["华视"],
    "民视": ["民视", "民视台湾", "民视台湾台", "民视第一", "民视第一台"],
}

_MISC_LOOKUP: dict[str, str] = {}
for std, aliases in MISC_ALIASES.items():
    for alias in aliases:
        _MISC_LOOKUP[alias.replace(" ", "")] = std


def normalize_misc(name: str) -> str | None:
    key = name.replace(" ", "")
    return _MISC_LOOKUP.get(key)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 主入口：标准化一个频道名
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def normalize(raw_name: str) -> str:
    """
    完整标准化流程：
    1. pre_clean：去画质后缀、噪音
    2. normalize_cctv：CCTV系匹配
    3. normalize_satellite：卫视系匹配
    4. normalize_misc：凤凰/TVB/台湾系匹配
    5. 都不匹配则返回pre_clean后的结果
    """
    cleaned = pre_clean(raw_name)
    result = normalize_cctv(cleaned) or normalize_satellite(cleaned) or normalize_misc(cleaned) or cleaned
    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 台标Logo库
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

LOGO_BASE = "https://gitee.com/suxuang/logo/raw/master/mylogo/"

# 特殊映射：标准频道名 → logo文件名（文件名与频道名不一致时才需要配置）
LOGO_NAME_OVERRIDES = {
    "CCTV-1": "CCTV1",
    "CCTV-2": "CCTV2",
    "CCTV-3": "CCTV3",
    "CCTV-4": "CCTV4",
    "CCTV-5": "CCTV5",
    "CCTV-5+": "CCTV5+",
    "CCTV-6": "CCTV6",
    "CCTV-7": "CCTV7",
    "CCTV-8": "CCTV8",
    "CCTV-9": "CCTV9",
    "CCTV-10": "CCTV10",
    "CCTV-11": "CCTV11",
    "CCTV-12": "CCTV12",
    "CCTV-13": "CCTV13",
    "CCTV-14": "CCTV14",
    "CCTV-15": "CCTV15",
    "CCTV-16": "CCTV16",
    "CCTV-17": "CCTV17",
    "CCTV-4K": "CCTV4K",
    "CCTV-8K": "CCTV8K",
    "东方卫视": "东方卫视",
    "凤凰中文台": "凤凰中文",
    "凤凰资讯台": "凤凰资讯",
    "凤凰香港台": "凤凰香港",
    "TVB翡翠台": "翡翠台",
    "TVB明珠台": "明珠台",
}


def get_logo(std_name: str) -> str:
    """
    根据标准频道名返回台标URL。

    优先查 LOGO_NAME_OVERRIDES，找不到则直接用标准名作为文件名。
    返回格式：https://gitee.com/suxuang/logo/raw/master/mylogo/{name}.png
    """
    file_name = LOGO_NAME_OVERRIDES.get(std_name, std_name)
    return f"{LOGO_BASE}{file_name}.png"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# EPG节目单ID映射
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EPG_IDS: dict[str, str] = {
    # CCTV系
    "CCTV-1": "cctv1",
    "CCTV-2": "cctv2",
    "CCTV-3": "cctv3",
    "CCTV-4": "cctv4",
    "CCTV-5": "cctv5",
    "CCTV-5+": "cctv5plus",
    "CCTV-6": "cctv6",
    "CCTV-7": "cctv7",
    "CCTV-8": "cctv8",
    "CCTV-9": "cctv9",
    "CCTV-10": "cctv10",
    "CCTV-11": "cctv11",
    "CCTV-12": "cctv12",
    "CCTV-13": "cctv13",
    "CCTV-14": "cctv14",
    "CCTV-15": "cctv15",
    "CCTV-16": "cctv16",
    "CCTV-17": "cctv17",
    "CCTV-4K": "cctv4k",
    "CCTV-8K": "cctv8k",
    # 卫视系
    "北京卫视": "brtv",
    "东方卫视": "dongfangweishi",
    "湖南卫视": "hunantv",
    "江苏卫视": "jssat",
    "浙江卫视": "zjstv",
    "深圳卫视": "sztv",
    "广东卫视": "gdtv",
    "安徽卫视": "ahtv",
    "辽宁卫视": "lntv",
    "湖北卫视": "hbtv",
    "山东卫视": "sdtv",
    "四川卫视": "sctv",
    "重庆卫视": "cqtv",
    "黑龙江卫视": "hljtv",
    "天津卫视": "tjtv",
    "河南卫视": "henanavtv",
    "河北卫视": "hebei",
    "陕西卫视": "sxrtv",
    "江西卫视": "jxtv",
    "广西卫视": "gxtv",
    "贵州卫视": "gztv",
    "云南卫视": "yntv",
    "内蒙古卫视": "nmengtv",
    "吉林卫视": "jltv",
    "新疆卫视": "xjtv",
    "西藏卫视": "xizang",
    "青海卫视": "qhtv",
    "宁夏卫视": "nxtv",
    "甘肃卫视": "gstv",
    "海南卫视": "hainantv",
    "山西卫视": "shanxi",
    "福建卫视": "fjtv",
    "三沙卫视": "sansha",
    # 港澳台
    "凤凰中文台": "fhzw",
    "凤凰资讯台": "fhzx",
    "TVB翡翠台": "tvbjade",
    "TVB明珠台": "tvbpearl",
    "TVBS亚洲台": "tvbsasia",
    "TVBS新闻台": "tvbsnews",
    # 扩展频道
    "广东体育": "gdty",
    "深圳体育": "szty",
    "北京卡酷": "kaku",
    "嘉佳卡通": "jiajia",
    "金鹰卡通": "jinying",
}


def get_epg_id(std_name: str) -> str:
    """
    根据标准频道名返回EPG ID。

    优先查 EPG_IDS，找不到则返回空字符串""。
    """
    return EPG_IDS.get(std_name, "")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 自测：验证别名库效果
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    TEST_CASES = [
        # 输入                        期望输出
        ("CCTV1", "CCTV-1"),
        ("CCTV-1 (1080p)", "CCTV-1"),
        ("CCTV-1 综合", "CCTV-1"),
        ("中央1台", "CCTV-1"),
        ("CCTV-4K (1080p)", "CCTV-4K"),
        ("CCTV4K超高清", "CCTV-4K"),
        ("CCTV-8K 超高清", "CCTV-8K"),
        ("CCTV-5+ 体育赛事", "CCTV-5+"),
        ("CCTV5+赛事台", "CCTV-5+"),
        ("CCTV-16 奥林匹克", "CCTV-16"),
        ("湖南卫视4K", "湖南卫视"),
        ("BRTV 北京卫视 (1080p)", "北京卫视"),
        ("黑龙卫视 (720p)", "黑龙江卫视"),
        ("东南卫视 (2160p)", "福建卫视"),
        ("云南卫视 (576p) [Not 24/7]", "云南卫视"),
        ("凤凰中文高清", "凤凰中文台"),
        ("翡翠台4K", "TVB翡翠台"),
        ("TVB翡翠台 1080P", "TVB翡翠台"),
        ("TVBS新闻台", "TVBS新闻台"),
        ("民视第一台", "民视"),
        # 不应被修改的
        ("CCTV风云足球", "CCTV风云足球"),
        ("CCTV怀旧剧场", "CCTV怀旧剧场"),
        ("广东体育", "广东体育"),
        ("成都新闻综合", "成都新闻综合"),
        (
            'tvg-id="云南卫视" tvg-name="云南卫视" tvg-logo="xxx" group-title="卫视频道",云南卫视',
            "云南卫视",
        ),
    ]

    print("=== normalizer.py 自测 ===\n")
    passed = 0
    failed = 0
    for raw, expected in TEST_CASES:
        result = normalize(raw)
        ok = result == expected
        status = "✓" if ok else "✗"
        if ok:
            passed += 1
        else:
            failed += 1
        print(
            f"  {status} [{raw[:40]:<40}]  →  {result}"
            + (f"  (期望: {expected})" if not ok else "")
        )
    print(f"\n结果: {passed} 通过 / {failed} 失败 / 共 {len(TEST_CASES)} 项")
    print("\n=== 自测完毕 ===")

    print("\n=== Logo & EPG ID 验证 ===")

    test_channels = [
        "CCTV-1", "CCTV-5+", "CCTV-4K",
        "湖南卫视", "凤凰中文台", "TVB翡翠台", "广东体育"
    ]

    for name in test_channels:
        logo = get_logo(name)
        epg = get_epg_id(name)
        print(f"  {name}")
        print(f"    logo:   {logo}")
        print(f"    epg_id: {epg if epg else '(无映射)'}")
