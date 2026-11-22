#!/usr/bin/env python3
"""样例生成器 CLI。

用法：
  python scripts/make_sample.py create [name]            生成样例根目录（默认 demo）
  python scripts/make_sample.py mutate <root> [--duration 10] [--interval 0.05]
  python scripts/make_sample.py list

只写 samples/ 下的目录，不触碰机器其它位置。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backend import samplegen  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def main() -> None:
    ap = argparse.ArgumentParser(description="样例根目录生成器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="生成样例根目录")
    c.add_argument("name", nargs="?", default="demo")
    c.add_argument("--samples-dir", default=str(SAMPLES))

    m = sub.add_parser("mutate", help="在读取期间反复替换样例中的易变文件")
    m.add_argument("root", help="样例根目录路径")
    m.add_argument("--duration", type=float, default=10.0)
    m.add_argument("--interval", type=float, default=0.05)

    sub.add_parser("list", help="列出已生成的样例")

    args = ap.parse_args()

    if args.cmd == "create":
        root = Path(args.samples_dir) / args.name
        meta = samplegen.create_sample(root, outside_dir=Path(args.samples_dir))
        print(f"已生成样例根目录：{root}")
        print(f"  说明：{meta['description']}")
        print(f"  越界链接目标：{Path(args.samples_dir) / 'outside_secret.txt'}")
    elif args.cmd == "mutate":
        root = Path(args.root)
        target = samplegen.find_mutate_target(root)
        print(f"开始替换 {target}（{args.duration}s，每 {args.interval}s 一次）…")
        m = samplegen.Mutator(target, interval=args.interval, duration=args.duration)
        m.start()
        n = m.finish(timeout=args.duration + 5)
        print(f"完成，共替换 {n} 次")
    elif args.cmd == "list":
        for p in sorted(SAMPLES.iterdir()):
            if p.is_dir() and (p / samplegen.MARKER).exists():
                print(p.name, "→", p)


if __name__ == "__main__":
    main()
