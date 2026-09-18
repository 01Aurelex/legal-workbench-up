/* 档案库：文件树 + 飞书式多维表格 + 笔记编辑 + 右键打开本地文档 */
import { ref, reactive, computed, onMounted, watch } from 'vue';
import { api, store, esc, fmtSize, relTime, fileIcon, downloadUrl, md, debounce } from '../core.js';
import { toast, toastOk, toastErr, openCtx, modal, confirm, prompt } from '../ui.js';

const COLUMNS = [
  { key: 'title', name: '标题', width: '260px', edit: true },
  { key: 'category', name: '分类', width: '86px' },
  { key: 'client', name: '客户', width: '110px', edit: true },
  { key: 'case_ref', name: '关联案件', width: '150px', edit: true },
  { key: 'ext', name: '类型', width: '66px' },
  { key: 'size', name: '大小', width: '84px', align: 'right' },
  { key: 'mtime', name: '修改时间', width: '132px' },
  { key: 'open_count', name: '打开次数', width: '86px', align: 'right' },
  { key: 'last_open', name: '最近打开', width: '132px' },
  { key: 'tags', name: '标签', width: '130px', edit: true },
  { key: 'remark', name: '备注', width: '180px', edit: true },
  { key: 'rel_path', name: '本地路径', width: '260px' },
];

