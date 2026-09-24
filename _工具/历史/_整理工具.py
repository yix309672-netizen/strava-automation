# -*- coding: utf-8 -*-
"""把我这一路写的辅助脚本归类整理, 别都堆在项目根目录。

★★ 用户原话:「这些都还有用吗?」/「不能分类整理好吗?」★★
   根目录堆了 90 多个 _查_/_验证_/_生成_/_修_ 脚本, 99% 是一次性的。

分法(不删任何东西, 只是换个位置):
    根目录      只留 3 个【流程/运行时】需要的
    _工具\生成\  改文案、改启动器时要跑的生成器
    _工具\体检\  以后还会用到的回归验证 + 数据修复工具
    _工具\历史\  一次性脚本, 归档备查(哪天想翻"当时为什么这么改"还有)

★ 移完要修 ROOT: 有些脚本用 Path(__file__).parent 定位项目根, 往下挪一层
  就找错了。这里给"还要用"的那批统一插一段【向上找项目根】的代码,
  无论放在哪一层都能找到(判据: 有 主脚本/strava_ads.py 的那一层)。
"""
import re
import shutil
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")

KEEP_ROOT = ["_launch_gui.py", "_同步分发.py", "_打包给同事.py"]

KEEP_GEN = ["_生成_中文提示.py", "_生成_中文启动器.py", "_生成_隐藏支持.py",
            "_生成_界面启动器.py", "_生成_推送启动器.py"]

KEEP_CHECK = ["_验证_同事拿到能用.py", "_验证_服务器包带修复.py",
              "_验证_列序错位.py", "_验证_采集计数.py",
              "_验证_关闭多余标签.py", "_验证_链接实时落盘.py",
              "_验证_链接跨零点.py", "_验证_快速编辑已关闭.py",
              "_验证_界面消息落盘.py", "_查_结果文件错位.py",
              "_查_账号文件错位.py", "_查_错位诊断.py",
              "_验证_错位还原假设.py", "_修_结果错位.py",
              "_试跑_真机.py", "_试跑_塞标签.py", "_试跑_探API.py"]

ROOT_FIX = '''
# ★ 归类整理后: 向上找项目根(判据: 有 主脚本\\strava_ads.py 的那一层)。
#   原来是 Path(__file__).parent, 脚本一挪位置就找错了。
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

'''


def move(names, subdir):
    dst_dir = ROOT / "_工具" / subdir
    dst_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for n in names:
        src = ROOT / n
        if not src.is_file():
            continue
        dst = dst_dir / n
        if dst.exists():
            dst.unlink()
        shutil.move(str(src), str(dst))
        moved += 1
    return moved


def patch_root(names, subdir):
    """给还要用的脚本插入"向上找项目根", 并把原来的写法替换掉。"""
    dst_dir = ROOT / "_工具" / subdir
    fixed = []
    for n in names:
        p = dst_dir / n
        if not p.is_file():
            continue
        t = p.read_text(encoding="utf-8")
        if "_find_project_root" in t:
            continue
        # 1) 插入 helper(放在最后一条 import 之后)
        lines = t.splitlines(keepends=True)
        last = None
        for i, ln in enumerate(lines[:60]):
            if re.match(r"^(import |from )\S", ln):
                last = i
        if last is None:
            continue
        lines.insert(last + 1, ROOT_FIX)
        t = "".join(lines)
        # 2) 把 Path(__file__).resolve().parent / Path(__file__).parent 换成向上找
        t2 = re.sub(
            r"Path\(__file__\)\.resolve\(\)\.parent",
            "_find_project_root(__file__)", t)
        t2 = re.sub(
            r"Path\(__file__\)\.parent",
            "_find_project_root(__file__)", t2)
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            fixed.append(n)
    return fixed


def main():
    all_mine = sorted(p.name for p in ROOT.glob("_*.py") if p.is_file())

    keep = set(KEEP_ROOT) | set(KEEP_GEN) | set(KEEP_CHECK)
    hist = [n for n in all_mine if n not in keep]

    print("=" * 74)
    print(f"根目录下我的脚本: {len(all_mine)} 个")

    n1 = move(KEEP_GEN, "生成")
    n2 = move(KEEP_CHECK, "体检")
    n3 = move(hist, "历史")
    print(f"  -> _工具\\生成\\   {n1} 个")
    print(f"  -> _工具\\体检\\   {n2} 个")
    print(f"  -> _工具\\历史\\   {n3} 个")
    print(f"  留在根目录: {len(KEEP_ROOT)} 个 -> {KEEP_ROOT}")

    fx = patch_root(KEEP_GEN, "生成") + patch_root(KEEP_CHECK, "体检")
    print()
    print(f"已修正项目根定位的: {len(fx)} 个")
    for x in fx:
        print("   ", x)

    left = sorted(p.name for p in ROOT.glob("_*.py") if p.is_file())
    print()
    print(f"根目录剩下的 _*.py ({len(left)} 个): {left}")
    print("=" * 74)


if __name__ == "__main__":
    main()
