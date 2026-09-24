# -*- coding: utf-8 -*-
"""把注入的 _find_project_root 整个换成自包含、不自递归的版本。

要修的两个毛病:
  ① 函数体用了裸 `Path(...)`, 但有些脚本是 `import pathlib` -> NameError
  ② 上一次的全局替换把函数【自己的回退行】也改了, 变成
        return _find_project_root(__file__)
     也就是自己调自己 —— 万一找不到项目根就是无限递归。
做法: 按行定位 def, 一直吃到函数结束(遇到下一个非缩进非空行), 整段换掉。
"""
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
DIRS = [ROOT / "_工具" / d for d in ("生成", "体检", "历史")]

NEW = '''def _find_project_root(start=None):
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


def replace_func(lines):
    """按行把 _find_project_root 整段换掉。返回 (新行列表, 是否改了)。"""
    out, i, n, hit = [], 0, len(lines), False
    while i < n:
        ln = lines[i]
        if ln.startswith("def _find_project_root("):
            hit = True
            out.extend(NEW.splitlines())
            i += 1
            # 吃掉函数体(缩进行)和尾随空行
            while i < n and (lines[i].strip() == "" or lines[i][:1] in (" ", "\t")):
                if lines[i].strip() == "" and i + 1 < n and lines[i + 1][:1] not in (" ", "\t") and lines[i + 1].strip():
                    break
                i += 1
            continue
        out.append(ln)
        i += 1
    return out, hit


fixed = []
for d in DIRS:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        if "def _find_project_root(" not in t:
            continue
        new_lines, hit = replace_func(t.splitlines())
        if hit:
            p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            fixed.append(p.name)

print("=" * 70)
print(f"已重写 _find_project_root 的: {len(fixed)} 个")
for x in fixed:
    print("   ", x)

# 复查: 不该再有裸 Path( 在函数体里, 也不该再自己调自己
bad = []
for d in DIRS:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        if "def _find_project_root(" not in t:
            continue
        seg = t.split("def _find_project_root(", 1)[1].split("\ndef ", 1)[0]
        if "from pathlib import Path as _P" not in seg:
            bad.append((p.name, "不是自包含版"))
        if seg.count("_find_project_root(__file__)") > 0:
            bad.append((p.name, "还在自己调自己"))
print()
if bad:
    print("★ 还有问题:")
    for n, why in bad:
        print(f"   {n}: {why}")
else:
    print("复查通过: 都是自包含、不自递归的版本")
print("=" * 70)
