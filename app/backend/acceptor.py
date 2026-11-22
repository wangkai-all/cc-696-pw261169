"""接收（采集）与一致性核对。

规则：
- 接收前、读取后各取一次 lstat 快照（dev/ino/size/mtime_ns/ctime_ns 全比对）。
- 读取期间被替换 → 记入变化队列，丢弃已读部分，重新完整读取；绝不把前后两份拼起来。
- 扫描后被替换 / 内容被改写 → 同样记入变化队列，再按当前对象完整接收。
- 越界路径（接收前被换成指向根外的链接）直接拒绝。
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path

from .discovery import disp, is_within, object_id

MAX_ATTEMPTS = 3
# 小于该尺寸的文件接收时做"二次读取"校验：有的文件系统时间戳粒度很粗，
# 写入后 mtime/ctime 可能纹丝不动，单靠 stat 快照无法发现读取期间的替换。
VERIFY_REREAD_LIMIT = 64 * 1024 * 1024


def stat_snapshot(st: os.stat_result) -> dict:
    return {
        "dev": st.st_dev,
        "ino": st.st_ino,
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
    }


class ChangeQueue:
    """每个根目录一个变化队列。"""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self._seq = 0

    def add(self, kind: str, path: str, object_id_: str | None,
            before: dict | None, after: dict | None, note: str = "") -> dict:
        self._seq += 1
        ev = {
            "seq": self._seq,
            "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "kind": kind,
            "path": path,
            "object_id": object_id_,
            "before": before,
            "after": after,
            "note": note,
        }
        self.events.append(ev)
        return ev

    def clear(self) -> None:
        self.events.clear()


def _reject(obj: dict | None, reason: str, events: list[dict]) -> dict:
    return {
        "requested_id": obj.get("id") if obj else None,
        "status": "rejected",
        "reason": reason,
        "events": events,
        "entry": None,
    }


def accept_one(root_real: str, obj: dict, dest_dir: Path,
               changes: ChangeQueue) -> dict:
    """接收单个内容对象。返回 {status, reason, entry, events}。"""
    events: list[dict] = []

    if obj.get("reference_only"):
        return _reject(obj, "根目录之外的引用只登记、不接收", events)
    kind = obj.get("kind")
    if kind == "symlink":
        return _reject(obj, f"符号链接本身不接收（链接状态：{obj.get('link_status')}），请选择其目标文件", events)
    if kind == "dir":
        return _reject(obj, "目录不直接接收，请选择其中的文件", events)
    if kind != "file":
        return _reject(obj, f"类型 {kind} 不可接收", events)
    if not obj.get("paths"):
        return _reject(obj, "对象没有可用的真实路径", events)

    rel = obj["paths"][0]
    abs_path = os.path.join(root_real, rel)
    scan_snap = {"dev": obj["dev"], "ino": obj["ino"], "size": obj["size"],
                 "mtime_ns": obj["mtime_ns"]}
    scan_id = obj["id"]

    dest_dir.mkdir(parents=True, exist_ok=True)
    last_reason = "接收失败"

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # ---- 接收前快照 ------------------------------------------------
        try:
            pre = os.lstat(abs_path)
        except FileNotFoundError:
            ev = changes.add("vanished", rel, scan_id, scan_snap, None,
                             "接收时文件已消失")
            events.append(ev)
            return _reject(obj, "接收时文件已消失", events)
        except OSError as e:
            return _reject(obj, f"接收前 stat 失败：{e.strerror or e}", events)

        pre_snap = stat_snapshot(pre)
        current_id = object_id("file", pre.st_dev, pre.st_ino)

        if (pre.st_dev, pre.st_ino) != (obj["dev"], obj["ino"]):
            ev = changes.add("replaced_since_scan", rel, scan_id, scan_snap,
                             pre_snap, "扫描后被替换，按新对象重新核对")
            events.append(ev)
        elif (pre_snap["size"], pre_snap["mtime_ns"]) != (scan_snap["size"], scan_snap["mtime_ns"]):
            ev = changes.add("modified_since_scan", rel, scan_id, scan_snap,
                             pre_snap, "同一对象在扫描后被改写")
            events.append(ev)

        # ---- 越界防护：路径若在接收前被换成链接，真实目标必须仍在根内 ----
        resolved = os.path.realpath(abs_path)
        if not is_within(root_real, resolved):
            ev = changes.add("escaped", rel, scan_id, pre_snap, None,
                             f"接收前路径变为越界链接 → {resolved}")
            events.append(ev)
            return _reject(obj, "接收前路径变为指向根目录之外的链接，已拒绝", events)
        try:
            rst = os.stat(resolved)
        except OSError as e:
            ev = changes.add("vanished", rel, scan_id, pre_snap, None,
                             f"解析后目标不可读：{e.strerror or e}")
            events.append(ev)
            return _reject(obj, "接收前目标不可读", events)
        if (rst.st_dev, rst.st_ino) != (pre.st_dev, pre.st_ino):
            # 路径被换成了指向其它对象的链接：按替换处理，下一轮重新核对
            ev = changes.add("replaced_since_scan", rel, scan_id, pre_snap,
                             stat_snapshot(rst), "路径在接收前被换成指向其它对象的链接")
            events.append(ev)
            continue

        # ---- 完整读取 + 哈希 + 落盘（先写临时文件） ----------------------
        tmp_dest = dest_dir / f".tmp-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        h = hashlib.sha256()
        total = 0
        try:
            with open(abs_path, "rb") as src, open(tmp_dest, "wb") as out:
                for chunk in iter(lambda: src.read(1024 * 1024), b""):
                    h.update(chunk)
                    out.write(chunk)
                    total += len(chunk)
        except OSError as e:
            try:
                tmp_dest.unlink(missing_ok=True)
            except OSError:
                pass
            last_reason = f"读取失败：{e.strerror or e}"
            ev = changes.add("read_error", rel, scan_id, pre_snap, None, last_reason)
            events.append(ev)
            continue

        # ---- 读取后快照：任何字段变化都视为"采集期间被替换" --------------
        try:
            post = os.lstat(abs_path)
        except FileNotFoundError:
            post = None
        post_snap = stat_snapshot(post) if post else None
        if post_snap != pre_snap:
            tmp_dest.unlink(missing_ok=True)
            ev = changes.add("replaced_during_read", rel, scan_id, pre_snap,
                             post_snap,
                             f"第 {attempt} 次读取期间被替换，已丢弃该次读取")
            events.append(ev)
            last_reason = "采集期间文件被替换"
            continue  # 重新完整读取，绝不拼接

        # ---- 二次读取校验：时间戳粒度粗的文件系统上，stat 可能察觉不到 ----
        verify = "stat"
        if total <= VERIFY_REREAD_LIMIT:
            h2 = hashlib.sha256()
            try:
                with open(abs_path, "rb") as src2:
                    for chunk in iter(lambda: src2.read(1024 * 1024), b""):
                        h2.update(chunk)
            except OSError as e:
                tmp_dest.unlink(missing_ok=True)
                ev = changes.add("read_error", rel, scan_id, pre_snap, None,
                                 f"校验读取失败：{e.strerror or e}")
                events.append(ev)
                last_reason = "校验读取失败"
                continue
            try:
                post2 = os.lstat(abs_path)
                post2_snap = stat_snapshot(post2)
            except OSError:
                post2_snap = None
            if h2.digest() != h.digest() or post2_snap != pre_snap:
                tmp_dest.unlink(missing_ok=True)
                ev = changes.add("replaced_during_read", rel, scan_id, pre_snap,
                                 post2_snap,
                                 f"第 {attempt} 次读取的两次校验不一致（内容在读取期间变化），已丢弃")
                events.append(ev)
                last_reason = "采集期间文件内容变化"
                continue
            verify = "reread"

        # ---- 一致：落定为正式副本 ---------------------------------------
        # 名字带随机后缀：inode 号可能被复用，绝不让新副本覆盖旧副本
        digest = h.hexdigest()
        final_name = (f"{current_id}__{disp(os.path.basename(rel))}"
                      f"__{uuid.uuid4().hex[:8]}")
        final_path = dest_dir / final_name
        os.replace(tmp_dest, final_path)

        # 内容级核对：扫描期摘要与接收摘要不一致 → 内容在扫描后被改写
        if obj.get("sha256") and obj["sha256"] != digest and not any(
                e["kind"] == "modified_since_scan" for e in events):
            ev = changes.add("modified_since_scan", rel, scan_id, scan_snap,
                             pre_snap, "内容摘要在扫描后发生变化（时间戳可能未变）")
            events.append(ev)

        entry = {
            "requested_id": scan_id,
            "object_id": current_id,
            "identity_note": ("与扫描时相同" if current_id == scan_id
                              else f"扫描时为 {scan_id}，接收时为 {current_id}（被替换）"),
            "source_paths": list(obj["paths"]),
            "via_symlinks": list(obj.get("via_symlinks", [])),
            "size": total,
            "sha256": digest,
            "scan_sha256": obj.get("sha256"),
            "content_matches_scan": (obj.get("sha256") in (None, digest)),
            "verify": verify,
            "stored_as": str(final_path),
            "accepted_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "attempts": attempt,
        }
        return {"requested_id": scan_id, "status": "accepted",
                "reason": None, "events": events, "entry": entry}

    return _reject(obj, f"{last_reason}（{MAX_ATTEMPTS} 次尝试均未得到一致版本，未拼接前后内容）", events)
