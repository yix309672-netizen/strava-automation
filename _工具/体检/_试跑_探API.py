# -*- coding: utf-8 -*-
"""跑之前先探一下比特浏览器 API 通不通、有哪些窗口可用。

引擎连的是 CDP, 但"开哪个窗口"要靠这个本地 HTTP API。
不通的话后面一步都跑不起来, 先确认。
"""
import json
import sys
import urllib.request

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

API = "http://127.0.0.1:54345"


def post(path, payload):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


try:
    j = post("/browser/list", {"page": 0, "pageSize": 200})
except Exception as e:
    print("★ 连不上比特 API:", str(e)[:120])
    sys.exit(1)

print("success =", j.get("success"), " msg =", str(j.get("msg"))[:60])
lst = ((j.get("data") or {}).get("list")) or []
print("窗口总数:", len(lst))

import json as _j
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

res = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\数据\bit_results.json")
known = {}
if res.is_file():
    try:
        known = _j.loads(res.read_text(encoding="utf-8"))
    except Exception:
        pass
logged = {str(v.get("win")) for v in known.values()
          if isinstance(v, dict) and str(v.get("login")) == "是"}
print("结果文件里 登录=是 的窗口:", len(logged))

print()
print("前 8 个窗口:")
for w in lst[:8]:
    seq = str(w.get("seq"))
    print("   seq={:<4} id={:<34} name={!r:<22} 登录过={}".format(
        seq, str(w.get("id"))[:34], str(w.get("name"))[:20],
        ("_" + seq) in logged))

usable = [w for w in lst if ("_" + str(w.get("seq"))) in logged]
print()
print("可用于本次试跑的窗口:", len(usable))
if usable:
    u = usable[0]
    print("   打算用 seq={} id={} name={!r}".format(
        u.get("seq"), u.get("id"), u.get("name")))
