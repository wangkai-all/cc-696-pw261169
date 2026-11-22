# 本地目录数据发现（pointwise-delivery）

面向本地目录的数据发现应用：选择**准备好的样例根目录**后浏览文件、目录与链接关系，
挑选可接收的文件形成清单。页面既展示内容对象，也保留它从哪些路径被发现。

## 核心规则

- **身份只认真实对象**：文件 / 目录 / 符号链接一律以 `(st_dev, st_ino)` 为身份，
  不使用规范化后的名字 —— 中文名、仅大小写差异（`ReadMe.txt` / `readme.txt`）、
  不同目录下的同名文件都不会被混淆。
- **硬链接**：共享同一内容对象，但每条发现路径都保留（清单里的 `source_paths`）。
- **符号链接**：成环（ELOOP）、断链、指向根目录外三类分别标记；遍历按目录真实身份
  识别循环，保证终止。**边界外的目标只登记引用，绝不读取内容。**
- **接收核对**：接收前 / 读取后各取一次 stat 快照，并对 ≤64MB 文件做二次读取校验
  （有的文件系统时间戳粒度粗到写入后 mtime 不变）。读取期间被替换的文件进入
  **变化队列**，丢弃该次读取后重新完整读取 —— 绝不把前后两份拼起来。
- **不扫描整台电脑**：API 只接受 `samples/` 下带 `.discovery-root.json` 标记的
  样例根目录名，拒绝任意路径。

## 快速开始

```bash
python3 -m venv .venv && .venv/bin/pip install fastapi "uvicorn[standard]" pytest httpx
bash scripts/run_prod.sh          # 构建前端并启动 http://localhost:8000
# 或者开发模式（前端热更新 :5173）：
bash scripts/run_dev.sh
```

生成 / 操作样例：

```bash
.venv/bin/python scripts/make_sample.py create demo      # 生成样例根目录
.venv/bin/python scripts/make_sample.py mutate samples/demo --duration 10
.venv/bin/python scripts/make_sample.py list
```

样例树包含：硬链接（跨目录、中文名）、符号链接循环（`loop/p↔q`、`loop/self`）、
断链、越界链接（相对与绝对）、中文名、大小写孪生、同名文件、以及会被反复替换的
`volatile/news.txt`（点界面的「⚡ 替换演示」或上面的 mutate 命令触发）。

## 页面

- **浏览**：目录树 + 对象详情（所有发现路径、经由哪些符号链接到达、链接解析链、拒绝原因）。
- **链接图**：从选中对象出发展开「包含 / 链接到」两类边，↩ 标注循环。
- **接收与清单**：勾选文件 → 接收 → 查看每项结果与拒绝原因、变化队列，
  下载带源路径关系的接收清单（JSON）。

## 测试

```bash
.venv/bin/python -m pytest
```

18 个测试覆盖：硬链接路径保留、身份不依赖名字、循环识别与终止、断链 / 越界登记、
接收前后一致性、读取期间替换进变化队列且内容无拼接、API 全流程。

## 结构

```
app/backend/    discovery.py（遍历建图） acceptor.py（接收核对+变化队列）
                samplegen.py（样例生成+替换器） store.py main.py
app/frontend/   React 单页（树 / 详情 / 链接图 / 接收面板）
app/tests/      pytest
scripts/        make_sample.py、run_dev.sh、run_prod.sh
samples/        样例根目录（运行时生成，已 gitignore）
accepted/       接收到的副本（运行时生成，已 gitignore）
```
