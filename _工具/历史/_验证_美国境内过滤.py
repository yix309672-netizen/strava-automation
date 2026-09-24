# -*- coding: utf-8 -*-
"""验证: 只采美国境内的用户 —— 真调 check_athlete(), 不是读代码猜。

为什么要真调:
  上一轮我插进 check_athlete 的那段用了 _us_on / _us_strict 两个变量, 却
  【忘了定义】。py_compile 查不出来(语法没问题), 只有真跑一次才会 NameError。
  所以这个测试用一个假 page 把整条判定路径走通。

打桩: rate_gate / goto_retry / wait_text 换成空操作(它们只影响速度, 与判定无关)。
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
    print("    %s %-52s %r" % ("OK  " if ok else "★FAIL", label, got))
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

# ---- 打桩: 只保留判定逻辑 ----
m.rate_gate = lambda *a, **k: None
m.goto_retry = lambda *a, **k: None
m.wait_text = lambda *a, **k: True


class FakePage:
    """只回答 check_athlete 会问的两个问题。"""
    def __init__(self, followers=50, following=50, private=False, loc=""):
        self.f, self.g, self.p, self.loc = followers, following, private, loc
    def evaluate(self, js, *a):
        s = str(js)
        if "var pick = function" in s:          # JS_READ_LOC
            return {"loc": self.loc}
        if "document.body.innerText" in s:      # 资料页 JS
            if self.p:
                return {"private": True}
            return {"private": False, "followers": self.f, "following": self.g}
        return 1                                # wait_text 之类

# ★ 两个引擎的圆心函数名不同: ADS 叫 geo_resolve_center, 比特叫 resolve_center_safe
_fn = getattr(m, "geo_resolve_center", None) or getattr(m, "resolve_center_safe")
CENTER = _fn("Chicago, Illinois")[:3]
out = {}

def run(loc, us_only=True, strict=False, geo=True, followers=50):
    p = FakePage(followers=followers, following=50, loc=loc)
    try:
        ok, why = m.check_athlete(p, "123", max_followers=200, geo_filter=geo,
                                  center=CENTER, exempt_max=False,
                                  us_only=us_only, us_only_strict=strict)
        return [ok, why]
    except Exception as e:
        return ["EXC", "%s: %s" % (type(e).__name__, str(e)[:60])]

# ① 名字都对得上 -> 必须不抛异常(上一轮的 NameError 就死在这里)
out["smoke"] = run("Chicago, Illinois")

# ② 美国境内(离芝加哥 <100km 的会被环带淘汰, 所以用远处的美国城市)
out["us_far"] = run("New York, NY")          # 约 1145km -> 环带内(<=1000? 不, 淘汰)
out["us_mid"] = run("Nashville, Tennessee")  # 约 700km -> 环带内
out["us_small"] = run("Wahiawa, Hawaii")     # 小地方 -> 是美国
out["us_bare"] = run("Medicine Lodge")       # 裸名, 补表后认得出

# ③ 境外 -> 必须淘汰(不管环带)
out["fr"] = run("Paris, France")
out["ca"] = run("Toronto, Ontario")
out["la"] = run("Vientiane, Laos")
out["cn"] = run("Beijing, China")

# ④ 认不出 -> 默认保留; strict 时淘汰
out["unk_keep"] = run("Vientiane", strict=False)
out["unk_strict"] = run("Vientiane", strict=True)

# ⑤ 关掉 us_only -> 境外也不该因为这个被淘汰
out["off"] = run("Paris, France", us_only=False)

# ⑥ 空位置
out["empty_keep"] = run("", strict=False)
out["empty_strict"] = run("", strict=True)
out["empty_off"] = run("", us_only=False)

# ⑦ 圆心: 配置是 Chicago, 所以纳什维尔(约700km)应在带内, 纽约(约1145km)应太远
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def main():
    print("=" * 86)
    print("验证: 只采美国境内 + 圆心按脚本位置")
    print("=" * 86)
    for name in ("ads", "bit"):
        print()
        print("--- strava_%s.py ---" % name)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="usonly_"))
        shutil.copy2(ROOT / "主脚本" / ("strava_%s.py" % name),
                     tmp / ("strava_%s.py" % name))
        # ★ 必须把 geo_cities.py 一起拷过去: 否则引擎 import 不到州表,
        #   国别判定全部走"认不出"分支(我第一次就漏了, 结果美国城市被判境外)
        shutil.copy2(ROOT / "geo_cities.py", tmp / "geo_cities.py")
        (tmp / "config.json").write_text(json.dumps({
            "location": "Chicago, Illinois", "geo_center": "config",
            "us_only": True, "us_only_strict": False,
            "geo_filter": True, "geo_band_min_km": 100, "geo_band_max_km": 1000,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pf = tmp / "_p.py"
        pf.write_text(PROBE, encoding="utf-8")
        env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run([sys.executable, str(pf), str(tmp),
                            str(tmp / ("strava_%s.py" % name))],
                           cwd=str(tmp), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300, env=env)
        res = None
        for line in (r.stdout or "").splitlines():
            if line.startswith("PROBE="):
                res = json.loads(line[6:])
        if res is None:
            FAIL.append("%s 探测失败" % name)
            print("  ★FAIL 探测失败:")
            print(((r.stdout or "") + (r.stderr or ""))[-1200:])
            shutil.rmtree(tmp, ignore_errors=True)
            continue

        # ① 不抛异常(这条就是上一轮那个 bug 的回归)
        ck("① 正常资料页不抛异常(修 NameError)",
           res["smoke"][0] in (True, False), True)
        if res["smoke"][0] == "EXC":
            print("        ★ 异常内容: %s" % res["smoke"][1])

        # ② 美国境内的不能因为"国别"被淘汰(被环带淘汰是允许的, 理由要能区分)
        for k, label in (("us_mid", "Nashville, Tennessee"),
                         ("us_small", "Wahiawa, Hawaii"),
                         ("us_bare", "Medicine Lodge(裸名)")):
            why = str(res[k][1])
            ck("② 美国 %-24s 不是因国别淘汰" % label,
               ("美国" not in why), True)
        ck("② 美国 Nashville 在环带内被保留", res["us_mid"][0], True)
        ck("② 美国 New York(1145km) 因太远淘汰",
           res["us_far"][0], False)

        # ③ 境外必须淘汰
        for k, label in (("fr", "Paris, France"), ("ca", "Toronto, Ontario"),
                         ("la", "Vientiane, Laos"), ("cn", "Beijing, China")):
            ck("③ 境外 %-22s 淘汰" % label, res[k][0], False)
            ck("③   理由=不在美国境内", "不在美国境内" in str(res[k][1]), True)

        # ④ 认不出: 默认留, 严格淘汰
        ck("④ 认不出 -> 默认保留", res["unk_keep"][0] in (True, False), True)
        ck("④ 认不出 -> 严格模式淘汰", res["unk_strict"][0], False)
        ck("④   严格理由", "国别认不出" in str(res["unk_strict"][1]), True)

        # ⑤ 关掉 us_only
        ck("⑤ us_only=false 时境外不因国别淘汰", "不在美国境内" in str(res["off"][1]), False)

        # ⑥ 空位置
        ck("⑥ 空位置 -> 默认保留", res["empty_keep"][0] in (True, False), True)
        ck("⑥ 空位置 -> 严格淘汰", res["empty_strict"][0], False)
        ck("⑥ 空位置 -> us_only=false 不淘汰", res["empty_off"][0] in (True, False), True)

        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 86)
    if FAIL:
        print("★ 失败 %d 项:" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✓ 通过 %d 项: 真调 check_athlete() —— 美国人保留 · 境外淘汰 · 认不出默认留"
          % len(PASS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
