# IPTV Engine · 前后端一体化完整开发路线图 V2

> 文档路径：E:\VSCODE\iptv-engine\docs\ROADMAP_V2.md
> 版本：V2（整合前端需求后重新规划）
> 总课程：50节
> 更新时间：第10课完成后

---

## 一、系统全景架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        A程序（数据发动机）                        │
│                                                                   │
│  组件1：数据生产流水线（Python）          每6小时自动运行         │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐   │
│  │ 抓取 │→│ 解析 │→│标准化│→│深度  │→│ 分层 │→│ 合并输出 │   │
│  │ 20源 │ │ m3u  │ │频道名│ │测速  │ │ Tier │ │channels  │   │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────────┘   │
│                            ↑                                      │
│  新渠道注入：全国广电CDN + 酒店IPTV + FOFA udpxy                 │
│                                                                   │
│  组件2：动态解析API服务（Node.js）        常驻运行               │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ /api/bilibili/:id  /api/douyin/:id  /api/kuaishou/:id  │    │
│  │ 实时302重定向 → 平台CDN → 用户设备                      │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
          channels.json（开发期→本地 / 发布期→GitHub Pages）
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    B程序（Electron播放客户端）                    │
│  启动30秒后拉取 → 多备用线自动切换 → 5秒水滴滴灌测速 → 播放    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、前端对后端的硬性输出规范

以下是前端B程序明确要求后端必须满足的格式，后端所有开发都以此为终点目标。

### 2.1 channels.json 最终格式
```json
[
  {
    "name": "湖南卫视",
    "group": "卫视频道",
    "urls": [
      "http://最低延迟URL.m3u8",
      "http://备用线路1.m3u8",
      "http://备用线路2.m3u8"
    ],
    "delay_ms": 109.0,
    "logo": "https://gitee.com/suxuang/logo/raw/master/mylogo/湖南卫视.png",
    "epg_id": "hunanweishi",
    "source_tier": 1,
    "last_verified": "2026-06-20T14:00:00Z"
  },
  {
    "name": "B站经典电影",
    "group": "★ 24H轮播",
    "urls": [
      "http://[A程序IP]/api/bilibili/605"
    ],
    "delay_ms": 10.0,
    "logo": "https://...",
    "epg_id": "bilibili_605",
    "source_tier": 0
  }
]
```

### 2.2 字段约束
| 字段 | 要求 |
|------|------|
| name | 经normalizer.py标准化后的干净中文名 |
| group | 严格匹配分类体系，不允许"未分类" |
| urls | 数组，最多3条，按延迟从低到高排序 |
| delay_ms | 最优线路的延迟（ms），float |
| logo | 公网可访问的台标图片URL |
| epg_id | 对应EPG节目单的频道ID |
| source_tier | 1=官方CDN，2=平台，3=个人，4=IP直连，0=动态解析 |
| last_verified | ISO8601时间戳，B端用于判断数据新鲜度 |

### 2.3 测速深度要求（前端提出的关键需求）
- **不能只测M3U8是否200**，必须进一步验证：
  1. 检测302重定向最终URL是否包含黑名单关键词
  2. 解析M3U8，提取第一个.ts切片URL
  3. 实际请求该.ts切片，下载前10KB验证真实可播
- 只有通过以上三步的URL才能进入最终channels.json

### 2.4 输出路径（双阶段）
- **开发期**：`E:\vscode\iptv-project\data\channels.json`（直接写入B程序目录）
- **发布期**：同时推送到GitHub Pages，供B程序从网络拉取

---

## 三、50节完整课程规划

### ◆ 第一阶段：数据基础建设（第1-10课）✅ 已完成

| 课程 | 内容 | 状态 |
|------|------|------|
| 第1课 | asyncio异步抓取框架 | ✅ |
| 第2课 | 15个源存活率验证 | ✅ |
| 第3课 | 镜像竞速+20源扩充 | ✅ |
| 第4课 | GitHub API自动发现新仓库 | ✅ |
| 第5课 | m3u解析器+去重统计 | ✅ |
| 第6课 | 频道名标准化+别名库 | ✅ |
| 第7课 | 50线程并发测速 | ✅ |
| 第8课 | URL稳定性分层（Tier1-4） | ✅ |
| 第9课 | 浙江广电CDN规律挖掘 | ✅ |
| 第10课 | 系统评估+全局重新规划 | ✅ |

