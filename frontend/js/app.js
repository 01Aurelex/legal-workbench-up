/* 主应用：外壳布局、分组导航（折叠态图标）、命令面板、状态栏、授权闸门 */
import { createApp, ref, reactive, computed, onMounted, watch } from 'vue';
import { api, store, bootstrap, setTheme, toggleSidebar, daysLeft, loadAck, ackSig } from './core.js';
import { mountUI, toast, toastOk, toastErr, openCommand } from './ui.js';

const VIEWS = {
  home: () => import('./views/home.js'),
  cases: () => import('./views/cases.js'),
  clients: () => import('./views/clients.js'),
  vault: () => import('./views/vault.js'),
  graph: () => import('./views/graph.js'),
  revenue: () => import('./views/finance.js'),
  invoice: () => import('./views/finance.js'),
  calendar: () => import('./views/misc.js'),
  remind: () => import('./views/misc.js'),
  timer: () => import('./views/tools.js'),
  settings: () => import('./views/settings.js'),
};

/* 部分模块一个文件导出多个视图，需按 key 选择导出名 */
const NAMED = { invoice: 'InvoiceView', calendar: 'CalendarView' };

/* 已下线的功能（AI 助手 / 接案笔录-语音转写）：后端返回的导航里一并隐藏 */
const HIDDEN_KEYS = new Set(['ai', 'intake']);

/* 侧边栏分组：按功能类型合并划分，界面更简洁 */
const GROUPS = [
  { key: 'work', label: '工作台', keys: ['home'] },
  { key: 'case', label: '案件业务', keys: ['clients', 'cases', 'vault', 'graph'] },
  { key: 'fin', label: '财务', keys: ['revenue', 'invoice'] },
  { key: 'eff', label: '效率', keys: ['calendar', 'remind', 'timer'] },
  { key: 'sys', label: '系统', keys: ['settings'] },
];

