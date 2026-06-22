# 🛸 IPTV Engine 项目全景深度记忆 (2026-06-22 日间终态)

## 1. 项目核心背景

本项目目标是构建一个覆盖中国 31 省（由县到省）的广电 IPTV 数字化探测与高精洗白引擎。经过日间四轮迭代攻坚，已实现从"五维 CDN 探测"到"多源智能聚合 + 双轨制高精洗白清洗线"的完整跨越。

---

## 2. 核心架构：SMMD v2（多源智能聚合与双轨制高精洗白清洗线）

### 2.1 九大黄金 IPv4 订阅源池

`src/iptv_washer.py` 的 `SOURCES` 列表配置 9 个国内可直连的纯 IPv4 高产源，每个 GitHub Raw 链接均配备 `gh-proxy.com` 代理兜底：

| 批次 | 源名称 | 地址 | 特点 |
|------|--------|------|------|
| 第一批 | Guovin/iptv-api | `gd/output/ipv4/result.m3u` | 日更验证，酒店源/组播源筛选 |
| 第一批 | suxuang/myIPTV | `ipv4.m3u` | 典藏卫视专线，全覆盖省级卫视 |
| 第一批 | vbskycn/iptv | `tv/iptv4.txt` | 数千频道，全套央视+卫视 |
| 第一批 | frankwuzp/iptv-cn | `tv-ipv4-cmcc.m3u` | 移动宽带深度优化 |
| 第一批 | BurningC4/Chinese-IPTV | `TV-IPV4.m3u` | 纯 IPv4 央视卫视 |
| 第二批 | yuanzl77/IPTV | `live.m3u` | 日更级，13,534 个频道（超级大户） |
| 第二批 | joevess/IPTV | `m3u/iptv.m3u` | 家用网络优化，完整台标 EPG |
| 第二批 | YanG-1989/Gather | `tv.iill.top/m3u/Gather` | 国内高速直连，数百市县级地方台 |
| 第二批 | Kimentanm/aptv | `m3u/iptv.m3u` | APTV 官方精选纯净源 |

### 2.2 三级最严清洗流水线

```
Stage 1: 并发拉取 9 源 → M3U/TXT 混合解析 → MD5 URL 去重
Stage 2: Phase 1 (HEAD + #EXTM3U 校验) → Phase 2 (双轨制流验证)
Stage 3: 频道名标准化 → 央视/卫视/地方台/其他 → M3U + JSON 输出
```

#### Phase 1：HEAD + #EXTM3U 校验
- HEAD 请求：接受 200/405/403，其余判死
- GET 前 1024 字节：检查 `#EXTM3U` 标识

#### Phase 2：双轨制流验证器 (Dual-Track Stream Validator)

**轨道 1 — 标准 HLS 分片流**：
- 解析 M3U8 → 提取首个 `.ts` 子切片 → 并发下载 10KB 验证
- 适用于标准 HLS 直播流

**轨道 2 — 连续/直达流**：
- 触发条件：URL 以 `.flv` / `.ts` 结尾，或轨道 1 解析无子切片（降级）
- 直连主 URL，4 秒超时，读取前 10KB
- 特征匹配：
  - FLV：前 3 字节 == `b'FLV'`（魔数 `0x46 0x4C 0x56`）
  - TS：第 1 字节 == `0x47`（MPEG-TS 同步字）
  - M3U8：包含 `b'#EXTM3U'`
- 匹配成功 → 100% 存活

**成效**：Phase 2 通过率从 41.9% 暴涨至 **98.0%**，挽救 500+ 被误杀的连续媒体流。

### 2.3 频道分类引擎

`classify_channel()` 基于 `normalizer.py` 的标准化结果进行四级分类：
- **央视**：标准化后以 `CCTV` 开头
- **卫视**：在 `SATELLITE_ALIASES` 别名表中，或以"卫视"结尾
- **地方台**：包含省市名或地方台特征关键词
- **其他**：不匹配以上规则的频道

---

## 3. 最新战况数据（截至 2026-06-22 日间）

### 3.1 清洗流水线数据

| 指标 | v1.0 | v2.0 | v3.0 | **v4.0** |
|------|------|------|------|---------|
| 订阅源数 | 11 | 5 | 9 | **9** |
| 进场候选池 | ~900 | 2,155 | 15,746 | **15,746** |
| Phase 1 存活 | ~350 | 880 | 1,006 | **1,074** |
| Phase 2 存活 | 252 | 844 | 422 | **1,052** |
| Phase 2 通过率 | 72% | 95.9% | 41.9% | **98.0%** |
| 总耗时 | ~3min | ~2.4min | ~23.4min | **~20.2min** |

### 3.2 最终分类统计（v4.0）

| 分类 | 线路数 | 不同频道名数 |
|------|--------|------------|
| **央视** | 144 | 19 |
| **卫视** | 253 | 39 |
| **地方台** | 418 | 300 |
| **其他** | 237 | 179 |
| **总计** | **1,052** | **537** |

### 3.3 输出文件

- `output/cleaned_iptv_list.m3u`（212,825 bytes）— 标准 M3U，按央视/卫视/地方台/其他分组，含 `tvg-logo`、`tvg-id`、`group-title` 完整元数据
- `output/cleaned_channels.json`（278,321 bytes）— JSON 格式，含分类统计

---

## 4. 关键算法文件索引

| 文件 | 行数 | 核心功能 |
|------|------|---------|
| `src/iptv_washer.py` | 559 | 主清洗线（九大源拉取 → 三级验证 → 分类输出） |
| `src/parser.py` | 232 | M3U/TXT 混合格式解析 |
| `src/normalizer.py` | 428 | 频道名标准化、分类别名库、Logo/EPG 映射 |
| `src/config.py` | 66 | 路径常量、HEADERS、OUTPUT_DIR |
| `src/cdn_explorer.py` | 959 | CDN 域名探测引擎（SMMD v1 五维探测） |
| `src/data/cdn_domains.json` | — | CDN 域名库（94KB，分层结构） |

---

## 5. 架构演进路线

### 已完成
- ✅ SMMD v1：五维 CDN 探测引擎（`cdn_explorer.py`）
- ✅ SMMD v2 高精洗白清洗线（`iptv_washer.py`）
  - ✅ v2.0：纯 IPv4 黄金源替换（5 源，844 存活）
  - ✅ v3.0：九大超级源扩充（15,746 候选，Phase 1 破 1000）
  - ✅ v4.0：双轨制流验证器（1,052 存活，98% 通过率）

### 待开启
- 🔲 **GitHub Actions 云端定时清洗流水线**：无人值守定时执行 → 自动提交 M3U → jsDelivr CDN 分发 → TiviMate/PotPlayer 免拷贝自动订阅
- 🔲 **EPG 节目单绑定**：完善 `tvg-id` 映射，实现全自动 EPG 匹配
- 🔲 **yuanzl77 源高并发优化**：针对该源的海量频道优化拉取稳定性
- 🔲 **IPv6 链路恢复**：物理网卡绑定 + IPv6 探测（需原生 IPv6 环境）

---

## 6. 环境依赖

```
Python 3.x
aiohttp      # 异步 HTTP 客户端
psutil       # 物理网卡识别（后续版本）
```

---

## 7. 仓库信息

- **GitHub**: `https://github.com/zhaoyangzhao88-max/iptv-engine`
- **核心入口**: `python src/iptv_washer.py`
- **输出目录**: `output/`

---

*本文档由 Claude Code 于 2026-06-22 日间攻坚结束后自动生成，反映项目最新终态。*
