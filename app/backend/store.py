"""会话内状态：已准备的根目录、扫描结果、接收清单、变化队列、mutator。"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from . import samplegen
from .acceptor import ChangeQueue
from .discovery import Graph

_NAME_RE = re.compile(r"^[\w\-]{1,64}$", re.UNICODE)


class Workspace:
    def __init__(self, samples_dir: str | Path, accepted_dir: str | Path):
        self.samples_dir = Path(samples_dir)
        self.accepted_dir = Path(accepted_dir)
        self.samples_dir.mkdir(parents=True, exist_ok=True)
        self.accepted_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.graphs: dict[str, dict] = {}       # name -> graph dict
        self.collections: dict[str, dict] = {}  # name -> {accepted, rejected}
        self.changes: dict[str, ChangeQueue] = {}
        self.mutators: dict[str, samplegen.Mutator] = {}

    # ---- 根目录 --------------------------------------------------------
    def root_path(self, name: str) -> Path:
        """只接受准备好的样例根目录名；拒绝任意路径，绝不扫描整台电脑。"""
        if not _NAME_RE.match(name) or name in (".", ".."):
            raise ValueError(f"非法根目录名：{name!r}")
        p = (self.samples_dir / name).resolve()
        if os.path.commonpath((str(self.samples_dir.resolve()), str(p))) \
                != str(self.samples_dir.resolve()):
            raise ValueError("根目录越界")
        return p

    def list_roots(self) -> list[dict]:
        out = []
        for p in sorted(self.samples_dir.iterdir()):
            if not p.is_dir():
                continue
            marker = p / samplegen.MARKER
            meta = {}
            if marker.exists():
                try:
                    meta = json.loads(marker.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    meta = {}
            out.append({
                "name": p.name,
                "prepared": marker.exists(),
                "meta": meta,
                "scanned": p.name in self.graphs,
            })
        return out

    def create_sample(self, name: str) -> dict:
        root = self.root_path(name)  # 校验名字合法
        meta = samplegen.create_sample(root, outside_dir=self.samples_dir)
        with self.lock:
            self.graphs.pop(name, None)  # 旧扫描结果失效
        return meta

    # ---- 扫描 / 接收状态 ------------------------------------------------
    def set_graph(self, name: str, g: Graph) -> dict:
        d = g.to_dict()
        with self.lock:
            self.graphs[name] = d
        return d

    def get_graph(self, name: str) -> dict | None:
        with self.lock:
            return self.graphs.get(name)

    def get_collection(self, name: str) -> dict:
        with self.lock:
            return self.collections.setdefault(
                name, {"accepted": {}, "rejected": {}, "updated_at": None})

    def get_changes(self, name: str) -> ChangeQueue:
        with self.lock:
            return self.changes.setdefault(name, ChangeQueue())

    def record_accept_result(self, name: str, result: dict) -> None:
        col = self.get_collection(name)
        key = result["requested_id"]
        with self.lock:
            if result["status"] == "accepted":
                col["accepted"][key] = result["entry"]
                col["rejected"].pop(key, None)
            else:
                col["rejected"][key] = {
                    "reason": result["reason"],
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                }
            col["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    def manifest(self, name: str) -> dict:
        graph = self.get_graph(name)
        col = self.get_collection(name)
        changes = self.get_changes(name)
        return {
            "root": name,
            "root_real": graph["root_real"] if graph else None,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "accepted": list(col["accepted"].values()),
            "rejected": [{"object_id": k, **v} for k, v in col["rejected"].items()],
            "changes": list(changes.events),
        }
