"""文件发现遍历：把准备好的样例根目录走一遍，构建"真实内容对象 + 发现路径 + 链接关系"图。

身份规则（贯穿全模块）：
- 真实对象（文件 / 目录 / 符号链接本身）一律用 lstat/stat 的 (st_dev, st_ino) 做身份，
  绝不使用规范化后的名字 —— 中文名、仅大小写差异、同名文件都不会被混淆。
- 目录循环用同一身份（已扫描目录集合）识别，符号链接成环因此一定会终止。
- 根目录边界外的符号链接目标只登记引用：不打开、不读取、不哈希其内容。
- 硬链接共享同一个内容对象，但每条发现路径都保留在对象上。
"""
from __future__ import annotations

import errno
import hashlib
import os
import stat as statmod
import time
from pathlib import Path

# 扫描期哈希的大小上限（演示样例都很小，远高于即可）
HASH_SIZE_LIMIT = 256 * 1024 * 1024

_KIND_PREFIX = {"file": "f", "dir": "d", "symlink": "l", "special": "s"}


def disp(s: str) -> str:
    """把可能含 surrogateescape 的路径名转成可安全 JSON 序列化的显示串。

    只用于展示；对象身份从不经过这里。
    """
    return s.encode("utf-8", "replace").decode("utf-8")


def object_id(kind: str, dev: int, ino: int) -> str:
    return f"{_KIND_PREFIX.get(kind, 'x')}{dev:x}-{ino:x}"


def is_within(root: str, path: str) -> bool:
    """path（绝对路径）是否位于 root 之内。纯路径判断，不做任何名字规范化比较之外的读取。"""
    try:
        return os.path.commonpath((root, path)) == root
    except ValueError:
        return False


def link_chain(link_abs: str, max_hops: int = 32) -> list[str]:
    """沿最后一级符号链接逐跳读取 link 文本，用于展示链条；有跳数上限，成环也能停。"""
    chain: list[str] = []
    current = link_abs
    for _ in range(max_hops):
        try:
            st = os.lstat(current)
        except OSError:
            break
        if not statmod.S_ISLNK(st.st_mode):
            break
        try:
            target = os.readlink(current)
        except OSError:
            break
        chain.append(disp(target))
        current = os.path.normpath(os.path.join(os.path.dirname(current), target))
    return chain


