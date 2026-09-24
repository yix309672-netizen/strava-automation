# -*- coding: utf-8 -*-
"""从服务器重新下载最新包, 核对里面真的是修复后的内容(闭环验证)。"""
import hashlib
import io
import json
import urllib.request
import zipfile


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

CFG = json.loads(open("配置/config.json", encoding="utf-8").read())
SRV = CFG["claim_server"].rstrip("/")
HDR = {"X-API-Key": CFG["claim_key"]}

req = urllib.request.Request(SRV + "/pkg/manifest", headers=HDR)
man = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
print("服务器版本 =", man["version"])
req = urllib.request.Request(SRV + "/pkg/latest.zip", headers=HDR)
blob = urllib.request.urlopen(req, timeout=180).read()
zf = zipfile.ZipFile(io.BytesIO(blob))
names = {n.split("/")[-1]: n for n in zf.namelist() if not n.endswith("/")}
print("包内文件 %d 个, 大小 %d KB" % (len(names), len(blob) // 1024))
print()

MUST = {
    "strava_ads.py": ["_ADMIN_POLICY_REV = 2", "enforce_admin_policy()",
                      '"collect_regions": ["New York"]', "def rate_gate",
                      "def grid_pan_targets",
                      # ★ 会员三态判定(2026-09-19 用户报"会员号显示否"后修)
                      "_PREMIUM_JS", "_prem is not False", "会员状态读不到",
                      # ★ claim_client 自愈(2026-09-19 用户报"文件在却报缺"后修)
                      "_reload_claim_client", "已自动补上",
                      # ★ 榜单口径 + 地点搜索(2026-09-19 用户要求做下拉框)
                      "AGE_GROUPS_VALID", "def _lb_filters", "region_search_key",
                      "def region_is_ny", "lb_gender"],
    "strava_bit.py": ["_ADMIN_POLICY_REV = 2", "enforce_admin_policy()",
                      "_PREMIUM_JS", "_prem is not False", "会员状态读不到",
                      "_reload_claim_client", "已自动补上",
                      "AGE_GROUPS_VALID", "def _lb_filters", "region_search_key",
                      "def region_is_ny", "lb_gender"],
    "_gui_ads.py": ["_ADMIN_POLICY_REV = 2", "if _rev < _ADMIN_POLICY_REV:",
                    "_rc = {**_rc, **_fixed}",
                    # ★ "?" 必须和 -1 一样被当成"本次读不到"
                    '"None", "-1", "?"',
                    # ★ 4 个下拉框
                    "REGION_CHOICES", "AGE_CHOICES", "_save_collect_choice"],
    "_gui_bit.py": ["_ADMIN_POLICY_REV = 2", "if _rev < _ADMIN_POLICY_REV:",
                    "_rc = {**_rc, **_fixed}",
                    '"None", "-1", "?"',
                    "REGION_CHOICES", "AGE_CHOICES", "_save_collect_choice"],
    "update.py": ["POLICY_KEYS", "按管理员口径纠正"],
    "fix_update.py": ["urllib.request.urlopen", "def main()", "_policy_rev",
                      "POLICY_KEYS"],
    "修复更新.bat": ['"%~dp0fix_update.py"', "PYCMD"],
}
MUSTNOT = {
    "_gui_ads.py": ["if _cur == _LEGACY_REGIONS:", "_LEGACY_REGIONS = ["],
    "_gui_bit.py": ["if _cur == _LEGACY_REGIONS:", "_LEGACY_REGIONS = ["],
}

bad = 0
print("=== 每一项【必须有】 ===")
for f, marks in MUST.items():
    if f not in names:
        print("  ★FAIL %-16s 包里没有这个文件" % f)
        bad += 1
        continue
    t = zf.read(names[f]).decode("utf-8", "replace")
    for m in marks:
        ok = m in t
        bad += 0 if ok else 1
        print("  %-16s %s  %s" % (f, "OK  " if ok else "★FAIL", m))

print()
print("=== 每一项【必须没有】 ===")
for f, marks in MUSTNOT.items():
    t = zf.read(names[f]).decode("utf-8", "replace")
    for m in marks:
        ok = m not in t
        bad += 0 if ok else 1
        print("  %-16s %s  %s" % (f, "已清除" if ok else "★FAIL 还在", m))

print()
print("=== fix_update.py 必须【不依赖 requests】(老机器常常没装) ===")
_r = zf.read(names["fix_update.py"]).decode("utf-8", "replace")
_uses_req = "urllib.request.urlopen" in _r
_guarded = "try:\n        import requests" in _r or "import requests  # noqa" in _r
ok = _uses_req and _guarded
bad += 0 if ok else 1
print("  %s 下载走 urllib.request.urlopen: %s" % ("OK  " if _uses_req else "★FAIL", _uses_req))
print("  %s requests 只是 try 里探测(缺了也不影响): %s"
      % ("OK  " if _guarded else "★FAIL", _guarded))

print()
print("=== 分发包 config.json 绝不能带 _policy_rev ===")
c = json.loads(zf.read(names["config.json"]).decode("utf-8"))
ok = "_policy_rev" not in c
bad += 0 if ok else 1
print("  %s _policy_rev = %r" % ("OK  " if ok else "★FAIL", c.get("_policy_rev")))
print("  口径: 采集州=%s 每段>=%s 并发=%s adspower_key=%r"
      % (c.get("collect_regions"), c.get("min_athletes"), c.get("jobs"),
         c.get("adspower_key")))

print()
print("=== 文件大小 ===")
for f in sorted(names):
    print("  %-22s %9d B" % (f, len(zf.read(names[f]))))

print()
print("闭环核对: 问题项 = %d" % bad)
raise SystemExit(1 if bad else 0)
