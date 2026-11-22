"""样例根目录生成器：制造硬链接、符号链接循环、断链、越界链接，
以及"读取过程中替换文件"的易变文件（mutator）。

只操作指定的样例目录，绝不触碰机器上的其它位置。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

MARKER = ".discovery-root.json"
MUTATE_MARKER = ".mutate-target"


def _w(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)


def _ln_hard(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    os.link(src, dst)


def _ln_sym(target: str, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    os.symlink(target, link)


def create_sample(root: str | Path, outside_dir: str | Path | None = None) -> dict:
    """在 root 处生成一套覆盖全部边界情形的样例树。返回摘要信息。"""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    outside = Path(outside_dir) if outside_dir else root.parent

    # 根目录之外的"秘密"文件：越界链接指向它，系统只应登记引用、绝不读取
    _w(outside / "outside_secret.txt", "TOP SECRET — 根目录之外，不应被读取\n")

    _w(root / "README.md",
       "# 发现样例\n\n包含：硬链接、符号链接循环、断链、越界链接、中文名、"
       "同名文件、仅大小写不同的文件、易变文件。\n")

    # 普通文件 + 中文名
    _w(root / "docs" / "报告.txt", "季度报告 v1\n")
    _w(root / "docs" / "notes.txt", "会议纪要：链接图演示。\n")
    _w(root / "docs" / "data.csv", "id,name\n1,甲\n2,乙\n")

    # 硬链接：同一内容对象，多条路径（跨目录、跨语言文件名）
    _ln_hard(root / "docs" / "data.csv", root / "backup" / "data-backup.csv")
    _w(root / "媒体" / "照片.jpg", b"\xff\xd8\xff\xe0FAKE-JPEG\x00\x01\x02")
    _ln_hard(root / "媒体" / "照片.jpg", root / "backup" / "照片备份.jpg")

    # 仅大小写不同的两个不同文件（身份不能靠规范化名字）
    _w(root / "Case" / "ReadMe.txt", "UPPER twin — 对象 A\n")
    _w(root / "Case" / "readme.txt", "lower twin — 对象 B\n")

    # 相同显示名、不同内容、不同目录
    _w(root / "a" / "config.json", '{"where": "a"}\n')
    _w(root / "b" / "config.json", '{"where": "b"}\n')

    # 符号链接：目录链接（目标在根内，目录会经由两条路径被发现）
    _ln_sym("../docs", root / "links" / "docs_link")
    # 符号链接链：chain1 → chain2 → 文件
    _ln_sym("chain2", root / "links" / "chain1")
    _ln_sym("../docs/notes.txt", root / "links" / "chain2")
    # 断链（根内但不存在）
    _ln_sym("../no/such/file.txt", root / "links" / "dangling")
    # 越界链接（相对 + 绝对）
    _ln_sym("../../outside_secret.txt", root / "links" / "escape")
    _ln_sym("/etc/hostname", root / "links" / "abs_etc")

    # 符号链接成环：p → q → p
    _ln_sym("q", root / "loop" / "p")
    _ln_sym("p", root / "loop" / "q")
    # 目录经由符号链接回到自身：遍历必须按真实对象身份终止
    _ln_sym(".", root / "loop" / "self")

    # 易变文件：mutator 会在读取期间反复替换它
    _w(root / "volatile" / "news.txt", "edition 0\n")
    _w(root / "volatile" / MUTATE_MARKER, "news.txt\n")

    meta = {
        "name": root.name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "generator": "samplegen",
        "description": "硬链接 / 循环 / 断链 / 越界 / 中文名 / 大小写孪生 / 易变文件",
    }
    _w(root / MARKER, json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def find_mutate_target(root: str | Path) -> Path:
    root = Path(root)
    marker = root / "volatile" / MUTATE_MARKER
    rel = marker.read_text(encoding="utf-8").strip().splitlines()[0]
    target = (root / "volatile" / rel).resolve()
    if os.path.commonpath((str(root.resolve()), str(target))) != str(root.resolve()):
        raise ValueError("mutate 目标越界，拒绝")
    return target


def mutate_loop(target: Path, stop: threading.Event, interval: float,
                editions_log: list[bytes] | None = None) -> int:
    """每 interval 秒用 临时文件+os.replace 原子替换 target（每次替换都是新 inode）。
    返回替换次数。editions_log 若给出，会记录每个写入版本的完整字节（供测试核对无拼接）。
    """
    i = 0
    tmp = target.with_name(target.name + ".mutating")
    while not stop.is_set():
        i += 1
        content = f"edition {i} @ {time.time_ns()}\n".encode()
        tmp.write_bytes(content)
        os.replace(tmp, target)
        if editions_log is not None:
            editions_log.append(content)
        stop.wait(interval)
    return i


class Mutator:
    """后台线程形式的文件替换器。"""

    def __init__(self, target: Path, interval: float = 0.05, duration: float = 10.0):
        self.target = target
        self.interval = interval
        self.duration = duration
        self.stop = threading.Event()
        self.thread: threading.Thread | None = None
        self.replacements = 0

    def start(self) -> None:
        def run() -> None:
            end = time.monotonic() + self.duration
            tmp = self.target.with_name(self.target.name + ".mutating")
            i = 0
            while not self.stop.is_set() and time.monotonic() < end:
                i += 1
                tmp.write_bytes(f"edition {i} @ {time.time_ns()}\n".encode())
                os.replace(tmp, self.target)
                self.stop.wait(self.interval)
            self.replacements = i
            self.stop.set()

        self.thread = threading.Thread(target=run, daemon=True,
                                       name=f"mutator-{self.target.name}")
        self.thread.start()

    def finish(self, timeout: float | None = None) -> int:
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=timeout)
        return self.replacements

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())
