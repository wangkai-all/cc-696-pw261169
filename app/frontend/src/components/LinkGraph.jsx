import React, { useState } from 'react'
import { childrenOf, linksFrom, KIND_ICON, badges } from '../graph.js'

// 可展开的链接图：每个节点可展开"包含"与"链接到"两类边；
// 沿展开路径记录祖先，遇到循环时标注而不再深入。
function GNode({ graph, id, ancestors, onSelect }) {
  const [open, setOpen] = useState(false)
  const obj = graph.objects[id]
  if (!obj) return null
  const cycle = ancestors.has(id)
  const nextAncestors = new Set(ancestors)
  nextAncestors.add(id)
  const kids = open && !cycle ? childrenOf(graph, id) : []
  const links = open && !cycle ? linksFrom(graph, id) : []
  return (
    <div className="gnode">
      <div className="grow">
        <button className="twisty btn" onClick={() => !cycle && setOpen(!open)}>
          {cycle ? '↩' : open ? '▾' : '▸'}
        </button>
        <span className="glabel" onClick={() => onSelect(id)}>
          {KIND_ICON[obj.kind] || '❓'} {obj.name || obj.id}
        </span>
        <code className="gpath">{(obj.paths && obj.paths[0]) || obj.resolved || ''}</code>
        {badges(obj).map((b, i) => <span key={i} className={'badge ' + b.cls}>{b.text}</span>)}
        {cycle && <span className="badge b-cycle">循环回到此对象</span>}
      </div>
      {open && !cycle && (
        <div className="gchildren">
          {links.map((t) => (
            <div key={'L' + t.id} className="gedge">
              <span className="edgelabel">🔗 链接到</span>
              <GNode graph={graph} id={t.id} ancestors={nextAncestors} onSelect={onSelect} />
            </div>
          ))}
          {kids.map(({ edge, obj: child }) => (
            <div key={'C' + edge.name + child.id} className="gedge">
              <span className="edgelabel">📁 包含</span>
              <GNode graph={graph} id={child.id} ancestors={nextAncestors} onSelect={onSelect} />
            </div>
          ))}
          {kids.length === 0 && links.length === 0 && (
            <div className="muted indent">（没有出边）</div>
          )}
        </div>
      )}
    </div>
  )
}

export default function LinkGraph({ graph, startId, onSelect }) {
  if (!graph || !startId) return <div className="muted">先扫描并选择起始对象</div>
  return (
    <div className="linkgraph">
      <GNode graph={graph} id={startId} ancestors={new Set()} onSelect={onSelect} />
    </div>
  )
}
