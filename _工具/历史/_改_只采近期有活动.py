# -*- coding: utf-8 -*-
"""一次性手术: 采集时只保留"近期还有活动"的人(默认 60 天)。

用户 2026-09-22: "设置一下只采集近期两个月有活动轨迹的用户。"

★★ 数据从哪来(真页面上探过, 不是猜的) ★★
   Strava 资料页把活动时间放在结构化标签上:
       <time class="timeago" datetime="2026-09-21T17:47:06Z">7 hours ago</time>
   读 datetime 属性就行 —— 不用管界面语言、也不用解析 "7 hours ago" 这种文字。
   另外还有一句兜底: "Last 4 Weeks N Total Activities"。
   check_athlete() 本来就会打开 /athletes/{id}, 所以这是【零额外请求】。

补 6 处(两个引擎都要, 且保持一致):
   ① from datetime import datetime -> + timezone
   ② check_athlete 签名加 recent_days=0
   ③ 那段 JS 里多读 recent_dates / four_week
   ④ check_athlete 里做判定(放在粉丝判定之前)
   ⑤ collect_regions 里从 CFG 读 recent_days(默认 60, 0=不启用)
   ⑥ 调用点把 recent_days=_recent 传下去

★ 每处都先数出现次数, 不是恰好 1 次就不动文件。
"""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\1\Desktop\Strava自动化_备份_20260917")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

# ① 导入 timezone
P1_OLD = "from datetime import datetime\n"
P1_NEW = "from datetime import datetime, timezone\n"

# ② 签名
P2_OLD = ("                  us_only=None, us_only_strict=None):\n")
P2_NEW = ("                  us_only=None, us_only_strict=None, recent_days=0):\n")

# ③ JS: 多读近期活动
P3_OLD = ("            if (m) { var k = _lab(e.textContent); if (k) out[k] = parseInt(m[1].replace(/,/g, '')); }\n"
          "        }\n"
          "        return out;\n")
P3_NEW = ("            if (m) { var k = _lab(e.textContent); if (k) out[k] = parseInt(m[1].replace(/,/g, '')); }\n"
          "        }\n"
          "        // ---- ★ 2026-09-22 用户要求: 只采\"近期还有活动\"的人 ----\n"
          "        //   Strava 把活动时间放在 <time class=\"timeago\" datetime=\"ISO\"> 上,\n"
          "        //   读 datetime 属性即可 —— 不用管界面语言, 也不用解析 \"7 hours ago\"。\n"
          "        var ds = [];\n"
          "        var tns = document.querySelectorAll('time[datetime]');\n"
          "        for (var q = 0; q < tns.length; q++) {\n"
          "            var dv = tns[q].getAttribute('datetime');\n"
          "            if (dv) ds.push(dv);\n"
          "        }\n"
          "        out.recent_dates = ds.slice(0, 40);\n"
          "        // 兜底: \"Last 4 Weeks 12 Total Activities\"\n"
          "        var m4 = t.match(/Last\\s+4\\s+Weeks[\\s\\S]{0,60}?([\\d,]+)\\s+Total\\s+Activit/i)\n"
          "              || t.match(/\\u6700\\u8fd1\\s*4\\s*\\u5468[\\s\\S]{0,30}?([\\d,]+)\\s*(?:\\u6b21)?\\u6d3b\\u52a8/);\n"
          "        out.four_week = m4 ? parseInt(m4[1].replace(/,/g, '')) : -1;\n"
          "        return out;\n")

