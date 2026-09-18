/* 客户管理 */
import { ref, reactive, computed, onMounted } from 'vue';
import { api, store, fmtMoney, relTime } from '../core.js';
import { toast, toastOk, toastErr, modal, confirm, openCtx } from '../ui.js';

const ClientForm = {
  props: { initial: Object },
  emits: ['submit', 'cancel'],
  setup(props) {
    const f = reactive({
      name: '', contact: '', idno: '', opponent: '', address: '', note: '',
      ...(props.initial || {}),
    });
    return { f };
  },
  template: `
<div class="fgrid">
  <div class="field"><label>客户名称 *</label><input class="input" v-model="f.name" placeholder="自然人姓名或企业名称" /></div>
  <div class="field"><label>联系方式</label><input class="input" v-model="f.contact" placeholder="手机号 / 座机" /></div>
  <div class="field"><label>身份证号 / 统一社会信用代码</label><input class="input" v-model="f.idno" /></div>
  <div class="field"><label>对方当事人</label><input class="input" v-model="f.opponent" /></div>
  <div class="field full"><label>地址</label><input class="input" v-model="f.address" /></div>
  <div class="field full"><label>备注</label><textarea class="textarea" v-model="f.note" placeholder="客户背景、来源渠道、特殊约定等"></textarea></div>
  <div class="modal-f full" style="margin:10px -20px -20px">
    <button class="btn" @click="$emit('cancel')">取消</button>
    <button class="btn btn-primary" @click="$emit('submit', f)">保存客户</button>
  </div>
</div>`,
};

