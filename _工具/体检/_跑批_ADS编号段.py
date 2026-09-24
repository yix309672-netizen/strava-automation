# -*- coding: utf-8 -*-
"""按编号段跑 ADS 全流程 —— 注册 / 资料 / 隐私 / 单位 / 上传轨迹, 【不含采集】。

用法:
    python _跑批_ADS编号段.py --from 83 --to 104            # 跑 83~104
    python _跑批_ADS编号段.py --from 83 --to 104 --dry      # 只看会跑哪些号
    python _跑批_ADS编号段.py --from 83 --to 104 --jobs 1   # 串行(最稳)

和界面「▶ 开始任务」走的是同一条路: 引擎的 run_one_seq()。
本脚本【不调用 collect_one】, 所以一个链接都不会采 —— 采集只归「◎ 只采集」。

★ 默认把浏览器设成"跑完就关"(界面里的 auto_close 是 false, 22 个号会攒下
  22 个浏览器)。要保留窗口加 --keep。
"""
import argparse, importlib.util, json, logging, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

WS = Path(__file__).resolve().parents[2]          # 项目根
LOG_DIR = WS / "_过程记录"
_RES_LOCK = threading.Lock()


def merge_result(seq, res, acc):
    """把引擎结果合并进 数据/ads_results.json。

    ★ 引擎自己【不写】这个文件, 只有界面在写。跑批脚本不补这一步的话,
      界面表格里那几列还是上一轮的旧值(实测: 85 跑成了 Lake Los Angeles,
      表格里却还显示 Los Angeles)。
    ★ 只合并不覆盖 —— 和界面 _save_results 同一个口径, 免得把别人的结果清掉。
    """
    if not isinstance(res, dict):
        return
    f = WS / "数据" / "ads_results.json"
    with _RES_LOCK:
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            return                      # 读不出来就别写, 免得用空表覆盖
        k = str(seq)
        row = dict(data.get(k) or {})
        row["seq"], row["win"] = k, k
        if acc:
            row.setdefault("email", acc[0])
            row.setdefault("password", acc[1])
        for kk in ("name", "city", "acts", "prem", "priv"):
            if res.get(kk) not in (None, ""):
                row[kk] = res[kk]
        if res.get("login") is not None:
            row["login"] = "是" if res["login"] else "否"
        data[k] = row
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(f)


def find_engine():
    for c in (WS / "主脚本" / "strava_ads.py", WS / "strava_ads.py"):
        if c.is_file():
            return c
    raise SystemExit("找不到 主脚本/strava_ads.py")


def load_engine(path):
    os.chdir(str(path.parent))                    # 和界面一致: 相对路径按引擎目录解析
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("strava_ads", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["strava_ads"] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="a", type=int, required=True)
    ap.add_argument("--to", dest="b", type=int, required=True)
    ap.add_argument("--jobs", type=int, default=0, help="并发数, 默认读 config.json")
    ap.add_argument("--dry", action="store_true", help="只列出要跑的号")
    ap.add_argument("--keep", action="store_true", help="跑完不关浏览器")
    ap.add_argument("--only", default="", help="只跑这几个号, 逗号分隔, 如 83,84")
    args = ap.parse_args()

    eng = find_engine()
    SA = load_engine(eng)
    print(f"[引擎] {eng}")
    print(f"[配置] {getattr(SA, 'ROOT', '?')}")

    acc = json.loads((WS / "配置" / "ads_accounts.json").read_text(encoding="utf-8"))
    lo, hi = min(args.a, args.b), max(args.a, args.b)
    want = [int(x) for x in args.only.split(",") if x.strip()] if args.only \
        else list(range(lo, hi + 1))

    creds, skip = {}, []
    for s in want:
        d = acc.get(str(s)) or {}
        if d.get("email") and d.get("password"):
            creds[s] = (d["email"], d["password"])
        else:
            skip.append(s)

    # ★ 同一个邮箱的号错开: 重复邮箱挪到最后, 免得并发时两个浏览器登同一个 Strava 号
    seen, first, dup = set(), [], []
    for s in want:
        if s not in creds:
            continue
        e = creds[s][0].lower()
        (dup if e in seen else first).append(s)
        seen.add(e)
    order = first + dup

    cfg = dict(SA.CFG)
    cfg["task_mode"] = ""                         # 空 = 全部(资料+隐私+轨迹)
    cfg["auto_close"] = not args.keep
    if args.jobs:
        cfg["jobs"] = args.jobs
    jobs = max(1, min(int(cfg.get("jobs") or 1), 3))

    print(f"\n=== 计划 ===")
    print(f"  编号      : {order[0]}~{order[-1]} 共 {len(order)} 个" if order else "  没有可跑的号")
    print(f"  并发      : {jobs}")
    print(f"  执行内容  : 注册/资料/隐私/单位/上传轨迹  (★不含采集)")
    print(f"  位置      : {cfg.get('location')}")
    print(f"  轨迹目录  : {cfg.get('gpx_dir')}")
    print(f"  头像目录  : {cfg.get('avatar_dir')}")
    print(f"  每号上限  : {cfg.get('daily_cap')} 个/天")
    print(f"  跑完关窗  : {cfg['auto_close']}")
    if dup:
        print(f"  重复邮箱  : {dup}  (已排到最后, 避免和前面的号撞车)")
    if skip:
        print(f"  没账号密码: {skip}  (跳过)")
    if args.dry:
        print("\n[dry] 没有真的跑。")
        return 0
    if not order:
        return 1

    LOG_DIR.mkdir(exist_ok=True)
    lf = LOG_DIR / f"跑批_{order[0]}-{order[-1]}_{time.strftime('%Y%m%d_%H%M%S')}.log"
    fh = logging.FileHandler(lf, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger("strava").addHandler(fh)
    print(f"  日志      : {lf}\n")

    try:
        SA.STOP_EVENT.clear()
    except Exception:
        pass
    task = SA.new_task_ctx(mode="跑批", worker="batch")
    t0, done, fail = time.time(), 0, []

    def one(s):
        em, pw = creds[s]
        try:
            r = SA.run_one_seq(s, em, pw, cfg, task)
            merge_result(s, r, (em, pw))
            print(f"  [完成] {s}  {r}")
            return s, r
        except Exception as e:
            print(f"  [失败] {s}  {type(e).__name__}: {str(e)[:110]}")
            return s, None

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        for fut in as_completed([ex.submit(one, s) for s in order]):
            s, r = fut.result()
            if r is None:
                fail.append(s)
            else:
                done += 1

    print(f"\n=== 跑完 ===  成功 {done} / {len(order)}   失败 {fail or '无'}"
          f"   用时 {(time.time() - t0) / 60:.1f} 分钟")
    try:
        fin = SA.finalize_task(task)
        if fin:
            print(f"汇总文件: {fin}")
    except Exception as e:
        print(f"汇总失败: {str(e)[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