/* 线性图标（stroke SVG，随主题着色）；收起侧边栏时只显示图标 */
const ico = (d, w) =>
  `<svg viewBox="0 0 24 24" width="${w || 16}" height="${w || 16}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const ICONS = {
  home: ico('<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/>'),
  clients: ico('<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>'),
  cases: ico('<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/>'),
  vault: ico('<path d="M21 8v13H3V8"/><path d="M1 3h22v5H1z"/><path d="M10 12h4"/>'),
  graph: ico('<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.59 13.51l6.83 3.98"/><path d="M15.41 6.51l-6.82 3.98"/>'),
  revenue: ico('<path d="M23 6l-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/>'),
  invoice: ico('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/>'),
  calendar: ico('<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/>'),
  timer: ico('<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>'),
  remind: ico('<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>'),
  settings: ico('<path d="M4 21v-7"/><path d="M4 10V3"/><path d="M12 21v-9"/><path d="M12 8V3"/><path d="M20 21v-5"/><path d="M20 12V3"/><path d="M1 14h6"/><path d="M9 8h6"/><path d="M17 16h6"/>'),
  _lock: ico('<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>'),
  _chevron: ico('<path d="M6 9l6 6 6-6"/>', 12),
  _fold: ico('<path d="m11 6-6 6 6 6M18 6l-6 6 6 6"/>', 15),
  _unfold: ico('<path d="m13 6 6 6-6 6M6 6l6 6-6 6"/>', 15),
};

/* 分组折叠状态持久化 */
const FOLD_KEY = 'lw_nav_fold';
function loadFold() {
  try { return new Set(JSON.parse(localStorage.getItem(FOLD_KEY) || '[]')); } catch { return new Set(); }
}
function saveFold(set) {
  try { localStorage.setItem(FOLD_KEY, JSON.stringify([...set])); } catch { /* ignore */ }
}

/* 追光效果：鼠标在元素上移动时写入 --mx/--my，由 CSS 渲染柔和光斑 */
function bindSpotlight(root = document) {
  root.addEventListener('mousemove', (e) => {
    const el = e.target.closest?.('.spot');
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  }, { passive: true });
}

const App = {
  setup() {
    const loading = ref(true);
    const viewComp = ref(null);
    const counts = reactive({ cases: 0, clients: 0 });
    const folded = reactive({ set: loadFold() });

    function toggleFold(key) {
      if (folded.set.has(key)) folded.set.delete(key); else folded.set.add(key);
      saveFold(folded.set);
    }

    /* 分组导航：过滤已下线与已停用项，再按分组排序（组内保持后端顺序） */
    const groupedNav = computed(() => {
      const items = (store.nav || []).filter((n) => n.enabled !== false && !HIDDEN_KEYS.has(n.key));
      const rank = new Map(GROUPS.flatMap((g) => g.keys.map((k, i) => [k, i])));
      const sorted = [...items].sort((a, b) => (rank.get(a.key) ?? 99) - (rank.get(b.key) ?? 99));
      const out = [];
      for (const g of GROUPS) {
        const group = sorted.filter((n) => g.keys.includes(n.key));
        if (!group.length) continue;
        out.push({ key: g.key, header: g.label, items: group, folded: folded.set.has(g.key) });
      }
      // 兜底：不在预定义分组里的项（自定义 key）归入「其他」
      const rest = sorted.filter((n) => !GROUPS.some((g) => g.keys.includes(n.key)));
      if (rest.length) out.push({ key: '_other', header: '其他', items: rest, folded: false });
      return out;
    });
    const currentName = computed(() =>
      (store.nav || []).find((n) => n.key === store.view)?.name || '工作台');

    /* 加载视图组件（seq 防止快速切换时旧视图晚到覆盖新视图） */
    let loadSeq = 0;
    async function loadView(key) {
      const seq = ++loadSeq;
      const loader = VIEWS[key];
      if (!loader) { viewComp.value = null; return; }
      try {
        const mod = await loader();
        if (seq !== loadSeq) return;   // 已切换到其他视图，丢弃过期结果
        viewComp.value = NAMED[key] ? (mod[NAMED[key]] || mod.default) : mod.default;
      } catch (e) {
        if (seq !== loadSeq) return;
        toastErr('视图加载失败：' + e.message);
        viewComp.value = null;
      }
    }
    watch(() => store.view, loadView, { immediate: false });

    /* 命令面板 */
    async function openCmd() {
      const navItems = (store.nav || [])
        .filter((n) => n.enabled !== false && !HIDDEN_KEYS.has(n.key))
        .map((n) => ({ icon: '', title: n.name, sub: '功能', act: () => (store.view = n.key) }));
      let cases = [], docs = [];
      try {
        const [c, d] = await Promise.all([api.get('/api/cases'), api.get('/api/archive/table?limit=200')]);
        cases = c.cases.map((x) => ({
          icon: '', title: `${x.client}·${x.cause}`, sub: '案件',
          keywords: x.case_no + x.court, act: () => { store.view = 'cases'; store.pendingCase = x.rel_path; },
        }));
        docs = d.rows.slice(0, 60).map((x) => ({
          icon: '', title: x.title, sub: '档案 · ' + x.category,
          act: () => { store.view = 'vault'; store.pendingNote = x.rel_path; },
        }));
      } catch { /* ignore */ }
      const acts = [
        { icon: '', title: '新建案件', sub: '操作', act: () => (store.view = 'cases') },
        { icon: '', title: '新建客户', sub: '操作', act: () => (store.view = 'clients') },
        { icon: '', title: '收取邮箱发票', sub: '操作', act: async () => {
            const r = await api.post('/api/invoices/fetch', {});
            toast(r.ok ? `收取完成：新增 ${r.saved?.length || 0} 份` : (r.error || '收取失败')); } },
        { icon: '', title: '同步档案总表到飞书', sub: '操作', act: async () => {
            const r = await api.post('/api/bitable/sync', { dataset: 'archive' });
            toast(r.ok ? `已同步 ${r.written} 行` : (r.error || '同步失败')); } },
        { icon: '', title: '重建档案总表索引', sub: '操作', act: async () => {
            const r = await api.post('/api/registry/sync', {}); toastOk('已刷新索引'); } },
      ];
      const picked = await openCommand([...navItems, ...cases, ...docs, ...acts]);
      if (picked?.act) picked.act();
    }

    /* 全局快捷键 */
    function onKey(e) {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); openCmd(); }
      if (mod && e.key === 'b') { e.preventDefault(); toggleSidebar(); }
    }

    /* 状态栏刷新 */
    async function refreshStatus() {
      try {
        const [c, cl] = await Promise.all([api.get('/api/cases'), api.get('/api/clients')]);
        counts.cases = c.cases.length; counts.clients = cl.clients.length;
      } catch { /* ignore */ }
    }

    async function loadBadge() {
      try {
        const r = await api.get('/api/reminders');
        const acked = loadAck();
        store.badge = r.reminders.filter((x) => !acked.has(ackSig(x))).filter((x) => {
          const n = daysLeft(x.due);
          return n !== null && n <= 3;
        }).length;
      } catch { /* ignore */ }
    }

    onMounted(async () => {
      setTheme(store.theme);
      document.documentElement.setAttribute('data-theme', store.theme);
      try {
        if (!new URLSearchParams(location.search).get('token')) await bootstrap();
        const nav = await api.get('/api/nav');
        store.nav = nav.items;
        const saved = localStorage.getItem('lw_view');
        if (saved && (store.nav || []).some((n) => n.key === saved && !HIDDEN_KEYS.has(n.key))) store.view = saved;
        await loadView(store.view);
        await Promise.all([refreshStatus(), loadBadge()]);
      } catch (e) { toastErr(e.message); }
      loading.value = false;
      window.addEventListener('keydown', onKey);
      bindSpotlight();
      setInterval(loadBadge, 120000);
    });

    watch(() => store.view, (v) => localStorage.setItem('lw_view', v));

    return {
      store, loading, viewComp, counts, groupedNav, currentName, ICONS,
      openCmd, toggleSidebar, setTheme, api, toggleFold,
      toggleTheme: () => setTheme(store.theme === 'dark' ? 'light' : 'dark'),
    };
  },
  template: `