**阶段成果**：20源100%抓取，1,232个存活频道，398个Tier1官方CDN频道

---

### ◆ 第二阶段：测速引擎深度升级（第11-15课）

**目标**：彻底解决假台问题，把"能打开"升级为"真的能看"

#### 第11课：302重定向拦截器
**解决问题**：很多假源M3U8请求返回200，但实际302跳转到广告页

```python
# 核心逻辑：
async with session.get(url, allow_redirects=True) as resp:
    final_url = str(resp.url)  # 获取最终重定向URL
    blacklist = ["epg.pw", "freetv.fun", "catvod", "fongmi",
                 "ok.bkpcp.top", "livednow.com"]
    if any(b in final_url.lower() for b in blacklist):
        return None  # 判定为假台，丢弃
```

**输出**：升级后的speedtest.py，增加redirect_check()函数

---

#### 第12课：TS切片深度验证
**解决问题**：M3U8正常但.ts切片403/404，导致播放2秒后黑屏

```python
# 核心逻辑：
async def verify_ts_slice(session, m3u8_url):
    # 1. 下载M3U8内容
    m3u8_text = await fetch_text(session, m3u8_url)
    # 2. 提取第一个.ts切片URL
    ts_url = extract_first_ts(m3u8_text, base_url=m3u8_url)
    if not ts_url:
        return False
    # 3. 请求.ts切片，只下载前10KB
    async with session.get(ts_url, timeout=5) as resp:
        if resp.status == 200:
            await resp.content.read(10240)  # 只读10KB
            return True
    return False  # 403/404 = 假台
```

**注意**：此步骤会增加测速时间，需要评估总耗时是否在可接受范围内

**输出**：speedtest.py增加ts_verify()函数，可配置开关

---

#### 第13课：测速引擎性能压测
**目标**：加入302检测+TS验证后，测速总耗时评估

- 当前耗时：587秒（3,487个频道，仅测M3U8首包）
- 加入TS验证后预估：1,200-1,800秒（20-30分钟）
- 如果超出20分钟，需要优化策略：
  - 策略A：只对Tier3/4做TS验证（Tier1官方CDN跳过）
  - 策略B：限制每个频道只验证最快的1条URL
  - 策略C：TS验证独立成一个阶段，仅对通过M3U8测速的URL做

**输出**：优化后的测速引擎，确保6小时内跑完全流程

---

#### 第14课：台标Logo库建立
**解决问题**：前端需要每个频道的台标图片URL

**方案**：使用现成的开源台标库，不自己托管图片
```python
# 使用 suxuang/logo 仓库（已在现有源URL中出现过）
# 格式：https://gitee.com/suxuang/logo/raw/master/mylogo/{频道名}.png

LOGO_BASE = "https://gitee.com/suxuang/logo/raw/master/mylogo/"

def get_logo(std_name):
    # 标准频道名 → logo URL
    return f"{LOGO_BASE}{std_name}.png"
```

**输出**：normalizer.py增加get_logo()函数，logo字段写入channels.json

---

#### 第15课：EPG节目单ID映射
**目标**：为每个标准频道分配EPG ID，供B端接入节目单

**方案**：使用 epg.112114.xyz 或 diyp.112114.xyz 的标准EPG ID
```python
EPG_IDS = {
    "CCTV-1":  "cctv1",
    "CCTV-2":  "cctv2",
    "湖南卫视": "hunantv",
    "浙江卫视": "zhejiangsat",
    # ... 覆盖所有标准化后的频道名
}
```

**输出**：normalizer.py增加get_epg_id()函数

---

### ◆ 第三阶段：渠道C——全国广电CDN主动探测（第16-25课）

**目标**：不依赖GitHub数据，主动发现全国31省广电CDN的直播频道

#### 第16课：全国广电CDN域名研究报告
**这节课纯研究，不写代码**

