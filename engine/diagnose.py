import sys
import urllib.request
import time

import config

FAILED_URLS = config.FAILED_URLS


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    print("=== 串行诊断（每个URL最长60秒）===\n")

    results = {"alive": [], "dead_404": [], "dead_timeout": [], "dead_other": []}

    for i, url in enumerate(FAILED_URLS, 1):
        short = url.split("githubusercontent.com/")[1]
        print(f"[{i:02d}/{len(FAILED_URLS)}] 测试: {short}")
        t = time.time()
        try:
            req = urllib.request.Request(url, headers=config.HEADERS)
            with urllib.request.urlopen(req, timeout=60) as resp:
                status = resp.status
                # 只读前1KB判断格式，不下载完整文件
                chunk = resp.read(1024).decode("utf-8", errors="ignore")
                elapsed = int((time.time() - t) * 1000)
                # 判断是否是真实m3u内容
                is_m3u = "#EXTM3U" in chunk or "#EXTINF" in chunk
                content_len = resp.headers.get("Content-Length", "未知")
                print(
                    f"  -> OK HTTP {status} | {elapsed}ms | size:{content_len} | {'M3U' if is_m3u else 'NOT M3U'}"
                )
                results["alive"].append((url, content_len, is_m3u))
        except urllib.error.HTTPError as e:
            elapsed = int((time.time() - t) * 1000)
            print(f"  -> FAIL HTTP {e.code} | {elapsed}ms")
            results["dead_404"].append(url)
        except Exception as e:
            elapsed = int((time.time() - t) * 1000)
            err_type = type(e).__name__
            print(f"  -> FAIL {err_type} | {elapsed}ms")
            if "Timeout" in err_type or "timeout" in str(e).lower():
                results["dead_timeout"].append(url)
            else:
                results["dead_other"].append((url, str(e)))

    print(
        f"""
============ 诊断结果 ============
存活（可访问）  : {len(results['alive'])} 个
死链（404）    : {len(results['dead_404'])} 个
真超时（60秒）  : {len(results['dead_timeout'])} 个
其他错误       : {len(results['dead_other'])} 个
存活URL详情："""
    )
    for url, size, is_m3u in results["alive"]:
        short = url.split("githubusercontent.com/")[1]
        print(f"  OK {short} | {size} bytes | {'M3U' if is_m3u else 'NOT M3U'}")

    print("\n死链URL：")
    for url in results["dead_404"]:
        print(f"  X {url.split('githubusercontent.com/')[1]}")

    print("\n真超时URL（60秒内无响应，建议彻底放弃）：")
    for url in results["dead_timeout"]:
        print(f"  X {url.split('githubusercontent.com/')[1]}")

    print("\n其他错误：")
    for url, err in results["dead_other"]:
        print(f"  X {url.split('githubusercontent.com/')[1]} -> {err}")

    print("=================================")


if __name__ == "__main__":
    main()
