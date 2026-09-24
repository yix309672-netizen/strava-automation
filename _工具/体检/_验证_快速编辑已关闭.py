# -*- coding: utf-8 -*-
"""验证 "关掉控制台快速编辑" 这个修复。

★★ 背景(用户 2026-09-20 实测) ★★
   Windows 控制台默认开着【快速编辑】: 在窗口里点一下(开始选文字),
   控制台就挂起所有输出。而引擎的 logging 是
       先 FileHandler(写文件) -> 再 StreamHandler(写控制台)
   于是现象是: 日志文件还在长, 黑窗口却停住不动 -> 看起来就像脚本卡死。
   更严重的是那次写控制台永远不返回, 主线程停住, 心跳不跳,
   15 分钟后看门狗 os._exit(9) 把进程杀掉。
   用户 10:49:34 那条 watchdog 报错就是这么来的。

★★ 这个环境测不了"真控制台" ★★
   本会话的控制台是 headless 的: GetConsoleMode 读得到(0x0003),
   但它【根本不支持快速编辑】—— SetConsoleMode 永远失败(err=87
   ERROR_INVALID_PARAMETER), 连"先把快速编辑打开"都做不到。
   所以这里只能验:
     ① 位运算对不对(纯逻辑, 可验)
     ② 两个引擎都定义了这个函数、且 import 时确实调用了(可验)
   真控制台上的效果, 只能在你自己双击开的窗口里体现。
"""
import ast
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
ENGINES = [("ADS", ROOT / "主脚本" / "strava_ads.py"),
           ("BIT", ROOT / "主脚本" / "strava_bit.py")]
ok_all = True

# ---------------- ① 位运算 ----------------
print("=" * 68)
print("① 清快速编辑的位运算(这是最容易写错的地方)")
QE, EXT = 0x0040, 0x0080
cases = [
    ("开了快速编辑的典型控制台", 0x0003 | QE, True),
    ("已带 EXTENDED_FLAGS", 0x0003 | QE | EXT, True),
    ("本来就没开", 0x0003, False),
    ("带 VT 处理(0x0004)", 0x0003 | QE | 0x0004, True),
]
for name, mode, had_qe in cases:
    new = (mode & ~QE) | EXT
    qe_cleared = not (new & QE)
    ext_on = bool(new & EXT)
    # ★ 比"其它位有没有被碰过"时必须【两边都把 EXT 位遮掉】:
    #   EXT 是我们主动置上的, 留着它去比就一定不相等 —— 第一版就是这么
    #   把正确的实现误判成 FAIL 的。
    kept = (new & ~EXT) == (mode & ~QE & ~EXT)
    good = qe_cleared and ext_on and kept
    if not good:
        ok_all = False
    print(f"   {'OK ' if good else '★  '} {name:24s} 0x{mode:04X} -> 0x{new:04X}"
          f"  快速编辑已清={qe_cleared} EXT置位={ext_on} 其它位不变={kept}")

# ---------------- ② 两个引擎都装了 ----------------
print()
print("② 两个引擎里函数在不在、import 时有没有调用")
for tag, path in ENGINES:
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"   ★ {tag} 语法错: {e}")
        ok_all = False
        continue
    has_def = any(isinstance(n, ast.FunctionDef) and n.name == "_disable_quick_edit"
                  for n in tree.body)
    # 模块级必须有一句裸调用 _disable_quick_edit()
    has_call = any(
        isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "_disable_quick_edit"
        for n in tree.body)
    flag = "OK " if (has_def and has_call) else "★  "
    if not (has_def and has_call):
        ok_all = False
    print(f"   {flag}{tag:4s} 定义={has_def}  import时调用={has_call}")

# ---------------- ③ 顺带确认心跳补上了 ----------------
print()
print("③ sleep_or_stop 里有没有补心跳(避免长时间等待被误判成卡死)")
for tag, path in ENGINES:
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "sleep_or_stop"), None)
    beat = False
    if fn is not None:
        body = ast.dump(fn)
        beat = "'_STALL'" in body and "'beat'" in body
    if not beat:
        ok_all = False
    print(f"   {'OK ' if beat else '★  '}{tag:4s} sleep_or_stop 里打心跳={beat}")

# ---------------- ④ 本机控制台支不支持快速编辑 ----------------
print()
print("④ 本机(这个会话)的控制台情况 —— 仅作说明, 不算失败")
try:
    import ctypes
    k = ctypes.windll.kernel32
    h = k.GetStdHandle(-11)
    m = ctypes.c_uint()
    if k.GetConsoleMode(h, ctypes.byref(m)):
        supported = k.SetConsoleMode(h, (m.value | QE | EXT))
        print(f"   控制台模式=0x{m.value:04X}  支持快速编辑={bool(supported)}")
        if not supported:
            print("   ★ 这个会话是无控制台的(headless), 设不上 —— 真控制台上才会生效")
            print("     你自己的黑窗口里, 模式通常是 0x0003|0x0040, 清得掉。")
    else:
        print("   拿不到控制台句柄(输出被重定向) —— 引擎会安全跳过")
except Exception as e:
    print("   查询失败:", str(e)[:80])

print()
print("=" * 68)
print("★★★ 逻辑与接线都对 ★★★" if ok_all else "★★★ 有检查没过 ★★★")
sys.exit(0 if ok_all else 1)
