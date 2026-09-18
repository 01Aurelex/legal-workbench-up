/* 核心：HTTP 客户端、全局状态、通用工具 */
import { reactive, ref } from 'vue';

export const TOKEN_KEY = 'lw_token';

let TOKEN = new URLSearchParams(location.search).get('token') || localStorage.getItem(TOKEN_KEY) || '';

async function bootstrap() {
  const r = await fetch('/api/bootstrap');
  const d = await r.json();
  if (d.token) {
    TOKEN = d.token;
    localStorage.setItem(TOKEN_KEY, TOKEN);
  }
  return TOKEN;
}

function headers(json = true, extra = {}) {
  const h = { 'X-Auth-Token': TOKEN, ...extra };
  if (json) h['Content-Type'] = 'application/json';
  return h;
}

async function handle(r) {
  const d = await r.json().catch(() => ({ ok: false, error: '响应解析失败' }));
  if (r.status === 401) {
    await bootstrap();
    return { ok: false, error: '会话已刷新，请重试' };
  }
  if (!d.ok) throw new Error(d.error || '请求失败');
  return d;
}

export const api = {
  get: (path) => fetch(path, { headers: headers(false) }).then(handle),
  post: (path, body) => fetch(path, { method: 'POST', headers: headers(), body: JSON.stringify(body || {}) }).then(handle),
  patch: (path, body) => fetch(path, { method: 'PATCH', headers: headers(), body: JSON.stringify(body || {}) }).then(handle),
  del: (path) => fetch(path, { method: 'DELETE', headers: headers(false) }).then(handle),
  upload: (path, formData) => fetch(path, { method: 'POST', headers: { 'X-Auth-Token': TOKEN }, body: formData }).then(handle),

  /** 流式 POST（NDJSON），逐块回调 */
  async stream(path, body, onChunk) {
    const r = await fetch(path, { method: 'POST', headers: headers(), body: JSON.stringify(body || {}) });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const reader = r.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try { onChunk(JSON.parse(line)); } catch { /* skip */ }
      }
    }
    if (buf.trim()) {
      try { onChunk(JSON.parse(buf)); } catch { /* skip */ }
    }
  },
};

export { bootstrap };
export const token = () => TOKEN;

/* ========================= 全局状态 ========================= */
export const store = reactive({
  ready: false,
  theme: localStorage.getItem('lw_theme') || 'dark',
  sidebarMini: localStorage.getItem('lw_sidebar') === 'mini',
  view: 'home',
  nav: [],
  badge: 0,
  status: { model: '', law: '', vault: '', secure: true },
  settings: null,
  aiStatus: null,
  scheduler: null,
  cases: [],
  clients: [],
  types: [],
  typesGrouped: {},
});

export function setTheme(t) {
  store.theme = t;
  document.documentElement.setAttribute('data-theme', t);
  localStorage.setItem('lw_theme', t);
}

export function toggleSidebar() {
  store.sidebarMini = !store.sidebarMini;
  localStorage.setItem('lw_sidebar', store.sidebarMini ? 'mini' : 'full');
}

/* ========================= 已知悉（本地忽略）清单 =========================
   后端每次拉取 /api/reminders 都会重建「期限」提醒（先删除再重插，行 id 会变），
   仅靠后端的 done 标记无法保持状态。故前端按「类型+标题+到期日」签名本地记忆，
   点击「已知悉」后立即移出列表并写入 localStorage。 */
const LS_ACK = 'lw_ack_v1';
export const ackSig = (r) => [r?.kind || '', r?.title || '', r?.due || ''].join('|');
export function loadAck() {
  try {
    const a = JSON.parse(localStorage.getItem(LS_ACK) || '[]');
    return new Set(Array.isArray(a) ? a : []);
  } catch { return new Set(); }
}
export function saveAck(set) {
  try { localStorage.setItem(LS_ACK, JSON.stringify([...set])); } catch { /* ignore */ }
}

/* ========================= 工具函数 ========================= */
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const today = () => new Date().toISOString().slice(0, 10);
export const nowTime = () => new Date().toLocaleTimeString('zh-CN', { hour12: false });

export function fmtDate(v, withTime = false) {
  if (!v) return '';
  const s = String(v);
  if (withTime) return s.slice(0, 16);
  return s.slice(0, 10);
}

export function fmtSize(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB';
  return (n / 1024 / 1024 / 1024).toFixed(2) + ' GB';
}

