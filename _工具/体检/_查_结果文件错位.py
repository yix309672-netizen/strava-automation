# -*- coding: utf-8 -*-
"""检查结果文件有没有被"错位一格"的刷新/保存写坏。

错位的特征很明确:
    正常:  note  = "关注None / 小组None"  或别的备注文字
           email = xxx@yyy.zz
    错位:  note  = xxx@yyy.zz          <- 邮箱跑进备注列了
           email = 密码 / 登录状态       <- 账号列被别的值占了

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
MAIL = re.compile(r"^[\w\.\-\+]+@[\w\-]+\.[\w\.\-]+$")
bad_any = False

for name in ("ads_results.json", "bit_results.json"):
    p = ROOT / "数据" / name
    if not p.is_file():
        print(f"[{name}] 不存在")
        continue
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[{name}] 读不了: {e}")
        continue
    if not isinstance(d, dict) or not d:
        print(f"[{name}] 空文件")
        continue

    note_is_mail = []      # 邮箱跑进了备注列
    email_not_mail = []    # 账号列不是邮箱
    for k, v in d.items():
        if not isinstance(v, dict):
            continue
        note = str(v.get("note") or "").strip()
        email = str(v.get("email") or "").strip()
        if MAIL.match(note):
            note_is_mail.append((k, note, email))
        elif email and not MAIL.match(email):
            email_not_mail.append((k, email, note))

    print("=" * 70)
    print(f"[{name}]  共 {len(d)} 条")
    print(f"   备注列里是邮箱(错位特征): {len(note_is_mail)} 条")
    for k, n, e in note_is_mail[:3]:
        print(f"      [{k}] note={n!r}")
        print(f"            email={e!r}")
    print(f"   账号列不是邮箱: {len(email_not_mail)} 条")
    for k, e, n in email_not_mail[:3]:
        print(f"      [{k}] email={e!r}  note={n!r}")

    if note_is_mail or email_not_mail:
        bad_any = True
    else:
        # 正常长什么样, 也给个例子
        k0 = next(iter(d))
        v0 = d[k0] if isinstance(d[k0], dict) else {}
        print(f"   正常样例 [{k0}]: email={str(v0.get('email'))[:34]!r}")
        print(f"                note={str(v0.get('note'))[:34]!r}")

print()
print("★★★ 结果文件干净, 没有被错位写坏 ★★★" if not bad_any
      else "★★★ 有错位痕迹 —— 需要修复数据 ★★★")
sys.exit(1 if bad_any else 0)
