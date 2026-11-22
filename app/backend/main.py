"""FastAPI 入口：本地目录数据发现应用。

边界约定：
- 只允许操作 samples 目录下"准备好的"样例根目录（带标记文件），不扫描整台电脑。
- 前端构建产物（app/frontend/dist）若存在则由同一进程托管。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import samplegen
from .acceptor import accept_one
from .discovery import scan_root
from .store import Workspace

BASE_DIR = Path(__file__).resolve().parents[2]  # /workspace
DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"


class CreateRoot(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class MutateReq(BaseModel):
    duration: float = Field(default=10.0, gt=0, le=120)
    interval: float = Field(default=0.05, gt=0.005, le=5)


class AcceptReq(BaseModel):
    object_ids: list[str] = Field(min_length=1, max_length=500)


def create_app(ws: Workspace | None = None) -> FastAPI:
    if ws is None:
        ws = Workspace(
            os.environ.get("DISCOVERY_SAMPLES_DIR", BASE_DIR / "samples"),
            os.environ.get("DISCOVERY_ACCEPTED_DIR", BASE_DIR / "accepted"),
        )
    app = FastAPI(title="本地目录数据发现", version="0.1.0")
    app.state.ws = ws

    # ---- 根目录 --------------------------------------------------------
    @app.get("/api/roots")
    def list_roots() -> dict:
        return {"roots": ws.list_roots()}

    @app.post("/api/roots", status_code=201)
    def create_root(body: CreateRoot) -> dict:
        try:
            meta = ws.create_sample(body.name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"created": meta}

    def _require_root(name: str) -> Path:
        try:
            p = ws.root_path(name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not p.is_dir():
            raise HTTPException(404, f"根目录不存在：{name}")
        return p

    # ---- 扫描 ----------------------------------------------------------
    @app.post("/api/roots/{name}/scan")
    def scan(name: str) -> dict:
        root = _require_root(name)
        g = scan_root(root, root_name=name)
        return ws.set_graph(name, g)

    @app.get("/api/roots/{name}/graph")
    def graph(name: str) -> dict:
        _require_root(name)
        g = ws.get_graph(name)
        if g is None:
            raise HTTPException(409, "尚未扫描，请先 POST scan")
        return g

    # ---- 易变文件演示 ----------------------------------------------------
    @app.post("/api/roots/{name}/mutate", status_code=202)
    def mutate(name: str, body: MutateReq) -> dict:
        root = _require_root(name)
        old = ws.mutators.get(name)
        if old and old.running:
            old.finish(timeout=2)
        try:
            target = samplegen.find_mutate_target(root)
        except (OSError, ValueError, IndexError) as e:
            raise HTTPException(409, f"样例没有可替换的目标文件：{e}")
        m = samplegen.Mutator(target, interval=body.interval, duration=body.duration)
        m.start()
        ws.mutators[name] = m
        return {"mutating": str(target), "duration": body.duration,
                "interval": body.interval}

    # ---- 接收 ----------------------------------------------------------
    @app.post("/api/roots/{name}/accept")
    def accept(name: str, body: AcceptReq) -> dict:
        root = _require_root(name)
        g = ws.get_graph(name)
        if g is None:
            raise HTTPException(409, "尚未扫描，请先 POST scan")
        changes = ws.get_changes(name)
        dest = ws.accepted_dir / name
        results = []
        for oid in body.object_ids:
            obj = g["objects"].get(oid)
            if obj is None:
                results.append({"requested_id": oid, "status": "rejected",
                                "reason": "对象不在最近一次扫描结果中（请重新扫描）",
                                "events": [], "entry": None})
            else:
                results.append(accept_one(str(root.resolve()), obj, dest, changes))
            ws.record_accept_result(name, results[-1])
        n_ok = sum(1 for r in results if r["status"] == "accepted")
        return {"results": results, "accepted": n_ok,
                "rejected": len(results) - n_ok,
                "change_events_total": len(changes.events)}

    # ---- 变化队列 / 清单 -------------------------------------------------
    @app.get("/api/roots/{name}/changes")
    def list_changes(name: str) -> dict:
        _require_root(name)
        return {"changes": ws.get_changes(name).events}

    @app.delete("/api/roots/{name}/changes")
    def clear_changes(name: str) -> dict:
        _require_root(name)
        ws.get_changes(name).clear()
        return {"cleared": True}

    @app.get("/api/roots/{name}/collection")
    def collection(name: str) -> dict:
        _require_root(name)
        return ws.get_collection(name)

    @app.delete("/api/roots/{name}/collection")
    def clear_collection(name: str) -> dict:
        _require_root(name)
        with ws.lock:
            ws.collections.pop(name, None)
        return {"cleared": True}

    @app.get("/api/roots/{name}/manifest")
    def manifest(name: str) -> dict:
        _require_root(name)
        return ws.manifest(name)

    @app.get("/api/roots/{name}/manifest/download")
    def manifest_download(name: str) -> JSONResponse:
        _require_root(name)
        return JSONResponse(
            ws.manifest(name),
            headers={"Content-Disposition":
                     f'attachment; filename="manifest-{name}.json"'},
        )

    # ---- 前端静态资源（生产模式） ---------------------------------------
    if DIST_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(DIST_DIR), html=True), name="spa")

    return app


app = create_app()
