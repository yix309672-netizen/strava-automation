#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领取客户端 —— 每台机器用这一个文件跟 VPS 上的 claim_server 打交道

核心原则: fail-closed
    领不到就停下来等人处理,【绝不】退化成"本地去重继续跑"。
    因为本地去重一旦启动, 20 个人立刻开始互相重复采集。

用法(集成到 strava_ads.py):
    from claim_client import ClaimClient, ServerDown, ServerConfigError
    cli = ClaimClient(server="http://1.2.3.4:8000", key="xxx", worker="PC07")
    ...
    r = cli.claim_batch(aids)         # 批量领取
    for aid in r["mine"]:  ...处理...
    cli.finish(aid, "pass", note="粉丝120/关注80", location=..., dist_km=...)
    cli.collect(aid, url, ...)        # 落成果
"""
import json
import os
import random
import threading
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("缺依赖: pip install requests")
    raise

# ---------------------------------------------------------------- 异常
class ServerDown(Exception):
    """服务端不可达/持续报错 —— 上层必须停下来, 不能继续采集"""


class ServerConfigError(Exception):
    """配置问题(密钥错等), 重试无意义"""


# ---------------------------------------------------------------- 常量
# ★ 只有这三个状态才算"真的问过服务端了"(终态)。下面两个都不是终态:
#   pending —— 只是暂时归某台机器处理。服务端对【未过期的 pending】同样回
#              taken(claim_store.py:162-163), 而租约一到期就会重新放开给别人领;
#   error   —— 服务端明确可重试(claim_store.py:156-161), 要重试超过
#              MAX_TRIES=3 才真正放弃(claim_store.py:149-155)。
#   把这两种当"问过了"的后果: 本机 130 人(ADS 32+16、BIT 82)被永久拉黑,
#   其中 95 人中心至今没有任何结论 = 真漏采。
_TERMINAL = ("pass", "reject", "done")


# ---------------------------------------------------------------- 客户端
class ClaimClient:
    def __init__(self, server: str, worker: str, key: str = "",
                 timeout: float = 15.0, retries: int = 5,
                 cache_file: str | None = None, cache_refresh_sec: float = 120.0,
                 verbose: bool = True):
        self.server = server.rstrip("/")
        self.worker = worker
        self.key = key
        self.timeout = timeout
        self.retries = retries
        self.verbose = verbose
        self.sess = requests.Session()
        if key:
            self.sess.headers["X-API-Key"] = key
        self.sess.headers["Content-Type"] = "application/json"
        # 本地缓存: 只为减少请求, 不承担去重正确性(正确性在服务端)
        self.cache_file = Path(cache_file) if cache_file else None
        self._cache = {}                # aid -> {"status":..,"note":..}
        self._cache_ts = 0.0
        self.cache_refresh_sec = cache_refresh_sec
        self._lock = threading.Lock()
        self.stats = {"claim": 0, "mine": 0, "taken": 0, "known_hit": 0,
                      "finish": 0, "collect": 0, "retry": 0, "down": 0}
        self._load_cache()

    # ---------------- 基础请求(指数退避) ----------------
    def _post(self, path, payload):
        url = f"{self.server}{path}"
        last = None
        for i in range(self.retries):
            try:
                r = self.sess.post(url, data=json.dumps(payload), timeout=self.timeout)
                if r.status_code == 401:
                    raise ServerConfigError("密钥错误(401), 检查 CLAIM_KEY")
                if r.status_code >= 500:
                    raise ServerDown(f"服务端 {r.status_code}")
                r.raise_for_status()
                return r.json()
            except ServerConfigError:
                raise
            except Exception as e:
                last = e
                self.stats["retry"] += 1
                if i < self.retries - 1:
                    wait = min(30.0, (2 ** i) + random.uniform(0, 0.5))
                    if self.verbose:
                        print(f"[claim] {path} 失败({str(e)[:60]}), {wait:.1f}s 后重试 "
                              f"{i+2}/{self.retries}")
                    time.sleep(wait)
        self.stats["down"] += 1
        raise ServerDown(f"{path} 重试{self.retries}次仍失败: {str(last)[:120]}")

    def _get(self, path, params=None):
        url = f"{self.server}{path}"
        last = None
        for i in range(self.retries):
            try:
                r = self.sess.get(url, params=params, timeout=self.timeout)
                if r.status_code == 401:
                    raise ServerConfigError("密钥错误(401)")
                r.raise_for_status()
                return r.json()
            except ServerConfigError:
                raise
            except Exception as e:
                last = e
                if i < self.retries - 1:
                    time.sleep(min(30.0, 2 ** i))
        raise ServerDown(f"{path} 失败: {str(last)[:120]}")

    # ---------------- 健康检查 ----------------
    def ping(self):
        try:
            return self._get("/health")
        except ServerDown:
            return None

    # ---------------- 本地缓存 ----------------
    def _load_cache(self):
        if self.cache_file and self.cache_file.exists():
            try:
                d = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if d.get("worker") == self.worker:
                    # ★ 历史缓存里混进了 pending/error 这些"非结论"(claim_batch
                    #   把服务端回整批 taken 都写了进来), 读盘时必须按 _TERMINAL
                    #   过滤, 否则老机器一启动就把这 130 人继续拉黑。
                    self._cache = {str(k): x
                                   for k, x in (d.get("known") or {}).items()
                                   if (x or {}).get("status") in _TERMINAL}
                    self._cache_ts = d.get("ts") or 0.0
            except Exception:
                self._cache = {}

    def _save_cache(self):
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_file.with_name(
                self.cache_file.name
                + f".{os.getpid()}.{threading.get_ident()}.tmp")   # 与 _state_write 同款
            tmp.write_text(json.dumps({"worker": self.worker, "known": self._cache,
                                       "ts": self._cache_ts}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, self.cache_file)          # 原子替换
        except Exception:
            pass

    def cache_stale(self):
        """缓存超过阈值就该刷新(防止拿旧状态导致重复劳动)"""
        return (time.time() - self._cache_ts) > self.cache_refresh_sec

    def refresh_known(self, aids):
        """从服务端批量拉已知状态, 合并进本地缓存"""
        aids = [str(a) for a in aids if a]
        if not aids:
            return {}
        merged = {}
        for i in range(0, len(aids), 500):
            chunk = aids[i:i + 500]
            r = self._post("/known", {"aids": chunk})
            merged.update(r.get("known") or {})
        with self._lock:
            # ★ 写侧也只存终态: 服务端 /known 返回的是"非 pending"的状态, 里面
            #   仍然包含 error(可重试)。只靠读侧 local_known 过滤虽然功能上安全,
            #   但会让缓存文件长期留着非终态记录 —— 写侧收口一次, 文件自洽。
            self._cache.update({k: v for k, v in merged.items()
                                if (v or {}).get("status") in _TERMINAL})
            self._cache_ts = time.time()
        self._save_cache()
        return merged

    def local_known(self, aid):
        """只有【终态】才算问过服务端, 否则返回 None(必须去问服务端)。

        现状是 if v: —— 而 {"status": "pending"} 本身就是真值字典, 于是
        "暂时归我处理"被当成了"永远别碰", 本机共 130 人(ADS 32+16、BIT 82)
        被永久拉黑, 其中 95 人中心至今没有任何结论 = 真漏采。
        """
        v = self._cache.get(str(aid))
        if v and (v.get("status") in _TERMINAL):
            self.stats["known_hit"] += 1
            return v
        return None

    # ---------------- 领取 ----------------
    def claim_batch(self, aids):
        """批量领取。返回 {"mine":[...], "taken":[{aid,status,note}...]}
        先用本地缓存剔掉已知的, 剩下的才问服务端(省往返)。
        """
        aids = [str(a) for a in aids if a]
        if not aids:
            return {"mine": [], "taken": []}
        # 1) 本地缓存预筛
        unknown = []
        taken_local = []
        for a in aids:
            v = self.local_known(a)
            if v:
                taken_local.append({"aid": a, "status": v.get("status"),
                                    "note": v.get("note", ""), "src": "cache"})
            else:
                unknown.append(a)
        if not unknown:
            return {"mine": [], "taken": taken_local}
        # 2) 问服务端
        r = self._post("/claim", {"aids": unknown, "worker": self.worker})
        mine = r.get("mine") or []
        taken = taken_local + (r.get("taken") or [])
        self.stats["claim"] += len(unknown)
        self.stats["mine"] += len(mine)
        self.stats["taken"] += len(taken)
        # 3) 把"别人已处理过"的写进本地缓存
        #    ★ 只写终态: 服务端对"未过期的 pending"也会回 taken(claim_store.py:162),
        #      把它写进缓存就等于谎报"问过了"; error 也是可重试的。读侧虽然已经过滤,
        #      这里再收一次口, 保证缓存文件里【永远】只有 pass/reject/done。
        with self._lock:
            for t in (r.get("taken") or []):
                if t.get("status") in _TERMINAL:
                    self._cache[str(t["aid"])] = {"status": t.get("status"),
                                                  "note": t.get("note", "")}
        self._save_cache()
        return {"mine": mine, "taken": taken}

    def claim_one(self, aid):
        r = self.claim_batch([aid])
        return (aid in r["mine"]), r["taken"]

    # ---------------- 提交 ----------------
    def finish(self, aid, status, note="", name="", location="",
               dist_km=None, hub=""):
        """status: pass / reject / error
        reject = 确定淘汰(以后谁都不再查)   error = 可重试(不算淘汰)
        """
        self._post("/finish", {"aid": str(aid), "worker": self.worker,
                               "status": status, "note": note, "name": name,
                               "location": location, "dist_km": dist_km, "hub": hub})
        self.stats["finish"] += 1
        # ★ error 在服务端是可重试的(claim_store.py:156-161), 而且重试超过
        #   MAX_TRIES=3 才放弃 —— 写进缓存就等于谎报"问过了", 下次不再重问,
        #   该重试的人被永久跳过。所以只有终态才落缓存; 非终态顺手把可能残留
        #   的旧结论清掉, 逼下一次去问服务端(正确性永远在服务端)。
        with self._lock:
            if status in _TERMINAL:
                self._cache[str(aid)] = {"status": status, "note": note}
            else:
                self._cache.pop(str(aid), None)
        self._save_cache()

    def collect(self, aid, url, name="", location="", region="",
                segment="", age="", dist_km=None):
        r = self._post("/collected", {"aid": str(aid), "url": url, "worker": self.worker,
                                      "name": name, "location": location,
                                      "region": region, "segment": segment,
                                      "age": age, "dist_km": dist_km})
        self.stats["collect"] += 1
        return r

    # ---------------- 看板 / 导出 ----------------
    def stats_remote(self):
        return self._get("/stats")

    def export_csv(self, out_path):
        r = self.sess.get(f"{self.server}/export", params={"fmt": "csv"},
                          timeout=self.timeout * 4)
        r.raise_for_status()
        Path(out_path).write_bytes(r.content)
        return out_path


def resolve_worker_id(explicit=""):
    """生成机器标识: 优先用参数, 否则 环境变量 主机名"""
    if explicit:
        return explicit
    env = os.environ.get("STRAVA_WORKER")
    if env:
        return env
    import socket
    return socket.gethostname()


if __name__ == "__main__":
    import argparse

    def _cfg_defaults():
        """从本文件旁边的 config.json 读 server/key, 省得手输那一长串 key"""
        for base in (Path(__file__).resolve().parent, Path.cwd()):
            cfg = base / "config.json"
            try:
                if cfg.is_file():
                    d = json.loads(cfg.read_text(encoding="utf-8"))
                    return (d.get("claim_server") or "", d.get("claim_key") or "")
            except Exception:
                continue
        return ("", "")

    _srv_def, _key_def = _cfg_defaults()

    ap = argparse.ArgumentParser(description="领取服务客户端自检")
    ap.add_argument("--server", default=_srv_def,
                    help="如 http://1.2.3.4:8000 (默认读同目录 config.json)")
    ap.add_argument("--key", default=os.environ.get("CLAIM_KEY", "") or _key_def,
                    help="默认读同目录 config.json 的 claim_key")
    ap.add_argument("--worker", default="")
    ap.add_argument("--test", action="store_true", help="跑一次领取->提交的连通性测试")
    a = ap.parse_args()

    if not a.server:
        print("缺少服务端地址: 加 --server, 或把 config.json 放到本文件旁边")
        raise SystemExit(2)
    if not a.key:
        print("警告: 没有 key, 服务端会拒绝。检查 config.json 里的 claim_key")

    w = resolve_worker_id(a.worker)
    cli = ClaimClient(a.server, w, a.key)
    print(f"worker = {w}")
    h = cli.ping()
    if not h:
        print("服务端不可达 —— 采集必须停止(不能退化成本地去重)")
        raise SystemExit(1)
    print(f"服务端 OK: {h}")
    if a.test:
        aid = f"selftest-{int(time.time())}"
        r = cli.claim_batch([aid])
        print(f"领取 {aid} -> mine={r['mine']} taken={r['taken']}")
        if aid in r["mine"]:
            cli.finish(aid, "reject", note="自检, 不算数")
            print("已提交为 reject(自检数据)")
        r2 = cli.claim_batch([aid])
        print(f"再领一次 -> mine={r2['mine']} taken={r2['taken']}  (应为 taken)")
        print("本地统计:", cli.stats)