export function fmtMoney(n, symbol = '¥') {
  const v = Number(n) || 0;
  return symbol + v.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtMoneyShort(n) {
  const v = Number(n) || 0;
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(1) + '万';
  return v.toFixed(0);
}

export function daysLeft(due) {
  if (!due) return null;
  const d = new Date(String(due).slice(0, 10));
  const t = new Date(today());
  return Math.round((d - t) / 86400000);
}

export function dueLabel(due) {
  const n = daysLeft(due);
  if (n === null) return { text: '', cls: '' };
  if (n < 0) return { text: `逾期${-n}天`, cls: 'badge-danger' };
  if (n === 0) return { text: '今天到期', cls: 'badge-danger' };
  if (n <= 3) return { text: `${n}天后`, cls: 'badge-warn' };
  return { text: `${n}天后`, cls: '' };
}

export function relTime(v) {
  if (!v) return '';
  const s = String(v).replace('T', ' ').slice(0, 19);
  const d = new Date(s);
  if (isNaN(d)) return s.slice(0, 10);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return Math.floor(diff / 60) + ' 分钟前';
  if (diff < 86400) return Math.floor(diff / 3600) + ' 小时前';
  if (diff < 86400 * 7) return Math.floor(diff / 86400) + ' 天前';
  return s.slice(0, 10);
}

// v0.9.9：去除文件类型 emoji，统一以扩展名文本标签呈现（纯文字 UI）
export const FILE_ICON = {};

export const fileIcon = (name = '', isDir = false) => {
  if (isDir) return '';
  const i = name.lastIndexOf('.');
  return (i >= 0 ? name.slice(i + 1) : 'file').slice(0, 5).toUpperCase();
};

export const TYPE_COLOR = {
  客户: 'var(--primary)', 案件: 'var(--purple)', 材料: 'var(--warn)',
  文书: 'var(--success)', 笔记: 'var(--text-3)', 其他: 'var(--cyan)',
};

export function downloadUrl(path) {
  return `/api/file/download?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token())}`;
}

export function rawUrl(path) {
  return `/api/file/raw?path=${encodeURIComponent(path)}&token=${encodeURIComponent(token())}`;
}

/** 极简 Markdown 渲染（支持标题/粗体/代码/列表/引用/表格/双链） */
export function md(src) {
  let html = esc(src || '');
  html = html.replace(/```([\s\S]*?)```/g, (m, c) => `<pre><code>${c.replace(/^\n/, '')}</code></pre>`);
  html = html.replace(/\[\[([^\]]+?)\]\]/g,
    (m, t) => `<span class="wikilink" data-wiki="${esc(t.trim())}">${esc(t.split('|').pop().split('/').pop())}</span>`);
  const lines = html.split('\n');
  const out = [];
  let inList = false, inTable = false;
  const closeList = () => { if (inList) { out.push('</ul>'); inList = false; } };
  const closeTable = () => { if (inTable) { out.push('</tbody></table>'); inTable = false; } };
  for (let i = 0; i < lines.length; i++) {
    let ln = lines[i];
    if (/^\s*\|(.+)\|\s*$/.test(ln)) {
      const cells = ln.trim().slice(1, -1).split('|').map((c) => c.trim());
      if (!inTable) {
        closeList();
        out.push('<table><thead><tr>' + cells.map((c) => `<th>${c}</th>`).join('') + '</tr></thead><tbody>');
        inTable = true;
        const nxt = lines[i + 1] || '';
        if (/^\s*\|[\s:|-]+\|\s*$/.test(nxt)) i++;
        continue;
      }
      out.push('<tr>' + cells.map((c) => `<td>${c}</td>`).join('') + '</tr>');
      continue;
    }
    closeTable();
    if (/^\s*(#{1,6})\s+/.test(ln)) {
      closeList();
      const lv = ln.match(/^\s*(#{1,6})\s+/)[1].length;
      out.push(`<h${lv}>${ln.replace(/^\s*#{1,6}\s+/, '')}</h${lv}>`);
      continue;
    }
    if (/^\s*[-*+]\s+/.test(ln)) {
      if (!inList) { out.push('<ul>'); inList = true; }
      out.push(`<li>${ln.replace(/^\s*[-*+]\s+/, '')}</li>`);
      continue;
    }
    if (/^\s*>\s?/.test(ln)) {
      closeList();
      out.push(`<blockquote>${ln.replace(/^\s*>\s?/, '')}</blockquote>`);
      continue;
    }
    closeList();
    if (ln.trim() === '') { out.push(''); continue; }
    out.push(`<p>${ln}</p>`);
  }
  closeList(); closeTable();
  html = out.join('\n')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/(?<!`)\*([^*\n]+)\*(?!`)/g, '<i>$1</i>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  return html;
}

/** 等待 DOM 更新 */
export const nextTick = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

/** 简易防抖 */
export function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}
