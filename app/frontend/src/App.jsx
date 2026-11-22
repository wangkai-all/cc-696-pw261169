import React, { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { rootDirId } from './graph.js'
import TreeView from './components/TreeView.jsx'
import DetailsPanel from './components/DetailsPanel.jsx'
import LinkGraph from './components/LinkGraph.jsx'
import AcceptPanel from './components/AcceptPanel.jsx'

export default function App() {
  const [roots, setRoots] = useState([])
  const [root, setRoot] = useState('')
  const [graph, setGraph] = useState(null)
  const [selected, setSelected] = useState(null)
  const [checked, setChecked] = useState(new Set())
  const [tab, setTab] = useState('browse') // browse | graph | accept
  const [results, setResults] = useState(null)
  const [accepting, setAccepting] = useState(false)
  const [changes, setChanges] = useState([])
  const [collection, setCollection] = useState({ accepted: {}, rejected: {} })
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const refreshRoots = useCallback(async () => {
    try {
      const data = await api.roots()
      setRoots(data.roots)
    } catch (e) { setError(String(e)) }
  }, [])

  useEffect(() => { refreshRoots() }, [refreshRoots])

  const refreshChanges = useCallback(async (name) => {
    if (!name) return
    try {
      const [ch, col] = await Promise.all([api.changes(name), api.collection(name)])
      setChanges(ch.changes)
      setCollection(col)
    } catch { /* 根目录可能尚未就绪 */ }
  }, [])

  useEffect(() => {
    if (!root) return
    refreshChanges(root)
    const t = setInterval(() => refreshChanges(root), 3000)
    return () => clearInterval(t)
  }, [root, refreshChanges])

  async function run(fn, label) {
    setBusy(label); setError('')
    try { await fn() } catch (e) { setError(String(e)) } finally { setBusy('') }
  }

  const doCreate = () => run(async () => {
    const name = `demo-${new Date().toISOString().slice(11, 19).replaceAll(':', '')}`
    await api.createRoot(name)
    await refreshRoots()
    setRoot(name)
    setGraph(null); setChecked(new Set()); setResults(null)
  }, '生成样例中…')

  const doScan = () => run(async () => {
    const g = await api.scan(root)
    setGraph(g); setSelected(rootDirId(g)); setChecked(new Set()); setResults(null)
  }, '扫描中…')

  const doMutate = () => run(async () => {
    await api.mutate(root, 10, 0.05)
  }, '启动替换演示…')

  const doAccept = () => run(async () => {
    setAccepting(true)
    try {
      const r = await api.accept(root, [...checked])
      setResults(r.results)
      const acceptedIds = new Set(r.results.filter((x) => x.status === 'accepted').map((x) => x.requested_id))
      setChecked((prev) => new Set([...prev].filter((id) => !acceptedIds.has(id))))
      await refreshChanges(root)
      setTab('accept')
    } finally { setAccepting(false) }
  }, '接收中…')

  const toggleCheck = (id) => setChecked((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id); else next.add(id)
    return next
  })

  const rid = graph ? rootDirId(graph) : null

  return (
    <div className="app">
      <header>
        <h1>本地目录数据发现</h1>
        <select value={root} onChange={(e) => {
          setRoot(e.target.value); setGraph(null); setChecked(new Set()); setResults(null)
        }}>
          <option value="">选择样例根目录…</option>
          {roots.map((r) => (
            <option key={r.name} value={r.name}>
              {r.name}{r.prepared ? '' : '（未准备）'}{r.scanned ? ' ·已扫描' : ''}
            </option>
          ))}
        </select>
        <button onClick={doCreate} disabled={!!busy}>＋ 生成样例</button>
        <button onClick={doScan} disabled={!root || !!busy}>⟳ 扫描</button>
        <button onClick={doMutate} disabled={!root || !!busy} title="10 秒内反复替换 volatile/news.txt">
          ⚡ 替换演示
        </button>
        {busy && <span className="busy">{busy}</span>}
        {error && <span className="error">{error}</span>}
      </header>

      {graph && (
        <div className="stats">
          对象 {Object.keys(graph.objects).length} ·
          文件 {graph.stats.objects_by_kind.file || 0} ·
          目录 {graph.stats.objects_by_kind.dir || 0} ·
          符号链接 {graph.stats.objects_by_kind.symlink || 0} ·
          越界引用 {graph.stats.objects_by_kind.external || 0} ·
          已哈希 {graph.stats.files_hashed} ·
          扫描于 {graph.scanned_at}
          {graph.errors.length > 0 && <span className="error"> · {graph.errors.length} 个扫描异常</span>}
        </div>
      )}

      <nav className="tabs">
        <button className={tab === 'browse' ? 'on' : ''} onClick={() => setTab('browse')}>浏览</button>
        <button className={tab === 'graph' ? 'on' : ''} onClick={() => setTab('graph')} disabled={!graph}>链接图</button>
        <button className={tab === 'accept' ? 'on' : ''} onClick={() => setTab('accept')} disabled={!graph}>
          接收与清单{checked.size ? `（已选 ${checked.size}）` : ''}
        </button>
      </nav>

      {tab === 'browse' && (
        <main className="split">
          <div className="pane left">
            <TreeView
              graph={graph} rootId={rid} selected={selected}
              onSelect={setSelected} checked={checked} onCheck={toggleCheck}
            />
          </div>
          <div className="pane right">
            {graph && <DetailsPanel graph={graph} id={selected} onSelect={setSelected} />}
          </div>
        </main>
      )}

      {tab === 'graph' && graph && (
        <main>
          <div className="hint">从当前选中对象出发展开链接图；↩ 表示沿该路径会遇到循环。</div>
          <LinkGraph graph={graph} startId={selected || rid} onSelect={setSelected} />
        </main>
      )}

      {tab === 'accept' && graph && (
        <main>
          <AcceptPanel
            root={root} graph={graph} checked={checked}
            onUncheck={toggleCheck} onAccept={doAccept} accepting={accepting}
            results={results} collection={collection} changes={changes}
            onClearChanges={() => run(async () => { await api.clearChanges(root); await refreshChanges(root) }, '清空中…')}
            onClearCollection={() => run(async () => { await api.clearCollection(root); await refreshChanges(root) }, '清空中…')}
            manifestUrl={api.manifestUrl(root)}
          />
        </main>
      )}
    </div>
  )
}
