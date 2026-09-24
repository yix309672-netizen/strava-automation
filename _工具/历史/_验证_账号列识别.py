# -*- coding: utf-8 -*-
"""验证: 账号列自动识别 + 备注列挪到账号前面。

用户要的两件事:
  ① 点「连接并加载」时, 不是账号的文字("跑步26 N")不该塞进【账号】, 要进【备注】
  ② 【备注】列要排在【账号】列前面
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent
PASS, FAIL = [], []


def ck(label, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(label)
    print("    %s %-50s %r" % ("OK  " if ok else "★FAIL", label, got))
    return ok


PROBE = r'''
import importlib.util, json, pathlib, sys


# ★ 控制台/管道是 GBK 时, print 到 ✓ 这类字符会 UnicodeEncodeError 直接崩。
#   这里兜住, 免得"验证脚本自己崩了"被误判成被测对象有问题。
for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(errors="replace")
    except Exception:
        pass
tmp = pathlib.Path(sys.argv[1]); eng = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("ee", eng)
m = importlib.util.module_from_spec(spec)
sys.modules["ee"] = m
spec.loader.exec_module(m)

out = {}
out["looks"] = {
    "邮箱": m._looks_email("rhh3ivg5o23h@stubsyouki.us"),
    "标签": m._looks_email("跑步26 N"),
    "空": m._looks_email(""),
    "带空格": m._looks_email("a @b.com"),
    "中文": m._looks_email("跑步"),
}

# ★ 造两个环境: 一个是邮箱名, 一个是标签名(备注里才有真账号)
FAKE = [
    {"serial_number": 2, "name": "rhh3ivg5o23h@stubsyouki.us",
     "remark": "账号：rhh3ivg5o23h@stubsyouki.us 密码：jihBd1Mg"},
    {"serial_number": 376, "name": "跑步26 N",
     "remark": "账号：pao376abc@yangca.us 密码：pw376xyz"},
    {"serial_number": 400, "name": "跑步40 N", "remark": ""},
]
m.ads_list = lambda *a, **k: FAKE
items = {it["seq"]: it for it in m.list_items()}
out["it"] = items
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def main():
    print("=" * 86)
    print("验证: 账号列自动识别 + 备注列提前")
    print("=" * 86)

    for name in ("ads", "bit"):
        print()
        print("--- 引擎 strava_%s.py ---" % name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="acct_"))
        shutil.copy2(ROOT / "主脚本" / ("strava_%s.py" % name),
                     tmp / ("strava_%s.py" % name))
        (tmp / "config.json").write_text(json.dumps({
            "location": "Chicago, Illinois"}, ensure_ascii=False), encoding="utf-8")
        pf = tmp / "_p.py"
        pf.write_text(PROBE, encoding="utf-8")
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, str(pf), str(tmp),
                            str(tmp / ("strava_%s.py" % name))],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=240, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            FAIL.append("%s 探测失败" % name)
            print("  ★FAIL 探测失败:")
            print(((r.stdout or "") + (r.stderr or ""))[-900:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        L = res["looks"]
        ck("邮箱 -> 认得出是账号", L["邮箱"], True)
        ck("'跑步26 N' -> 不是账号", L["标签"], False)
        ck("空 -> 不是账号", L["空"], False)
        ck("带空格 -> 不是账号", L["带空格"], False)

        if name == "ads":
            it = res["it"]
            ck("① 邮箱名环境: 账号=邮箱", it["2"]["email"],
               "rhh3ivg5o23h@stubsyouki.us")
            ck("① 标签名环境: 账号【不】是那个标签",
               it["376"]["email"] != "跑步26 N", True)
            ck("① 标签名环境: 账号从备注里抠出来了",
               it["376"]["email"], "pao376abc@yangca.us")
            ck("① 标签名环境: 密码也从备注里抠出来了",
               it["376"]["password"], "pw376xyz")
            ck("① 备注里保留了标签原文",
               "跑步26 N" in it["376"]["note"], True)
            ck("① 备注里没有邮箱的环境: 账号留空",
               it["400"]["email"], "")
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------------- 界面列序 ----------------
    print()
    print("--- 界面列序 ---")
    for gui in ("界面/ADS自动化.py", "界面/比特派自动化.py"):
        spec = importlib.util.spec_from_file_location("gx", ROOT / gui)
        g = importlib.util.module_from_spec(spec)
        sys.modules["gx"] = g
        spec.loader.exec_module(g)
        f = list(g.FIELDS)
        print("    %s FIELDS = %s" % (pathlib.Path(gui).name, f))
        ck("② 备注(note) 在 账号(email) 前面", f.index("note") < f.index("email"), True)
        ck("② 备注紧贴在账号前一位", f.index("email") - f.index("note"), 1)
        ck("② FIELDS 仍是 11 列", len(f), 11)
        ck("② 表头有「备注」", g.HEADS.get("note"), "备注")

    print()
    print("=" * 86)
    if FAIL:
        print("★ 失败 %d 项:" % len(FAIL))
        for x in FAIL:
            print("   - " + x)
        return 1
    print("✓ 通过 %d 项: 非账号文字进备注(并从备注里找回真账号) · 备注列排在账号前"
          % len(PASS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