研究内容：
- 各省广电局官方直播域名
- CDN服务商（阿里云/腾讯云/自建）
- URL路径规律

已知样本分析：
```
浙江：ali-m-l.cztv.com/channels/lantian/{code}/{res}.m3u8
湖南：dxtx.hntv.tv/...
哈尔滨：hrbtv.net/...
吉林：jlntv.cn/...
```

**输出**：docs/SOURCE_RESEARCH.md，全国广电CDN域名库

---

#### 第17课：全国广电CDN域名库文件
**基于第16课研究，建立机器可读的域名库**

```json
// src/data/cdn_domains.json
{
  "浙江": {
    "province": "浙江",
    "province_en": "Zhejiang",
    "domains": ["cztv.com", "cztvcloud.com"],
    "url_patterns": [
      "http://ali-m-l.cztv.com/channels/lantian/{code}/{res}.m3u8"
    ],
    "res_options": ["1080p", "720p", "360p"],
    "known_codes": {
      "channel001": "浙江卫视",
      "channel002": "浙江钱江",
      "SXyuyao1": "余姚新闻综合"
    },
    "discovery_method": "sequential_probe"
  },
  "湖南": {...},
  "广东": {...}
}
```

---

#### 第18课：广电CDN频道探测引擎
**核心功能**：对每个省的CDN，并发探测所有可能的频道代码

```python
# src/cdn_explorer.py 升级版（从浙江扩展到全国）

async def explore_province(province_config):
    """探测单个省的CDN频道"""
    # 对该省所有URL模式 × 所有可能code × 所有分辨率并发探测
    ...

async def explore_all():
    """并发探测全国所有省份"""
    tasks = [explore_province(cfg) for cfg in CDN_DOMAINS.values()]
    results = await asyncio.gather(*tasks)
    ...
```

---

#### 第19-23课：各省广电CDN专项接入
每节课专门研究并接入2-3个省，重点攻关URL规律复杂的省份

| 课程 | 覆盖省份 |
|------|----------|
| 第19课 | 广东、广西、福建 |
| 第20课 | 湖南、湖北、江西 |
| 第21课 | 江苏、安徽、山东 |
| 第22课 | 北京、天津、河北 |
| 第23课 | 四川、重庆、云南、贵州 |

---

#### 第24课：CDN探测结果验证与入库
- 对探测到的所有URL做TS切片深度验证
- 去重、标准化、分配Tier1标签
- 写入 `output/cdn_channels.json`

#### 第25课：CDN渠道与GitHub渠道首次合并测试
- 评估合并后总频道数提升幅度
- 目标：Tier1频道 398 → 1,000+

---

### ◆ 第四阶段：渠道B——酒店IPTV全国扩展（第26-30课）

**目标**：从13个已知酒店系统扩展到全国100+个

#### 第26课：酒店IPTV系统特征研究
已发现的系统特征：
- 端口：8000, 8009, 808, 880, 8088, 8800, 8801, 9003, 9901
- 路径：`/hls/{N}/index.m3u8` 或 `/tsfile/live/{N}.m3u8`
- 频道数：通常50-100个，覆盖全国卫视+本地台

研究内容：如何从公网发现这类系统（不使用FOFA API的方案）

---

#### 第27课：酒店IPTV发现方案——搜索引擎法
**不需要FOFA API，使用搜索引擎**

方法：Bing/百度搜索 `inurl:"/hls/" inurl:"index.m3u8"` 等特征关键词
或利用已知IP段推算：酒店IPTV通常在电信/联通的固定IP段

---

#### 第28课：酒店IPTV频道号→频道名映射库
**问题**：同一个hls/25在不同系统里可能是不同频道

**方案**：
- 对多个系统的相同频道号做交叉比对
- 下载M3U8内容，从title标签提取频道名
- 建立 `src/data/hotel_channel_map.json`

---

#### 第29课：酒店IPTV全国批量探测
- 对所有已知酒店IP并发探测hls/1到hls/200
- 自动匹配频道名（用第28课的映射库）
- 写入 `output/hotel_channels.json`

