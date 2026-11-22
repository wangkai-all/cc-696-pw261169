import React from 'react'

const KIND_LABEL = {
  replaced_during_read: '读取期间被替换',
  replaced_since_scan: '扫描后被替换',
  modified_since_scan: '扫描后被改写',
  vanished: '接收时消失',
  escaped: '接收前越界',
  read_error: '读取错误',
}

export function ChangeList({ changes }) {
  if (!changes.length) return <div className="muted">暂无变化事件</div>
  return (
    <table className="changes">
      <thead>
        <tr><th>#</th><th>时间</th><th>类型</th><th>路径</th><th>说明</th></tr>
      </thead>
      <tbody>
        {changes.map((c) => (
          <tr key={c.seq}>
            <td>{c.seq}</td>
            <td>{c.time}</td>
            <td><span className="badge b-warn">{KIND_LABEL[c.kind] || c.kind}</span></td>
            <td><code>{c.path}</code></td>
            <td>{c.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function AcceptPanel({
  root, graph, checked, onUncheck, onAccept, accepting,
  results, collection, changes, onClearChanges, onClearCollection, manifestUrl,
}) {
  const checkedObjs = [...checked].map((id) => graph.objects[id]).filter(Boolean)
  const accepted = Object.values(collection.accepted || {})
  const rejected = Object.entries(collection.rejected || {})
  return (
    <div className="accept">
      <section>
        <h3>待接收（{checkedObjs.length}）</h3>
        {checkedObjs.length === 0 && <div className="muted">在目录树中勾选文件</div>}
        <ul className="sel-list">
          {checkedObjs.map((o) => (
            <li key={o.id}>
              📄 <code>{o.paths[0]}</code>
              {o.paths.length > 1 && <span className="badge b-hard">硬链接 {o.paths.length}</span>}
              <button className="mini" onClick={() => onUncheck(o.id)}>移除</button>
            </li>
          ))}
        </ul>
        <button disabled={!checkedObjs.length || accepting} onClick={onAccept}>
          {accepting ? '接收中…' : `接收所选（${checkedObjs.length}）`}
        </button>
      </section>

      {results && (
        <section>
          <h3>本次接收结果</h3>
          <ul className="results">
            {results.map((r, i) => (
              <li key={i} className={r.status === 'accepted' ? 'ok' : 'bad'}>
                {r.status === 'accepted' ? '✅' : '❌'} <code>{r.requested_id}</code>
                {r.status === 'accepted' ? (
                  <>
                    {' '}已接收（{r.entry.attempts} 次尝试，校验：{r.entry.verify}）
                    <div className="sub">
                      源路径：{r.entry.source_paths.map((p) => <code key={p}>{p}</code>)}
                      {r.entry.identity_note !== '与扫描时相同' && (
                        <span className="badge b-warn">{r.entry.identity_note}</span>
                      )}
                      {!r.entry.content_matches_scan && (
                        <span className="badge b-warn">内容与扫描时不一致</span>
                      )}
                    </div>
                  </>
                ) : (
                  <span className="reason"> {r.reason}</span>
                )}
                {r.events.length > 0 && (
                  <span className="badge b-info">{r.events.length} 个变化事件</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>
          接收清单（{accepted.length} 项）
          <a className="btn-link" href={manifestUrl} download>⬇ 下载清单（含源路径关系）</a>
          <button className="mini" onClick={onClearCollection}>清空</button>
        </h3>
        {accepted.length > 0 && (
          <table className="changes">
            <thead>
              <tr><th>对象</th><th>大小</th><th>SHA-256</th><th>源路径</th></tr>
            </thead>
            <tbody>
              {accepted.map((e, i) => (
                <tr key={i}>
                  <td><code>{e.object_id}</code></td>
                  <td>{e.size}</td>
                  <td><code>{e.sha256.slice(0, 16)}…</code></td>
                  <td>{e.source_paths.map((p) => <code key={p} className="chain">{p}</code>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {rejected.length > 0 && (
          <>
            <h4>拒绝记录（{rejected.length}）</h4>
            <ul className="results">
              {rejected.map(([oid, r]) => (
                <li key={oid} className="bad">❌ <code>{oid}</code> <span className="reason">{r.reason}</span></li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section>
        <h3>
          变化队列（{changes.length}）
          <button className="mini" onClick={onClearChanges}>清空</button>
        </h3>
        <ChangeList changes={changes} />
      </section>
    </div>
  )
}