class Graph:
    """一次扫描的产物：对象表 + 边表 + 扫描期异常。"""

    def __init__(self, root_real: str, root_name: str):
        self.root_real = root_real
        self.root_name = root_name
        self.objects: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.errors: list[dict] = []
        self._scanned_dirs: set[tuple[int, int]] = set()
        self.stats = {"files_hashed": 0, "files_hash_skipped": 0}

    # ---- 对象 ----------------------------------------------------------
    def ensure_object(self, kind: str, st: os.stat_result) -> dict:
        oid = object_id(kind, st.st_dev, st.st_ino)
        obj = self.objects.get(oid)
        if obj is None:
            obj = {
                "id": oid,
                "kind": kind,
                "dev": st.st_dev,
                "ino": st.st_ino,
                "name": "",
                "paths": [],
                "via_symlinks": [],
                "size": st.st_size if kind == "file" else None,
                "mtime_ns": st.st_mtime_ns,
                "nlink": st.st_nlink,
                "sha256": None,
                "error": None,
            }
            if kind == "symlink":
                obj.update({
                    "link_text": None,
                    "link_chain": [],
                    "link_status": "unresolved",
                    "resolved": None,
                    "target": None,
                    "reason": None,
                })
            self.objects[oid] = obj
        return obj

    def ensure_ref(self, kind: str, resolved: str, reason: str) -> dict:
        """外部 / 失效目标的引用节点：只登记，不读取。"""
        rid = f"{kind}:{hashlib.sha1(resolved.encode('utf-8', 'replace')).hexdigest()[:12]}"
        obj = self.objects.get(rid)
        if obj is None:
            obj = {
                "id": rid,
                "kind": kind,  # external | missing
                "name": os.path.basename(resolved) or resolved,
                "paths": [],
                "via_symlinks": [],
                "resolved": resolved,
                "reference_only": True,
                "reason": reason,
            }
            self.objects[rid] = obj
        return obj

    @staticmethod
    def add_path(obj: dict, rel: str, name: str) -> None:
        if rel not in obj["paths"]:
            obj["paths"].append(rel)
        if not obj["name"]:
            obj["name"] = name

    def add_edge(self, frm: str, to: str, kind: str, name: str = "") -> None:
        self.edges.append({"from": frm, "to": to, "kind": kind, "name": name})

    def add_error(self, path: str, reason: str) -> None:
        self.errors.append({"path": path, "reason": reason})

    # ---- 符号链接 ------------------------------------------------------
    def handle_symlink(self, link_abs: str, link_rel: str, st: os.stat_result,
                       parent: dict) -> dict:
        obj = self.ensure_object("symlink", st)
        self.add_path(obj, link_rel, os.path.basename(link_rel))
        self.add_edge(parent["id"], obj["id"], "contains", os.path.basename(link_rel))
        if obj["link_status"] != "unresolved":
            return obj  # 同一链接对象已被解析过（多条路径到达）

        try:
            link_text = os.readlink(link_abs)
        except OSError as e:
            obj["link_status"] = "unreadable"
            obj["reason"] = f"无法读取链接：{e.strerror or e}"
            return obj
        obj["link_text"] = disp(link_text)
        obj["link_chain"] = link_chain(link_abs)

        # realpath 只做路径解析（最多 lstat 中间组件），绝不打开目标内容。
        resolved = os.path.realpath(link_abs)
        obj["resolved"] = resolved

        if not is_within(self.root_real, resolved):
            obj["link_status"] = "external"
            obj["reason"] = "目标在根目录之外，仅登记引用，不读取内容"
            ref = self.ensure_ref("external", resolved, "根目录之外的目标（未读取）")
            obj["target"] = ref["id"]
            self.add_edge(obj["id"], ref["id"], "links")
            return obj

        # 目标在边界内：用 stat 取得真实身份。ELOOP → 成环；ENOENT → 断链。
        try:
            tst = os.stat(link_abs)
        except OSError as e:
            if e.errno == errno.ELOOP:
                obj["link_status"] = "cycle"
                obj["reason"] = "符号链接成环，无法解析"
            elif e.errno in (errno.ENOENT, errno.ENOTDIR):
                obj["link_status"] = "broken"
                obj["reason"] = "目标不存在（断链）"
                ref = self.ensure_ref("missing", resolved, "链接目标不存在")
                obj["target"] = ref["id"]
                self.add_edge(obj["id"], ref["id"], "links")
            else:
                obj["link_status"] = "error"
                obj["reason"] = f"解析失败：{e.strerror or e}"
            return obj

        if statmod.S_ISDIR(tst.st_mode):
            tkind = "dir"
        elif statmod.S_ISREG(tst.st_mode):
            tkind = "file"
        elif statmod.S_ISLNK(tst.st_mode):
            tkind = "symlink"  # 理论上 stat 已跟随到底，防御性保留
        else:
            tkind = "special"
        target = self.ensure_object(tkind, tst)
        target["via_symlinks"].append({
            "symlink": obj["id"], "path": link_rel, "link_text": obj["link_text"],
        })
        obj["link_status"] = "ok"
        obj["target"] = target["id"]
        self.add_edge(obj["id"], target["id"], "links")
        return obj

    # ---- 主遍历 --------------------------------------------------------
    def scan(self, hash_limit: int = HASH_SIZE_LIMIT) -> None:
        stack: list[tuple[str, str]] = [(self.root_real, "")]
        while stack:
            dir_abs, rel = stack.pop()
            try:
                lst = os.lstat(dir_abs)
            except OSError as e:
                self.add_error(rel or ".", f"目录不可读：{e.strerror or e}")
                continue
            dkey = (lst.st_dev, lst.st_ino)
            if dkey in self._scanned_dirs:
                continue  # 真实对象身份识别循环：同一目录只扫一次
            self._scanned_dirs.add(dkey)
            dir_obj = self.ensure_object("dir", lst)
            self.add_path(dir_obj, rel or ".", os.path.basename(rel) if rel else self.root_name)

            try:
                entries = list(os.scandir(dir_abs))
            except OSError as e:
                dir_obj["error"] = f"目录不可读：{e.strerror or e}"
                continue

            for entry in entries:
                name = disp(entry.name)
                child_abs = os.path.join(dir_abs, entry.name)
                child_rel = f"{rel}/{name}" if rel else name
                try:
                    st = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    self.add_error(child_rel, "扫描期间消失")
                    continue
                except OSError as e:
                    self.add_error(child_rel, f"stat 失败：{e.strerror or e}")
                    continue

                mode = st.st_mode
                if statmod.S_ISLNK(mode):
                    self.handle_symlink(child_abs, child_rel, st, dir_obj)
                elif statmod.S_ISDIR(mode):
                    obj = self.ensure_object("dir", st)
                    self.add_path(obj, child_rel, name)
                    self.add_edge(dir_obj["id"], obj["id"], "contains", name)
                    if (st.st_dev, st.st_ino) not in self._scanned_dirs:
                        stack.append((child_abs, child_rel))
                elif statmod.S_ISREG(mode):
                    obj = self.ensure_object("file", st)
                    self.add_path(obj, child_rel, name)
                    self.add_edge(dir_obj["id"], obj["id"], "contains", name)
                    self._hash_file(obj, child_abs, hash_limit)
                else:
                    obj = self.ensure_object("special", st)
                    self.add_path(obj, child_rel, name)
                    self.add_edge(dir_obj["id"], obj["id"], "contains", name)
                    obj["error"] = "特殊文件（非普通文件/目录/符号链接），不读取内容"

    def _hash_file(self, obj: dict, path: str, limit: int) -> None:
        if obj["sha256"] is not None or obj["error"]:
            return  # 硬链接共享内容：同一对象只哈希一次
        size = obj["size"] or 0
        if size > limit:
            obj["error"] = f"超过哈希上限 {limit} 字节，扫描期未取摘要"
            self.stats["files_hash_skipped"] += 1
            return
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
        except OSError as e:
            obj["error"] = f"扫描期读取失败：{e.strerror or e}"
            return
        obj["sha256"] = h.hexdigest()
        self.stats["files_hashed"] += 1

    def to_dict(self) -> dict:
        by_kind: dict[str, int] = {}
        for o in self.objects.values():
            by_kind[o["kind"]] = by_kind.get(o["kind"], 0) + 1
        return {
            "root_name": self.root_name,
            "root_real": self.root_real,
            "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "objects": self.objects,
            "edges": self.edges,
            "errors": self.errors,
            "stats": {**self.stats, "objects_by_kind": by_kind,
                      "dirs_scanned": len(self._scanned_dirs)},
        }


def scan_root(root: str | Path, root_name: str | None = None,
              hash_limit: int = HASH_SIZE_LIMIT) -> Graph:
    root_real = os.path.realpath(os.fspath(root))
    if not os.path.isdir(root_real):
        raise NotADirectoryError(f"不是目录：{root_real}")
    g = Graph(root_real, root_name or os.path.basename(root_real))
    g.scan(hash_limit=hash_limit)
    return g
