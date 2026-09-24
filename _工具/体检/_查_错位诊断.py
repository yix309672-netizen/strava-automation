# -*- coding: utf-8 -*-
"""诊断: 结果文件到底被错位了几格, 能不能还原。

从实测样例反推出来的错位规律(老刷新代码把资料列整体左移一格):
    现在.password  = 原来.login
    现在.login     = 原来.name
    现在.name      = 原来.city
    现在.city      = 原来.acts
    现在.acts      = 原来.prem
    现在.prem      = 原来.priv
    现在.priv      = 原来.note
    现在.note      = 原来.note(本来非空时) 或 邮箱(本来为空时)
    现在.email / .win / .seq  没被动

判定依据(这些列有固定取值范围, 一眼能看出有没有移位):
    login 只能是 是/否       -> 移位后会变成人名
    password 只能是 是/否    -> 移位后会变成 login(是/否)  ← 对, 所以 password 必须靠账号文件补
    acts  只能是数字(活动数) -> 移位后会变成 prem(是/否)
只读, 不改任何文件。
"""
import json
import re
import sys
from pathlib import Path

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

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
YN = {"是", "否", ""}
MAIL = re.compile(r"^[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+$")


def analyse(path, acc_path):
    if not path.is_file():
        print(f"[{path.name}] 不存在")
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or not d:
        print(f"[{path.name}] 空")
        return None
    acc = {}
    if acc_path.is_file():
        try:
            acc = json.loads(acc_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    n = len(d)
    c = {"login_是人名": 0, "login_是是否": 0, "acts_是数字": 0, "acts_是是否": 0,
         "note_是邮箱": 0, "note_nonempty": 0, "priv_等于note": 0}
    for v in d.values():
        if not isinstance(v, dict):
            continue
        login = str(v.get("login") or "").strip()
        acts = str(v.get("acts") or "").strip()
        note = str(v.get("note") or "").strip()
        priv = str(v.get("priv") or "").strip()
        if login and login not in YN:
            c["login_是人名"] += 1
        if login in YN and login:
            c["login_是是否"] += 1
        if acts.isdigit():
            c["acts_是数字"] += 1
        if acts in YN and acts:
            c["acts_是是否"] += 1
        if MAIL.match(note):
            c["note_是邮箱"] += 1
        if note:
            c["note_nonempty"] += 1
        if priv and priv == note:
            c["priv_等于note"] += 1

    print("=" * 72)
    print(f"[{path.name}]  共 {n} 条")
    for k, val in c.items():
        print(f"    {k:16s}= {val}")
    # 判定
    shifted = c["login_是人名"] > 0 or c["acts_是是否"] > 0
    print()
    if shifted:
        print("    ★ 结论: 【被错位过】")
        print(f"      login 是人名的有 {c['login_是人名']} 条 "
              f"(正常应该是 是/否)")
        print(f"      acts 是 是/否 的有 {c['acts_是是否']} 条 "
              f"(正常应该是数字)")
        print(f"      note 是邮箱的有 {c['note_是邮箱']} 条 (正常是备注文字)")
    else:
        print("    ✓ 结论: 正常, 没有被错位")
    # 账号文件能不能补回 password
    if acc:
        have = sum(1 for v in d.values()
                   if isinstance(v, dict)
                   and MAIL.match(str(v.get("email") or "").strip())
                   and str(v.get("email") or "").strip().lower() in
                   {k.lower() for k in acc})
        print(f"    账号文件里有 {len(acc)} 条, 能对上邮箱的 {have} 条 "
              f"-> password 可以据此补回")
    return c


analyse(ROOT / "数据" / "ads_results.json", ROOT / "配置" / "ads_accounts.json")
analyse(ROOT / "数据" / "bit_results.json", ROOT / "配置" / "bit_accounts.json")
