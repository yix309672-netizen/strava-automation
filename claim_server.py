#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""领取服务端 (部署在 VPS) —— 20 台机器共享的唯一真源

存储与去重逻辑全在 claim_store.py (纯标准库)。这里只是 HTTP 外壳。

VPS 上安装:
    pip install fastapi uvicorn
启动:
    export CLAIM_KEY='你的随机密钥'
    python claim_server.py --port 8000

接口(全部需要请求头 X-API-Key):
    GET  /health                        健康检查
    POST /claim        {aids,worker}    批量领取
    POST /finish       {aid,worker,status,note,...}
    POST /known        {aids}           批量查已知状态(预筛)
    POST /collected    {aid,url,...}    落一条成果(幂等)
    GET  /stats                         看板
    GET  /export?fmt=csv|json           导出成果
    POST /backup                        生成快照(可上传网盘归档)
    POST /reset_stale                   回收超时未提交的领取
    GET  /pkg/manifest                  客户端自动更新: 版本 + 每个文件的哈希
    GET  /pkg/latest.zip                客户端自动更新: 整包下载
    POST /pkg/upload                    管理员发版: 上传新包(zip 原样 body)
"""
import argparse
import hashlib
import io
import os
import shutil
import zipfile
from pathlib import Path

try:
    from fastapi import FastAPI, Header, HTTPException, Query, Request
    from fastapi.responses import FileResponse, PlainTextResponse
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("缺依赖, VPS 上先执行:  pip install fastapi uvicorn")
    raise

from claim_store import ClaimStore

API_KEY = os.environ.get("CLAIM_KEY", "")
DEFAULT_DB = str(Path(__file__).resolve().parent / "strava_claim.db")
store: ClaimStore | None = None

# ------------------------------------------------------------ 脚本分发
# 同事那边的 update.py 来这里比对版本并拉新脚本。
# ★ 这里只放脚本和说明: 账号文件、采集数据、_python 都不进这个包。
PKG_DIR = Path(__file__).resolve().parent / "pkg"
PKG_ZIP = PKG_DIR / "latest.zip"
PKG_PREV = PKG_DIR / "latest.zip.prev"      # 上一版, 出事能回滚

# ★ 上传保护: 不限制体积 + 不校验内容的话,
#   (1) 一个 zip 炸弹就能把 /pkg/manifest 打到内存耗尽 -> 20 台全部停采;
#   (2) 传一个无关的 zip 会"发布成功"而 files 为空 ->
#       所有客户端判定"服务器还没发布过版本" -> 全体静默停止更新。
MAX_PKG_BYTES = 25 * 1024 * 1024            # 整包上限 25 MB
MAX_ENTRY_BYTES = 8 * 1024 * 1024           # 单个文件上限 8 MB
PKG_REQUIRED = ("update.py", "claim_client.py", "strava_ads.py", "strava_bit.py")
_PKG_CACHE = {"mtime": 0.0, "manifest": None}


def _load_pkg_manifest():
    """读 latest.zip 算出清单(带 mtime 缓存, 不会每次重算)"""
    if not PKG_ZIP.is_file():
        return {"version": "", "count": 0, "files": {}, "ts": 0}
    mt = PKG_ZIP.stat().st_mtime
    if _PKG_CACHE["manifest"] and _PKG_CACHE["mtime"] == mt:
        return _PKG_CACHE["manifest"]
    files = {}
    with zipfile.ZipFile(PKG_ZIP) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # ★★ 2026-09-20 支持子目录(claude: 这行是【最关键的一处】) ★★
            #   原来用 Path(...).name 拍平, 于是清单里只有 "light.tcl",
            #   而 zip 里是 "sv_ttk/theme/light.tcl" —— 两者口径不一致:
            #   客户端按清单比对, 永远看不到子目录文件 -> 子目录建不起来,
            #   反而可能在根目录撒出 __init__.py。必须保留相对路径。
            nm = info.filename.replace("\\", "/")
            if not nm or nm.startswith("."):
                continue
            data = zf.read(info)
            files[nm] = {"sha256": hashlib.sha256(data).hexdigest(),
                         "size": len(data)}
    ver = hashlib.sha256(
        "".join(f"{k}:{v['sha256']}" for k, v in sorted(files.items()))
        .encode()).hexdigest()[:16]
    m = {"version": ver, "count": len(files), "files": files, "ts": mt}
    _PKG_CACHE.update(mtime=mt, manifest=m)
    return m


# ---------------------------------------------------------------- 请求模型
class ClaimReq(BaseModel):
    aids: list[str]
    worker: str


class FinishReq(BaseModel):
    aid: str
    worker: str
    status: str                  # pass / reject / error
    note: str = ""
    name: str = ""
    location: str = ""
    dist_km: float | None = None
    hub: str = ""


class KnownReq(BaseModel):
    aids: list[str]


class CollectedReq(BaseModel):
    aid: str
    url: str
    worker: str
    name: str = ""
    location: str = ""
    region: str = ""
    segment: str = ""
    age: str = ""
    dist_km: float | None = None


class ResetReq(BaseModel):
    worker: str = ""
    older_than: float | None = None


app = FastAPI(title="Strava Claim Server", version="2.0")


def auth(key):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="bad key")


# ---------------------------------------------------------------- 接口
@app.get("/health")
def health():
    st = store.stats()
    return {"ok": True, "athletes": sum(st["athletes_by_status"].values()),
            "collected": st["collected_total"], "ts": __import__("time").time()}


@app.post("/claim")
def claim(req: ClaimReq, x_api_key: str = Header(default="")):
    auth(x_api_key)
    r = store.claim(req.aids, req.worker)
    return {"mine": r["mine"], "taken": r["taken"],
            "mine_n": len(r["mine"]), "taken_n": len(r["taken"])}


@app.post("/finish")
def finish(req: FinishReq, x_api_key: str = Header(default="")):
    auth(x_api_key)
    if req.status not in ("pass", "reject", "error"):
        raise HTTPException(400, "status must be pass/reject/error")
    store.finish(req.aid, req.worker, req.status, note=req.note, name=req.name,
                 location=req.location, dist_km=req.dist_km, hub=req.hub)
    return {"ok": True}


@app.post("/known")
def known(req: KnownReq, x_api_key: str = Header(default="")):
    auth(x_api_key)
    out = store.known(req.aids)
    return {"known": out, "n": len(out)}


@app.post("/collected")
def add_collected(req: CollectedReq, x_api_key: str = Header(default="")):
    auth(x_api_key)
    ins = store.collect(req.aid, req.url, req.worker, name=req.name,
                        location=req.location, region=req.region,
                        segment=req.segment, age=req.age, dist_km=req.dist_km)
    return {"ok": True, "inserted": ins}


@app.get("/stats")
def stats(x_api_key: str = Header(default="")):
    # ★ 以前完全不需要 key: worker 名单、领取/合格/淘汰计数、成果区域分布
    #   全都对外可见。
    auth(x_api_key)
    return store.stats()


@app.get("/export")
def export(fmt: str = Query("csv"), x_api_key: str = Header(default="")):
    auth(x_api_key)
    rows = store.export_rows()
    cols = ["aid", "url", "name", "location", "region", "segment", "age",
            "dist_km", "worker", "ts"]
    if fmt == "json":
        return [dict(zip(cols, r)) for r in rows]
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerows(rows)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@app.post("/backup")
def backup(x_api_key: str = Header(default="")):
    auth(x_api_key)
    p = store.backup()
    return {"ok": True, "snapshot": p, "size": os.path.getsize(p)}


@app.post("/reset_stale")
def reset_stale(req: ResetReq, x_api_key: str = Header(default="")):
    """把超时未提交的领取打回, 便于崩溃后恢复(正常由租约自动处理)"""
    auth(x_api_key)
    return {"ok": True, "n": store.reset_stale(req.worker or None, req.older_than)}


# ---------------------------------------------------------------- 脚本分发
@app.get("/pkg/manifest")
def pkg_manifest(x_api_key: str = Header(default="")):
    """客户端启动时先问这个(很小), 版本一样就不下载"""
    auth(x_api_key)
    m = _load_pkg_manifest()
    return {"version": m["version"], "count": m["count"],
            "files": m["files"], "ts": m["ts"]}


@app.get("/pkg/latest.zip")
def pkg_latest(x_api_key: str = Header(default="")):
    auth(x_api_key)
    if not PKG_ZIP.is_file():
        raise HTTPException(404, "还没有发布过任何版本")
    return FileResponse(str(PKG_ZIP), media_type="application/zip",
                        filename="latest.zip")


@app.post("/pkg/upload")
async def pkg_upload(request: Request, x_api_key: str = Header(default="")):
    """管理员发版: 把 zip 原样 POST 上来。先写临时文件再原子替换,
    所以同事正在下载时也不会拿到半个包。"""
    auth(x_api_key)
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    if len(body) > MAX_PKG_BYTES:
        raise HTTPException(413, f"包太大: {len(body)} > {MAX_PKG_BYTES}")
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            names = [i.filename.replace("\\", "/") for i in infos]
            # 单文件体积(防 zip 炸弹; info.file_size 是解压后大小)
            big = [i.filename for i in infos if i.file_size > MAX_ENTRY_BYTES]
            if big:
                raise HTTPException(413, f"单个文件过大: {big[:3]}")
            total = sum(i.file_size for i in infos)
            if total > MAX_PKG_BYTES * 4:
                raise HTTPException(413, f"解压后过大: {total}")
            bad = zf.testzip()
            if bad:
                raise HTTPException(400, f"zip 损坏: {bad}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"不是合法的 zip: {e}")

    # ★ 必须包含核心文件, 否则客户端会把"发布成功但清单为空"当成
    #   "服务器还没发布过版本", 全体静默停止更新。
    missing = [n for n in PKG_REQUIRED if n not in names]
    if missing:
        raise HTTPException(400, f"包缺少必需文件: {missing}")

    PKG_DIR.mkdir(parents=True, exist_ok=True)
    # 保留上一版, 出事能回滚
    if PKG_ZIP.is_file():
        try:
            shutil.copy2(PKG_ZIP, PKG_PREV)
        except Exception:
            pass
    tmp = PKG_ZIP.with_suffix(".zip.tmp")
    tmp.write_bytes(body)
    os.replace(tmp, PKG_ZIP)
    _PKG_CACHE.update(mtime=0.0, manifest=None)      # 让下一次重算
    m = _load_pkg_manifest()
    return {"ok": True, "version": m["version"], "count": m["count"],
            "size": len(body), "files": sorted(names)}


@app.on_event("startup")
def _startup():
    print(f"[srv] 鉴权: {'开' if API_KEY else '关  <-- 强烈建议设置 CLAIM_KEY'}")
    print("[srv] /health /claim /finish /known /collected /stats /export /backup /reset_stale")
    print("[srv] /pkg/manifest /pkg/latest.zip /pkg/upload")
    m = _load_pkg_manifest()
    if m["version"]:
        print(f"[pkg] 已发布版本 {m['version']} ({m['count']} 个文件)")
    else:
        print(f"[pkg] 还没有发布过脚本包 (放一个 zip 到 {PKG_ZIP})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--key", default="")
    a = ap.parse_args()
    API_KEY = a.key or API_KEY
    store = ClaimStore(a.db)
    print(f"[db] {a.db}")
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
