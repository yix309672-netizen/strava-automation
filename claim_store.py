#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领取/去重 核心存储 —— 纯标准库, 无任何 web 依赖

这一层是"不重复采集"的唯一真源。claim_server.py(HTTP层) 和本地测试都调用它。

存储: SQLite + WAL
    * aid 做主键 -> 全局唯一, 去重由数据库保证, 不依赖应用层判断
    * reject(淘汰) 也落库 -> 以后任何人都不再查这个人 (最大的一笔节省)
    * error(读取失败) 与 reject 严格区分 -> 可重试, 不会把真客户当废数据丢掉
    * 领取带租约 -> 领取者崩溃后自动回收, 不会永久卡死

用法:
    from claim_store import ClaimStore
    st = ClaimStore("strava_claim.db")
    r = st.claim(["123","456"], worker="PC07")
    st.finish("123", "PC07", "reject", note="距Chicago仅46km")
"""
import sqlite3
import threading
import time
from pathlib import Path

# 领取租约(秒): 超时未提交视为放弃, 允许他人接管。
# ★ 原来是 900 秒(15 分钟)。但 collect_regions 是【一批最多 40 个人】一起领的
#   (check_per_segment 默认 40), 逐个打开资料页筛完很容易超过 15 分钟 ——
#   队尾那些人就会被别的机器抢走 = 重复采集。宁可锁久一点, 也不能重复采;
#   真有人崩了, 管理员用 /reset_stale 手动回收即可。
LEASE_SEC = 3600

# status='error'(读页面失败, 可重试) 最多被重领几次。
# ★ 原来是"无条件可领", 于是一个被封号/删号的运动员会被 20 台机器
#   无限重领, 每次都白跑一遍完整流程。
MAX_TRIES = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS athletes (
    aid       TEXT PRIMARY KEY,          -- Strava athlete id
    status    TEXT NOT NULL,             -- pending / pass / reject / error
    worker    TEXT NOT NULL,
    note      TEXT,
    name      TEXT,
    location  TEXT,
    dist_km   REAL,
    hub       TEXT,
    ts        REAL NOT NULL,
    lease_ts  REAL,
    tries     INTEGER DEFAULT 0          -- 被重领过几次(超过 MAX_TRIES 就不再发)
);
CREATE INDEX IF NOT EXISTS idx_ath_status ON athletes(status);
CREATE INDEX IF NOT EXISTS idx_ath_worker ON athletes(worker);

CREATE TABLE IF NOT EXISTS collected (
    aid      TEXT PRIMARY KEY,           -- 全局唯一: 一个人只落一条
    url      TEXT NOT NULL,
    name     TEXT,
    location TEXT,
    region   TEXT,
    segment  TEXT,
    age      TEXT,
    dist_km  REAL,
    worker   TEXT,
    ts       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_col_worker ON collected(worker);
CREATE INDEX IF NOT EXISTS idx_col_region ON collected(region);

CREATE TABLE IF NOT EXISTS workers (
    worker    TEXT PRIMARY KEY,
    last_seen REAL,
    claims    INTEGER DEFAULT 0,
    passed    INTEGER DEFAULT 0,
    rejected  INTEGER DEFAULT 0,
    errors    INTEGER DEFAULT 0
);
"""


