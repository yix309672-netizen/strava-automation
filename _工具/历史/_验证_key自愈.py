# -*- coding: utf-8 -*-
"""验证: 改完 config.json 的 adspower_key, 【不重启程序】也能生效。

复刻同事那台机器的确切情形:
    程序启动时 config.json 里 adspower_key 是空的 -> 引擎用空 key -> 一直报错
    后来把 key 填进去了, 但没重启 -> 旧代码永远读不到(一次性快照)
"""
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
out["key_at_import"] = m.ADS_KEY                 # 启动时是空的
out["hdr_at_import"] = m.ADS_H.get("Authorization")

# ---- 模拟同事后来把 key 填进 config.json(程序没重启) ----
cfg = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
cfg["adspower_key"] = "FILLED_IN_LATER_0123456789abcdef"
(tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                 encoding="utf-8")

# ---- 下一次发请求时会调 ads_headers() ----
h = m.ads_headers()
out["key_after"] = m.ADS_KEY
out["hdr_after"] = h.get("Authorization")
out["healed"] = m.ADS_KEY == "FILLED_IN_LATER_0123456789abcdef"

# 再调一次应当保持(不再重复读盘)
out["stable"] = m.ads_headers().get("Authorization") == h.get("Authorization")

# ★ 关键: 已经是好的 key 时, 不该被空值覆盖回去
cfg["adspower_key"] = ""
(tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
out["after_blanking"] = m.ads_headers().get("Authorization")
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''


def main():
    print("=" * 84)
    print("验证: adspower_key 改完不重启也能生效(self-heal)")
    print("=" * 84)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="keyheal_"))
    shutil.copy2(ROOT / "主脚本" / "strava_ads.py", tmp / "strava_ads.py")
    # ★ 复刻同事的起点: key 是空的
    (tmp / "config.json").write_text(json.dumps({
        "adspower_key": "",                 # ← 空的
        "adspower_api": "http://127.0.0.1:50325",
        "location": "Chicago, Illinois",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pf = tmp / "_p.py"
    pf.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, str(pf), str(tmp), str(tmp / "strava_ads.py")],
                       cwd=str(tmp), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240, env=env)
    res = None
    for line in (r.stdout or "").splitlines():
        if line.startswith("PROBE="):
            res = json.loads(line[6:])
    if res is None:
        print("  ★ 探测失败:")
        print(((r.stdout or "") + (r.stderr or ""))[-1200:])
        shutil.rmtree(tmp, ignore_errors=True)
        return 1

    ck("前提: 导入时 key 确实是空的", res["key_at_import"], "")
    ck("前提: 导入时请求头是 'Bearer '(空)",
       res["hdr_at_import"], "Bearer ")
    ck("★ 改配置后 ads_headers() 自动读到新 key", res["healed"], True)
    ck("★ 请求头变成 'Bearer FILLED_IN_LATER...'",
       res["hdr_after"], "Bearer FILLED_IN_LATER_0123456789abcdef")
    ck("好 key 不会被空值覆盖回去",
       res["after_blanking"], "Bearer FILLED_IN_LATER_0123456789abcdef")
    ck("重复调用保持稳定", res["stable"], True)
    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 84)
    if FAIL:
        print("★ 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print("✓ 通过 %d 项: 同事填完 key 保存即可生效, 不用重启程序" % len(PASS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
