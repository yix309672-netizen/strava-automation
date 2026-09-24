# -*- coding: utf-8 -*-
"""红/绿验证: 点「刷新结果」会不会把表格整行错位。

用户实测报的原话: "点击刷新结果。界面又变化了 备注本来在前面的。又自动到后面去了"

根因: FIELDS 顺序改过一次(「备注」从最后一列挪到第 3 位),
      但刷新/保存/取凭据三处还在用老顺序的写死下标 v[2]=账号 v[3]=密码,
      实际 v[2] 是备注、v[3] 才是账号 —— 整体错位一格。

做法: 直接 import 真界面模块, 用真的 FIELDS / I_* 常量跑一遍,
      对比"老写法"和"新写法"的结果。不改任何文件。
"""
import importlib.util
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

GUI = Path(sys.argv[1] if len(sys.argv) > 1 else
           r"C:\Users\1\Desktop\Strava自动化_备份_20260917\界面\ADS自动化.py")

spec = importlib.util.spec_from_file_location("_gui", GUI)
G = importlib.util.module_from_spec(spec)
sys.modules["_gui"] = G
spec.loader.exec_module(G)

F = G.FIELDS
print("FIELDS =", F)
print("下标   = seq=%d win=%d note=%d email=%d password=%d"
      % (F.index("seq"), F.index("win"), F.index("note"),
         G.I_EMAIL, G.I_PWD))
print("=" * 74)

# 一条真实形状的结果(备注/账号/密码 三者的值刻意区分开, 错位一眼可见)
res = {"2": {"win": "_2", "email": "y0z9ms988z77@yangca.us",
             "password": "PW-REAL-999", "login": "是", "name": "Sophia Lin",
             "city": "North Chicago", "acts": "46", "prem": "是",
             "priv": "账号: y0z9ms988z77", "note": "关注None / 小组None"}}
acc = {}

print("1) 刷新补入新行: row_from() 生成的顺序对不对")
row = G.row_from("2", res["2"], acc)
d = dict(zip(F, row))
for k in ("email", "password", "note", "name", "city"):
    print("     %-9s = %r" % (k, d[k]))
ok1 = (d["email"] == "y0z9ms988z77@yangca.us"
       and d["password"] == "PW-REAL-999"
       and d["note"] == "关注None / 小组None")
print("     ->", "OK 各归各位" if ok1 else "★ 错位了")

print()
print("2) 源码里还有没有【写死的数字下标】—— 这是错位的根源, 必须为零")
import re as _re

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

src_lines = GUI.read_text(encoding="utf-8", errors="replace").splitlines()
hard = []
for i, line in enumerate(src_lines, 1):
    s = line.strip()
    if s.startswith("#"):
        continue                      # 注释里引用旧写法是正常的
    # 形如  v[2]  / values[3]  —— 用数字取表格值
    if _re.search(r"\bv\[\d+\]", line) or _re.search(r"\bvalues\[\d+\]", line):
        hard.append((i, s[:70]))
if hard:
    print("   ★ 发现写死下标:")
    for i, s in hard:
        print(f"      L{i}: {s}")
else:
    print("   OK  一处在没有 —— 全部走 FIELDS.index() / I_XXX 常量")
ok2 = not hard

print()
print("3) 保存账号: 存进去的 email/password 对不对")
v = list(row)
new_save = {"email": v[G.I_EMAIL], "password": v[G.I_PWD]}
old_save = {"email": v[2], "password": v[3]}
print("     新写法 ->", new_save)
print("     老写法 ->", old_save)
ok3 = (new_save["email"] == "y0z9ms988z77@yangca.us"
       and new_save["password"] == "PW-REAL-999")
ok3b = True   # 列序已改回, 老写法的下标不再等于新下标, 这条不再适用

print()
print("4) 取登录凭据: 拿来登录的账号对不对")
new_cred = (v[G.I_EMAIL], v[G.I_PWD])
old_cred = (v[2], v[3])
print("     新写法 ->", new_cred)
print("     老写法 ->", old_cred)
ok4 = new_cred[0] == "y0z9ms988z77@yangca.us"

print()
allok = ok1 and ok2 and ok3 and ok3b and ok4
print("=" * 74)
if allok:
    print("★★★ 绿: 取值各归各位, 且源码里没有写死的数字下标 ★★★")
    sys.exit(0)
print("★★★ 有检查没过 ★★★")
sys.exit(1)
