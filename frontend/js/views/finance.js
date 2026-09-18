/* 创收管理 + 发票管理 */
import { ref, reactive, computed, onMounted, watch } from 'vue';
import { api, store, token, fmtMoney, fmtMoneyShort, relTime } from '../core.js';
import { toast, toastOk, toastErr, modal, confirm, openCtx } from '../ui.js';
import { BarChart, Donut, PALETTE } from '../charts.js';

/* ============================ 创收管理 ============================ */
export default {
  name: 'RevenueView',
  components: { BarChart, Donut },
  setup() {
    const data = ref(null);
    const rows = ref([]);
    const loading = ref(true);
    const filter = reactive({ rtype: '', year: '', keyword: '' });
    const showForm = ref(false);
    const editing = ref(null);
    const form = reactive({
      record_type: '律师费', client: '', title: '', amount: '',
      fee_date: new Date().toISOString().slice(0, 10), method: '银行转账',
      invoice_no: '', invoiced: false, note: '', case_path: '',
    });

    async function load() {
      loading.value = true;
      try {
        const p = new URLSearchParams();
        if (filter.rtype) p.set('rtype', filter.rtype);
        if (filter.year) p.set('year', filter.year);
        if (filter.keyword) p.set('keyword', filter.keyword);
        const [a, b] = await Promise.all([
          api.get('/api/revenue/records?' + p.toString()),
          api.get('/api/revenue/summary?year=' + (filter.year || '')),
        ]);
        rows.value = a.rows; data.value = b;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);
    watch(() => [filter.rtype, filter.year], load);
    watch(() => filter.keyword, () => { clearTimeout(window.__rw); window.__rw = setTimeout(load, 300); });

    const s = computed(() => data.value?.summary || {});
    const monthly = computed(() => (data.value?.monthly || []).map((m) => ({
      label: m.ym.slice(2), value: m.收入合计, cost: m.成本支出, ym: m.ym,
    })));

    const clientBars = computed(() => (data.value?.by_client || []).slice(0, 8).map((c) => ({
      label: c.key, value: c.amount,
    })));

    const typeDonut = computed(() => {
      const x = s.value;
      return [
        { label: '律师费', value: x.律师费 || 0, color: PALETTE[0] },
        { label: '其他收入', value: x.其他收入 || 0, color: PALETTE[1] },
        { label: '成本支出', value: x.成本支出 || 0, color: PALETTE[5] },
      ].filter((i) => i.value > 0);
    });

    function resetForm() {
      Object.assign(form, {
        record_type: '律师费', client: '', title: '', amount: '',
        fee_date: new Date().toISOString().slice(0, 10), method: '银行转账',
        invoice_no: '', invoiced: false, note: '', case_path: '',
      });
      editing.value = null;
    }

    function openForm(row = null) {
      resetForm();
      if (row) { Object.assign(form, row); editing.value = row.id; }
      showForm.value = true;
    }

    async function save() {
      if (!form.amount || Number(form.amount) === 0) return toastErr('请填写金额');
      try {
        if (editing.value) {
          await api.patch('/api/revenue/records/' + editing.value, { ...form });
          toastOk('已更新');
        } else {
          await api.post('/api/revenue/records', { ...form });
          toastOk('已登记');
        }
        showForm.value = false; load();
      } catch (e) { toastErr(e.message); }
    }

    async function remove(r) {
      const okd = await confirm({ title: '删除记录', danger: true, okText: '删除',
        message: `确定删除「${r.title} ¥${r.amount}」这条记录？` });
      if (!okd) return;
      await api.del('/api/revenue/records/' + r.id);
      toastOk('已删除'); load();
    }

    function rowMenu(ev, r) {
      openCtx(ev, [
        { icon: '', label: '编辑', onClick: () => openForm(r) },
        { icon: '', label: '删除', danger: true, onClick: () => remove(r) },
      ]);
    }

    const typeBadge = (t) => t === '律师费' ? 'badge-accent'
      : t === '其他收入' ? 'badge-success' : 'badge-warn';

    return {
      data, rows, loading, filter, s, monthly, clientBars, typeDonut,
      showForm, form, editing, openForm, save, resetForm, remove, rowMenu, load,
      fmtMoney, fmtMoneyShort, typeBadge, relTime,
      years: computed(() => data.value?.years || []),
      methods: computed(() => data.value?.meta?.methods || []),
      types: computed(() => data.value?.meta?.types || []),
    };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div><h1>创收管理</h1><div class="desc">律师费、其他收入与成本支出统一管理，自动生成月度与维度分析</div></div>
    <div class="actions">
      <select class="select" style="width:110px" v-model="filter.year">
        <option value="">全部年度</option>
        <option v-for="y in years" :key="y" :value="y">{{ y }} 年</option>
      </select>
      <button class="btn" @click="load()">刷新</button>
      <button class="btn" @click="openForm({record_type:'成本支出'})">－ 登记成本</button>
      <button class="btn btn-primary" @click="openForm()">＋ 登记收入</button>
    </div>
  </div>

  <div v-if="loading" class="empty"><div class="spinner"></div></div>
  <template v-else>
    <div class="grid g-4 sec">
      <div class="stat accent"><div class="stat-ico"></div><div class="k">律师费</div>
        <div class="v">¥{{ fmtMoneyShort(s.律师费) }}</div><div class="d">核心业务收入</div></div>
      <div class="stat green"><div class="stat-ico"></div><div class="k">其他收入</div>
        <div class="v">¥{{ fmtMoneyShort(s.其他收入) }}</div><div class="d">咨询、顾问等</div></div>
      <div class="stat red"><div class="stat-ico"></div><div class="k">成本支出</div>
        <div class="v">¥{{ fmtMoneyShort(s.成本支出) }}</div><div class="d">差旅、外包、检索等</div></div>
      <div class="stat blue"><div class="stat-ico"></div><div class="k">净收益</div>
        <div class="v">¥{{ fmtMoneyShort(s.净收益) }}</div>
        <div class="d">总收入 ¥{{ fmtMoneyShort(s.总收入) }} · 待回款 <b class="down">¥{{ fmtMoneyShort(s.未回款金额) }}</b></div></div>
    </div>

    <div class="grid g-main sec">
      <div class="card">
        <div class="card-h"><div><h3>月度趋势</h3><div class="sub">收入与成本对比</div></div>
          <span class="badge badge-accent">{{ monthly.length }} 个月</span></div>
        <div v-if="!monthly.length" class="empty" style="padding:26px"><div class="t">暂无数据</div></div>
        <template v-else>
          <BarChart :data="monthly" :height="150" />
          <div class="row gap-3 wrap tiny dim mt-3">
            <span v-for="m in monthly.slice(-6)" :key="m.ym">{{ m.label }}：收 {{ m.value }} / 支 {{ m.cost }}</span>
          </div>
        </template>
      </div>
      <div class="card">
        <div class="card-h"><h3>收入构成</h3></div>
        <Donut :data="typeDonut" :size="112" :thickness="14"
               :center-text="'¥'+fmtMoneyShort(s.总收入)" center-sub="总收入" />
      </div>
    </div>

    <div class="card sec">
      <div class="card-h"><h3>客户创收排行</h3><span class="sub">按累计收入</span></div>
      <BarChart :data="clientBars" horizontal />
    </div>

    <div class="card">
      <div class="card-h">
        <h3>收支明细</h3>
        <div class="row gap-2">
          <input class="input" style="width:200px;height:28px" placeholder="搜索项目/备注/发票号…" v-model="filter.keyword" />
          <span :class="['chip', !filter.rtype?'on':'']" @click="filter.rtype=''">全部</span>
          <span v-for="t in types" :key="t" :class="['chip', filter.rtype===t?'on':'']"
                @click="filter.rtype = filter.rtype===t ? '' : t">{{ t }}</span>
        </div>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr>
            <th>日期</th><th>类型</th><th>客户</th><th>项目/案件</th>
            <th class="num">金额</th><th>方式</th><th>发票号</th><th>备注</th><th></th>
          </tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id" @contextmenu="rowMenu($event, r)">
              <td class="mono small">{{ r.fee_date }}</td>
              <td><span class="badge" :class="typeBadge(r.record_type)">{{ r.record_type }}</span></td>
              <td>{{ r.client || '—' }}</td>
              <td class="ellip" style="max-width:220px">{{ r.title }}</td>
              <td class="num" :style="{ color: r.record_type==='成本支出' ? 'var(--danger)' : 'var(--success)', fontWeight:600 }">
                {{ r.record_type==='成本支出' ? '-' : '+' }}{{ fmtMoney(r.amount) }}
              </td>
              <td class="small">{{ r.method }}</td>
              <td class="small mono">{{ r.invoice_no || '—' }}</td>
              <td class="small dim ellip" style="max-width:180px">{{ r.note || '—' }}</td>
              <td><button class="btn btn-sm btn-ghost" @click="openForm(r)">编辑</button></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="9"><div class="empty"><div class="t">暂无记录</div>
              <div class="d">点击右上角「登记收入」录入第一笔律师费</div></div></td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>

  <!-- 登记表单 -->
  <div v-if="showForm" class="mask" @click.self="showForm=false">
    <div class="modal">
      <div class="modal-h">
        <h3>{{ editing ? '编辑记录' : '登记收支' }}</h3>
        <button class="tbtn tbtn-close" @click="showForm=false">×</button>
      </div>
      <div class="modal-b fgrid">
        <div class="field"><label>类型</label>
          <select class="select" v-model="form.record_type">
            <option v-for="t in types" :key="t" :value="t">{{ t }}</option>
          </select></div>
        <div class="field"><label>金额（元）*</label>
          <input class="input" type="number" step="0.01" v-model="form.amount" placeholder="0.00" /></div>
        <div class="field"><label>客户</label>
          <input class="input" v-model="form.client" list="revClients" placeholder="选填" />
          <datalist id="revClients"><option v-for="c in (clientBars||[])" :key="c.label" :value="c.label" /></datalist></div>
        <div class="field"><label>日期</label><input class="input" type="date" v-model="form.fee_date" /></div>
        <div class="field"><label>项目 / 案件</label>
          <input class="input" v-model="form.title" placeholder="如：劳动争议·律师费" /></div>
        <div class="field"><label>收付方式</label>
          <select class="select" v-model="form.method">
            <option v-for="m in methods" :key="m" :value="m">{{ m }}</option></select></div>
        <div class="field"><label>发票号</label><input class="input" v-model="form.invoice_no" placeholder="选填" /></div>
        <div class="field"><label>已开票</label>
          <label class="checkbox" style="height:34px">
            <input type="checkbox" v-model="form.invoiced" /><span class="small">是</span></label></div>
        <div class="field full"><label>备注</label>
          <input class="input" v-model="form.note" placeholder="如：首期款 / 差旅报销" /></div>
      </div>
      <div class="modal-f">
        <button class="btn" @click="showForm=false">取消</button>
        <button class="btn btn-primary" @click="save()">{{ editing ? '保存修改' : '确认登记' }}</button>
      </div>
    </div>
  </div>
</div>`,
};

/* ============================ 发票管理 ============================ */
export const InvoiceView = {
  name: 'InvoiceView',
  setup() {
    const rows = ref([]);
    const stats = ref({ count: 0, total_amount: 0, by_month: [] });
    const settings = ref(null);
    const loading = ref(true);
    const fetching = ref(false);
    const keyword = ref('');
    const tab = ref('list');     // list | settings

    async function load() {
      loading.value = true;
      try {
        const d = await api.get('/api/invoices?keyword=' + encodeURIComponent(keyword.value));
        rows.value = d.rows; stats.value = d.stats;
        settings.value = (await api.get('/api/invoices/settings')).settings;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);

    async function fetchMail() {
      fetching.value = true;
      try {
        const r = await api.post('/api/invoices/fetch', {});
        if (r.ok) {
          toastOk(r.saved?.length
            ? `收取完成：新增 ${r.saved.length} 份发票${r.notified ? '，已推送微信' : ''}`
            : `扫描 ${r.scanned} 封邮件，无新增发票`);
          if (r.errors?.length) toastErr(r.errors[0]);
        } else toastErr(r.error || '收取失败');
        load();
      } catch (e) { toastErr(e.message); }
      fetching.value = false;
    }

    function importLocal() {
      const inp = document.createElement('input');
      inp.type = 'file'; inp.multiple = true; inp.accept = '.pdf,.ofd,.jpg,.jpeg,.png,.zip,.xml';
      inp.onchange = async () => {
        const fd = new FormData();
        [...inp.files].forEach((f) => fd.append('files', f));
        const r = await api.upload('/api/invoices/import', fd);
        toastOk(`已导入 ${r.saved.filter((s) => s.ok).length} 份`);
        load();
      };
      inp.click();
    }

    async function saveSettings() {
      try {
        await api.post('/api/invoices/settings', form);
        toastOk('邮箱设置已保存（密码加密存储于本机）');
        load();
      } catch (e) { toastErr(e.message); }
    }

    const form = reactive({});
    watch(settings, (v) => { if (v) Object.assign(form, v); });

    async function openInv(id) {
      const r = await api.post('/api/invoices/open', { id });
      if (!r.ok) toastErr(r.error || '打开失败');
    }
    async function revealInv(id) { await api.post('/api/invoices/reveal', { id }); }
    async function notifyInv(id) {
      const r = await api.post(`/api/invoices/${id}/notify`, {});
      toastOk(r.notified ? '已通过微信推送' : '微信未启用，已保留在本地提醒中心');
    }
    async function removeInv(r) {
      const okd = await confirm({ title: '删除发票', danger: true, okText: '删除',
        message: `确定删除发票「${r.file_name}」？可勾选同时删除本地文件。` });
      if (!okd) return;
      await api.del(`/api/invoices/${r.id}?remove_file=0`);
      toastOk('已从列表移除'); load();
    }

    function invMenu(ev, r) {
      openCtx(ev, [
        { icon: '', label: '打开本地文件', onClick: () => openInv(r.id) },
        { icon: '', label: '打开所在文件夹', onClick: () => revealInv(r.id) },
        { icon: '', label: '下载', onClick: () => window.open(`/api/invoice/file?id=${r.id}&download=1&token=${encodeURIComponent(store.token || '')}`) },
        { icon: '', label: '推送微信提醒', onClick: () => notifyInv(r.id) },
        { sep: true },
        { icon: '', label: '删除记录', danger: true, onClick: () => removeInv(r) },
      ]);
    }

    const monthBars = computed(() => (stats.value.by_month || []).slice(0, 8)
      .map((m) => ({ label: m.month, value: m.amount })).reverse());

    return {
      rows, stats, settings, loading, fetching, keyword, tab, form,
      load, fetchMail, importLocal, saveSettings, openInv, revealInv, invMenu, notifyInv,
      fmtMoney, monthBars,
    };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div>
      <h1>发票管理</h1>
      <div class="desc">邮箱收到新发票后自动下载、按开票日期归档到本地，并通过微信公众号推送告知</div>
    </div>
    <div class="actions">
      <div class="seg">
        <button :class="tab==='list'?'on':''" @click="tab='list'">发票列表</button>
        <button :class="tab==='settings'?'on':''" @click="tab='settings'">邮箱设置</button>
      </div>
      <button class="btn" @click="load()">刷新</button>
      <button class="btn" @click="importLocal()">手工导入</button>
      <button class="btn btn-primary" :disabled="fetching" @click="fetchMail()">
        <span v-if="fetching" class="spinner"></span>{{ fetching ? '收取中…' : '立即收取' }}
      </button>
    </div>
  </div>

  <div v-if="loading" class="empty"><div class="spinner"></div></div>

  <template v-else-if="tab==='list'">
    <div class="grid g-4 sec">
      <div class="stat accent"><div class="stat-ico"></div><div class="k">发票总数</div>
        <div class="v">{{ stats.count }}<small>份</small></div></div>
      <div class="stat green"><div class="stat-ico"></div><div class="k">金额合计</div>
        <div class="v">¥{{ (stats.total_amount||0).toLocaleString() }}</div></div>
      <div class="stat blue"><div class="stat-ico"></div><div class="k">本月归档</div>
        <div class="v">{{ (stats.by_month.find(m=>m.month===new Date().toISOString().slice(0,7))||{}).count || 0 }}<small>份</small></div></div>
      <div class="stat purple"><div class="stat-ico"></div><div class="k">邮箱状态</div>
        <div class="v small" style="padding-top:8px">
          {{ settings?.configured ? '已配置' : '未配置' }}
        </div>
        <div class="d">{{ settings?.last_checked ? '上次收取 ' + settings.last_checked : '尚未收取过' }}</div></div>
    </div>

    <div class="card sec" v-if="monthBars.length">
      <div class="card-h"><h3>按月归档</h3></div>
      <BarChart :data="monthBars" horizontal />
    </div>

    <div class="card">
      <div class="card-h">
        <h3>发票清单</h3>
        <input class="input" style="width:220px;height:28px" placeholder="搜索开票方/文件名…" v-model="keyword" @keyup.enter="load()" />
      </div>
      <div v-if="!rows.length" class="empty">
        <div class="ico">◇</div><div class="t">暂无发票</div>
        <div class="d">配置邮箱后点击「立即收取」，或手工导入已有发票文件</div>
      </div>
      <div class="tbl-wrap" v-else>
        <table class="tbl">
          <thead><tr>
            <th>开票日期</th><th>开票方</th><th class="num">金额</th>
            <th>文件名</th><th>来源</th><th>归档月份</th><th>操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id" @dblclick="openInv(r.id)" @contextmenu="invMenu($event, r)">
              <td class="mono small">{{ r.invoice_date || '—' }}</td>
              <td class="ellip" style="max-width:200px">{{ r.sender || '—' }}</td>
              <td class="num" style="font-weight:600">{{ r.amount ? '¥'+r.amount.toLocaleString() : '—' }}</td>
              <td class="small ellip" style="max-width:260px" :title="r.file_name">{{ r.file_name }}</td>
              <td><span class="badge" :class="r.source==='email'?'badge-primary':'badge-cyan'">
                {{ r.source==='email' ? '邮箱' : '手工' }}</span></td>
              <td class="small mono">{{ r.month_dir }}</td>
              <td class="row gap-1">
                <button class="btn btn-sm" @click="openInv(r.id)">打开</button>
                <button class="btn btn-sm" @click="revealInv(r.id)">定位</button>
                <button class="btn btn-sm" @click="notifyInv(r.id)">推送</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </template>

  <template v-else>
    <div class="card" style="max-width:720px">
      <div class="panel-title">邮箱自动收取（IMAP）</div>
      <p class="small muted mb-4">
        配置后系统会定时连接邮箱，识别标题或附件名含关键词的邮件，把发票附件按开票日期
        归档到 <code class="mono">data/invoices/年月/</code>，并通过微信公众号推送。
        未启用时不发起任何外网请求。
      </p>
      <div class="fgrid" v-if="form">
        <div class="field full">
          <label class="checkbox"><input type="checkbox" v-model="form.enabled" /><span>启用邮箱自动收取</span></label>
        </div>
        <div class="field"><label>IMAP 服务器</label>
          <input class="input" v-model="form.imap_host" placeholder="imap.qq.com" /></div>
        <div class="field"><label>端口</label>
          <input class="input" type="number" v-model="form.imap_port" placeholder="993" /></div>
        <div class="field"><label>邮箱账号</label>
          <input class="input" v-model="form.username" placeholder="your@email.com" /></div>
        <div class="field"><label>授权码 / 密码</label>
          <input class="input" type="password" v-model="form.password" placeholder="留空则不修改已保存的" /></div>
        <div class="field"><label>收取文件夹</label>
          <input class="input" v-model="form.folder" placeholder="INBOX" /></div>
        <div class="field"><label>回溯天数</label>
          <input class="input" type="number" v-model="form.days" /></div>
        <div class="field full"><label>识别关键词（逗号分隔）</label>
          <input class="input" v-model="form.keywords" placeholder="发票,invoice,增值税" /></div>
        <div class="field"><label>轮询间隔（分钟）</label>
          <input class="input" type="number" v-model="form.interval_minutes" /></div>
        <div class="field"><label>仅收取未读</label>
          <label class="checkbox" style="height:34px"><input type="checkbox" v-model="form.only_unseen" /><span class="small">是</span></label></div>
        <div class="field full">
          <label class="checkbox"><input type="checkbox" v-model="form.auto_notify" />
            <span>归档后自动通过微信公众号推送告知</span></label>
        </div>
      </div>
      <div class="row gap-2 mt-4">
        <button class="btn btn-primary" @click="saveSettings()">保存设置</button>
        <button class="btn" @click="fetchMail()" :disabled="fetching">
          {{ fetching ? '收取中…' : '测试收取' }}</button>
        <span class="tiny dim">常见邮箱 IMAP：QQ邮箱 imap.qq.com:993 ｜ 163 imap.163.com:993 ｜ Gmail imap.gmail.com:993</span>
      </div>
    </div>
  </template>
</div>`,
};
