# -*- coding: utf-8 -*-
"""生成两个隐藏窗口用的小工具(都放进分发包)。

★★ 为什么是两个外部文件, 而不是塞进 .bat ★★
   .bat 里不能出现任何非 ASCII 字符(cmd 按字节偏移回读, 中文会让解析崩),
   所以"隐藏窗口"和"弹中文提示框"这两件事必须交给外部程序;
   .bat 只用【纯 ASCII 的调用语句】去调它们。

· _hide.ps1   隐藏【当前控制台窗口】。
              powershell 由 cmd 启动时共用同一个控制台,
              所以 GetConsoleWindow() 拿到的就是那个黑窗口的句柄。
· _msgbox.vbs 把一个 UTF-8 文本文件的内容弹成消息框。
              窗口藏起来之后, 出错信息只能靠它传达给同事。

两个文件名都必须是 ASCII —— .bat 里引用它们时是【字面量】。
"""
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

PKG = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917\_分发给同事")

HIDE_PS1 = r'''# Hide the console window shared with the calling cmd.exe.
# Called by the daily launchers so colleagues never see a black window.
# ASCII only on purpose: a .bat cannot safely carry non-ASCII bytes.
$ErrorActionPreference = "Stop"
try {
    Add-Type -Name Con -Namespace W -MemberDefinition @"
[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
"@
    $h = [W.Con]::GetConsoleWindow()
    if ($h -eq [IntPtr]::Zero) { exit 3 }
    [void][W.Con]::ShowWindow($h, 0)
    exit 0
} catch {
    exit 4
}
'''

MSGBOX_VBS = r'''' _msgbox.vbs  <utf8-text-file>  [title]
' Show the file's content in a message box.
' ASCII only: the Chinese text lives in the file, because a .bat
' cannot carry non-ASCII bytes without breaking cmd's parser.
Option Explicit
Dim fso, sh, a, p, title, st, text
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
Set a   = WScript.Arguments
If a.Count < 1 Then WScript.Quit 1
p = a(0)
title = "Strava"
If a.Count >= 2 Then title = a(1)
If Not fso.FileExists(p) Then WScript.Quit 2
On Error Resume Next
Set st = CreateObject("ADODB.Stream")
st.Type = 2
st.Charset = "utf-8"
st.Open
st.LoadFromFile p
text = st.ReadText
st.Close
If Err.Number <> 0 Then
    text = "Cannot read the message file: " & p & vbCrLf & Err.Description
    Err.Clear
End If
On Error GoTo 0
' 4160 = 64 (information icon) + 4096 (keep on top of other windows)
sh.Popup text, 0, title, 4160
'''


def main():
    bad = []
    for name, text in (("_hide.ps1", HIDE_PS1), ("_msgbox.vbs", MSGBOX_VBS)):
        body = text.replace("\r\n", "\n").replace("\n", "\r\n")
        try:
            data = body.encode("ascii", "strict")
        except UnicodeEncodeError as e:
            bad.append("%s 含非 ASCII: %s" % (name, e))
            continue
        (PKG / name).write_bytes(data)
        print("  + %-14s %5d B  ASCII OK" % (name, len(data)))

    # _hide.ps1 必须是 UTF-8 无 BOM(PowerShell 对 BOM 敏感, 但无 BOM 也能跑)
    b = (PKG / "_hide.ps1").read_bytes()
    if b[:3] == b"\xef\xbb\xbf":
        bad.append("_hide.ps1 带了 BOM")
    print()
    if bad:
        print("★★★ 有问题 ★★★")
        for x in bad:
            print("   -", x)
        return 1
    print("★★★ 两个隐藏工具已生成(纯 ASCII) ★★★")
    return 0


if __name__ == "__main__":
    sys.exit(main())
