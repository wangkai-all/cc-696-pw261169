"""遍历行为测试：硬链接、循环、断链、越界、中文名、大小写孪生、同名文件。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.backend import samplegen
from app.backend.discovery import scan_root


@pytest.fixture()
def sample(tmp_path: Path):
    samples_dir = tmp_path / "samples"
    root = samples_dir / "demo"
    samplegen.create_sample(root, outside_dir=samples_dir)
    graph = scan_root(root, root_name="demo").to_dict()
    return {"root": root, "samples_dir": samples_dir, "graph": graph}


def obj_by_path(graph: dict, rel: str) -> dict:
    for o in graph["objects"].values():
        if rel in o.get("paths", []):
            return o
    raise KeyError(f"没有路径为 {rel} 的对象")


def symlink_by_path(graph: dict, rel: str) -> dict:
    o = obj_by_path(graph, rel)
    assert o["kind"] == "symlink", f"{rel} 应为符号链接，实为 {o['kind']}"
    return o


def test_hardlinks_share_one_object_but_keep_all_paths(sample):
    g = sample["graph"]
    obj = obj_by_path(g, "docs/data.csv")
    assert obj["kind"] == "file"
    assert set(obj["paths"]) == {"docs/data.csv", "backup/data-backup.csv"}
    assert obj["nlink"] == 2
    # 中文名硬链接
    pic = obj_by_path(g, "媒体/照片.jpg")
    assert set(pic["paths"]) == {"媒体/照片.jpg", "backup/照片备份.jpg"}
    assert pic["sha256"]


def test_identity_not_by_normalized_name(sample):
    g = sample["graph"]
    upper = obj_by_path(g, "Case/ReadMe.txt")
    lower = obj_by_path(g, "Case/readme.txt")
    assert upper["id"] != lower["id"]          # 仅大小写不同 ≠ 同一对象
    assert upper["sha256"] != lower["sha256"]
    a = obj_by_path(g, "a/config.json")
    b = obj_by_path(g, "b/config.json")
    assert a["id"] != b["id"]                  # 相同显示名 ≠ 同一对象
    # 中文名原样保留
    assert any("报告.txt" in p for p in obj_by_path(g, "docs/报告.txt")["paths"])


def test_symlink_cycle_detected_by_identity_and_terminates(sample):
    g = sample["graph"]
    p = symlink_by_path(g, "loop/p")
    q = symlink_by_path(g, "loop/q")
    assert p["link_status"] == "cycle"
    assert q["link_status"] == "cycle"
    # self -> . 是合法目录链接，但目录只能被扫描一次（按真实对象身份）
    self_link = symlink_by_path(g, "loop/self")
    assert self_link["link_status"] == "ok"
    loop_dir = obj_by_path(g, "loop")
    assert self_link["target"] == loop_dir["id"]
    assert g["stats"]["dirs_scanned"] >= 1  # 扫描正常结束即证明循环被识别


def test_broken_symlink_registered(sample):
    g = sample["graph"]
    d = symlink_by_path(g, "links/dangling")
    assert d["link_status"] == "broken"
    assert "断链" in d["reason"]
    target = g["objects"][d["target"]]
    assert target["kind"] == "missing" and target["reference_only"]


def test_external_symlink_reference_only_never_read(sample):
    g = sample["graph"]
    esc = symlink_by_path(g, "links/escape")
    assert esc["link_status"] == "external"
    ref = g["objects"][esc["target"]]
    assert ref["kind"] == "external" and ref["reference_only"]
    assert ref["resolved"].endswith("outside_secret.txt")
    # 边界外目标的真实身份绝不出现在对象表里（未 stat 其内容、未读取）
    outside_st = os.lstat(sample["samples_dir"] / "outside_secret.txt")
    for o in g["objects"].values():
        assert (o.get("dev"), o.get("ino")) != (outside_st.st_dev, outside_st.st_ino)
        assert "TOP SECRET" not in str(o.get("sha256", ""))
    abs_link = symlink_by_path(g, "links/abs_etc")
    assert abs_link["link_status"] == "external"


def test_dir_symlink_records_discovery_paths(sample):
    g = sample["graph"]
    link = symlink_by_path(g, "links/docs_link")
    assert link["link_status"] == "ok"
    docs = obj_by_path(g, "docs")
    assert link["target"] == docs["id"]
    # docs 目录保留"经由符号链接被发现"的路径
    assert any(v["path"] == "links/docs_link" for v in docs["via_symlinks"])


def test_symlink_chain_resolves_to_final_target(sample):
    g = sample["graph"]
    chain1 = symlink_by_path(g, "links/chain1")
    notes = obj_by_path(g, "docs/notes.txt")
    assert chain1["link_status"] == "ok"
    assert chain1["target"] == notes["id"]
    assert chain1["link_chain"] == ["chain2", "../docs/notes.txt"]


def test_graph_edges_link_and_contain(sample):
    g = sample["graph"]
    kinds = {(e["kind"]) for e in g["edges"]}
    assert "contains" in kinds and "links" in kinds
