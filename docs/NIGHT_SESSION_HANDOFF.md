# 🌙 夜间接力交接棒 — IPTV Engine 项目

> **交接时间**：2026-06-22 日间攻坚结束后
> **交接人**：严总技术组
> **接棒人**：新电脑上的 Claude Code

---

## 一、交接语

恭喜！在你接棒之前，日间攻坚已经完成了史诗级的跨越：

- **进场候选池**：从 9 个黄金订阅源解析去重后获取了 **15,746 个唯一频道**
- **Phase 1 存活**：**1,074 个**（正式突破 1000+ 存活目标！）
- **Phase 2 存活**：**1,052 个**（三级最严清洗通过，98% 极高保留率）
- **精准分类**：央视 144 个、卫视 253 个（完美覆盖 39 个不同省级卫视）、地方台 418 个（涵盖 300 个不同市县级频道）、其他 237 个

核心突破是 **双轨制流验证器** 的引入，将 Phase 2 通过率从 41.9% 暴涨至 98.0%，挽救了 500+ 被误杀的连续媒体流（HTTP-FLV / 直接 TS）。

**你接棒时，项目已经跨越了 1000+ 纯净存活的黄金大关。** 今晚的任务是迈向终极闭环——云端自动化。

---

## 二、当前代码现状概述

### 2.1 `src/iptv_washer.py`（559 行）— 核心清洗线
- **版本**：IPTV Washer v4.0
- **功能**：九大黄金源并发拉取 → M3U/TXT 混合解析 → MD5 去重 → HEAD+#EXTM3U 校验 → 双轨制流验证 → 频道分类 → M3U+JSON 输出
- **关键函数**：
  - `fetch_and_parse_sources()`：并发拉取 9 源，gh-proxy 兜底
  - `validate_basic()`：Phase 1（HEAD + #EXTM3U）
  - `validate_deep()`：Phase 2 双轨制调度器
  - `_validate_continuous_stream()`：轨道 2（FLV/TS 连续流特征验证）
  - `classify_channel()`：四级分类（央视/卫视/地方台/其他）
- **输出**：`output/cleaned_iptv_list.m3u`（212KB）、`output/cleaned_channels.json`（278KB）

### 2.2 `src/cdn_explorer.py`（959 行）— CDN 探测引擎
- **版本**：SMMD v1 五维探测体系
- **功能**：域名模板扫描、API 探测、CDN 边缘节点 IP 段探测、社交媒体情报提取、聚合站回血
- **状态**：独立模块，与 `iptv_washer.py` 无直接耦合

### 2.3 `src/data/cdn_domains.json`（94,812 bytes）— CDN 域名库
- 分层结构：basic / method_1_probe / method_a_api / method_b_sniffer / method_c_social_hints / method_d_aggregator

### 2.4 辅助模块
- `src/parser.py`：M3U/TXT 混合格式解析
- `src/normalizer.py`：频道名标准化、SATELLITE_ALIASES 别名库、Logo/EPG 映射
- `src/config.py`：路径常量、HEADERS

---

## 三、新电脑运行前置环境自检指南

在开始任何开发之前，请依次执行以下自检步骤：

### 步骤 1：Python 环境检查
```bash
python --version
pip list | findstr aiohttp
```
确保 Python 3.8+ 和 aiohttp 已安装。如未安装：
```bash
pip install aiohttp
```

### 步骤 2：代码语法检查
```bash
cd E:\VSCODE\iptv-engine
python -m py_compile src/iptv_washer.py
python -m py_compile src/parser.py
python -m py_compile src/normalizer.py
```
确保无语法错误。

### 步骤 3：物理网卡识别
```bash
ipconfig /all
```
记录以下信息：
- **物理网卡名称**（如 `WLAN`、`以太网`、`Wi-Fi`）
- **当前分配的 IPv4 地址**（如 `192.168.1.xxx`）
- **是否有 IPv6 地址**（如 `2409:xxxx:xxxx:xxxx::`）

> ⚠️ 如果新电脑使用了 VPN/代理（如 singbox、clash），请确认物理网卡名称与日间环境不同，后续可能需要调整网卡绑定参数。

### 步骤 4：验证日间成果可复现
```bash
python src/iptv_washer.py
```
预期输出：进场 15,746 → Phase 1 存活 ≥ 1,000 → Phase 2 存活 ≥ 1,000，总耗时约 20 分钟。

---

## 四、今晚攻坚方向