---

#### 第30课：酒店渠道合并与评估
- 酒店IPTV频道合并入主数据库
- 目标：总存活频道 1,232 → 2,500+

---

### ◆ 第五阶段：数据质量深度提升（第31-35课）

#### 第31课：分类体系完善（消灭"未分类"）
当前问题：大量频道group是"未分类"

完整分类体系（16个分组）：
```
央视频道 / 卫视频道 / 港澳台频道
地方台-华东 / 地方台-华南 / 地方台-华北
地方台-华中 / 地方台-华西 / 地方台-东北 / 地方台-西北
体育竞技 / 新闻资讯 / 少儿动漫
电影剧场 / 音乐文艺 / 纪实科教
```

---

#### 第32课：频道名别名库扩充
- 当前覆盖：CCTV系、卫视系、凤凰、TVB、台湾系
- 需要扩充：地方台别名（如"湖南经济电视台"→"湖南经济"）
- 引入fuzzy matching，处理轻微拼写差异

---

#### 第33课：URL存活率历史追踪
**问题**：现在每次测速结果是独立的，不知道哪些URL长期稳定

**方案**：建立历史记录
```json
// output/url_history.json
{
  "http://example.com/stream.m3u8": {
    "checks": 28,        // 历史检测次数
    "alive": 25,         // 存活次数
    "rate": 0.893,       // 存活率 89.3%
    "last_alive": "2026-06-20T12:00:00Z",
    "avg_delay_ms": 156
  }
}
```

---

#### 第34课：智能权重评分系统
基于多维度给每个URL打分，决定排序权重：
```
score = (
  tier_score * 0.4 +          # 来源稳定性（Tier1最高）
  survival_rate * 0.3 +        # 历史存活率
  (1 / delay_ms) * 0.2 +      # 速度（延迟越低越高）
  freshness_score * 0.1        # 数据新鲜度
)
```

---

#### 第35课：死亡频道自动追踪与重发现
**问题**：2,255个死亡频道就这么放弃了吗？

**方案**：对死亡频道做"持续关注"
- 记录死亡频道的频道名
- 每次新数据入库时，检查是否有新URL对应这些频道名
- 形成"待复活"队列

---

### ◆ 第六阶段：组件2——动态解析API服务（第36-42课）

**目标**：实现原始Spec文档里的B站、抖音、快手实时302解析

#### 第36课：Node.js + Fastify项目初始化
```
E:\VSCODE\iptv-api\
├── src\
│   ├── index.js       # 主入口
│   ├── bilibili.js    # B站解析
│   ├── douyin.js      # 抖音解析
│   └── kuaishou.js    # 快手解析
└── package.json
```

---

#### 第37课：B站直播解析接口
```
GET /api/bilibili/:room_id
→ 请求 B站API → 提取m3u8 → HTTP 302
```

---

#### 第38课：抖音直播解析接口
```
GET /api/douyin/:room_id
→ 请求直播页 → 提取hls_pull_url → HTTP 302
```

注意：抖音反爬严格，需要处理UA、Cookie等

---

#### 第39课：快手直播解析接口
```
GET /api/kuaishou/:room_id
→ 请求快手H5 → 提取播放地址 → HTTP 302
```

---

#### 第40课：解析接口缓存机制
**问题**：每次请求都实时解析，延迟高且容易被限流

**方案**：内存缓存，5分钟内复用同一个解析结果
```javascript
const cache = new Map();
// key: room_id, value: {url, expires_at}
```

---

#### 第41课：解析接口健壮性——降级方案
当实时解析失败时的处理：
- 返回上一次成功解析的缓存URL（即使已过期）
- 返回HTTP 503 + 错误信息（比静默失败好）
- 监控解析成功率，写入日志

---

#### 第42课：组件2部署方案
- 开发期：本地运行，B端直接访问 `http://localhost:3000/api/...`
- 发布期：Vercel/Cloudflare Workers免费部署
- channels.json里的动态频道URL格式：
  `http://[部署域名]/api/bilibili/605`

---

### ◆ 第七阶段：自动化调度与发布（第43-47课）

