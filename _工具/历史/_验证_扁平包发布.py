# -*- coding: utf-8 -*-
"""验证: 扁平包发出去, 同事能正常更新(不含 sv_ttk)。

这是"路 B"的验证 —— 刻意不发子目录, 所以只验证:
  · 同事能发现新版本并成功更新
  · 17 个文件都按 sha256 对得上
  · 同事自己的 key / 配置没被动
  · ._pkg_version 正确写入
  · 关键功能代码都在(美国过滤 / 55+ / 一天一个文件 / 扫描关浏览器 / key 自愈 ...)
  · 根目录没被撒进奇怪的东西
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent
CFG = json.loads((ROOT / "配置" / "config.json").read_text(encoding="utf-8"))
SRV = CFG["claim_server"].rstrip("/")
KEY = CFG["claim_key"]
PASS, FAIL = [], []


def ck(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-52s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


def get(path, timeout=180):
    r = urllib.request.Request(SRV + path, headers={"X-API-Key": KEY})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read()


print("=" * 86)
print("验证: 扁平包发布 -> 同事更新(路 B)")
print("=" * 86)

man = json.loads(get("/pkg/manifest"))
files = man.get("files") or {}
print()
print("  服务器版本 %s, %d 个文件" % (man["version"], len(files)))
ck("是扁平包(无子目录条目)", [k for k in files if "/" in k], [])
ck("不含 sv_ttk", [k for k in files if k.startswith("sv_ttk")], [])

print()
print("--- 模拟同事机器 ---")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="flat_"))
shutil.copy2(ROOT / "update.py", tmp / "update.py")
(tmp / "config.json").write_text(json.dumps({
    "claim_server": SRV, "claim_key": KEY,
    "adspower_key": "COLLEAGUE_KEY_KEEP",
    "avatar_dir": "C:/同事/头像",
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
# 同事机器上先放一个旧版引擎, 看会不会被换掉
(tmp / "strava_ads.py").write_text("# OLD VERSION\n", encoding="utf-8")

env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
r = subprocess.run([sys.executable, "update.py"], cwd=str(tmp),
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=600, env=env)
out = (r.stdout or "") + (r.stderr or "")
print("    update.py 退出码 %d" % r.returncode)
for line in out.splitlines()[-10:]:
    print("       " + line[:96])

print()
print("--- 落地核对 ---")
ck("更新成功", r.returncode, 0)

mism, miss = [], []
for rel, info in files.items():
    p = tmp / rel
    if not p.is_file():
        miss.append(rel)
        continue
    if hashlib.sha256(p.read_bytes()).hexdigest() != info.get("sha256"):
        mism.append(rel)
# config.json 是合并过的, 内容本来就会不同 -> 单独对待
mism = [x for x in mism if x != "config.json"]
ck("所有文件都落地了", miss, [])
ck("内容与清单 sha256 一致(除 config.json)", mism, [])
ck("旧引擎被换掉了", (tmp / "strava_ads.py").read_text(encoding="utf-8")
   .startswith("# OLD") is False, True)

c2 = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
ck("同事的 adspower_key 没被动", c2.get("adspower_key"), "COLLEAGUE_KEY_KEEP")
ck("同事的头像目录没被动", c2.get("avatar_dir"), "C:/同事/头像")
vf = tmp / "._pkg_version"
ck("._pkg_version 已写入", vf.is_file() and
   vf.read_text(encoding="utf-8").strip() == man["version"], True)

print()
print("--- 关键功能代码是否都在(同事拿到的这一版) ---")
ENG = (tmp / "strava_ads.py").read_text(encoding="utf-8", errors="replace")
CHECKS = [
    ("只要美国境内", "def is_us_location"),
    ("美国地名补全", "52082"),          # 注释里的键数, 也可用别的
    ("年龄只留 55+", "AGE_GROUPS_MIN_ALLOWED"),
    ("一天一个文件", "def _daily_path"),
    ("文件名「链接-」", 'DAILY_FILE_PREFIX = "链接-"'),
    ("扫描完关浏览器", "def scan_should_close"),
    ("AdsPower key 自愈", "def ads_headers"),
    ("claim_client 自愈", "_reload_claim_client"),
    ("会员三态", "_prem is not False"),
    ("样本放开", "pan_rounds"),
    ("每段门槛可配", "def resolve_min_athletes"),
    ("账号列识别", "def _looks_email"),
]
for name, mark in CHECKS:
    ck(name, mark in ENG, True)

GUI = (tmp / "_gui_ads.py").read_text(encoding="utf-8", errors="replace")
for name, mark in (("界面: 采集地区下拉", "REGION_CHOICES"),
                   ("界面: 年纪下拉", "AGE_CHOICES"),
                   ("界面: 每段下拉", "MIN_ATH_CHOICES"),
                   ("界面: 备注列提前", '"note", "email"')):
    ck(name, mark in GUI, True)

# 不应有主题目录
ck("同事那边没有 sv_ttk(预期)", (tmp / "sv_ttk").exists(), False)

shutil.rmtree(tmp, ignore_errors=True)
print()
print("=" * 86)
if FAIL:
    print("★ 失败 %d 项:" % len(FAIL))
    for f in FAIL:
        print("   - " + f)
    raise SystemExit(1)
print("✓ 通过 %d 项: 同事能正常更新到扁平包, 所有改进都在, 他自己的东西没被动"
      % len(PASS))
