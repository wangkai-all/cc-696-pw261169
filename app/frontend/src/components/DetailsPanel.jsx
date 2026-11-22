import React from 'react'
import { KIND_ICON, LINK_STATUS_LABEL, badges } from '../graph.js'

function Row({ k, children }) {
  return (
    <tr>
      <td className="k">{k}</td>
      <td>{children}</td>
    </tr>
  )
}

export default function DetailsPanel({ graph, id, onSelect }) {
  const obj = id ? graph.objects[id] : null
  if (!obj) return <div className="muted">在左侧选择一个对象查看详情</div>
  const target = obj.target ? graph.objects[obj.target] : null
  return (
    <div className="details">
      <h3>
        {KIND_ICON[obj.kind] || '❓'} {obj.name || obj.id}{' '}
        {badges(obj).map((b, i) => <span key={i} className={'badge ' + b.cls}>{b.text}</span>)}
      </h3>
      <table className="kv">
        <tbody>
          <Row k="对象 ID">{obj.id}</Row>
          <Row k="类型">{obj.kind}{obj.reference_only ? '（引用，不读取）' : ''}</Row>
          {obj.dev !== undefined && <Row k="设备 / inode">{obj.dev} / {obj.ino}</Row>}
          {obj.size !== null && obj.size !== undefined && <Row k="大小">{obj.size} 字节</Row>}
          {obj.nlink !== undefined && <Row k="硬链接数">{obj.nlink}</Row>}
          {obj.sha256 && <Row k="SHA-256"><code>{obj.sha256}</code></Row>}
          {obj.reason && <Row k="原因">{obj.reason}</Row>}
          {obj.error && <Row k="异常">{obj.error}</Row>}
        </tbody>
      </table>

      <h4>被发现于（{obj.paths?.length || 0} 条路径）</h4>
      <ul className="paths">
        {(obj.paths || []).map((p) => <li key={p}><code>{p === '.' ? '（根目录）' : p}</code></li>)}
      </ul>
      {(obj.via_symlinks || []).length > 0 && (
        <>
          <h4>经由符号链接到达</h4>
          <ul className="paths">
            {obj.via_symlinks.map((v, i) => (
              <li key={i}>
                <code>{v.path}</code>（链接文本 <code>{v.link_text}</code>）{' '}
                <button className="mini" onClick={() => onSelect(v.symlink)}>查看链接</button>
              </li>
            ))}
          </ul>
        </>
      )}

      {obj.kind === 'symlink' && (
        <>
          <h4>链接信息</h4>
          <table className="kv">
            <tbody>
              <Row k="链接文本"><code>{obj.link_text}</code></Row>
              <Row k="状态">{LINK_STATUS_LABEL[obj.link_status] || obj.link_status}</Row>
              {obj.link_chain?.length > 0 && (
                <Row k="解析链">{obj.link_chain.map((c, i) => <code key={i} className="chain">{c}</code>)}</Row>
              )}
              {obj.resolved && <Row k="解析为"><code>{obj.resolved}</code></Row>}
              {target && (
                <Row k="目标">
                  <button className="mini" onClick={() => onSelect(target.id)}>
                    {KIND_ICON[target.kind]} {target.name || target.id}
                  </button>
                </Row>
              )}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}
