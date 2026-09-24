# -*- coding: utf-8 -*-
"""界面启动桥 —— 纯 ASCII 文件名 + 纯 ASCII 内容。

★★ 为什么需要它 ★★
   两个界面脚本的文件名是中文(界面\\ADS自动化.py / 界面\\比特派自动化.py),
   而 .bat 里【不能写中文】—— cmd 按字节偏移回读, 中文会让解析崩
   (实测报 'elayedExpansion' is not recognized)。
   所以让 .bat 只写这个 ASCII 名字, 由它自己去拼中文路径。
   和分发包里的 open_app.py 是同一个套路。

用法:  python _launch_gui.py ads
       python _launch_gui.py bit
"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

TARGETS = {
    "ads": BASE / "界面" / "ADS自动化.py",
    "bit": BASE / "界面" / "比特派自动化.py",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TARGETS:
        sys.stderr.write("usage: _launch_gui.py [ads|bit]\n")
        return 2
    script = TARGETS[sys.argv[1]]
    if not script.is_file():
        sys.stderr.write("[ERROR] GUI file not found: %s\n" % script.name)
        return 1
    sys.stdout.write("Starting %s ...\n" % script.name)
    sys.stdout.flush()
    try:
        return subprocess.call([sys.executable, str(script)], cwd=str(BASE))
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        sys.stderr.write("[ERROR] %s\n" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
