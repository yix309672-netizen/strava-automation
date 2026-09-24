# -*- coding: utf-8 -*-
"""查: 为什么"一键推送"之后同事还是老版本。

思路: 站在【老客户端】的角度, 看它能不能认出这个新包。
核心怀疑: /pkg/manifest 的响应结构变了, 老 update.py 解析不了 -> 静默跳过。
"""
import hashlib
import io
import json
import urllib.request
import zipfile

CFG = json.loads(open("配置/config.json", encoding="utf-8").read())
SRV = CFG["claim_server"].rstrip("/")
KEY = CFG["claim_key"]
H = {"X-API-Key": KEY}


def get(path, timeout=180):
    with urllib.request.urlopen(
            urllib.request.Request(SRV + path, headers=H), timeout=timeout) as r:
        return r.read()


print("=" * 82)
print("1) 服务器 manifest 的实际结构")
print("=" * 82)
raw = get("/pkg/manifest")
man = json.loads(raw.decode())
print("  顶层字段: %s" % sorted(man.keys()))
print("  version : %s" % man.get("version"))
print("  count   : %s" % man.get("count"))
f0 = list((man.get("files") or {}).items())[:2]
for k, v in f0:
    print("  files[%s] = %s" % (k, json.dumps(v, ensure_ascii=False)[:110]))
print("  ★ 每个文件项里的字段: %s"
      % sorted((list((man.get('files') or {}).values())[0] or {}).keys()))

print()
print("=" * 82)
print("2) 老 update.py 认哪些字段(看各历史版本的代码)")
print("=" * 82)
import pathlib


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
cands = list(pathlib.Path(".").glob("update.py"))
cands += list(pathlib.Path("_改造前备份_20260919_051455").glob("*.py"))
cands += list(pathlib.Path("_收敛前备份_*").glob("update.py"))
cands += list(pathlib.Path("_子目录改造前备份_*").glob("update.py"))
seen = set()
for p in cands:
    try:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        s = p.read_text(encoding="utf-8")
    except Exception:
        continue
    if "manifest" not in s:
        continue
    print()
    print("  --- %s (%d B) ---" % (p, p.stat().st_size))
    for i, l in enumerate(s.splitlines()):
        t = l.strip()
        if ("manifest" in t and ("get(" in t or "[" in t)) or \
           ("sha256" in t and "=" in t) or "version" in t and "=" in t and "get(" in t:
            print("     %5d: %s" % (i + 1, t[:92]))

print()
print("=" * 82)
print("3) 包内每个文件的 sha256 与清单是否一致")
print("=" * 82)
blob = get("/pkg/latest.zip")
zf = zipfile.ZipFile(io.BytesIO(blob))
zn = {n for n in zf.namelist() if not n.endswith("/")}
print("  zip 条目 %d, 清单 %d" % (len(zn), len(man.get("files") or {})))
bad = []
for n, info in (man.get("files") or {}).items():
    if n not in zn:
        bad.append(n + "(zip里没有)")
        continue
    h = hashlib.sha256(zf.read(n)).hexdigest()
    if h != info.get("sha256"):
        bad.append(n + "(哈希不符)")
print("  不一致: %s" % (bad if bad else "无 ✓"))

print()
print("=" * 82)
print("4) 包里的 update.py 和本地是否一致(同事拿到的更新器是不是最新的)")
print("=" * 82)
local = pathlib.Path("update.py").read_bytes()
inzip = zf.read("update.py")
print("  本地 update.py   : %d B  %s" % (len(local),
      hashlib.sha256(local).hexdigest()[:16]))
print("  包里 update.py   : %d B  %s" % (len(inzip),
      hashlib.sha256(inzip).hexdigest()[:16]))
print("  ★ 一致: %s" % ("是 ✓" if local == inzip else "★ 不一致!"))
# 包里 update.py 有没有自愈/子目录这些新东西
t = inzip.decode("utf-8", "replace")
for name, mark in (("safe_rel(路径校验)", "def safe_rel"),
                   ("policy 强制纠正", "POLICY_KEYS"),
                   ("保护 链接- 文件", '"链接-"')):
    print("     包里 update.py 含 %-20s %s" % (name, "✓" if mark in t else "★ 没有"))