class ClaimStore:
    def __init__(self, path="strava_claim.db", lease_sec=LEASE_SEC):
        self.path = str(path)
        self.lease_sec = lease_sec
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        c = self._conn
        c.execute("PRAGMA journal_mode=WAL")     # 并发读 + 单写
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000")   # 锁冲突自动排队
        c.executescript(SCHEMA)
        # 老库没有 tries 列, 补上(列已存在时 ALTER 会报错, 忽略即可)
        try:
            c.execute("ALTER TABLE athletes ADD COLUMN tries INTEGER DEFAULT 0")
        except Exception:
            pass
        c.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------ 内部
    def _touch(self, worker):
        self._conn.execute(
            """INSERT INTO workers(worker,last_seen) VALUES(?,?)
               ON CONFLICT(worker) DO UPDATE SET last_seen=excluded.last_seen""",
            (worker, time.time()))

    def _bump(self, worker, field, n=1):
        self._conn.execute(f"UPDATE workers SET {field}={field}+? WHERE worker=?",
                           (n, worker))

    # ------------------------------------------------------------ 领取
    def claim(self, aids, worker):
        """批量领取。返回 {"mine":[...], "taken":[{aid,status,note,worker}...]}

        mine  = 归你处理, 去访问资料页
        taken = 别人已处理过(带结论) -> 直接跳过, 一个字节流量都不花
        """
        aids = [str(a) for a in aids if a]
        if not aids:
            return {"mine": [], "taken": []}
        now = time.time()
        mine, taken = [], []
        with self._lock:
            c = self._conn
            self._touch(worker)
            for aid in aids:
                row = c.execute(
                    "SELECT status,worker,note,lease_ts,tries FROM athletes "
                    "WHERE aid=?", (aid,)).fetchone()
                if row is None:
                    c.execute("""INSERT INTO athletes(aid,status,worker,ts,lease_ts)
                                 VALUES(?,?,?,?,?)""", (aid, "pending", worker, now, now))
                    mine.append(aid)
                    continue
                status, owner, note, lease = row[:4]
                _tries = int((row[4] if len(row) > 4 else 0) or 0)
                expired = (lease is not None) and (now - lease > self.lease_sec)
                # ★ 已经有成果的行直接算"别人做过": collect() 和 finish() 是
                #   两次独立请求, 中间崩溃/断网会留下"成果已入库但状态还是
                #   pending", 租约一到期就会被另一台机器重采一遍(白跑)。
                if status == "pending" and c.execute(
                        "SELECT 1 FROM collected WHERE aid=?", (aid,)).fetchone():
                    taken.append({"aid": aid, "status": "done",
                                  "note": "已有成果", "worker": owner})
                    continue
                if status == "error" and _tries >= MAX_TRIES:
                    # ★ 重试够多次了, 不再发出去 —— 否则永远失败的人会被
                    #   整队机器一轮一轮地重领。
                    taken.append({"aid": aid, "status": "error",
                                  "note": f"重试{_tries}次仍失败, 已放弃",
                                  "worker": owner})
                    continue
                if status == "error" or (status == "pending" and expired):
                    c.execute("""UPDATE athletes SET status='pending',worker=?,ts=?,
                                 lease_ts=?,tries=tries+1 WHERE aid=?""",
                              (worker, now, now, aid))
                    mine.append(aid)
                    continue
                taken.append({"aid": aid, "status": status,
                              "note": note or "", "worker": owner})
            c.execute("UPDATE workers SET claims=claims+? WHERE worker=?",
                      (len(mine), worker))
            c.commit()
        return {"mine": mine, "taken": taken}

    # ------------------------------------------------------------ 提交
    def finish(self, aid, worker, status, note="", name="", location="",
               dist_km=None, hub=""):
        """status: pass(合格已采) / reject(确定淘汰) / error(可重试)"""
        if status not in ("pass", "reject", "error"):
            raise ValueError("status 必须是 pass/reject/error")
        with self._lock:
            c = self._conn
            self._touch(worker)
            c.execute("""UPDATE athletes SET status=?, note=?, name=?, location=?,
                         dist_km=?, hub=?, ts=?, lease_ts=NULL WHERE aid=?""",
                      (status, note, name, location, dist_km, hub, time.time(), str(aid)))
            self._bump(worker, {"pass": "passed", "reject": "rejected",
                                "error": "errors"}[status])
            c.commit()
        return True

    # ------------------------------------------------------------ 预筛
    def known(self, aids):
        """批量查询已知状态(不含 pending)。用于开跑前一次性预筛, 省大量往返。"""
        aids = [str(a) for a in aids if a]
        out = {}
        if not aids:
            return out
        c = self._conn
        for i in range(0, len(aids), 400):        # 规避 SQLite 变量数上限
            chunk = aids[i:i + 400]
            q = ",".join("?" * len(chunk))
            for aid, status, note in c.execute(
                    f"SELECT aid,status,note FROM athletes WHERE aid IN ({q})", chunk):
                if status != "pending":
                    out[aid] = {"status": status, "note": note or ""}
        return out

    # ------------------------------------------------------------ 成果
    def collect(self, aid, url, worker, name="", location="", region="",
                segment="", age="", dist_km=None):
        """落一条成果。aid 主键 -> 重复提交自动忽略(幂等)"""
        with self._lock:
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO collected
                   (aid,url,name,location,region,segment,age,dist_km,worker,ts)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (str(aid), url, name, location, region, segment, age, dist_km,
                 worker, time.time()))
            self._conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------ 查询
    def stats(self):
        c = self._conn
        byst = dict(c.execute("SELECT status,COUNT(*) FROM athletes GROUP BY status"))
        total_col = c.execute("SELECT COUNT(*) FROM collected").fetchone()[0]
        byreg = dict(c.execute("""SELECT COALESCE(region,'?'),COUNT(*) FROM collected
                                  GROUP BY region ORDER BY COUNT(*) DESC LIMIT 30"""))
        wk = c.execute("""SELECT worker,claims,passed,rejected,errors,last_seen
                          FROM workers ORDER BY passed DESC""").fetchall()
        return {
            "athletes_by_status": byst,
            "collected_total": total_col,
            "collected_by_region": byreg,
            "workers": [{"worker": w, "claims": cl, "passed": p, "rejected": r,
                         "errors": e, "idle_sec": round(time.time() - (ls or 0))}
                        for w, cl, p, r, e, ls in wk],
        }

    def export_rows(self, limit=None):
        q = """SELECT aid,url,name,location,region,segment,age,dist_km,worker,ts
               FROM collected ORDER BY ts"""
        if limit:
            q += f" LIMIT {int(limit)}"
        return self._conn.execute(q).fetchall()

    def export_csv(self, out_path):
        import csv
        cols = ["aid", "url", "name", "location", "region", "segment", "age",
                "dist_km", "worker", "ts"]
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(self.export_rows())
        return out_path

    def backup(self, out_path=None):
        """一致性快照(可上传网盘归档)"""
        if out_path is None:
            root = Path(self.path)
            out_path = root.with_name(
                f"{root.stem}_snapshot_{time.strftime('%Y%m%d_%H%M%S')}.db")
        with self._lock:
            dst = sqlite3.connect(str(out_path))
            try:
                self._conn.backup(dst)
            finally:
                dst.close()
        return str(out_path)

    def reset_stale(self, worker=None, older_than=None):
        """把超时的 pending 打回可领取(批量版, 便于运维)"""
        # ★ older_than 由调用方随便传: 传 0.05 就能把别人【还在有效期内】的
        #   租约打回, 然后两边同时采同一个人。下限钳到 lease_sec。
        _ot = self.lease_sec if older_than is None else max(
            float(older_than), float(self.lease_sec))
        cut = time.time() - _ot
        with self._lock:
            q = "UPDATE athletes SET status='error', note='lease过期回收' WHERE status='pending' AND lease_ts < ?"
            args = [cut]
            if worker:
                q += " AND worker=?"
                args.append(worker)
            n = self._conn.execute(q, args).rowcount
            self._conn.commit()
        return n


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="strava_claim.db")
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--export", default="")
    a = ap.parse_args()
    st = ClaimStore(a.db)
    s = st.stats()
    print(f"库: {a.db}")
    print(f"athletes: {s['athletes_by_status']}")
    print(f"collected: {s['collected_total']}")
    for w in s["workers"]:
        print(f"  {w['worker']:<12} 领取{w['claims']:>6} 合格{w['passed']:>6} "
              f"淘汰{w['rejected']:>6} 错误{w['errors']:>5} 空闲{w['idle_sec']}s")
    if a.export:
        print("导出 ->", st.export_csv(a.export))
    if a.backup:
        print("快照 ->", st.backup())