# ④ 判定(插在粉丝判定之前)
P4_OLD = ("            if followers < max_followers and following < max_followers:\n")
P4_NEW = ("            # ---- ★ 近期活动筛选(用户 2026-09-22: 只采近两个月还有活动的) ----\n"
          "            #   recent_days<=0 = 不启用(老行为)。判定优先级:\n"
          "            #     ① 页面上 <time datetime> 里最新的一条 —— 精确到秒, 首选\n"
          "            #     ② 页面不给具体日期时看 \"Last 4 Weeks N Total Activities\"\n"
          "            #        (4 周=28 天, 只要 >0 就必然落在 60 天窗口里)\n"
          "            #   两个都拿不到 = 资料页上看不到任何近期活动 -> 淘汰。\n"
          "            if recent_days and recent_days > 0:\n"
          "                _newest, _age = None, None\n"
          "                for _s in (r.get(\"recent_dates\") or []):\n"
          "                    try:\n"
          "                        _d = datetime.fromisoformat(str(_s).replace(\"Z\", \"+00:00\"))\n"
          "                    except Exception:\n"
          "                        continue\n"
          "                    if _newest is None or _d > _newest:\n"
          "                        _newest = _d\n"
          "                if _newest is not None:\n"
          "                    try:\n"
          "                        _age = (datetime.now(timezone.utc) - _newest).days\n"
          "                    except Exception:\n"
          "                        _age = None\n"
          "                _fw = r.get(\"four_week\", -1)\n"
          "                if _age is not None and _age <= recent_days:\n"
          "                    log.info(f\"[recent] {aid} 最近活动 {_age} 天前\"\n"
          "                             f\"(4周内 {_fw} 次) -> 保留\")\n"
          "                elif _age is None and isinstance(_fw, int) and _fw > 0 \\\n"
          "                        and recent_days >= 28:\n"
          "                    log.info(f\"[recent] {aid} 页面没给具体日期, \"\n"
          "                             f\"但 4 周内有 {_fw} 次活动 -> 保留\")\n"
          "                else:\n"
          "                    log.info(f\"[recent] {aid} 最近活动 \"\n"
          "                             + (f\"{_age} 天前\" if _age is not None else \"读不到\")\n"
          "                             + f\"(4周内 {_fw} 次) -> 淘汰(超过 {recent_days} 天)\")\n"
          "                    return False, f\"近{recent_days}天没活动\"\n"
          "            if followers < max_followers and following < max_followers:\n")

# ⑤ collect_regions 里解析 recent_days
P5_OLD = ("    _geo = bool(CFG.get(\"geo_filter\", True)) if geo_filter is None else bool(geo_filter)\n")
P5_NEW = ("    _geo = bool(CFG.get(\"geo_filter\", True)) if geo_filter is None else bool(geo_filter)\n"
          "    # ★ 2026-09-22 用户要求: 只采\"近期还有活动\"的人\n"
          "    #   默认 60 天(两个月); config.json 里 recent_days=0 可关掉。\n"
          "    try:\n"
          "        _recent = int(CFG.get(\"recent_days\", 60))\n"
          "    except Exception:\n"
          "        _recent = 60\n")

# ⑥ 调用点(两个引擎写法不同)
P6 = {
    "strava_ads.py": ("                                                    exempt_max=_exempt)\n",
                      "                                                    exempt_max=_exempt,\n"
                      "                                                    recent_days=_recent)\n"),
    "strava_bit.py": ("                                                    exempt_max=region_exempt)\n",
                      "                                                    exempt_max=region_exempt,\n"
                      "                                                    recent_days=_recent)\n"),
}

ok = True
for name in ("strava_ads.py", "strava_bit.py"):
    p = ROOT / "主脚本" / name
    src = p.read_text(encoding="utf-8")
    old_src = src
    patches = [("① timezone", P1_OLD, P1_NEW), ("② 签名", P2_OLD, P2_NEW),
               ("③ JS 读日期", P3_OLD, P3_NEW), ("④ 判定逻辑", P4_OLD, P4_NEW),
               ("⑤ 解析 recent_days", P5_OLD, P5_NEW),
               ("⑥ 调用点", P6[name][0], P6[name][1])]
    print(f"=== {name}")
    bad = False
    for tag, o, n in patches:
        c = src.count(o)
        if c != 1:
            print(f"   ★ {tag}: 命中 {c} 次(要恰好 1 次) —— 放弃, 文件没动")
            bad = True
            break
        src = src.replace(o, n, 1)
        print(f"   OK {tag}")
    if bad:
        ok = False
        continue
    try:
        compile(src, str(p), "exec")
    except SyntaxError as e:
        print(f"   ★ 改完语法不过: {e} —— 放弃, 文件没动")
        ok = False
        continue
    bak = p.with_name(p.name + f".bak_before_近期活动_{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(p, bak)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(src, encoding="utf-8")
    import os
    os.replace(tmp, p)
    print(f"   已写回 (+{len(src) - len(old_src)} 字节); 备份: {bak.name}")

print()
print("手术完成" if ok else "★ 有步骤失败, 见上")
sys.exit(0 if ok else 1)
