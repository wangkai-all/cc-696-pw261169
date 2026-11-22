"""API 端到端测试：准备根目录 → 扫描 → 接收 → 变化队列 → 清单。"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.backend.main import create_app
from app.backend.store import Workspace


@pytest.fixture()
def client(tmp_path: Path):
    ws = Workspace(tmp_path / "samples", tmp_path / "accepted")
    app = create_app(ws)
    with TestClient(app) as c:
        c.ws = ws  # type: ignore[attr-defined]
        yield c


def test_full_flow(client: TestClient):
    # 非法名字被拒绝（不扫描任意路径）
    assert client.post("/api/roots", json={"name": "../etc"}).status_code == 400
    assert client.post("/api/roots", json={"name": "a b"}).status_code == 400

    r = client.post("/api/roots", json={"name": "demo"})
    assert r.status_code == 201

    roots = client.get("/api/roots").json()["roots"]
    assert any(x["name"] == "demo" and x["prepared"] for x in roots)

    g = client.post("/api/roots/demo/scan").json()
    assert g["stats"]["objects_by_kind"]["file"] >= 6
    assert any(o["kind"] == "external" for o in g["objects"].values())
    assert any(o.get("link_status") == "cycle" for o in g["objects"].values())

    # 重复 GET 同一份扫描结果
    assert client.get("/api/roots/demo/graph").json()["root_name"] == "demo"

    def find(rel):
        return next(o for o in g["objects"].values() if rel in o.get("paths", []))

    broken = next(o for o in g["objects"].values()
                  if o.get("link_status") == "broken")
    ids = [find("docs/data.csv")["id"], find("docs/报告.txt")["id"],
           find("Case/ReadMe.txt")["id"], broken["id"], "fdead-beef"]

    r = client.post("/api/roots/demo/accept", json={"object_ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 3
    assert body["rejected"] == 2  # 断链符号链接 + 不存在的对象
    reasons = [x["reason"] for x in body["results"] if x["status"] == "rejected"]
    assert any("符号链接" in x for x in reasons)
    assert any("重新扫描" in x for x in reasons)

    # 清单包含源路径关系
    m = client.get("/api/roots/demo/manifest").json()
    assert len(m["accepted"]) == 3
    hard = next(e for e in m["accepted"] if "docs/data.csv" in e["source_paths"])
    assert set(hard["source_paths"]) == {"docs/data.csv", "backup/data-backup.csv"}

    d = client.get("/api/roots/demo/manifest/download")
    assert d.status_code == 200
    assert "attachment" in d.headers["content-disposition"]

    # 变化队列端点
    assert client.get("/api/roots/demo/changes").json()["changes"] == []
    assert client.delete("/api/roots/demo/changes").json()["cleared"] is True


def test_mutate_endpoint_and_change_queue(client: TestClient):
    client.post("/api/roots", json={"name": "demo"})
    g = client.post("/api/roots/demo/scan").json()
    volatile = next(o for o in g["objects"].values()
                    if "volatile/news.txt" in o.get("paths", []))

    r = client.post("/api/roots/demo/mutate", json={"duration": 3, "interval": 0.01})
    assert r.status_code == 202
    try:
        deadline = time.monotonic() + 4
        seen = set()
        while time.monotonic() < deadline:
            client.post("/api/roots/demo/accept", json={"object_ids": [volatile["id"]]})
            changes = client.get("/api/roots/demo/changes").json()["changes"]
            seen = {c["kind"] for c in changes}
            if seen & {"replaced_during_read", "replaced_since_scan", "modified_since_scan"}:
                break
            time.sleep(0.01)
        assert seen & {"replaced_during_read", "replaced_since_scan", "modified_since_scan"}
    finally:
        client.post("/api/roots/demo/mutate", json={"duration": 0.01, "interval": 0.01})

    # 清单里带变化记录
    m = client.get("/api/roots/demo/manifest").json()
    assert len(m["changes"]) >= 1


def test_scan_unknown_root_404(client: TestClient):
    assert client.post("/api/roots/nope/scan").status_code == 404
    assert client.get("/api/roots/nope/manifest").status_code == 404
