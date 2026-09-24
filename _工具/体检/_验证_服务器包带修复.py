# -*- coding: utf-8 -*-
"""验证: 服务器上的包真的带上了今天全部改动。

不信任"上传成功"这种话 —— 把服务器上的 zip 拉下来解开逐条看。
"""
import io
import json
import sys
import urllib.request
import zipfile

# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\strava_ads.py 的那一层)。
#   原来是 _find_project_root(__file__), 脚本一挪位置就找错了。
def _find_project_root(start=None):
    """向上找项目根(判据: 有 主脚本/strava_ads.py 的那一层)。

    ★ 归类整理后脚本不一定在根目录, 所以不能再用 Path(__file__).parent。
    ★ 函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path` 都能跑；兜底也不再调自己(那样会无限递归)。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent

SRV = "http://137.175.71.171:8000"
KEY = "g1jVQg7y_K5UOtfHUgUEg6seJ4WeKJjAUGJt7shPYvk"
H = {"X-API-Key": KEY}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

with urllib.request.urlopen(urllib.request.Request(SRV + "/pkg/manifest", headers=H),
                            timeout=40) as r:
    man = json.loads(r.read().decode("utf-8"))
print("版本号:", man.get("version"))
print("清单文件数:", len(man.get("files") or {}))

with urllib.request.urlopen(urllib.request.Request(SRV + "/pkg/latest.zip", headers=H),
                            timeout=180) as r:
    blob = r.read()
print("zip: %.0f KB" % (len(blob) / 1024))
z = zipfile.ZipFile(io.BytesIO(blob))
names = set(z.namelist())
print("包内文件:", len(names))
print()


def code_of(text):
    """去掉注释行 —— 解释性注释里会引用旧写法, 直接 in 全文会假报 FAIL。"""
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


MSGS = ["msg_setup.txt", "msg_setup_ok.txt", "msg_setup_fail.txt", "msg_ads.txt",
        "msg_bit.txt", "msg_update.txt", "msg_repair.txt", "msg_test.txt",
        "msg_check.txt", "msg_nopython.txt", "msg_running.txt", "msg_done.txt",
        "msg_fail.txt", "msg_hidden_fail.txt", "msg_hidden_nopython.txt"]
BATS = ["启动.bat", "更新.bat", "修复更新.bat", "Test_Server.bat",
        "Start_AdsPower.bat", "Start_BitBrowser.bat"]
HIDE_TOOLS = ["_hide.ps1", "_msgbox.vbs"]

bad = []

# 1) 13 个中文提示文件都在, 且是真中文
for m in MSGS:
    if m not in names:
        bad.append("缺 %s" % m)
        continue
    t = z.read(m).decode("utf-8", errors="replace")
    if len(t.strip()) < 10:
        bad.append("%s 内容为空" % m)
print("1) 中文提示文件: %d/%d 在包里" % (len([m for m in MSGS if m in names]), len(MSGS)))

# 2) 每个 .bat: 纯 ASCII + CRLF + 引用的 msg 都在包里
for b in BATS:
    if b not in names:
        bad.append("缺 %s" % b)
        continue
    data = z.read(b)
    non = sum(1 for x in data if x > 127)
    bare = data.count(b"\n") - data.count(b"\r\n")
    if non:
        bad.append("%s 含 %d 个非 ASCII 字节(会让 cmd 解析崩)" % (b, non))
    if bare:
        bad.append("%s 有 %d 个裸 LF(需要 CRLF)" % (b, bare))
    txt = data.decode("ascii", errors="replace")
    for line in txt.splitlines():
        s = line.strip()
        if s.lower().startswith("type "):
            tgt = s[5:].strip().strip('"').replace("%~dp0", "")
            # 含 % 的是变量(:DIE 里的 "%~dp0%~1"), 运行时才展开, 不是文件名
            if "%" in tgt:
                continue
            if tgt not in names:
                bad.append("%s 引用 %s, 但包里没有" % (b, tgt))
print("2) .bat 纯ASCII+CRLF+引用完整: %d 个已查" % len([b for b in BATS if b in names]))

# 2b) 隐藏窗口: 两个工具必须在, 且 Start_*.bat 顺序正确
for m in HIDE_TOOLS:
    if m not in names:
        bad.append("缺隐藏窗口工具 %s" % m)
        continue
    raw = z.read(m)
    na = sum(1 for x in raw if x > 127)
    if na:
        bad.append("%s 含 %d 个非 ASCII 字节" % (m, na))
for b in ("Start_AdsPower.bat", "Start_BitBrowser.bat"):
    if b not in names:
        continue
    t = z.read(b).decode("ascii", "replace")
    i_hide, i_py = t.find("_hide.ps1"), t.find("py -3 -c")
    if i_hide < 0:
        bad.append("%s 没调用 _hide.ps1" % b)
    elif i_py >= 0 and i_hide > i_py:
        bad.append("%s 先找 Python 再隐藏(黑窗口会闪)" % b)
    if "HIDDEN" not in t:
        bad.append("%s 缺 HIDDEN 逻辑" % b)
print("2b) 隐藏窗口工具+顺序: %d 个已查" % (len(HIDE_TOOLS) + 2))

# 3) 死数据删干净 + 修复还在
for f, needle, want in [
    ("strava_ads.py", "ctx.setdefault(\"urls\", {})", True),
    ("strava_bit.py", "ctx.setdefault(\"urls\", {})", True),
    ("_gui_ads.py", "链接已存到", True),
    ("_gui_bit.py", "链接已存到", True),
    # 死字典必须消失
    ("strava_ads.py", "_ADMIN_POLICY = {", False),
    ("strava_bit.py", "_ADMIN_POLICY = {", False),
    ("_gui_ads.py", "_ADMIN_POLICY = {", False),
    ("_gui_bit.py", "_ADMIN_POLICY = {", False),
    # 但版本号开关必须还在
    ("strava_ads.py", "_ADMIN_POLICY_REV = 2", True),
    ("strava_bit.py", "_ADMIN_POLICY_REV = 2", True),
    ("_gui_ads.py", "_ADMIN_POLICY_REV = 2", True),
    ("_gui_bit.py", "_ADMIN_POLICY_REV = 2", True),
    ("使用说明.txt", "链接-日期.txt", True),
    # ★ 2026-09-20: 修复更新.bat 绝不能把同事自己选的采集州/门槛吃掉
    ("fix_update.py", '"collect_regions", "collect_auto_regions"', False),
    ("fix_update.py", 'POLICY_KEYS', True),
    # ★★ 2026-09-20: 列序错位 —— 刷新结果会把表格整行左移一格 ★★
    #   判据: 必须用 FIELDS 推出的下标, 且旧的写死下标必须消失
    ("_gui_ads.py", "I_EMAIL = FIELDS.index", True),
    ("_gui_bit.py", "I_EMAIL = FIELDS.index", True),
    ("_gui_ads.py", 'v[2] = a["email"]', False),
    ("_gui_bit.py", 'v[2] = a["email"]', False),
    ("_gui_ads.py", '{"email": v[2], "password": v[3]}', False),
    ("_gui_bit.py", '{"email": v[2], "password": v[3]}', False),
    ("_gui_ads.py", 'creds[int(v[0])] = (v[2], v[3])', False),
    ("_gui_bit.py", 'creds[int(v[0])] = (v[2], v[3])', False),
    # ★ 2026-09-20: 备注挪回最后一列, 且宽度改成按字段名给(不再按位置)
    ("_gui_ads.py", '"name", "city", "acts", "prem", "priv", "note")', True),
    ("_gui_bit.py", '"name", "city", "acts", "prem", "priv", "note")', True),
    ("_gui_ads.py", 'WIDTHS = {"seq": 50', True),
    ("_gui_bit.py", 'WIDTHS = {"seq": 50', True),
    ("_gui_ads.py", "widths = (50, 60, 190", False),
    ("_gui_bit.py", "widths = (50, 60, 190", False),
    # ★★ 2026-09-20: 1000 个名字的名字库必须在包里, 且引擎确实去读它 ★★
    #   引擎 `from name_bank import NAMES`; 缺了会【静默】退回内置的 50 个
    #   名字(不报错), 只能在这里挡。
    ("name_bank.py", "NAMES = [", True),
    ("strava_ads.py", "from name_bank import NAMES", True),
    ("strava_bit.py", "from name_bank import NAMES", True),
]:
    if f not in names:
        bad.append("缺 %s" % f)
        continue
    txt = z.read(f).decode("utf-8", errors="replace")
    hay = txt if f.endswith(".txt") else code_of(txt)
    got = needle in hay
    if got != want:
        bad.append("%s 含 %r = %s, 期望 %s" % (f, needle, got, want))

# fix_update 与 update 的 POLICY_KEYS 必须【完全一致】, 否则修复更新会抹掉同事的选择
import re as _re
fu = z.read("fix_update.py").decode("utf-8", "replace")
up = z.read("update.py").decode("utf-8", "replace")


def _keys(text):
    m = _re.search(r"POLICY_KEYS = \((.*?)\n\)", text, _re.S)
    body = code_of(m.group(1)) if m else ""
    return set(_re.findall(r'"([^"]+)"', body))


kf, ku = _keys(fu), _keys(up)
if kf != ku:
    bad.append("fix_update 与 update 的 POLICY_KEYS 不一致: 多=%s 少=%s"
               % (sorted(kf - ku), sorted(ku - kf)))
print("3) 代码修复/死数据/版本开关/两处更新器一致: 已查")
print("   fix_update POLICY_KEYS=%d  update POLICY_KEYS=%d  一致=%s"
      % (len(kf), len(ku), kf == ku))

# 4) 成果文件绝不能混进来
for w in ("collected_users.txt", "链接-20260920.txt", "task_state.json",
          "bit_accounts.json", "ads_accounts.json"):
    if w in names:
        bad.append("★ 成果/账号文件泄露进包: %s" % w)
print("4) 成果与账号不泄露: 已查")

print()
if bad:
    print("★★★ 验证不通过 ★★★")
    for x in bad:
        print("   -", x)
    sys.exit(1)
print("★★★ 服务器包验证全部通过 ★★★")
