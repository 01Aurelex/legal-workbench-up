/* 提醒中心 + 日程日历 */
import { ref, reactive, computed, onMounted } from 'vue';
import { api, store, today, dueLabel, daysLeft, relTime, loadAck, saveAck, ackSig } from '../core.js';
import { toast, toastOk, toastErr, modal, confirm, prompt } from '../ui.js';

/* ============================ 提醒中心 ============================ */
export default {
  name: 'RemindView',
  setup() {
    const reminders = ref([]);
    const ackedItems = ref([]);
    const outbox = ref([]);
    const loading = ref(true);
    const tab = ref('due');
    const showAcked = ref(false);

    /* 后端每次拉取都会重建「期限」提醒（行 id 会变），因此本地按签名记忆已知悉项 */
    const acked = ref([]);
    const ackSet = computed(() => new Set(acked.value));

    async function load() {
      loading.value = true;
      try {
        const [a, b] = await Promise.all([api.get('/api/reminders'), api.get('/api/outbox')]);
        acked.value = [...loadAck()];
        const all = a.reminders || [];
        reminders.value = all.filter((r) => !ackSet.value.has(ackSig(r)));
        ackedItems.value = all.filter((r) => ackSet.value.has(ackSig(r)));
        outbox.value = b.rows;
        store.badge = reminders.value.filter((r) => {
          const n = daysLeft(r.due);
          return n !== null && n <= 3;
        }).length;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);

    /** 已知悉：本地记忆签名并从列表移除（后端重建不会使其复活） */
    async function done(r) {
      try { await api.post('/api/reminder/done', { id: r.id }); } catch { /* id 可能已重建，忽略 */ }
      if (!acked.value.includes(ackSig(r))) acked.value = [...acked.value, ackSig(r)];
      saveAck(new Set(acked.value));
      toastOk('已标记为已知悉');
      await load();
    }

    /** 恢复：把已知悉的提醒放回列表 */
    function restore(r) {
      acked.value = acked.value.filter((s) => s !== ackSig(r));
      saveAck(new Set(acked.value));
      toast('已恢复该提醒');
      load();
    }

    async function sendMsg(id) {
      const r = await api.post('/api/wechat/send', { id });
      toastOk(r.ok ? '已发送' : (r.error || '发送失败'));
      load();
    }

    const grouped = computed(() => {
      const g = { 逾期: [], 三天内: [], 本月: [], 以后: [] };
      for (const r of reminders.value) {
        const n = daysLeft(r.due);
        if (n === null) g['以后'].push(r);
        else if (n < 0) g['逾期'].push(r);
        else if (n <= 3) g['三天内'].push(r);
        else if (n <= 30) g['本月'].push(r);
        else g['以后'].push(r);
      }
      return g;
    });

    return {
      reminders, ackedItems, outbox, loading, tab, grouped, showAcked,
      done, restore, sendMsg, load, dueLabel, daysLeft, relTime,
    };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div><h1>提醒中心</h1><div class="desc">办案期限自动倒排、文档外部改动比对、系统提示</div></div>
    <div class="actions">
      <div class="seg">
        <button :class="tab==='due'?'on':''" @click="tab='due'">期限提醒</button>
        <button :class="tab==='outbox'?'on':''" @click="tab='outbox'">微信队列</button>
        <button :class="tab==='sys'?'on':''" @click="tab='sys'">系统提示</button>
      </div>
      <button class="btn" @click="load()">刷新</button>
    </div>
  </div>

  <div v-if="loading" class="empty"><div class="spinner"></div></div>

  <template v-else-if="tab==='due'">
    <div v-if="!reminders.length && !ackedItems.length" class="empty">
      <div class="ico">◇</div><div class="t">暂无待处理提醒</div>
      <div class="d">系统会在案件锚点日期确定后自动倒排法定期限并生成提醒</div>
    </div>
    <div v-else-if="!reminders.length" class="empty">
      <div class="ico">◇</div><div class="t">提醒均已处理</div>
      <div class="d">当前没有待处理的期限提醒</div>
    </div>
    <template v-for="(list, name) in grouped" :key="name">
      <div class="sec" v-if="list.length">
        <div class="sec-title">
          <span :class="['badge', name==='逾期'?'badge-danger':name==='三天内'?'badge-warn':'badge-primary']">
            {{ name }} {{ list.length }}</span>
        </div>
        <div class="card" style="padding:0">
          <div v-for="r in list" :key="r.id" class="li">
            <div class="li-ico" :style="{ background: r.level==='高' ? 'var(--danger-lo)' : 'var(--bg-4)', color: r.level==='高' ? 'var(--danger)' : 'var(--text-2)' }">
              ·
            </div>
            <div class="li-main">
              <div class="li-t">{{ r.title }}</div>
              <div class="li-s clamp2">{{ r.detail }}</div>
            </div>
            <div class="col" style="align-items:flex-end;gap:3px">
              <span class="badge" :class="dueLabel(r.due).cls">{{ r.due }}</span>
              <span class="tiny dim">{{ dueLabel(r.due).text }}</span>
            </div>
            <button class="btn btn-sm" @click="done(r)">已知悉</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 已忽略（已知悉） -->
    <div class="sec" v-if="ackedItems.length">
      <div class="sec-title row gap-2">
        <span class="badge">已知悉 {{ ackedItems.length }}</span>
        <button class="btn btn-sm btn-ghost" @click="showAcked = !showAcked">
          {{ showAcked ? '隐藏' : '显示' }}</button>
      </div>
      <div class="card" style="padding:0" v-if="showAcked">
        <div v-for="r in ackedItems" :key="'a'+r.id" class="li" style="opacity:.62">
          <div class="li-ico">·</div>
          <div class="li-main">
            <div class="li-t">{{ r.title }}</div>
            <div class="li-s clamp2">{{ r.detail }}</div>
          </div>
          <div class="col" style="align-items:flex-end;gap:3px">
            <span class="badge">{{ r.due }}</span>
            <span class="tiny dim">已处理</span>
          </div>
          <button class="btn btn-sm" @click="restore(r)">恢复</button>
        </div>
      </div>
    </div>
  </template>

  <template v-else-if="tab==='outbox'">
    <div class="card">
      <div class="card-h"><h3>待外发消息队列</h3>
        <span class="sub">启用微信后，到期提醒自动入队并可推送</span></div>
      <div v-if="!outbox.length" class="empty" style="padding:24px">
        <div class="t">队列为空</div><div class="d">在「设置 → 微信公众号提醒」中配置后，到期提醒会自动进入队列</div>
      </div>
      <div v-for="r in outbox" :key="r.id" class="li">
        <div class="li-ico">·</div>
        <div class="li-main">
          <div class="li-t ellip">{{ r.content }}</div>
          <div class="li-s">{{ r.channel }} · {{ r.status }} · {{ r.created }}</div>
        </div>
        <span class="badge" :class="r.status==='已发送'?'badge-success':r.status==='失败'?'badge-danger':'badge-warn'">
          {{ r.status }}</span>
        <button v-if="r.status==='待发送'" class="btn btn-sm" @click="sendMsg(r.id)">立即发送</button>
      </div>
    </div>
  </template>

  <template v-else>
    <div class="grid g-2">
      <div class="card">
        <div class="card-h"><h3>系统提示</h3></div>
        <div class="tiny dim" style="line-height:1.9">
          · 案件期限由流程引擎按《民事诉讼法》等现行规定自动倒排；<br>
          · 文档外部改动会与档案总表哈希比对，确认后才同步；<br>
          · 全部数据仅保存在程序目录 data/ 下，零云端上传。
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h3>数据安全</h3></div>
        <div class="small muted" style="line-height:1.9">
          · 全部数据仅保存在程序目录 data/ 下，零云端上传；<br>
          · 服务仅监听 127.0.0.1，访问需随机令牌；<br>
          · 飞书 / 微信 / 邮箱密钥经加密后仅存本机。
        </div>
      </div>
    </div>
  </template>
</div>`,
};

/* ============================ 日程日历 ============================ */
export const CalendarView = {
  name: 'CalendarView',
  setup() {
    const cur = ref(new Date());
    const reminders = ref([]);
    const tasks = ref([]);
    const loading = ref(true);
    const showAdd = ref(false);
    const form = reactive({ title: '', due: today(), kind: '待办', level: '普通', detail: '', remind: '', email: '' });

    async function load() {
      loading.value = true;
      try {
        const [a, b] = await Promise.all([api.get('/api/reminders'), api.get('/api/tasks')]);
        reminders.value = a.reminders; tasks.value = b.rows;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);

    const year = computed(() => cur.value.getFullYear());
    const month = computed(() => cur.value.getMonth() + 1);

    const cells = computed(() => {
      const y = year.value, m = month.value;
      const first = new Date(y, m - 1, 1);
      const start = first.getDay();
      const days = new Date(y, m, 0).getDate();
      const prevDays = new Date(y, m - 1, 0).getDate();
      const out = [];
      for (let i = start - 1; i >= 0; i--) {
        out.push({ d: prevDays - i, other: true, key: `${y}-${String(m - 1).padStart(2, '0')}-${prevDays - i}`, events: [] });
      }
      const t = today();
      for (let d = 1; d <= days; d++) {
        const key = `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const ev = [
          ...reminders.value.filter((r) => r.due === key).map((r) => ({ kind: r.kind, title: r.title, id: r.id, type: 'reminder' })),
          ...tasks.value.filter((x) => x.due === key).map((x) => ({ kind: x.kind, title: x.title, id: x.id, type: 'task' })),
        ];
        out.push({ d, other: false, key, today: key === t, events: ev });
      }
      while (out.length % 7 !== 0) {
        const n = out.length - start - days + 1;
        out.push({ d: n, other: true, key: '', events: [] });
      }
      return out;
    });

    function prev() { cur.value = new Date(year.value, month.value - 2, 1); }
    function next() { cur.value = new Date(year.value, month.value, 1); }
    function goToday() { cur.value = new Date(); }

    const upcoming = computed(() => {
      const t = today();
      return [
        ...reminders.value.filter((r) => r.due >= t).map((r) => ({ ...r, _t: '期限' })),
        ...tasks.value.map((x) => ({ ...x, _t: '待办' })),
      ].sort((a, b) => (a.due || '').localeCompare(b.due || '')).slice(0, 14);
    });

    async function addTask() {
      if (!form.title.trim()) return toastErr('请填写事项');
      await api.post('/api/tasks', { ...form });
      toastOk('已添加');
      form.title = ''; form.detail = ''; form.remind = ''; form.email = '';
      showAdd.value = false; load();
    }
    async function toggleTask(t) {
      await api.patch('/api/tasks/' + t.id, { done: 1 });
      load();
    }
    async function delTask(t) {
      await api.del('/api/tasks/' + t.id);
      load();
    }

    return {
      cur, year, month, cells, loading, prev, next, goToday, upcoming,
      showAdd, form, addTask, toggleTask, delTask, load, today, dueLabel, daysLeft,
    };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div><h1>日程日历</h1><div class="desc">办案期限与自定义待办同屏展示，支持按月浏览与快速登记</div></div>
    <div class="actions">
      <button class="btn" @click="prev()">‹ 上月</button>
      <button class="btn" @click="goToday()">今天</button>
      <button class="btn" @click="next()">下月 ›</button>
      <button class="btn btn-primary" @click="showAdd=true">＋ 新增待办</button>
    </div>
  </div>

  <div class="grid g-main">
    <div class="card">
      <div class="card-h">
        <h3>{{ year }} 年 {{ month }} 月</h3>
        <div class="row gap-2">
          <span class="badge badge-danger">期限</span>
          <span class="badge badge-primary">待办</span>
        </div>
      </div>
      <div class="cal-head">
        <div v-for="d in ['日','一','二','三','四','五','六']" :key="d">{{ d }}</div>
      </div>
      <div class="cal-grid">
        <div v-for="(c, i) in cells" :key="i" :class="['cal-cell', c.other?'other':'', c.today?'today':'']">
          <div class="cal-day">{{ c.d }}</div>
          <div v-for="(e, j) in c.events.slice(0, 3)" :key="j" :class="['cal-ev', e.kind]"
               :title="e.title">{{ e.title }}</div>
          <div v-if="c.events.length > 3" class="tiny dim">+{{ c.events.length - 3 }}</div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h3>即将到来</h3><button class="btn btn-sm btn-ghost" @click="load()">刷新</button></div>
      <div v-if="!upcoming.length" class="empty" style="padding:24px"><div class="t">暂无安排</div></div>
      <div v-for="(u, i) in upcoming" :key="i" class="li">
        <div class="li-ico">·</div>
        <div class="li-main">
          <div class="li-t ellip">{{ u.title }}</div>
          <div class="li-s">{{ u.due }} · {{ u.kind }} · <span :class="dueLabel(u.due).cls">{{ dueLabel(u.due).text }}</span></div>
        </div>
        <button v-if="u._t==='待办'" class="btn btn-sm" @click="toggleTask(u)">完成</button>
      </div>
    </div>
  </div>

  <div v-if="showAdd" class="mask" @click.self="showAdd=false">
    <div class="modal">
      <div class="modal-h"><h3>新增待办</h3><button class="tbtn tbtn-close" @click="showAdd=false">×</button></div>
      <div class="modal-b fgrid">
        <div class="field full"><label>事项 *</label><input class="input" v-model="form.title" placeholder="如：与当事人核对证据原件" /></div>
        <div class="field"><label>日期</label><input class="input" type="date" v-model="form.due" /></div>
        <div class="field"><label>类型</label>
          <select class="select" v-model="form.kind">
            <option>待办</option><option>庭审</option><option>面谈</option>
            <option>递交材料</option><option>会议</option><option>其他</option></select></div>
        <div class="field"><label>优先级</label>
          <select class="select" v-model="form.level"><option>普通</option><option>高</option><option>低</option></select></div>
        <div class="field"><label>提醒方式</label>
          <select class="select" v-model="form.remind">
            <option value="">不提醒</option>
            <option value="email">邮件提醒</option>
            <option value="wechat">微信提醒</option>
            <option value="both">邮件 + 微信</option>
          </select></div>
        <div class="field" v-if="form.remind==='email' || form.remind==='both'"><label>提醒邮箱</label>
          <input class="input" v-model="form.email" placeholder="留空用设置中的默认收件人" /></div>
        <div class="field full"><label>说明</label><input class="input" v-model="form.detail" /></div>
      </div>
      <div class="modal-f">
        <button class="btn" @click="showAdd=false">取消</button>
        <button class="btn btn-primary" @click="addTask()">添加</button>
      </div>
    </div>
  </div>
</div>`,
};
