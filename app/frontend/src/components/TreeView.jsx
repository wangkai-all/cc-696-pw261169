import React, { useState } from 'react'
import { childrenOf, KIND_ICON, badges } from '../graph.js'

function Node({ graph, id, name, depth, selected, onSelect, checked, onCheck }) {
  const [open, setOpen] = useState(depth < 2)
  const obj = graph.objects[id]
  if (!obj) return null
  const kids = obj.kind === 'dir' ? childrenOf(graph, id) : []
  const isFile = obj.kind === 'file'
  return (
    <div className="tnode" style={{ '--depth': depth }}>
      <div
        className={'trow' + (selected === id ? ' sel' : '')}
        onClick={() => onSelect(id)}
      >
        <span
          className={'twisty' + (kids.length ? '' : ' leaf')}
          onClick={(e) => { e.stopPropagation(); if (kids.length) setOpen(!open) }}
        >
          {kids.length ? (open ? '▾' : '▸') : '·'}
        </span>
        {isFile && (
          <input
            type="checkbox"
            checked={checked.has(id)}
            onClick={(e) => e.stopPropagation()}
            onChange={() => onCheck(id)}
            title="选择接收"
          />
        )}
        <span className="ticon">{KIND_ICON[obj.kind] || '❓'}</span>
        <span className="tname">{name}</span>
        {badges(obj).map((b, i) => (
          <span key={i} className={'badge ' + b.cls}>{b.text}</span>
        ))}
        {obj.kind === 'symlink' && (
          <span className="tlink">→ {obj.link_text}</span>
        )}
      </div>
      {open && kids.map(({ edge, obj: child }) => (
        <Node
          key={edge.name + '→' + child.id}
          graph={graph}
          id={child.id}
          name={edge.name}
          depth={depth + 1}
          selected={selected}
          onSelect={onSelect}
          checked={checked}
          onCheck={onCheck}
        />
      ))}
    </div>
  )
}

export default function TreeView({ graph, rootId, selected, onSelect, checked, onCheck }) {
  if (!graph || !rootId) return <div className="muted">尚未扫描</div>
  return (
    <div className="tree">
      <Node
        graph={graph}
        id={rootId}
        name={graph.root_name}
        depth={0}
        selected={selected}
        onSelect={onSelect}
        checked={checked}
        onCheck={onCheck}
      />
    </div>
  )
}
