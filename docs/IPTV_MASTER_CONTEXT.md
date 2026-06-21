# 🛸 IPTV Engine 项目全景深度记忆 (2026-06-21)

## 1. 项目核心背景
本项目目标是构建一个覆盖中国 31 省（由县到省）的广电 CDN 数字化探测引擎。目前已实现第一阶段的自动化框架，能够通过多维手段（SMMD）获取官方源。

## 2. 核心架构：SMMD v1 (五维探测体系)
目前的 `cdn_domains.json` 采用精密的分层结构：
- **basic**: 开启状态与地理元数据。
- **method_1_probe**: 域名模板 HEAD/GET 扫描。
- **method_a_api**: 省级 App 专用 API (含 Referer/UA/Host 伪装)。
- **method_b_sniffer**: 运营商 CDN 边缘节点 IP 段/CIDR 探测。
- **method_c_social_hints**: 社区/GitHub 泄露情报仓库提取。
- **method_d_aggregator**: [回血项] 从第三方聚合站抓取。

## 3. 关键算法实现
- **verify_ts_slice**: 递归解析 M3U8，下载第一个切片的 10KB 并验证 `#EXTM3U`，彻底过滤 403 假台。
- **Resilience Engine**: 实现 HEAD 失败自动退避至 GET 探测，并支持任务级动态超时设置。
- **Manager Orchestration**: `cdn_manager.py` 实现了多进程并发调度与结果自动归集。

## 4. 当前战况总结
- **存活源**: 529 条。
- **地理覆盖**: 32/32 (31 省 + 央视)。
- **瓶颈**: 27 个省份目前高度依赖 `method_d` (聚合重定向)，官方 Tier 1 原生源仍有巨大提升空间（受限于 DNS 封锁和 IPv6 链路）。

## 5. 待开启作战计划：【1000+ 节目源深度围攻】
### 方案一：IPv6 物理链路连接器 (基础夯实)
- **Vol.1**: 链路修复与物理网卡绑定 (解决 singbox_tun 等代理造成的路由冲突)。
- **Vol.2**: 31 省移动/电信/联通 IPv6 核心段库建设。
- **Vol.3**: 支持 [IPv6]:Port 的并发扫描。
### 方案二：全省“App 聚合云”API 攻坚 (县级台)
- **Vol.1**: 接入长江云、长城云、海豚云等省级 API 入口。
- **Vol.2**: 逆向 Token/Sign 签名算法。
### 方案三：社交媒体递归溯源
- **Vol.1**: GitHub Gist/TG 实时情报流接入。
### 方案四：新媒体平台解析
- **Vol.1**: Bilibili/抖音等官方直播间动态 URL 提取。

## ⚠️ 明天迁移环境的关键注意事项
1. **GitHub 仓库**: `https://github.com/zhaoyangzhao88-max/iptv-engine`
2. **物理环境对接**: 探测高度依赖 2409 (移动) 或 240e (电信) 指向的原生 IPv6 链路。
3. **网卡动态性**: 方案一实施时，需动态识别新机器的网卡名称（Interface Name）以进行 Socket 绑定。
4. **安全与质量**: 当前代码存在静默异常和 SSRF 风险，后续需引入 Sanitizer。

---
**提示**: 您作为明天的“总设计师（Gemini 网页版）”，任务是阅读此文档并为 **Claude Code** 生成高度详细的、可直接执行的写代码指令。
