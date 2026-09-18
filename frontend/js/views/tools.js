/* 计时工时 */
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue';
import { api, store, today, relTime } from '../core.js';
import { toast, toastOk, toastErr, confirm } from '../ui.js';
import { BarChart } from '../charts.js';

/* ============================ 计时工时 ============================ */
export default {
  name: 'TimerView',
  components: { BarChart },
  setup() {
    const rows = ref([]);
    const cases = ref([]);
    const loading = ref(true);
    const running = ref(false);
    const seconds = ref(0);
    const timer = ref(null);
    const form = reactive({ title: '', case_path: '', rate: '', note: '' });

    async function load() {
      loading.value = true;
      try {
        const [a, b] = await Promise.all([api.get('/api/timer'), api.get('/api/cases')]);
        rows.value = a.rows; cases.value = b.cases;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);

    function start() {
      if (running.value) return;
      if (!form.title.trim()) return toastErr('请先填写工作事项');
      running.value = true; seconds.value = 0;
      timer.value = setInterval(() => seconds.value++, 1000);
    }
    async function stop(save = true) {
      if (!running.value) return;
      clearInterval(timer.value);
      running.value = false;
      if (save && seconds.value > 0) {
        await api.post('/api/timer', {
          case_path: form.case_path, title: form.title,
          started: new Date(Date.now() - seconds.value * 1000).toISOString().slice(0, 19).replace('T', ' '),
          ended: new Date().toISOString().slice(0, 19).replace('T', ' '),
          seconds: seconds.value, rate: Number(form.rate) || 0, note: form.note, billable: 1,
        });
        toastOk(`已记录 ${fmtDur(seconds.value)}`);
      }
      seconds.value = 0;
      load();
    }
    async function discard() { await stop(false); }

    async function remove(r) {
      await api.del('/api/timer/' + r.id);
      load();
    }

    function fmtDur(s) {
      s = Number(s) || 0;
      const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
    }
    function display() { return fmtDur(seconds.value); }

    const total = computed(() => rows.value.reduce((s, r) => s + (r.seconds || 0), 0));
    const billable = computed(() => rows.value.filter((r) => r.billable)
      .reduce((s, r) => s + (r.seconds || 0) * (Number(r.rate) || 0) / 3600, 0));

    const byCase = computed(() => {
      const m = {};
      rows.value.forEach((r) => {
        const k = r.case_path ? r.case_path.split('/').pop().replace('.md', '') : '未关联案件';
        m[k] = (m[k] || 0) + (r.seconds || 0);
      });
      return Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, 8)
        .map(([k, v]) => ({ label: k, value: +(v / 3600).toFixed(1) }));
    });

    onBeforeUnmount(() => clearInterval(timer.value));

    return { rows, cases, loading, running, form, start, stop, discard, remove, display, total, billable, byCase, fmtDur, relTime };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div><h1>计时工时</h1><div class="desc">按案件记录可计费工时，为计时收费与工作量分析提供依据</div></div>
    <div class="actions"><button class="btn" @click="load()">刷新</button></div>
  </div>

  <div class="grid g-main sec">
    <div class="card">
      <div class="card-h"><h3>计时器</h3>
        <span :class="['badge', running ? 'badge-success badge-dot' : '']">{{ running ? '计时中' : '已停止' }}</span></div>
      <div style="font-size:52px;font-weight:700;font-family:var(--font-mono);letter-spacing:-.02em;text-align:center;padding:16px 0">
        {{ display() }}
      </div>
      <div class="fgrid">
        <div class="field full"><label>工作事项</label>
          <input class="input" v-model="form.title" placeholder="如：起草起诉状 / 电话沟通当事人" :disabled="running" /></div>
        <div class="field"><label>关联案件</label>
          <select class="select" v-model="form.case_path" :disabled="running">
            <option value="">— 不关联 —</option>
            <option v-for="c in cases" :key="c.rel_path" :value="c.rel_path">{{ c.client }}·{{ c.cause }}</option>
          </select></div>
        <div class="field"><label>小时费率（元）</label>
          <input class="input" type="number" v-model="form.rate" placeholder="选填" :disabled="running" /></div>
      </div>
      <div class="row gap-2 mt-4">
        <button class="btn btn-primary btn-lg grow" v-if="!running" @click="start()">开始计时</button>
        <template v-else>
          <button class="btn btn-lg grow" @click="stop(true)">停止并记录</button>
          <button class="btn btn-lg btn-danger" @click="discard()">放弃</button>
        </template>
      </div>
    </div>

    <div class="col-4">
      <div class="card">
        <div class="card-h"><h3>工时统计</h3></div>
        <div class="row gap-4">
          <div><div class="tiny dim">累计工时</div>
            <div style="font-size:24px;font-weight:680">{{ (total/3600).toFixed(1) }}<small style="font-size:13px"> h</small></div></div>
          <div><div class="tiny dim">可计费金额</div>
            <div style="font-size:24px;font-weight:680;color:var(--success)">¥{{ billable.toLocaleString(undefined,{maximumFractionDigits:0}) }}</div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h3>案件工时分布</h3><span class="sub">小时</span></div>
        <BarChart :data="byCase" horizontal unit="h" />
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-h"><h3>工时记录</h3><span class="sub">{{ rows.length }} 条</span></div>
    <div v-if="!rows.length" class="empty" style="padding:24px"><div class="t">暂无记录</div></div>
    <div class="tbl-wrap" v-else>
      <table class="tbl">
        <thead><tr><th>开始时间</th><th>事项</th><th>关联案件</th><th class="num">时长</th>
          <th class="num">费率</th><th class="num">金额</th><th></th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td class="small mono">{{ r.started }}</td>
            <td>{{ r.title }}</td>
            <td class="small dim">{{ r.case_path ? r.case_path.split('/').pop().replace('.md','') : '—' }}</td>
            <td class="num mono">{{ fmtDur(r.seconds) }}</td>
            <td class="num small">{{ r.rate ? '¥'+r.rate+'/h' : '—' }}</td>
            <td class="num">¥{{ r.rate ? (r.seconds/3600*r.rate).toFixed(0) : '—' }}</td>
            <td><button class="btn btn-sm btn-ghost" @click="remove(r)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</div>`,
};
