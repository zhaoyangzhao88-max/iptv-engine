import os

# ── 路径锚定 ──────────────────────────────────
# __file__ = src/config.py → dirname = src/ → dirname again = BASE_DIR
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
DATA_DIR = os.path.join(SRC_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# ── 自动环境准备 ──────────────────────────────
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 统一常量 ──────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0"}

SOURCE_LIST = [
    "https://raw.githubusercontent.com/Guovin/TV/gd/output/result.m3u",
    "https://raw.githubusercontent.com/CCSH/IPTV/main/live.m3u",
    "https://raw.githubusercontent.com/best-fan/iptv-sources/main/cn_all.m3u8",
    "https://raw.githubusercontent.com/best-fan/iptv-sources/main/cn_cctv.m3u8",
    "https://raw.githubusercontent.com/best-fan/iptv-sources/main/cn_province.m3u8",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u",
    "https://raw.githubusercontent.com/joevess/IPTV/main/iptv.m3u8",
    "https://raw.githubusercontent.com/hexinchuang/iptv/master/output/result.m3u",
    "https://raw.githubusercontent.com/FHWWC/FCLiveTool/main/直播源/国内地方台.m3u",
    "https://raw.githubusercontent.com/followheart/IPTV2/main/IPTV.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/main/Global.m3u",
    "https://raw.githubusercontent.com/4yt1k/m3u-autoupdate/master/output/result.m3u",
    "https://raw.githubusercontent.com/3377/IPTV/master/output/result.m3u",
    "https://raw.githubusercontent.com/tonnyli20/iptv_m3u/master/output/result.m3u",
    "https://raw.githubusercontent.com/st800820/iptv-api/master/output/result.m3u",
    "https://raw.githubusercontent.com/alexyanghx/TV/master/output/result.m3u",
    "https://raw.githubusercontent.com/xiaolong-nihao/IPTV-api/master/output/love.m3u",
]

FAILED_URLS = [
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/result.m3u",
    "https://raw.githubusercontent.com/yuanzl77/IPTV/main/live.m3u",
    "https://raw.githubusercontent.com/CCSH/IPTV/main/live.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://raw.githubusercontent.com/hexinchuang/iptv/master/output/result.m3u",
    "https://raw.githubusercontent.com/Rivens7/Livelist/master/live.m3u",
    "https://raw.githubusercontent.com/followheart/IPTV2/main/IPTV.m3u",
    "https://raw.githubusercontent.com/best-fan/iptv-sources/main/cn_all.m3u8",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/hk.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/main/Global.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/mo.m3u",
    "https://raw.githubusercontent.com/xisohi/CHINA-IPTV/main/unicast.m3u",
    "https://raw.githubusercontent.com/herbertwangh/IPTV-2025/main/tv.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    "https://raw.githubusercontent.com/YueChan/Live/main/IPTV.m3u",
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/tw.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/v.m3u",
    "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/hao.m3u",
    "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/zb.txt",
]


def output_path(filename: str) -> str:
    """返回 output 目录下的文件绝对路径（str 类型）"""
    return os.path.join(OUTPUT_DIR, filename)
