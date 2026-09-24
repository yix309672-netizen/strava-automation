# -*- coding: utf-8 -*-
r"""修「账号列错位」: 姓名进了 email 列、真邮箱被挤到 password 列。

★★ 症状(用户截图 + 磁盘实证) ★★
    配置/ads_accounts.json
      [9] {"email": "Chloe Zhao", "password": "xa4fmicfuh9f@yangca.us"}
    界面上「账号」列显示姓名, 「密码」列显示邮箱。

★★ 怎么修 ★★
    ① 认出这种行: email 不像邮箱, 而 password 长得就是邮箱
       -> 把两列【换回来】, 真邮箱归位
    ② 换回来之后 password 是空的 -> 拿邮箱去历史快照里查真密码
       (索引逻辑直接复用 _修_密码丢失.py, 不再写第二份)
    ③ 原来 email 列里那个姓名不动它 —— 备注列本来就有名字(预览分配写的),
       不往别处搬, 免得又造出新的错位

★★ 安全 ★★
    · 默认【只看不改】, 加 --apply 才写
    · 写之前自动备份到 数据/_修错位备份_<时间>/
    · 只动 email / password 两列, 其余列一个字节不碰
    · 写完复核: 邮箱列必须全是邮箱

用法:
    python _修_账号列错位.py            # 只看
    python _修_账号列错位.py --apply    # 真修
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path


def _find_project_root(start=None):
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

ROOT = _find_project_root(__file__)
APPLY = "--apply" in sys.argv
MAIL = re.compile(r"^[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+$")
PWD_LIKE = re.compile(r"^[A-Za-z0-9]{6,20}$")
FILES = [("配置/ads_accounts.json", "ADS账号", ("email", "password")),
         ("数据/ads_results.json", "ADS结果", ("email", "password"))]


def load_pwd_index():
    """复用 _修_密码丢失.py 的索引(历史快照 + 备注里的 账号：x 密码：y)。"""
    sys.path.insert(0, str(ROOT / "_工具" / "体检"))
    try:
        import importlib.util as iu
        spec = iu.spec_from_file_location(
            "_pwdmod", ROOT / "_工具" / "体检" / "_修_密码丢失.py")
        m = iu.module_from_spec(spec)
        sys.modules["_pwdmod"] = m
        # 它 import 时只定义函数和打印模式, 直接跑也没事; 保险起见吞掉输出
        import io as _io
        import contextlib
        with contextlib.redirect_stdout(_io.StringIO()):
            spec.loader.exec_module(m)
        return m.build_index()
    except Exception as e:
        print(f"  ★ 密码索引没建起来({str(e)[:60]}) -> 只换列, 密码留空待补")
        return {}


print("模式:", "真的修(--apply)" if APPLY else "只看不改(默认)")
print("-" * 74)
IDX = load_pwd_index()
print(f"历史快照里的真密码: {len(IDX)} 个邮箱")

bakdir = ROOT / "_备份" / f"_修账号列错位_{time.strftime('%Y%m%d_%H%M%S')}"
total_fix = total_orphan = 0

for rel, label, _cols in FILES:
    p = ROOT / rel
    if not p.is_file():
        print(f"[{label}] {rel} 不存在, 跳过")
        continue
    d = json.loads(p.read_text(encoding="utf-8"))
    fixed, orphan, okn = [], [], 0

    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        e = str(v.get("email") or "").strip()
        pw = str(v.get("password") or "").strip()
        if not e and not pw:
            continue
        if MAIL.match(e):
            okn += 1                       # 邮箱列本来就对, 不动
            continue
        if MAIL.match(pw):
            # ★ 这种行: 真邮箱被挤在 password 列 -> 换回来
            new_e = pw
            new_p = IDX.get(new_e.lower(), "")
            fixed.append((k, e, new_e, new_p))
            if APPLY:
                v["email"], v["password"] = new_e, new_p
            if not new_p:
                orphan.append(k)
        else:
            orphan.append(k)               # 认不出来, 留着报出来

    total_fix += len(fixed)
    total_orphan += len(orphan)
    print(f"[{label}] {rel}: 共 {len(d)} 条 -> 本来就对 {okn}, "
          f"★ 需要换回来 {len(fixed)}, 认不出 {len(orphan)}")
    for k, old_e, new_e, new_p in fixed[:4]:
        print(f"     [{k}] 账号列 {old_e[:16]!r} -> {new_e[:30]!r}"
              f"   密码 {'已找回' if new_p else '★ 待补'}")
    if orphan:
        print(f"     认不出的: {orphan[:8]}")

    if APPLY and fixed:
        bakdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, bakdir / Path(rel).name)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        import os
        os.replace(tmp, p)
        print(f"     已写回; 备份 {bakdir.name}\\{Path(rel).name}")

print("-" * 74)
if APPLY:
    print(f"共换回 {total_fix} 条; 其中密码待补 {total_orphan} 条")
    # 复核
    print()
    print("=== 复核: 邮箱列必须全是邮箱 ===")
    for rel, label, _c in FILES:
        p = ROOT / rel
        if not p.is_file():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        bad = [k for k, v in d.items() if isinstance(v, dict)
               and str(v.get("email") or "").strip()
               and not MAIL.match(str(v["email"]).strip())]
        print(f"  {label}: 邮箱列不是邮箱的还有 {len(bad)} 条 {bad[:6]}")
else:
    print(f"预计可换回 {total_fix} 条; 认不出 {total_orphan} 条")
    print("(未改动 —— 加 --apply 才真的写; 写前会自动备份)")
