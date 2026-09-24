# -*- coding: utf-8 -*-
"""确认所有源码都是最新的 —— 打包前先核对。

从服务器下载当前发布的包, 和本地源码逐个比对;
再检查关键功能标记是否都在。
"""
import hashlib
import io
import json
import pathlib
import urllib.request
import zipfile

ROOT = pathlib.Path(".").resolve()
CFG = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
SRV = CFG["claim_server"].rstrip("/")
KEY = CFG["claim_key"]

print("=" * 84)
print("打包前核对: 本地源码 vs 服务器已发布版本")
print("=" * 84)

with urllib.request.urlopen(
        urllib.request.Request(SRV + "/pkg/latest.zip",
                               headers={"X-API-Key": KEY}),
        timeout=200) as r:
    blob = r.read()
zf = zipfile.ZipFile(io.BytesIO(blob))
print("  服务器包: %d 个文件, %.0f KB" % (len(zf.namelist()), len(blob) / 1024))

# 本地真源 -> 包内名字
SRC_MAP = [
    ("主脚本/strava_ads.py", "strava_ads.py"),
    ("主脚本/strava_bit.py", "strava_bit.py"),
    ("界面/ADS自动化.py", "_gui_ads.py"),
    ("界面/比特派自动化.py", "_gui_bit.py"),
    ("claim_client.py", "claim_client.py"),
    ("update.py", "update.py"),
    ("fix_update.py", "fix_update.py"),
    ("geo_cities.py", "geo_cities.py"),
    ("open_app.py", "open_app.py"),
]

print()
print("  %-24s %-34s %s" % ("包内文件", "本地哈希", "和本地一致?"))
print("  " + "-" * 80)
diff = []
for src, inzip in SRC_MAP:
    p = ROOT / src
    if not p.is_file():
        print("  %-24s ★ 本地没有 %s" % (inzip, src))
        diff.append(inzip)
        continue
    h_local = hashlib.sha256(p.read_bytes()).hexdigest()
    try:
        h_zip = hashlib.sha256(zf.read(inzip)).hexdigest()
    except KeyError:
        print("  %-24s ★ 包里没有" % inzip)
        diff.append(inzip)
        continue
    same = h_local == h_zip
    if not same:
        diff.append(inzip)
    print("  %-24s %-34s %s" % (inzip, h_local[:16], "一致 ✓" if same else "★ 不一致"))

print()
print("  不一致: %s" % (diff if diff else "无 —— 包里就是本地最新版 ✓"))

# ---- 关键功能标记 ----
print()
print("=" * 84)
print("关键功能标记(以本地源码为准)")
print("=" * 84)
eng = (ROOT / "主脚本" / "strava_ads.py").read_text(encoding="utf-8")
bit = (ROOT / "主脚本" / "strava_bit.py").read_text(encoding="utf-8")
gui = (ROOT / "界面" / "ADS自动化.py").read_text(encoding="utf-8")
upd = (ROOT / "update.py").read_text(encoding="utf-8")

CHECKS = [
    ("引擎: 只要美国境内", "def is_us_location", eng),
    ("引擎: 年龄 55+", "AGE_GROUPS_MIN_ALLOWED", eng),
    ("引擎: 一天一个文件", "def _daily_path", eng),
    ("引擎: 文件名 链接-", 'DAILY_FILE_PREFIX = "链接-"', eng),
    ("引擎: 扫描关浏览器", "def scan_should_close", eng),
    ("引擎: AdsPower key 自愈", "def ads_headers", eng),
    ("引擎: claim 自愈", "def _reload_claim_client", eng),
    ("引擎: 会员三态", "_prem is not False", eng),
    ("引擎: 采样可配", "pan_rounds", eng),
    ("引擎: 门槛可配", "def resolve_min_athletes", eng),
    ("引擎: 账号列识别", "def _looks_email", eng),
    ("引擎: 管理员口径纠正", "enforce_admin_policy", eng),
    ("比特: 只要美国境内", "def is_us_location", bit),
    ("比特: 扫描关浏览器", "def scan_should_close", bit),
    ("界面: 采集地区下拉", "REGION_CHOICES", gui),
    ("界面: 年纪下拉", "AGE_CHOICES", gui),
    ("界面: 每段下拉", "MIN_ATH_CHOICES", gui),
    ("界面: 备注列提前", '"note", "email"', gui),
    ("界面: 深色主题可选", "ui_theme", gui),
    ("更新器: 路径校验", "def safe_rel", upd),
    ("更新器: 口径强制纠正", "POLICY_KEYS", upd),
    ("更新器: 保护 链接-", '"链接-"', upd),
]
miss = 0
for name, mark, body in CHECKS:
    ok = mark in body
    miss += 0 if ok else 1
    print("  %s %s" % ("OK  " if ok else "★MISS", name))
print()
print("  缺失 %d 项" % miss)

# ---- 两个引擎的一致性 ----
print()
print("=" * 84)
print("两个引擎的纯代码一致性")
print("=" * 84)
try:
    import ast
    import io as _io
    import tokenize as _tk

    def cmap(text):
        lines = text.splitlines()
        drop = set()
        for tok in _tk.generate_tokens(_io.StringIO(text).readline):
            if tok.type == _tk.COMMENT:
                drop.add(tok.start[0])
        out = {}
        for n in ast.walk(ast.parse(text)):
            if not isinstance(n, ast.FunctionDef):
                continue
            ds = set()
            b0 = n.body[0] if n.body else None
            if isinstance(b0, ast.Expr) and isinstance(b0.value, ast.Constant) \
                    and isinstance(b0.value.value, str):
                ds = set(range(b0.lineno, (b0.end_lineno or b0.lineno) + 1))
            out[n.name] = [lines[l - 1].strip()
                           for l in range(n.lineno, (n.end_lineno or n.lineno) + 1)
                           if l not in drop and l not in ds and lines[l - 1].strip()]
        return out

    ma, mb = cmap(eng), cmap(bit)
    both = sorted(set(ma) & set(mb))
    same = [n for n in both if ma[n] == mb[n]]
    print("  共同函数 %d, 纯代码逐行相同 %d" % (len(both), len(same)))
    print("  (有差异的多是浏览器适配层, 属正常)")
except Exception as e:
    print("  ★ 比对失败: %s" % str(e)[:80])

print()
print("结论:", "可以打包 ✓" if (not diff and miss == 0) else "★ 先解决上面标 ★ 的项")