export default {
  name: 'ClientsView',
  components: { ClientForm },
  setup() {
    const clients = ref([]);
    const loading = ref(true);
    const keyword = ref('');
    const detail = ref(null);
    const sortBy = ref('amount');
    const mode = ref('card');           // card | table

    async function load() {
      loading.value = true;
      try {
        clients.value = (await api.get('/api/clients')).clients;
        store.clients = clients.value;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);

    const filtered = computed(() => {
      let r = clients.value.slice();
      if (keyword.value) {
        const k = keyword.value.toLowerCase();
        r = r.filter((c) => `${c.title}${c.联系方式 || ''}${c.对方当事人 || ''}`.toLowerCase().includes(k));
      }
      if (sortBy.value === 'amount') r.sort((a, b) => (b.amount || 0) - (a.amount || 0));
      else if (sortBy.value === 'cases') r.sort((a, b) => (b.cases || 0) - (a.cases || 0));
      else r.sort((a, b) => (a.title || '').localeCompare(b.title || '', 'zh-CN'));
      return r;
    });

    const summary = computed(() => ({
      total: clients.value.length,
      amount: clients.value.reduce((s, c) => s + (c.amount || 0), 0),
      cases: clients.value.reduce((s, c) => s + (c.cases || 0), 0),
      active: clients.value.filter((c) => (c.cases || 0) > 0).length,
    }));

    async function create() {
      const d = await modal({ title: '新建客户', comp: ClientForm });
      if (!d) return;
      if (!d.name?.trim()) return toastErr('客户名称必填');
      try { await api.post('/api/clients', d); toastOk('客户已创建'); load(); }
      catch (e) { toastErr(e.message); }
    }

    async function openClient(c) {
      try {
        detail.value = { ...(await api.get('/api/client/detail?path=' + encodeURIComponent(c.rel_path))), path: c.rel_path };
      } catch (e) { toastErr(e.message); }
    }

    async function remove(c) {
      const okd = await confirm({ title: '删除客户', danger: true, okText: '删除',
        message: `确定删除客户「${c.title}」？该客户笔记文件将一并删除。` });
      if (!okd) return;
      await api.post('/api/archive/delete', { path: c.rel_path });
      toastOk('已删除'); detail.value = null; load();
    }

    function clientMenu(ev, c) {
      openCtx(ev, [
        { icon: '', label: '查看详情', onClick: () => openClient(c) },
        { icon: '', label: '打开本地文档', onClick: () => api.post('/api/archive/open', { path: c.rel_path }) },
        { icon: '', label: '打开所在文件夹', onClick: () => api.post('/api/archive/reveal', { path: c.rel_path }) },
        { sep: true },
        { icon: '', label: '删除客户', danger: true, onClick: () => remove(c) },
      ]);
    }

    return { clients, filtered, loading, keyword, detail, sortBy, mode, summary, create, openClient, clientMenu, load, fmtMoney, relTime, store };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div><h1>客户管理</h1><div class="desc">客户档案与案件、创收自动关联，支持一键打开本地客户文档</div></div>
    <div class="actions">
      <div class="seg">
        <button :class="mode==='card'?'on':''" @click="mode='card'">卡片</button>
        <button :class="mode==='table'?'on':''" @click="mode='table'">表格</button>
      </div>
      <select class="select" style="width:130px" v-model="sortBy">
        <option value="amount">按创收排序</option><option value="cases">按案件数排序</option><option value="name">按名称排序</option>
      </select>
      <button class="btn" @click="load()">刷新</button>
      <button class="btn btn-primary" @click="create()">＋ 新建客户</button>
    </div>
  </div>

  <div class="grid g-4 sec">
    <div class="stat blue"><div class="stat-ico"></div><div class="k">客户总数</div>
      <div class="v">{{ summary.total }}<small>位</small></div></div>
    <div class="stat green"><div class="stat-ico"></div><div class="k">累计创收</div>
      <div class="v">¥{{ (summary.amount||0).toLocaleString() }}</div></div>
    <div class="stat purple"><div class="stat-ico"></div><div class="k">关联案件</div>
      <div class="v">{{ summary.cases }}<small>件</small></div></div>
    <div class="stat accent"><div class="stat-ico"></div><div class="k">在手客户</div>
      <div class="v">{{ summary.active }}<small>位</small></div><div class="d">有在办案件</div></div>
  </div>

  <input class="input sec" style="max-width:320px" placeholder="搜索客户名称/联系方式…" v-model="keyword" />

  <div v-if="loading" class="empty"><div class="spinner"></div></div>
  <div v-else-if="mode==='card'" class="grid g-auto">
    <div v-for="c in filtered" :key="c.rel_path" class="card" style="cursor:pointer"
         @click="openClient(c)" @contextmenu="clientMenu($event, c)">
      <div class="row gap-3">
        <div style="width:42px;height:42px;border-radius:10px;display:grid;place-items:center;font-size:19px;flex:none"
             :style="{ background:'var(--primary-lo)', color:'var(--primary)' }">
          {{ c.title.slice(0, 1) }}
        </div>
        <div class="grow">
          <h4 class="ellip">{{ c.title }}</h4>
          <div class="tiny dim ellip">{{ c.联系方式 || '无联系方式' }}</div>
        </div>
      </div>
      <div class="divider" style="margin:11px 0"></div>
      <div class="row between">
        <div><div class="tiny dim">在手案件</div><div class="num" style="font-weight:650">{{ c.cases }}</div></div>
        <div style="text-align:right">
          <div class="tiny dim">累计创收</div>
          <div class="num" style="font-weight:650;color:var(--success)">¥{{ (c.amount||0).toLocaleString() }}</div>
        </div>
      </div>
    </div>
    <div v-if="!filtered.length" class="empty" style="grid-column:1/-1">
      <div class="ico">◇</div><div class="t">暂无客户</div><div class="d">点击「新建客户」建立第一份客户档案</div>
    </div>
  </div>

  <!-- 表格视图 -->
  <div v-else class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th>客户</th><th>联系方式</th><th>证件号码</th><th>对方当事人</th>
        <th class="num">在手案件</th><th class="num">累计创收</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="c in filtered" :key="c.rel_path" @click="openClient(c)" style="cursor:pointer">
          <td><b>{{ c.title }}</b></td>
          <td class="dim">{{ c.联系方式 || '—' }}</td>
          <td class="dim">{{ c['身份证/统一信用代码'] || '—' }}</td>
          <td class="dim">{{ c.对方当事人 || '—' }}</td>
          <td class="num">{{ c.cases }}</td>
          <td class="num" style="color:var(--success)">¥{{ (c.amount||0).toLocaleString() }}</td>
          <td><button class="btn btn-sm" @click.stop="openClient(c)">详情</button></td>
        </tr>
        <tr v-if="!filtered.length"><td colspan="7"><div class="empty"><div class="t">暂无客户</div></div></td></tr>
      </tbody>
    </table>
  </div>

  <!-- 详情 -->
  <div v-if="detail" class="mask" @click.self="detail=null">
    <div class="modal lg">
      <div class="modal-h">
        <h3>{{ detail.frontmatter.标题 || '客户详情' }}</h3>
        <button class="tbtn tbtn-close" @click="detail=null">×</button>
      </div>
      <div class="modal-b">
        <div class="grid g-2 mb-4">
          <div class="card">
            <div class="panel-title">基本信息</div>
            <table class="kv-table">
              <tr><td>联系方式</td><td>{{ detail.frontmatter.联系方式 || '—' }}</td></tr>
              <tr><td>证件号码</td><td>{{ detail.frontmatter['身份证/统一信用代码'] || '—' }}</td></tr>
              <tr><td>对方当事人</td><td>{{ detail.frontmatter.对方当事人 || '—' }}</td></tr>
              <tr><td>地址</td><td>{{ detail.frontmatter.地址 || '—' }}</td></tr>
            </table>
          </div>
          <div class="card">
            <div class="panel-title">经营数据</div>
            <div class="row gap-4">
              <div><div class="tiny dim">关联案件</div><div style="font-size:22px;font-weight:680">{{ detail.cases.length }}</div></div>
              <div><div class="tiny dim">累计创收</div>
                <div style="font-size:22px;font-weight:680;color:var(--success)">
                  ¥{{ detail.fees.filter(f=>f.record_type!=='成本支出').reduce((s,f)=>s+(f.amount||0),0).toLocaleString() }}
                </div></div>
            </div>
          </div>
        </div>

        <div class="panel-title">关联案件</div>
        <div v-if="!detail.cases.length" class="tiny dim mb-4">暂无关联案件</div>
        <div v-for="c in detail.cases" :key="c.rel_path" class="li"
             @click="store.view='cases'; store.pendingCase=c.rel_path; detail=null">
          <div class="li-ico">·</div>
          <div class="li-main">
            <div class="li-t">{{ c.cause }}</div>
            <div class="li-s">{{ c.case_type || '' }} · {{ c.stage }} · {{ c.court || '' }}</div>
          </div>
          <span class="badge">¥{{ (c.fee_amount||0).toLocaleString() }}</span>
        </div>

        <div class="panel-title mt-4">收费记录</div>
        <div v-if="!detail.fees.length" class="tiny dim">暂无收费记录</div>
        <div v-for="f in detail.fees" :key="f.id" class="row between" style="padding:5px 0;border-bottom:1px solid var(--border)">
          <span class="small">{{ f.fee_date }} · {{ f.title }}
            <span class="badge" :class="f.record_type==='成本支出'?'badge-warn':'badge-success'">{{ f.record_type }}</span></span>
          <b class="num">¥{{ (f.amount||0).toLocaleString() }}</b>
        </div>
      </div>
      <div class="modal-f">
        <button class="btn" @click="api.post('/api/archive/open', { path: detail.path })">打开本地文档</button>
        <button class="btn" @click="api.post('/api/archive/reveal', { path: detail.path })">所在文件夹</button>
        <button class="btn btn-primary" @click="detail=null">关闭</button>
      </div>
    </div>
  </div>
</div>`,
};
