# -*- coding: utf-8 -*-
"""验证"多余标签自动关闭"的逻辑与【安全线】。

用户要求: 浏览器里只保留脚本工作页面, 其他的全关掉(省内存)。
但关错一个就可能把正在用的页面关掉 -> 采集当场断。所以重点验安全线:

  ① 工作页绝对不关
  ② 指纹浏览器内部页(chrome://设置 之类)不关
  ③ 但【空白页/新建标签页】必须关 —— 它们最占内存又没用
     (第一版把 about:blank 也当内部页保护了, 等于放过了最该清的一类)
  ④ 绝不把页面关到一个不剩
  ⑤ 关的过程中出异常也不能把调用方搞挂

做法: 假页面对象(有 .url / .close() / .context), 调引擎里那个真函数。
"""
import importlib.util
import shutil
import sys
import tempfile
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


class FakePage:
    def __init__(self, url, ctx=None, boom=False):
        self.url = url
        self._ctx = ctx
        self.closed = False
        self._boom = boom

    @property
    def context(self):
        return self._ctx

    def close(self):
        if self._boom:
            raise RuntimeError("close failed (模拟)")
        self.closed = True


class FakeCtx:
    def __init__(self, pages):
        self.pages = pages
        for p in pages:
            p._ctx = self


def load_engine(tag, name):
    tmp = Path(tempfile.mkdtemp(prefix="_pg_"))
    src = ROOT / "主脚本" / name
    shutil.copy2(src, tmp / name)
    (tmp / "config.json").write_text("{}", encoding="utf-8")
    for dep in ("geo_cities.py", "claim_client.py"):
        if (ROOT / dep).is_file():
            shutil.copy2(ROOT / dep, tmp / dep)
    sys.path.insert(0, str(tmp))
    spec = importlib.util.spec_from_file_location("_e_" + tag, tmp / name)
    m = importlib.util.module_from_spec(spec)
    sys.modules["_e_" + tag] = m
    spec.loader.exec_module(m)
    return m


ok_all = True

for tag, name in (("ADS", "strava_ads.py"), ("BIT", "strava_bit.py")):
    m = load_engine(tag, name)
    f = m.close_extra_pages
    print("=" * 72)
    print(f"===== {tag} =====")
    cases = []

    # ① 工作页 + 3 个真标签 + 1 个空白 -> 全关
    work = FakePage("https://www.strava.com/maps/global-heatmap/segments")
    others = [FakePage("https://www.strava.com/athletes/1"),
              FakePage("https://www.strava.com/dashboard"),
              FakePage("https://www.strava.com/settings/profile"),
              FakePage("")]
    FakeCtx([work] + others)
    n = f(work, tag=" [case1]")
    cases.append(("工作页保留 + 关掉 4 个多余",
                  n == 4 and not work.closed and all(p.closed for p in others),
                  f"关掉={n} 工作页被关={work.closed}"))

    # ② 内部页不关, 但空白页要关
    work = FakePage("https://www.strava.com/maps/x")
    internal = [FakePage("chrome://settings"),
                FakePage("http://127.0.0.1:54345/console.bitbrowser")]
    blank = [FakePage("about:blank"), FakePage(""), FakePage("chrome://newtab/")]
    junk = [FakePage("https://example.com/x")]
    FakeCtx([work] + internal + blank + junk)
    n = f(work, tag=" [case2]")
    cases.append(("内部页保留, 空白页全部关掉",
                  n == 4
                  and not any(p.closed for p in internal)
                  and all(p.closed for p in blank + junk),
                  f"关掉={n} 内部页被关={any(p.closed for p in internal)}"
                  f" 空白页还剩={sum(1 for p in blank if not p.closed)}"))

    # ③ 只有工作页 -> 什么都不做
    work = FakePage("https://www.strava.com/maps/x")
    FakeCtx([work])
    n = f(work)
    cases.append(("只有工作页时不动作", n == 0 and not work.closed, f"关掉={n}"))

    # ④ ★ 工作页已失效(不在 ctx.pages 里) -> 绝不能全关光
    others = [FakePage("https://a.example/1"), FakePage("https://a.example/2")]
    ctx = FakeCtx(others)          # 工作页不在这里面
    ghost = FakePage("https://www.strava.com/maps/x", ctx=ctx)
    n = f(ghost, tag=" [case4]")
    left = sum(1 for p in others if not p.closed)
    cases.append(("工作页失效时至少留一个",
                  n == 1 and left == 1, f"关掉={n} 剩余={left}"))

    # ⑤ close() 抛异常 -> 不把调用方搞挂
    work = FakePage("https://www.strava.com/maps/x")
    bad = [FakePage("https://b.example/1", boom=True),
           FakePage("https://b.example/2")]
    FakeCtx([work] + bad)
    try:
        n = f(work)
        cases.append(("close 抛异常也不崩", not work.closed,
                      f"关掉={n} (一个失败被吞)"))
    except Exception as e:
        cases.append(("close 抛异常也不崩", False, f"抛了 {type(e).__name__}"))

    for name_, ok, detail in cases:
        if not ok:
            ok_all = False
        print(f"   {'OK ' if ok else '★  '}{name_:26s} {detail}")

print()
print("★★★ 只关多余的; 工作页/内部页安全, 空白页照关 ★★★" if ok_all
      else "★★★ 有失败项 ★★★")
sys.exit(0 if ok_all else 1)
