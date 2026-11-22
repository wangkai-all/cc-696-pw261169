"""接收核对测试：身份/大小/内容一致性、变化队列、不拼接前后两份。"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import pytest

from app.backend import samplegen
from app.backend.acceptor import ChangeQueue, accept_one
from app.backend.discovery import scan_root


@pytest.fixture()
def env(tmp_path: Path):
    samples_dir = tmp_path / "samples"
    root = samples_dir / "demo"
    samplegen.create_sample(root, outside_dir=samples_dir)
    graph = scan_root(root, root_name="demo").to_dict()
    return {
        "root": root,
        "graph": graph,
        "dest": tmp_path / "accepted" / "demo",
        "changes": ChangeQueue(),
    }


def obj_by_path(graph: dict, rel: str) -> dict:
    for o in graph["objects"].values():
        if rel in o.get("paths", []):
            return o
    raise KeyError(rel)


def accept(env, rel: str):
    obj = obj_by_path(env["graph"], rel)
    return accept_one(str(env["root"].resolve()), obj, env["dest"], env["changes"])


def test_accept_stable_file_with_all_source_paths(env):
    r = accept(env, "docs/data.csv")
    assert r["status"] == "accepted"
    e = r["entry"]
    assert set(e["source_paths"]) == {"docs/data.csv", "backup/data-backup.csv"}
    data = (env["root"] / "docs" / "data.csv").read_bytes()
    assert e["sha256"] == hashlib.sha256(data).hexdigest()
    assert Path(e["stored_as"]).read_bytes() == data
    assert e["content_matches_scan"] is True


def test_accept_chinese_name(env):
    r = accept(env, "docs/报告.txt")
    assert r["status"] == "accepted"
    assert "报告.txt" in r["entry"]["stored_as"]


def test_reject_symlink_and_external(env):
    r = accept(env, "links/chain2")
    assert r["status"] == "rejected" and "符号链接" in r["reason"]
    # 越界引用对象本身不可接收
    g = env["graph"]
    ext = next(o for o in g["objects"].values() if o["kind"] == "external")
    r2 = accept_one(str(env["root"].resolve()), ext, env["dest"], env["changes"])
    assert r2["status"] == "rejected" and "根目录之外" in r2["reason"]


def test_replaced_since_scan_goes_to_change_queue(env):
    target = env["root"] / "docs" / "notes.txt"
    old_id = obj_by_path(env["graph"], "docs/notes.txt")["id"]
    tmp = target.with_suffix(".new")
    tmp.write_bytes(b"brand new notes\n")
    os.replace(tmp, target)  # 新 inode：扫描后被替换

    r = accept(env, "docs/notes.txt")
    kinds = [e["kind"] for e in env["changes"].events]
    assert "replaced_since_scan" in kinds
    assert r["status"] == "accepted"                      # 按新对象完整接收
    assert r["entry"]["object_id"] != old_id
    assert r["entry"]["identity_note"].startswith("扫描时为")
    assert Path(r["entry"]["stored_as"]).read_bytes() == b"brand new notes\n"


def test_modified_in_place_detected(env):
    target = env["root"] / "docs" / "报告.txt"
    with open(target, "r+b") as f:  # 同一 inode 改写
        f.write("季度报告 v2\n".encode())
    r = accept(env, "docs/报告.txt")
    assert r["status"] == "accepted"
    assert any(e["kind"] == "modified_since_scan" for e in env["changes"].events)
    assert r["entry"]["content_matches_scan"] is False


def test_vanished_file_rejected(env):
    os.unlink(env["root"] / "docs" / "报告.txt")
    r = accept(env, "docs/报告.txt")
    assert r["status"] == "rejected" and "消失" in r["reason"]
    assert any(e["kind"] == "vanished" for e in env["changes"].events)


def test_replaced_during_read_never_spliced(env):
    """读取期间被替换 → 变化队列；接收到的内容必须是某一个完整版本，不是拼接。"""
    target = env["root"] / "volatile" / "news.txt"
    editions: list[bytes] = []
    stop = threading.Event()

    def mutator():
        i = 0
        tmp = target.with_name("news.txt.mutating")
        while not stop.is_set():
            i += 1
            content = f"edition {i} @ {time.time_ns()}\n".encode()
            tmp.write_bytes(content)
            os.replace(tmp, target)
            editions.append(content)
            stop.wait(0.002)

    t = threading.Thread(target=mutator, daemon=True)
    t.start()
    try:
        accepted_entries = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            r = accept(env, "volatile/news.txt")
            if r["status"] == "accepted":
                accepted_entries.append(r["entry"])
            kinds = {e["kind"] for e in env["changes"].events}
            if "replaced_during_read" in kinds and accepted_entries:
                break
        assert "replaced_during_read" in {e["kind"] for e in env["changes"].events}, \
            "高速替换下应至少捕获一次读取期间替换"
        assert accepted_entries, "重试后应能接收到一个一致版本"
        edition_set = set(editions)
        for e in accepted_entries:
            stored = Path(e["stored_as"]).read_bytes()
            assert stored in edition_set, "接收到的内容必须是某一个完整版本（无拼接）"
            assert e["sha256"] == hashlib.sha256(stored).hexdigest()
    finally:
        stop.set()
        t.join(timeout=2)