#### 第43课：scheduler.py——总调度器
**完整流程串联**：
```python
# src/scheduler.py
async def run_pipeline():
    print("=== 开始数据更新 ===")
    
    # 1. 抓取（fetcher.py）
    raw = await fetch_all()
    
    # 2. 解析（parser.py）
    channels = parse_m3u(raw)
    
    # 3. 标准化（normalizer.py）
    channels = [normalize_channel(ch) for ch in channels]
    
    # 4. CDN探测（cdn_explorer.py）
    cdn_chs = await explore_all_cdn()
    
    # 5. 酒店IPTV（hotel_scanner.py）
    hotel_chs = await scan_hotels()
    
    # 6. 合并（merger.py）
    master = merge_all(channels, cdn_chs, hotel_chs)
    
    # 7. 深度测速（speedtest.py，含302检测+TS验证）
    tested = await speed_test(master)
    
    # 8. 分层排序（url_tier.py）
    tiered = apply_tiers(tested)
    
    # 9. 输出（output_gen.py）
    generate_output(tiered)
    
    print("=== 数据更新完成 ===")
```

---

#### 第44课：Windows任务计划程序配置
```
# 一键配置命令（在cmd以管理员运行）
schtasks /create /tn "IPTV-Engine-Update" ^
  /tr "python E:\VSCODE\iptv-engine\src\scheduler.py" ^
  /sc hourly /mo 6 /st 00:00 /f

# 验证配置
schtasks /query /tn "IPTV-Engine-Update"

# 手动触发测试
schtasks /run /tn "IPTV-Engine-Update"
```

---

#### 第45课：运行日志与报告系统
每次运行自动生成报告：
```json
// output/run_report_20260620_140000.json
{
  "run_time": "2026-06-20T14:00:00Z",
  "duration_seconds": 847,
  "sources_fetched": "20/20",
  "total_channels": 3768,
  "alive_channels": 2341,
  "survival_rate": "62.1%",
  "tier1_channels": 856,
  "new_channels_found": 12,
  "channels_revived": 3,
  "output_file_size_kb": 892
}
```

保留最近7次运行报告，自动清理旧的。

---

#### 第46课：双输出路径配置
同时写入开发期和发布期两个路径：
```python
OUTPUT_PATHS = [
    # 开发期：直接写入B程序目录
    r"E:\vscode\iptv-project\data\channels.json",
    # 发布期：写入待推送目录
    r"E:\vscode\iptv-pages\channels.json",
]
```

---

#### 第47课：GitHub Pages自动推送
运行完成后自动git push更新：
```python
import subprocess

def push_to_github():
    cmds = [
        ["git", "-C", r"E:\vscode\iptv-pages", "add", "."],
        ["git", "-C", r"E:\vscode\iptv-pages", "commit",
         "-m", f"auto: update {datetime.now().isoformat()}"],
        ["git", "-C", r"E:\vscode\iptv-pages", "push"],
    ]
    for cmd in cmds:
        subprocess.run(cmd, check=True)
```

---

### ◆ 第八阶段：FOFA备用渠道接入（第48课）

#### 第48课：FOFA手动导出→批量探测
**不需要付费API，使用免费网页手动导出**

步骤：
1. 登录 fofa.info（免费账号）
2. 搜索：`body="udpxy" && country="CN"`
3. 手动导出结果CSV（免费账号可导出有限条数）
4. 脚本读取CSV，批量探测每个udpxy服务
5. 从udpxy的 `/status` 页面提取组播地址列表

---

### ◆ 第九阶段：系统集成测试与验收（第49-50课）

#### 第49课：全流程压力测试
- 连续跑7天，观察稳定性
- 验收标准：
  - 存活频道数 > 2,500个
  - Tier1官方CDN频道 > 1,000个
  - 全死率 < 25%（当前65%）
  - 单次运行时间 < 25分钟
  - 7天内自动发现新频道 > 50个

---

#### 第50课：文档整理与交付
输出最终文档：
- `docs/ARCHITECTURE.md` —— 系统架构说明
- `docs/API.md` —— 组件2 API文档
- `docs/DEPLOYMENT.md` —— 部署指南
- `docs/DATA_CONTRACT.md` —— 前后端数据格式约定