<div id="app">
  <!-- 顶栏 -->
  <header class="topbar">
    <div class="brand">
      <div class="brand-mark">法岩</div>
      <div>
        <div class="brand-name">法岩工作台</div>
        <div class="brand-sub">Legal Workbench</div>
      </div>
    </div>

    <div class="omni spot" @click="openCmd()">
      <span>搜索功能、案件、档案…</span><kbd>Ctrl K</kbd>
    </div>

    <div class="top-actions">
      <button class="tbtn tbtn-text" @click="store.view='remind'">
        提醒<span v-if="store.badge" class="tbadge">{{ store.badge }}</span></button>
      <button class="tbtn tbtn-text" @click="toggleTheme()">{{ store.theme==='dark'?'浅色模式':'深色模式' }}</button>
      <button class="tbtn tbtn-text" @click="store.view='settings'">设置</button>
    </div>
  </header>

  <div :class="['body-row', store.sidebarMini ? 'mini' : '']">
    <!-- 侧边栏：按功能类型分组；收起时仅显示图标 -->
    <aside :class="['sidebar', store.sidebarMini ? 'mini' : '']">
      <nav class="nav">
        <template v-for="g in groupedNav" :key="g.key">
          <div v-if="!store.sidebarMini" class="nav-group" @click="toggleFold(g.key)">
            <span class="nav-group-t">{{ g.header }}</span>
            <span class="nav-group-c" :class="g.folded ? 'is-folded' : ''" v-html="ICONS._chevron"></span>
          </div>
          <div v-else class="nav-sep"></div>
          <template v-if="!g.folded || store.sidebarMini">
            <div v-for="item in g.items" :key="item.key"
                 :class="['nav-item', 'spot', store.view===item.key ? 'active' : '',
                          (item.key==='remind' && store.badge) ? 'has-dot' : '']"
                 :title="item.name"
                 @click="store.view = item.key"
                 @contextmenu.prevent="store.view='settings'">
              <span class="ico" v-html="ICONS[item.key] || ICONS._lock"></span>
              <span class="lbl">{{ item.name }}</span>
              <span v-if="item.key==='cases' && counts.cases" class="cnt">{{ counts.cases }}</span>
              <span v-else-if="item.key==='clients' && counts.clients" class="cnt">{{ counts.clients }}</span>
              <span v-else-if="item.key==='remind' && store.badge" class="cnt cnt-danger">{{ store.badge }}</span>
            </div>
          </template>
        </template>
      </nav>

      <div class="side-foot">
        <div class="qk spot" @click="toggleSidebar()" :title="store.sidebarMini ? '展开侧边栏' : '收起侧边栏 (Ctrl+B)'">
          <span class="qk-ico" v-html="store.sidebarMini ? ICONS._unfold : ICONS._fold"></span>
          <span v-if="!store.sidebarMini">收起侧边栏</span>
        </div>
      </div>
    </aside>

    <!-- 主内容 -->
    <main class="main">
      <Transition name="view" mode="out-in">
        <component :is="viewComp" v-if="viewComp" :key="store.view" />
        <div v-else class="empty" style="flex:1">
          <div class="spinner"></div><div class="t">加载中…</div>
        </div>
      </Transition>
    </main>
  </div>

  <!-- 状态栏 -->
  <footer class="statusbar">
    <span class="si"><span class="dot-live"></span>本机运行 · 仅 127.0.0.1</span>
    <span class="si">案件：<b>{{ counts.cases }}</b> · 客户：<b>{{ counts.clients }}</b></span>
    <span style="margin-left:auto" class="si">数据全部留存本地 · 零云端上传</span>
  </footer>
</div>`,
};

mountUI();
createApp(App).mount('#app');
