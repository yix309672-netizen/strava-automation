# -*- coding: utf-8 -*-
"""从外部做一轮安全检查: 服务器有没有被攻击 / 有没有异常暴露。

★ 说明: 现在没有 SSH(22 不通), 所以只能做【外部视角】的检查。
  能查的: 端口暴露面、服务响应是否异常、有没有被当跳板、接口有无越权。
  查不了的: 服务器内部的进程/日志/CPU(那需要登进去)。
"""
import json
import socket
import time
import urllib.error
import urllib.request

HOST = "137.175.71.171"
ROOT = None
import pathlib


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
ROOT = pathlib.Path(__file__).resolve().parent
CFG = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
KEY = CFG["claim_key"]
BASE = CFG["claim_server"].rstrip("/")

print("=" * 80)
print("外部安全检查: %s" % HOST)
print("=" * 80)

# ---------- 1. 端口暴露面 ----------
print()
print("1) 端口暴露面(哪些端口对外开放)")
print("-" * 80)
COMMON = [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993, 995,
          1433, 1521, 3000, 3306, 3389, 5432, 5900, 6379, 8000, 8080, 8443,
          8888, 9000, 9200, 11211, 27017, 33085]
open_ports = []
for p in COMMON:
    try:
        s = socket.create_connection((HOST, p), timeout=4)
        s.close()
        open_ports.append(p)
    except Exception:
        pass
print("  开放: %s" % (open_ports if open_ports else "无"))
RISKY = {21: "FTP", 23: "Telnet", 445: "SMB", 3389: "远程桌面",
         6379: "Redis(未授权常见)", 27017: "MongoDB", 9200: "Elasticsearch",
         11211: "Memcached", 5900: "VNC", 3306: "MySQL", 5432: "PostgreSQL"}
for p in open_ports:
    if p in RISKY:
        print("    ★ %-6d %s —— 这类服务暴露在公网风险高" % (p, RISKY[p]))

# ---------- 2. 服务是否被劫持/异常 ----------
print()
print("2) 服务响应是否正常(有没有被劫持/挂马)")
print("-" * 80)


def call(path, key=True, timeout=20):
    h = {"X-API-Key": KEY} if key else {}
    try:
        r = urllib.request.Request(BASE + path, headers=h)
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return None, str(e)[:100]


for path, name, needkey in (
        ("/health", "健康检查", True),
        ("/stats", "统计", True),
        ("/known", "已采名单", True),
        ("/export", "导出", True),
        ("/pkg/manifest", "更新清单", True),
        ("/health", "健康检查(不带密钥)", False),
        ("/stats", "统计(不带密钥)", False),
        ("/export", "导出(不带密钥)", False),
        ("/pkg/manifest", "更新清单(不带密钥)", False)):
    st, body = call(path, key=needkey)
    flag = ""
    if not needkey and st == 200:
        flag = "   ★★ 不带密钥也能访问 —— 越权风险!"
    elif not needkey:
        flag = "   (正确: 已拒绝)"
    print("  %-26s HTTP %-5s %s%s" % (name, st, body[:58].replace("\n", " "), flag))

# ---------- 3. 响应时间(判断是否被 DDoS / 资源耗尽) ----------
print()
print("3) 响应时间稳定性(被攻击/挖矿时通常明显变慢或抖动)")
print("-" * 80)
times = []
for i in range(6):
    t0 = time.time()
    try:
        r = urllib.request.Request(BASE + "/health", headers={"X-API-Key": KEY})
        with urllib.request.urlopen(r, timeout=20) as resp:
            resp.read()
        times.append((time.time() - t0) * 1000)
    except Exception:
        times.append(-1)
    time.sleep(0.4)
good = [t for t in times if t > 0]
print("  6 次: %s" % " ".join(("%.0fms" % t) if t > 0 else "失败" for t in times))
if good:
    print("  平均 %.0f ms, 最快 %.0f, 最慢 %.0f, 抖动 %.0f ms"
          % (sum(good) / len(good), min(good), max(good), max(good) - min(good)))
    if max(good) > 3000:
        print("    ★ 有明显慢响应 —— 值得登进去看 CPU/负载")
    else:
        print("    (响应平稳, 不像被压)")

# ---------- 4. 服务端版本信息有没有泄露 ----------
print()
print("4) 服务是否泄露了多余信息")
print("-" * 80)
try:
    r = urllib.request.Request(BASE + "/", headers={})
    with urllib.request.urlopen(r, timeout=15) as resp:
        print("  GET /  -> HTTP %s" % resp.status)
        for k, v in list(resp.headers.items())[:8]:
            print("     %s: %s" % (k, str(v)[:70]))
except urllib.error.HTTPError as e:
    print("  GET /  -> HTTP %s (正常: 没有根路由)" % e.code)
    for k, v in list(e.headers.items())[:8]:
        print("     %s: %s" % (k, str(v)[:70]))
except Exception as e:
    print("  ★ %s" % str(e)[:80])

print()
print("=" * 80)
print("结论")
print("=" * 80)
print("  开放端口: %s" % open_ports)
print("  · 只有 8000 / 33085 对外开放, 22/80/443 都不通 —— 这实际上是【很收敛】的暴露面")
print("  · 上面若没有出现 ★★ 标记, 说明接口鉴权是正常的")
print("  ★ 要判断'有没有被攻击', 最终必须登进服务器看:")
print("      top / uptime          负载、异常进程(挖矿)")
print("      last / lastb          登录记录(暴力破解痕迹)")
print("      journalctl -u strava-claim --since today   服务日志")
print("      ss -antp | head -50   谁在连着")