---

## 四、文件目录最终结构

```
E:\VSCODE\iptv-engine\
├── src\
│   ├── fetcher.py           ✅ 抓取器
│   ├── parser.py            ✅ 解析器
│   ├── normalizer.py        ✅ 标准化（待扩充logo/epg_id）
│   ├── speedtest.py         ✅ 测速器（第11-13课升级）
│   ├── url_tier.py          ✅ 分层器
│   ├── discover.py          ✅ 仓库发现（第18课升级）
│   ├── cdn_probe.py         ✅ CDN探测（已有）
│   ├── cztv_explorer.py     ✅ 浙江广电（待扩展全国）
│   ├── cdn_explorer.py      📋 第18课：全国广电CDN探测
│   ├── hotel_scanner.py     📋 第29课：酒店IPTV全国扫描
│   ├── merger.py            📋 第30/35课：多渠道合并
│   ├── output_gen.py        📋 第46课：最终格式输出
│   ├── scheduler.py         📋 第43课：总调度器
│   └── data\
│       ├── cdn_domains.json    📋 第17课：全国CDN域名库
│       ├── cdn_channels.json   📋 第24课：频道代码映射
│       ├── hotel_channel_map.json 📋 第28课：酒店频道号映射
│       └── known_repos.json    📋 第18课升级：仓库累积库
├── output\
│   ├── channels_tested.json    ✅ 测速结果（当前）
│   ├── channels_tiered.json    ✅ 分层结果（当前）
│   ├── cdn_channels.json       📋 第24课
│   ├── hotel_channels.json     📋 第29课
│   ├── channels_master.json    📋 第30课：合并主库
│   ├── url_history.json        📋 第33课：存活率历史
│   ├── channels.json           📋 第46课：B端最终输出
│   └── run_report_*.json       📋 第45课：运行报告
├── docs\
│   ├── ROADMAP_V2.md           ✅ 本文件
│   ├── SOURCE_RESEARCH.md      📋 第16课：全国广电CDN研究
│   ├── API.md                  📋 第50课
│   └── RUN_LOG.md              📋 运行日志摘要
└── E:\VSCODE\iptv-api\         📋 第36课：组件2 Node.js项目
    ├── src\
    │   ├── index.js
    │   ├── bilibili.js
    │   ├── douyin.js
    │   └── kuaishou.js
    └── package.json
```

---

## 五、里程碑目标

| 里程碑 | 完成时 | 存活频道 | Tier1比例 | 全死率 |
|--------|--------|----------|-----------|--------|
| 当前（第10课） | 已完成 | 1,232 | 32% | 65% |
| M1（第15课） | 假台清零 | 900+ | 35% | 30% |
| M2（第25课） | 全国广电CDN | 1,800+ | 55% | 25% |
| M3（第30课） | 酒店IPTV接入 | 2,500+ | 50% | 20% |
| M4（第42课） | 组件2完成 | 2,500+ | 50% | 20% |
| M5（第50课） | 全系统完成 | 3,000+ | 60% | 15% |

---

## 六、关键决策记录

| 决策 | 选择 | 原因 |
|------|------|------|
| 技术栈 | Python（组件1）+ Node.js（组件2） | 各擅其长 |
| 测速策略 | M3U8首包 + 302检测 + TS切片验证 | 彻底消灭假台 |
| URL上限 | 每频道最多3条进入channels.json | 前端要求 |
| Tier优先级 | Tier1→2→3→4，同Tier按延迟 | 稳定性优先 |
| 更新频率 | 每6小时一次 | 平衡新鲜度和性能 |
| 输出格式 | 含logo/epg_id/last_verified | 前端B程序要求 |
| FOFA | 手动导出CSV方式（免费） | 避免付费API |
| 目标用户 | 大陆+海外华人 | 全覆盖策略 |
| 开发期输出 | E:\vscode\iptv-project\data\ | 直接联调B程序 |
| 发布期输出 | GitHub Pages | 云端无感更新 |
