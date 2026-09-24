# -*- coding: utf-8 -*-
"""体检: 账号文件有没有被"错位一格"的保存逻辑写坏。

背景(实测确认的 bug):
    界面 FIELDS = (seq, win, note, email, password, login, name, city, acts, prem, priv)
    但保存账号那行写的是  data[key] = {"email": v[2], "password": v[3]}
    v[2] 其实是【备注】, v[3] 才是【账号】—— 整体错位一格。
    只要它跑过一次并落盘, 文件里就会变成:
        email    = 备注的内容
        password = 真正的邮箱
本脚本就是查这个特征: 正常的 password 不该含 '@'。
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
CAND = [ROOT / "配置" / "ads_accounts.json",
        ROOT / "配置" / "bit_accounts.json",
        ROOT / "_分发给同事" / "ads_accounts.json",
        ROOT / "_分发给同事" / "bit_accounts.json"]

MAIL = re.compile(r"^[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+$")

bad_total = 0
for p in CAND:
    if not p.is_file():
        continue
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[{p.name}] 读不了: {e}")
        continue
    if not isinstance(d, dict) or not d:
        print(f"[{p.name}] 空的 ({p.stat().st_size} B) —— 跳过")
        continue
    good = weird = 0
    samples = []
    for k, v in d.items():
        e = str((v or {}).get("email") or "")
        pw = str((v or {}).get("password") or "")
        if MAIL.match(e) and "@" not in pw:
            good += 1
        else:
            weird += 1
            if len(samples) < 4:
                samples.append((k, e, pw))
    print(f"[{p.name}] 共 {len(d)} 条   正常 {good}   可疑 {weird}")
    for k, e, pw in samples:
        print(f"     [{k}] email={e[:44]!r}")
        print(f"           password={pw[:44]!r}")
    bad_total += weird

print()
if bad_total:
    print(f"★★★ 有 {bad_total} 条可疑 —— 可能已被错位保存写坏 ★★★")
    sys.exit(1)
print("★★★ 账号文件正常: 邮箱位是邮箱, 密码位不含 @ ★★★")