### 🎯 核心主攻任务（终极闭环）

**编写 `.github/workflows/iptv_washer_cron.yml`，建立 GitHub Actions 云端无人值守定时清洗流水线。**

目标架构：
```
GitHub Actions (cron: 每天 06:00 CST)
  → 检出代码
  → pip install aiohttp
  → python src/iptv_washer.py
  → git add output/cleaned_iptv_list.m3u output/cleaned_channels.json
  → git commit -m "Auto update: YYYY-MM-DD HH:MM"
  → git push origin main
  → jsDelivr CDN 自动分发
      → https://cdn.jsdelivr.net/gh/zhaoyangzhao88-max/iptv-engine@main/output/cleaned_iptv_list.m3u
```

电视盒（TiviMate/PotPlayer）订阅 URL：
```
https://cdn.jsdelivr.net/gh/zhaoyangzhao88-max/iptv-engine@main/output/cleaned_iptv_list.m3u
```

实现要点：
1. 创建 `.github/workflows/` 目录和 `iptv_washer_cron.yml` 文件
2. 配置 `schedule` trigger（cron 语法，每天北京时间 06:00 = UTC 22:00 前一天）
3. 配置 `jobs`：检出 → 安装依赖 → 运行清洗 → 提交推送
4. 配置 `GITHUB_TOKEN` 权限（需 Settings → Actions → General → Workflow permissions 设为 Read and write）
5. 首次运行后验证 jsDelivr CDN 可访问

### 🔧 可选优化任务

1. **yuanzl77 源高并发优化**：该源贡献了 13,534 个频道（占总量 86%），但拉取时可能因并发过高被限流。可考虑：
   - 为该源单独设置更长的 FETCH_TIMEOUT
   - 分批拉取（先拉其他 8 源，再单独拉 yuanzl77）

2. **EPG 节目单完善**：`normalizer.py` 中的 `EPG_IDS` 映射目前仅覆盖央视和卫视，可补充地方台的 EPG ID。

---

## 五、一键接力启动提示词

> **以下提示词可直接复制给新电脑上的 Claude Code：**

```
【夜间接力启动】

你好！我正在继续 IPTV Engine 项目的夜间攻坚。以下是项目当前状态：

## 项目位置
E:\VSCODE\iptv-engine

## 当前版本
IPTV Washer v4.0 — 双轨制流验证器

## 日间成果
- 九大黄金 IPv4 订阅源 → 15,746 个候选频道
- 三级最严清洗（HEAD → #EXTM3U → 双轨制 FLV/TS/HLS）
- 最终存活 1,052 个零死链秒播级频道
- 央视 144 / 卫视 253 / 地方台 418 / 其他 237

## 代码文件
- 核心清洗线：src/iptv_washer.py（559 行）
- 解析模块：src/parser.py
- 标准化模块：src/normalizer.py
- 配置模块：src/config.py

## 今晚核心任务
编写 .github/workflows/iptv_washer_cron.yml，建立 GitHub Actions 云端无人值守定时清洗流水线：
1. 每天北京时间 06:00 自动触发
2. 运行 python src/iptv_washer.py
3. 将 output/cleaned_iptv_list.m3u 和 output/cleaned_channels.json 自动提交推送回仓库
4. 通过 jsDelivr CDN 实现电视盒免拷贝自动订阅

## 前置自检
请先执行以下检查：
1. python -m py_compile src/iptv_washer.py（语法检查）
2. ipconfig /all（识别物理网卡名称和 IP）
3. 确认 GitHub 仓库地址：https://github.com/zhaoyangzhao88-max/iptv-engine

请开始执行！
```

---

## 六、注意事项

1. **网卡动态性**：新电脑的网卡名称可能与原电脑不同。如果后续需要物理网卡绑定功能，请先用 `ipconfig /all` 确认名称。
2. **GitHub Token**：GitHub Actions 的自动推送需要仓库 Settings → Actions → General → Workflow permissions 设为 "Read and write"。
3. **jsDelivr CDN**：首次推送后，jsDelivr 需要几分钟缓存刷新。CDN URL 格式：`https://cdn.jsdelivr.net/gh/{user}/{repo}@main/{path}`
4. **安全提醒**：`iptv_washer.py` 中的 `validate_basic()` 会向大量外部 URL 发起 HEAD/GET 请求，属于正常行为。

---

*本文档由 Claude Code 于 2026-06-22 日间攻坚结束后生成，确保夜间接力无缝衔接。*