export default {
  name: 'VaultView',
  setup() {
    const tree = ref([]);
    const rows = ref([]);
    const facets = ref({ categories: [], clients: [], cases: [] });
    const tab = ref('sheet');           // sheet | note
    const loading = ref(true);
    const expanded = reactive(new Set(['客户', '案件', '材料', '文书', '笔记']));
    const filter = reactive({ keyword: '', category: '', client: '', starred: false });
    const sortKey = ref('updated');
    const sortDesc = ref(true);
    const selected = ref(null);
    const editing = ref(null);          // {path, key}
    const editVal = ref('');
    const currentNote = ref(null);      // {path, text}
    const noteMode = ref('preview');    // edit | preview
    const backlinks = ref([]);
    const syncing = ref(false);
    const bitable = ref(null);

    const filtered = computed(() => {
      let r = rows.value.slice();
      if (filter.starred) r = r.filter((x) => x.starred);
      if (filter.category) r = r.filter((x) => x.category === filter.category);
      if (filter.client) r = r.filter((x) => x.client === filter.client);
      if (filter.keyword) {
        const k = filter.keyword.toLowerCase();
        r = r.filter((x) => (x.title + x.rel_path + (x.tags || '') + (x.remark || '') + (x.client || ''))
          .toLowerCase().includes(k));
      }
      return r;
    });

    async function loadTree() {
      const d = await api.get('/api/archive/tree');
      tree.value = d.tree;
    }

    async function loadTable() {
      const p = new URLSearchParams();
      if (filter.category) p.set('category', filter.category);
      if (filter.client) p.set('client', filter.client);
      if (filter.starred) p.set('starred', '1');
      p.set('sort', sortKey.value); p.set('desc', sortDesc.value ? '1' : '0');
      const d = await api.get('/api/archive/table?' + p.toString());
      rows.value = d.rows;
      facets.value = d.facets;
    }

    async function loadBitable() {
      try { bitable.value = (await api.get('/api/bitable/status')); } catch { /* ignore */ }
    }

    async function refresh() {
      loading.value = true;
      try {
        await Promise.all([loadTree(), loadTable(), loadBitable()]);
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }

    onMounted(async () => {
      await refresh();
      if (store.pendingNote) {
        const p = store.pendingNote; store.pendingNote = null;
        if (p.endsWith('.md')) openNote(p);
      }
    });
    watch(() => store.pendingNote, (v) => {
      if (v && v.endsWith('.md')) { const p = v; store.pendingNote = null; openNote(p); }
    });

    const searchDebounced = debounce(() => loadTable(), 260);
    watch(() => filter.keyword, () => searchDebounced());
    watch(() => [filter.category, filter.client, filter.starred], () => loadTable());

    /* ---------- 文件树 ---------- */
    function toggle(node) {
      if (expanded.has(node.path ?? node.name)) expanded.delete(node.path ?? node.name);
      else expanded.add(node.path ?? node.name);
    }
    const isOpen = (n) => expanded.has(n.path ?? n.name);

    /* ---------- 右键菜单 ---------- */
    function fileMenu(ev, path, row) {
      const items = [
        { icon: '', label: '打开本地文档', hint: '默认程序', onClick: () => openLocal(path) },
        { icon: '', label: '打开所在文件夹', onClick: () => reveal(path) },
        { icon: '', label: '下载到本地', onClick: () => window.open(downloadUrl(path)) },
      ];
      items.push(
        { sep: true },
        { icon: '', label: row?.starred ? '取消星标' : '设为常用', onClick: () => toggleStar(row) },
        { icon: '', label: '复制本地路径', onClick: () => copyPath(path) },
        { sep: true },
        { icon: '', label: '重命名', onClick: () => renameFile(path) },
        { icon: '', label: '删除', danger: true, onClick: () => removeFile(path) },
      );
      openCtx(ev, items);
    }

    function dirMenu(ev, node) {
      const p = node.path === '' ? '' : node.path;
      openCtx(ev, [
        { icon: '', label: '在系统资源管理器中打开', onClick: () => api.post('/api/archive/open-folder', { path: p }) },
        { icon: '', label: '新建笔记', onClick: () => newNote(p) },
        { icon: '', label: '新建子文件夹', onClick: () => newFolder(p) },
        { icon: '', label: '上传文件到此目录', onClick: () => uploadHere(p) },
        { sep: true },
        { icon: '', label: '重命名', onClick: () => renameFile(p) },
        { icon: '', label: '删除文件夹', danger: true, onClick: () => removeFile(p) },
      ]);
    }

    async function copyPath(p) {
      try { await navigator.clipboard.writeText(p); toast('路径已复制'); }
      catch { toast('复制失败：' + p, 'err'); }
    }

    async function openLocal(path) {
      const r = await api.post('/api/archive/open', { path });
      if (r.ok) { toastOk('已用本机默认程序打开'); loadTable(); }
      else toastErr(r.error || '打开失败');
    }
    async function reveal(path) {
      await api.post('/api/archive/reveal', { path });
    }

    async function toggleStar(row) {
      if (!row) return;
      await api.post('/api/archive/fields', { path: row.rel_path, patch: { starred: !row.starred } });
      row.starred = row.starred ? 0 : 1;
    }

    async function renameFile(path) {
      const name = await prompt({ title: '重命名', label: '新名称', value: path.split('/').pop(), placeholder: '请输入新名称' });
      if (!name || name === path.split('/').pop()) return;
      await api.post('/api/archive/rename', { path, name });
      toastOk('已重命名'); refresh();
    }

    async function removeFile(path) {
      const okd = await confirm({
        title: '删除档案', danger: true, okText: '删除',
        message: `确定要删除「${path.split('/').pop()}」吗？此操作会同时删除本地文件，不可恢复。`,
      });
      if (!okd) return;
      await api.post('/api/archive/delete', { path });
      toastOk('已删除'); refresh();
    }

    async function newFolder(parent) {
      const name = await prompt({ title: '新建文件夹', label: '文件夹名称', placeholder: '如：2026年度案卷' });
      if (!name) return;
      await api.post('/api/archive/new-folder', { parent, name });
      toastOk('已创建'); refresh();
    }

    async function newNote(dir) {
      const title = await prompt({ title: '新建笔记', label: '笔记标题', placeholder: '如：案情分析' });
      if (!title) return;
      const folder = (dir || '笔记').split('/')[0] || '笔记';
      await api.post('/api/note/create', { folder, title, body: '' });
      toastOk('已创建'); refresh();
    }

    function uploadHere(dir) {
      const inp = document.createElement('input');
      inp.type = 'file'; inp.multiple = true;
      inp.onchange = async () => {
        const fd = new FormData();
        [...inp.files].forEach((f) => fd.append('files', f));
        fd.append('folder', dir || '');
        await api.upload('/api/archive/upload', fd);
        toastOk('上传完成'); refresh();
      };
      inp.click();
    }

    /* ---------- 行内编辑 ---------- */
    function startEdit(row, col) {
      if (!col.edit) return;
      editing.value = { path: row.rel_path, key: col.key };
      editVal.value = row[col.key] ?? '';
    }
    async function commitEdit(row) {
      if (!editing.value) return;
      const { path, key } = editing.value;
      editing.value = null;
      if ((row[key] ?? '') === editVal.value) return;
      const r = await api.post('/api/archive/fields', { path, patch: { [key]: editVal.value } });
      Object.assign(row, r.row);
    }

    function sortBy(col) {
      if (sortKey.value === col) sortDesc.value = !sortDesc.value;
      else { sortKey.value = col; sortDesc.value = true; }
      loadTable();
    }

    /* ---------- 笔记 ---------- */
    async function openNote(path) {
      try {
        const d = await api.get('/api/note?path=' + encodeURIComponent(path));
        currentNote.value = { path, text: d.text };
        backlinks.value = d.backlinks || [];
        noteMode.value = 'preview';
        tab.value = 'note';
      } catch (e) { toastErr(e.message); }
    }
    async function saveNote() {
      await api.post('/api/note/save', { path: currentNote.value.path, text: currentNote.value.text });
      toastOk('已保存到本地'); refresh();
    }
    const rendered = computed(() => md(currentNote.value?.text || ''));

    /* ---------- 同步飞书 ---------- */
    async function syncFeishu() {
      syncing.value = true;
      try {
        const r = await api.post('/api/bitable/sync', { dataset: 'archive' });
        if (r.ok) toastOk(`已同步 ${r.written} 行到飞书多维表格`);
        else toastErr(r.error || '同步失败');
      } catch (e) { toastErr(e.message); }
      syncing.value = false;
    }
    async function exportCsv() {
      const r = await api.post('/api/bitable/export', { dataset: 'archive' });
      toastOk(`已导出 ${r.rows} 行：${r.name}`);
    }

    /* ---------- 一键导入：指定文件夹 → 递归扫描 → 关键词匹配归档 ---------- */
    async function importFolder() {
      const dir = await prompt({
        title: '一键导入本地文件夹',
        label: '文件夹绝对路径',
        placeholder: String.raw`如：D:\案卷资料\2026 —— 会递归扫描并复制进档案库（原文件保留）`,
      });
      if (!dir || !dir.trim()) return;
      toast('正在扫描并导入，请稍候…');
      let r;
      try {
        r = await api.post('/api/archive/import-folder', { dir: dir.trim(), move: false });
      } catch (e) { toastErr(e.message); return; }
      if (!r.ok) { toastErr(r.error || '导入失败'); return; }
      await refresh();
      modal({
        title: '一键导入完成',
        size: 'lg',
        comp: {
          setup: () => ({ r }),
          emits: ['submit'],
          template: `
          <div>
            <div class="import-summary">
              <div class="cell"><div class="n">{{ r.imported_count }}</div><div class="k">成功导入</div></div>
              <div class="cell"><div class="n">{{ r.matched_case + r.matched_client }}</div><div class="k">自动匹配案件/客户</div></div>
              <div class="cell"><div class="n">{{ r.duplicate_count }}</div><div class="k">重复跳过</div></div>
              <div class="cell"><div class="n">{{ r.unsupported_count }}</div><div class="k">不支持/失败</div></div>
            </div>
            <div class="tiny dim" style="margin-bottom:8px">
              来源：{{ r.source }} ｜ 共扫描 {{ r.total }} 个文件；匹配案件 {{ r.matched_case }} 个、匹配客户 {{ r.matched_client }} 个，其余归入「材料/外部导入」。
            </div>
            <div class="import-files">
              <div v-for="(f,i) in r.imported" :key="'i'+i" class="row-l">
                <span class="tag">{{ f.bind }}</span><span class="pth">{{ f.name }} → {{ f.dest }}</span>
              </div>
              <div v-for="(f,i) in r.duplicates" :key="'d'+i" class="row-l">
                <span class="tag skip">重复</span><span class="pth">{{ f.name }}（{{ f.reason }}）</span>
              </div>
              <div v-for="(f,i) in r.unsupported" :key="'u'+i" class="row-l">
                <span class="tag skip">跳过</span><span class="pth">{{ f.name }}（{{ f.reason }}）</span>
              </div>
            </div>
            <div class="modal-f" style="margin:16px -20px -20px">
              <button class="btn btn-primary" @click="$emit('submit', true)">完成</button>
            </div>
          </div>`,
        },
      });
      toastOk(`导入完成：${r.imported_count} 个文件已纳入管理`);
    }

    return {
      tree, rows, filtered, facets, tab, loading, isOpen, toggle, filter,
      sortKey, sortDesc, sortBy, selected, editing, editVal, startEdit, commitEdit,
      fileMenu, dirMenu, openLocal, reveal, toggleStar, renameFile, removeFile,
      newFolder, newNote, uploadHere, refresh, currentNote, noteMode, openNote,
      saveNote, rendered, backlinks, syncFeishu, exportCsv, importFolder, syncing, bitable,
      COLUMNS, fmtSize, relTime, fileIcon, downloadUrl, store,
    };
  },
  template: `
<div class="view flat">
  <div class="vault-layout">
    <!-- 文件树 -->
    <div class="vault-tree">
      <div class="row between mb-2" style="padding:0 6px">
        <b class="small" style="font-size:12px;color:var(--text-2)">档案库</b>
        <div class="row gap-1 tree-tools">
          <button class="tbtn" title="新建文件夹" @click="newFolder('')">新建</button>
          <button class="tbtn" title="上传文件到此目录" @click="uploadHere('')">上传</button>
          <button class="tbtn" title="刷新" @click="refresh()">刷新</button>
        </div>
      </div>
      <div v-if="!tree.length" class="empty" style="padding:20px"><div class="t">暂无档案</div></div>
      <template v-for="node in tree" :key="node.path ?? node.name">
        <div :class="['tree-node', selected === node.path ? 'active' : '']"
             @click="node.type==='dir' ? toggle(node) : openNote(node.path)"
             @contextmenu="node.type==='dir' ? dirMenu($event, node) : fileMenu($event, node.path)">
          <span v-if="node.type==='dir'" :class="['caret', isOpen(node) ? 'open' : '']"></span>
          <span v-else style="width:12px"></span>
          <span class="fico">{{ fileIcon(node.name, node.type==='dir') }}</span>
          <span class="nm">{{ node.name }}</span>
          <span v-if="node.type==='dir'" class="tiny dim">{{ (node.children||[]).length }}</span>
        </div>
        <div v-if="node.type==='dir' && isOpen(node)" class="tree-children">
          <template v-for="c in node.children" :key="c.path">
            <div :class="['tree-node']" @click="c.type==='dir' ? toggle(c) : openNote(c.path)"
                 @contextmenu="c.type==='dir' ? dirMenu($event, c) : fileMenu($event, c.path)">
              <span v-if="c.type==='dir'" :class="['caret', isOpen(c) ? 'open' : '']"></span>
              <span v-else style="width:12px"></span>
              <span class="fico">{{ fileIcon(c.name, c.type==='dir') }}</span>
              <span class="nm">{{ c.name }}</span>
            </div>
            <div v-if="c.type==='dir' && isOpen(c)" class="tree-children">
              <div v-for="g in c.children" :key="g.path" class="tree-node"
                   @click="g.type==='dir' ? toggle(g) : openNote(g.path)"
                   @contextmenu="g.type==='dir' ? dirMenu($event, g) : fileMenu($event, g.path)">
                <span v-if="g.type==='dir'" class="caret" :class="isOpen(g)?'open':''"></span>
                <span v-else style="width:12px"></span>
                <span class="fico">{{ fileIcon(g.name, g.type==='dir') }}</span>
                <span class="nm">{{ g.name }}</span>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>

    <!-- 主区 -->
    <div class="vault-main">
      <div class="tabbar">
        <div :class="['tab', tab==='sheet'?'active':'']" @click="tab='sheet'">总体管理表格</div>
        <div :class="['tab', tab==='note'?'active':'']" @click="tab='note'">
          {{ currentNote ? currentNote.path.split('/').pop() : '笔记' }}
        </div>
        <div style="margin-left:auto" class="row gap-2">
          <span class="tiny dim">共 {{ filtered.length }} 条</span>
        </div>
      </div>

      <!-- 多维表格 -->
      <template v-if="tab==='sheet'">
        <div class="sheet-toolbar">
          <input class="input" style="width:210px;height:28px" placeholder="搜索标题/标签/备注…" v-model="filter.keyword" />
          <div class="row gap-1 wrap">
            <span :class="['chip', !filter.category ? 'on' : '']" @click="filter.category=''">全部分类</span>
            <span v-for="c in facets.categories" :key="c" :class="['chip', filter.category===c?'on':'']"
                  @click="filter.category = filter.category===c ? '' : c">{{ c }}</span>
          </div>
          <div class="row gap-1" style="margin-left:auto">
            <span :class="['chip', filter.starred?'on':'']" @click="filter.starred=!filter.starred">常用</span>
            <button class="btn btn-sm" @click="importFolder()">一键导入</button>
            <button class="btn btn-sm" @click="refresh()">刷新</button>
            <button class="btn btn-sm" @click="exportCsv()">导出 CSV</button>
            <button class="btn btn-sm btn-primary" :disabled="syncing" @click="syncFeishu()">
              <span v-if="syncing" class="spinner"></span>{{ syncing ? '同步中' : '同步飞书' }}
            </button>
          </div>
        </div>
        <div class="sheet">
          <table class="tbl" style="border-collapse:separate">
            <thead>
              <tr>
                <th style="width:44px;background:var(--bg-3);position:sticky;left:0;z-index:4"></th>
                <th style="width:36px;background:var(--bg-3);position:sticky;left:44px;z-index:4"></th>
                <th v-for="c in COLUMNS" :key="c.key" :style="{ width: c.width, minWidth: c.width }">
                  <div class="th-in" @click="sortBy(c.key)">
                    <span class="ellip">{{ c.name }}</span>
                    <span v-if="sortKey===c.key" style="color:var(--accent)">{{ sortDesc ? '降' : '升' }}</span>
                  </div>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!filtered.length">
                <td :colspan="COLUMNS.length+2">
                  <div class="empty"><div class="ico">◇</div><div class="t">暂无档案</div>
                    <div class="d">点击左侧上传按钮或新建笔记，档案会自动登记到这张总表</div></div>
                </td>
              </tr>
              <tr v-for="(row, i) in filtered" :key="row.rel_path"
                  @click="selected = row.rel_path"
                  @dblclick="openLocal(row.rel_path)"
                  @contextmenu="fileMenu($event, row.rel_path, row)">
                <td class="row-no">{{ i + 1 }}</td>
                <td style="text-align:center">
                  <span :class="['star', row.starred ? 'on' : '']" @click.stop="toggleStar(row)">
                    {{ row.starred ? '已常用' : '设为常用' }}
                  </span>
                </td>
                <td v-for="c in COLUMNS" :key="c.key" :title="String(row[c.key] ?? '')">
                  <div class="td-in" :style="{ textAlign: c.align || 'left' }"
                       @click="startEdit(row, c)" v-if="editing?.path !== row.rel_path || editing.key !== c.key">
                    <template v-if="c.key==='size'">{{ fmtSize(row.size) }}</template>
                    <template v-else-if="c.key==='mtime'">{{ row.mtime ? new Date(row.mtime*1000).toLocaleString('zh-CN',{hour12:false}).slice(0,16) : '' }}</template>
                    <template v-else-if="c.key==='last_open'">{{ relTime(row.last_open) }}</template>
                    <template v-else-if="c.key==='title'">
                      <span>{{ fileIcon(row.rel_path) }}</span> {{ row.title }}
                    </template>
                    <template v-else>{{ row[c.key] ?? '' }}</template>
                  </div>
                  <input v-else class="cell-input" v-model="editVal" :ref="'ed'+i"
                         @blur="commitEdit(row)" @keyup.enter="commitEdit(row)"
                         @keyup.esc="editing=null" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="row" style="padding:7px 16px;border-top:1px solid var(--border);font-size:11.5px;color:var(--text-3)">
          <span>双击行用本机默认程序打开 · 右键查看更多操作 · 点击单元格可直接编辑</span>
          <span style="margin-left:auto" v-if="bitable">
            飞书多维表格：{{ bitable.configured ? '已配置' : '未配置（可用导出 CSV）' }}
            <span v-if="bitable.last_sync"> · 上次同步 {{ bitable.last_sync }}</span>
          </span>
        </div>
      </template>

      <!-- 笔记 -->
      <template v-else>
        <div v-if="!currentNote" class="empty" style="flex:1">
          <div class="ico">◇</div><div class="t">未打开笔记</div>
          <div class="d">在左侧文件树中选择一篇 Markdown 笔记，或新建一篇</div>
        </div>
        <template v-else>
          <div class="sheet-toolbar">
            <span class="badge">{{ currentNote.path }}</span>
            <div class="seg" style="margin-left:auto">
              <button :class="noteMode==='edit'?'on':''" @click="noteMode='edit'">编辑</button>
              <button :class="noteMode==='preview'?'on':''" @click="noteMode='preview'">预览</button>
            </div>
            <button class="btn btn-sm btn-primary" @click="saveNote()">保存</button>
            <button class="btn btn-sm" @click="openLocal(currentNote.path)">本地打开</button>
          </div>
          <div style="flex:1;display:grid;grid-template-columns:1fr 236px;overflow:hidden">
            <div style="overflow:auto;padding:18px 22px">
              <textarea v-if="noteMode==='edit'" v-model="currentNote.text"
                        style="width:100%;height:100%;min-height:400px;background:var(--bg-1);color:var(--text-1);border:1px solid var(--border);border-radius:var(--r-md);padding:14px;font-family:var(--font-mono);font-size:13px;line-height:1.75;resize:none;outline:none"></textarea>
              <div v-else class="md-body" v-html="rendered"></div>
            </div>
            <div style="border-left:1px solid var(--border);padding:14px;overflow:auto">
              <div class="panel-title">反向链接</div>
              <div v-if="!backlinks.length" class="tiny dim">暂无反向链接</div>
              <div v-for="b in backlinks" :key="b.rel_path" class="li" @click="openNote(b.rel_path)">
                <div class="li-ico">·</div>
                <div class="li-main"><div class="li-t ellip">{{ b.title }}</div></div>
              </div>
            </div>
          </div>
        </template>
      </template>
    </div>
  </div>
</div>`,
};
