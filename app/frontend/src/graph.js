// 图数据辅助：从 scan 结果派生树 / 链接关系
export function childrenOf(graph, id) {
  return graph.edges
    .filter((e) => e.kind === 'contains' && e.from === id)
    .map((e) => ({ edge: e, obj: graph.objects[e.to] }))
    .filter((x) => x.obj)
    .sort((a, b) => a.edge.name.localeCompare(b.edge.name, 'zh-CN'))
}

export function linksFrom(graph, id) {
  return graph.edges
    .filter((e) => e.kind === 'links' && e.from === id)
    .map((e) => graph.objects[e.to])
    .filter(Boolean)
}

export function rootDirId(graph) {
  for (const [id, o] of Object.entries(graph.objects)) {
    if (o.kind === 'dir' && (o.paths || []).includes('.')) return id
  }
  return null
}

export const KIND_ICON = {
  dir: '📁', file: '📄', symlink: '🔗', external: '🚪', missing: '❔', special: '⚙️',
}

export const LINK_STATUS_LABEL = {
  ok: '有效', broken: '断链', external: '越界', cycle: '成环',
  unreadable: '不可读', error: '解析错误', unresolved: '未解析',
}

export function badges(obj) {
  const out = []
  if (obj.kind === 'file' && (obj.paths?.length > 1 || obj.nlink > 1)) {
    out.push({ text: `硬链接 ${obj.paths.length}/${obj.nlink}`, cls: 'b-hard' })
  }
  if (obj.kind === 'symlink' && obj.link_status && obj.link_status !== 'ok') {
    out.push({ text: LINK_STATUS_LABEL[obj.link_status] || obj.link_status, cls: 'b-warn' })
  }
  if (obj.kind === 'external') out.push({ text: '仅登记·未读取', cls: 'b-warn' })
  if (obj.kind === 'missing') out.push({ text: '目标不存在', cls: 'b-warn' })
  if (obj.kind === 'special') out.push({ text: '特殊文件', cls: 'b-warn' })
  if (obj.error) out.push({ text: '读取异常', cls: 'b-warn' })
  if ((obj.via_symlinks || []).length > 0) out.push({ text: '经链接可达', cls: 'b-info' })
  return out
}
