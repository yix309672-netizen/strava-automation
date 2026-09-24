# -*- coding: utf-8 -*-
"""AdsPower API Key 自检 —— 发给同事, 双击就能跑出结论。

为什么需要它:
    日志里只有一句 "Require api-key", 看不出到底是
      · key 没填 / 填错文件
      · AdsPower 客户端没开 / 端口不对
      · AdsPower 的【本地API】没启用
      · 客户端版本老, 不认 Authorization 请求头(只认 URL 里的 api_key 参数)
    这四种都可能报同一句话。这里逐个试, 把每一步的真实返回打出来。

用法:
    python _测_AdsPowerKey.py
    (或放在项目根目录双击这个 .py)
"""
import json
import pathlib
import socket
import time
import sys
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent
TIMEOUT = 12


def rule(t):
    print("=" * 74)
    print(t)
    print("=" * 74)


def find_cfg():
    """和引擎完全一样的查找顺序 —— 免得同事改了一个、程序读的是另一个"""
    for c in (ROOT / "config.json", ROOT / "配置" / "config.json",
              ROOT.parent / "配置" / "config.json", ROOT.parent / "config.json"):
        if c.exists():
            return c
    return None


def probe(base, path, key, mode):
    """按指定方式发一次请求, 返回 (http状态, 正文前160字)"""
    url = base + path
    headers = {}
    if mode in ("query", "both") and key:
        url += "&api_key=" + key
    if mode in ("header", "both"):
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body[:160]
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode("utf-8", "replace")[:160])
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:80])


def is_ok(st, body):
    """成功返回长这样: {"data":{"list":[...  —— 里面【没有】 "code":0 字段。

    ★ 我第一版按 '"code":0' 判成功, 结果把真实成功的返回全判成了失败
      (成功响应压根不带 code 字段)。现在按"有 data、且没有 code:-1"判。
    """
    b = body.replace(" ", "")
    return st == 200 and '"data"' in b and '"code":-1' not in b


