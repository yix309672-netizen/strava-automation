# -*- coding: utf-8 -*-
"""把注入的 _find_project_root 改成【自包含】版本。

上一版里用了裸 `Path(...)`, 但有些脚本是 `import pathlib`(不是 from pathlib
import Path), 于是 NameError: name 'Path' is not defined。

新版在函数内部自己 import, 不依赖外面导入了什么 —— 放到哪个文件都不会炸。
"""
import re
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
    ★ 这里在函数内部自己 import, 不管调用方是 `import pathlib` 还是
      `from pathlib import Path`, 都能跑 —— 上一版用裸 Path 就炸过一回。
    """
    from pathlib import Path as _P
    _p = _P(start or __file__).resolve()
    for _ in range(6):
        _p = _p.parent
        if (_p / "主脚本" / "strava_ads.py").is_file():
            return _p
    return _P(__file__).resolve().parent
'''

# 匹配旧 helper 整体(从 def 到下一个顶层 def 或文件结尾前的空行)
OLD = re.compile(
    r"def _find_project_root\(start=None\):.*?return _P?ath\(__file__\)\.resolve\(\)\.parent\n",
    re.S)

fixed = []
for d in DIRS:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        if "_find_project_root" not in t or "def _find_project_root" not in t:
            continue
        t2 = OLD.sub(NEW, t, count=1)
        if t2 != t:
            p.write_text(t2, encoding="utf-8")
            fixed.append(p.name)

print("=" * 70)
print(f"已换成自包含版本: {len(fixed)} 个")
for x in fixed:
    print("   ", x)
left = []
for d in DIRS:
    if not d.is_dir():
        continue
    for p in sorted(d.glob("*.py")):
        t = p.read_text(encoding="utf-8", errors="replace")
        if "def _find_project_root" in t and "from pathlib import Path as _P" not in t:
            left.append(p.name)
print()
print("仍是旧版的:", left if left else "无")
print("=" * 70)