def main():
    rule("一、环境")
    print("  脚本目录   : %s" % ROOT)
    cfg_p = find_cfg()
    print("  读到的配置 : %s" % (cfg_p or "★ 一个都没找到!"))
    cfg = {}
    if cfg_p:
        try:
            cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
        except Exception as e:
            print("  ★ 配置读不了: %s" % str(e)[:80])
    key = str(cfg.get("adspower_key") or "").strip()
    base = str(cfg.get("adspower_api")
               or "http://127.0.0.1:50325").strip().rstrip("/")
    print("  API 地址   : %s" % base)
    print("  Key 长度   : %d" % len(key))
    if key:
        print("  Key 样子   : %s...%s" % (key[:8], key[-4:]))
    else:
        print("  ★ Key 是空的 —— 就是它。往下看第二节确认路径对不对。")

    # 端口通不通
    try:
        host = urllib.parse.urlparse(base).hostname or "127.0.0.1"
        port = urllib.parse.urlparse(base).port or 50325
        s = socket.create_connection((host, port), timeout=5)
        s.close()
        print("  端口 %d   : 通 ✓ (AdsPower 客户端在跑)" % port)
    except Exception as e:
        print("  ★ 端口不通: %s" % str(e)[:70])
        print("     -> AdsPower 客户端没开, 或者本地API没启用")

    rule("二、config.json 里到底有没有 adspower_key")
    if cfg_p:
        raw = cfg_p.read_text(encoding="utf-8")
        print("  文件: %s" % cfg_p)
        print("  里面出现 \"adspower_key\" 吗: %s"
              % ("有" if '"adspower_key"' in raw else "★ 没有这个键!"))
        print("  它现在的值长度: %d" % len(str(cfg.get('adspower_key') or '')))
        print()
        print("  ★ 注意: 程序按上面这个顺序找 config.json, 【只认第一个存在的】。")
        print("    如果你改的是别的目录里的那份, 改了也没用。")
        for c in (ROOT / "config.json", ROOT / "配置" / "config.json",
                  ROOT.parent / "配置" / "config.json",
                  ROOT.parent / "config.json"):
            if c.exists():
                try:
                    d = json.loads(c.read_text(encoding="utf-8"))
                    k = str(d.get("adspower_key") or "")
                    mark = "← 程序用的是这份" if c == cfg_p else ""
                    print("     %-52s key长度=%d %s" % (str(c), len(k), mark))
                except Exception:
                    print("     %-52s (读不了)" % str(c))

    rule("三、四种发法各试一次(这是关键)")
    # ★ 路径必须是 /api/v1/user/list —— 这是引擎真正在调的接口。
    #   我第一版写成 /api/v1/browser/list, 那个路径在这版 AdsPower 上返回 404,
    #   会让人误以为"接口不通"。
    # ★ 每个请求之间等 1.6 秒: AdsPower 有 ~1 次/秒 的限流, 发太快会返回
    #   "Too many request per second", 把结论污染掉。
    path = "/api/v1/user/list?page=1&page_size=1"
    tests = (("不带 key(看它怎么拒绝)", "none", key),
             ("只用 请求头 Bearer", "header", key),
             ("只用 URL 参数 ?api_key=", "query", key),
             ("两种一起发", "both", key),
             ("★ 用【空 key】走请求头", "header", ""))
    good = []
    first_when_no_key = None
    for label, mode, k in tests:
        time.sleep(1.6)
        st, body = probe(base, path, k, mode)
        ok = is_ok(st, body)      # ★ 成功的返回里没有 "code":0 字段, 不能按它判
        if ok:
            good.append(label)
        if "空 key" in label:
            first_when_no_key = body
        print("  %-30s -> HTTP %-6s %s %s"
              % (label, st, "✓ 能用" if ok else "✗", body[:90]))

    if first_when_no_key and "Require api-key" in first_when_no_key:
        print()
        print("  ★★ 重点: 用【空 key】返回的正是 'Require api-key'。")
        print("     所以日志里那句 'Require api-key' 的含义是【程序没读到 key】,")
        print("     而不是「key 填错了」。看第二节: 程序读的是哪份 config.json、")
        print("     那个键长度是多少 —— 长度 0 就是没读到。")

    rule("四、结论")
    HDR = "只用 请求头 Bearer"
    QRY = "只用 URL 参数 ?api_key="
    if not key and not good:
        print("  ★ Key 是空的。填进 config.json 的 \"adspower_key\" 再重跑这个脚本。")
        print("    拿 key 的地方: AdsPower 客户端 → 设置 → 本地API → 复制那一串")
    elif good:
        print("  ✓ 这几种发法能用: %s" % "、".join(good))
        if HDR in good:
            print("  ✓ 请求头方式(token)能用 —— 这是程序默认用的方式, 说明 key 没问题。")
            print("    如果程序里还报 'Require api-key', 那就是【程序没读到这个 key】:")
            print("      · 改完 config.json 没重开程序(key 只在启动时读一次)")
            print("      · 或者改的不是第二节里标着 '← 程序用的是这份' 的那个文件")
        elif QRY in good:
            print("  ★ 你这台 AdsPower【只认 URL 参数】, 不认请求头 ——")
            print("    老版本客户端会这样。新版程序两种一起发, 已经兼容, 不用管。")
        else:
            print("  ★ 只有'两种一起发'能用, 单发都不行 ——")
            print("    比较少见。新版程序两种一起发, 已经兼容, 不用管。")
    else:
        print("  ★ 四种发法全部失败。看第三节的返回内容:")
        print("     · 全是 'Require api-key' -> AdsPower 的【本地API 没启用】:")
        print("         AdsPower 客户端 → 设置 → 本地API → 打开开关 → 重开客户端")
        print("     · 全是 'API Key mismatch' -> key 填的不对(重新复制一次)")
        print("     · 全是连接错误 -> 客户端没开, 或端口不是 50325")
    print()
    print("把这一整屏截图发给管理员。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("★ 意外错误: %s" % str(e)[:200])
    try:
        input("按回车退出...")
    except Exception:
        pass
