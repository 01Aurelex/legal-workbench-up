/* 首页 · 工作台仪表盘（顶部随时间变化的天空背景：夜晚含流星） */
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue';
import { api, store, fmtSize, fmtMoney, fmtMoneyShort, relTime, dueLabel, fileIcon } from '../core.js';
import { toast, toastErr } from '../ui.js';
import { Sparkline, Donut, BarChart, ProgressRing, PALETTE } from '../charts.js';

/* 时段划分：夜 / 黎明 / 白天 / 黄昏 */
function phaseOf(h) {
  if (h < 5) return 'night';
  if (h < 7) return 'dawn';
  if (h < 17) return 'day';
  if (h < 19) return 'dusk';
  return 'night';
}
const PHASE_TEXT = { night: '夜深了', dawn: '黎明时分', day: '白昼当空', dusk: '华灯初上' };

export default {
  name: 'HomeView',
  components: { Sparkline, Donut, BarChart, ProgressRing },
  setup() {
    const d = ref(null);
    const activity = ref([]);
    const loading = ref(true);
    const customGreeting = ref('');
    const cv = ref(null);

    const hour = ref(new Date().getHours());
    const clock = ref(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    const phase = computed(() => phaseOf(hour.value));
    const phaseText = computed(() => PHASE_TEXT[phase.value]);

    const greet = computed(() => {
      if (customGreeting.value) return customGreeting.value;
      const h = hour.value;
      return h < 6 ? '凌晨好' : h < 11 ? '早上好' : h < 14 ? '中午好'
        : h < 18 ? '下午好' : '晚上好';
    });
    const dateText = new Date().toLocaleDateString('zh-CN',
      { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' });

    /* ---------- 天空动画（星空 + 流星 / 云） ---------- */
    let raf = 0, W = 0, H = 0, stars = [], meteors = [], clouds = [];
    let lastMeteor = 0, tick = 0;

    function resize() {
      const el = cv.value;
      if (!el) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = el.clientWidth; H = el.clientHeight;
      el.width = Math.max(1, Math.round(W * dpr));
      el.height = Math.max(1, Math.round(H * dpr));
      const ctx = el.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      build();
    }

    function build() {
      const n = Math.round((W * H) / 5200);
      stars = Array.from({ length: Math.max(40, Math.min(220, n)) }, () => ({
        x: Math.random() * W,
        y: Math.random() * H * 0.82,
        r: Math.random() * 1.15 + 0.28,
        a: Math.random() * 0.6 + 0.35,
        s: Math.random() * 0.02 + 0.004,
        p: Math.random() * Math.PI * 2,
      }));
      clouds = Array.from({ length: 5 }, (_, i) => ({
        x: Math.random() * W,
        y: H * (0.16 + Math.random() * 0.34),
        r: 26 + Math.random() * 46,
        v: 0.06 + Math.random() * 0.12,
        o: 0.06 + Math.random() * 0.1,
        i,
      }));
    }

    function spawnMeteor() {
      meteors.push({
        x: Math.random() * W * 0.75 + W * 0.12,
        y: Math.random() * H * 0.32,
        len: 70 + Math.random() * 110,
        sp: 4.6 + Math.random() * 4.4,
        life: 1,
      });
    }

    function frame(t) {
      const el = cv.value;
      if (!el) return;
      const ctx = el.getContext('2d');
      ctx.clearRect(0, 0, W, H);
      tick++;

      const nightish = phase.value === 'night' || phase.value === 'dawn' || phase.value === 'dusk';
      const starAlpha = phase.value === 'night' ? 1 : phase.value === 'dusk' ? 0.42 : phase.value === 'dawn' ? 0.3 : 0;

      /* 星空 */
      if (starAlpha > 0) {
        for (const s of stars) {
          s.p += s.s;
          const a = s.a * starAlpha * (0.62 + 0.38 * Math.sin(s.p));
          ctx.beginPath();
          ctx.fillStyle = `rgba(255,255,255,${a.toFixed(3)})`;
          ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      /* 白天云层 */
      if (phase.value === 'day') {
        for (const c of clouds) {
          c.x += c.v;
          if (c.x - c.r > W) c.x = -c.r;
          const g = ctx.createRadialGradient(c.x, c.y, 0, c.x, c.y, c.r);
          g.addColorStop(0, `rgba(255,255,255,${c.o + 0.16})`);
          g.addColorStop(1, 'rgba(255,255,255,0)');
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(c.x, c.y, c.r, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      /* 流星（夜晚与黎明/黄昏偶现） */
      if (nightish) {
        if (t - lastMeteor > 1600 + Math.random() * 3200) { spawnMeteor(); lastMeteor = t; }
        for (let i = meteors.length - 1; i >= 0; i--) {
          const m = meteors[i];
          m.x += m.sp; m.y += m.sp * 0.44; m.life -= 0.008;
          const a = Math.max(0, m.life) * (phase.value === 'night' ? 1 : 0.7);
          const dx = -m.len * 0.92, dy = -m.len * 0.4;
          const g = ctx.createLinearGradient(m.x, m.y, m.x + dx, m.y + dy);
          g.addColorStop(0, `rgba(255,255,255,${(0.95 * a).toFixed(3)})`);
          g.addColorStop(0.25, `rgba(190,220,255,${(0.5 * a).toFixed(3)})`);
          g.addColorStop(1, 'rgba(190,220,255,0)');
          ctx.strokeStyle = g;
          ctx.lineWidth = 1.7;
          ctx.lineCap = 'round';
          ctx.beginPath();
          ctx.moveTo(m.x, m.y);
          ctx.lineTo(m.x + dx, m.y + dy);
          ctx.stroke();
          if (m.life <= 0 || m.x - m.len > W + 60 || m.y - m.len > H + 60) meteors.splice(i, 1);
        }
      }
      raf = requestAnimationFrame(frame);
    }

    function onResize() { resize(); }
    let timer = 0;
    function refreshClock() {
      const now = new Date();
      hour.value = now.getHours();
      clock.value = now.toLocaleTimeString('zh-CN', { hour12: false });
    }

    onMounted(() => {
      load();
      resize();
      requestAnimationFrame(() => { resize(); raf = requestAnimationFrame(frame); });
      // 视图切换动画结束后再校准一次画布尺寸
      setTimeout(resize, 320);
      window.addEventListener('resize', onResize);
      timer = setInterval(refreshClock, 20000);
    });
    onUnmounted(() => {
      cancelAnimationFrame(raf);
      clearInterval(timer);
      window.removeEventListener('resize', onResize);
    });

    async function load() {
      loading.value = true;
      try {
        const [r1, r2] = await Promise.all([api.get('/api/dashboard'), api.get('/api/stats/activity?limit=24')]);
        d.value = r1;
        activity.value = r2.rows;
        customGreeting.value = r1.ui?.greeting || '';
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }

    const ov = computed(() => d.value?.overview || {});
    const cs = computed(() => d.value?.cases || {});

    const trendData = computed(() => (ov.value.active_trend || []).map((t) => t.open + t.add));
    const trendLabels = computed(() => (ov.value.active_trend || []).map((t) => t.date));

    const typeDonut = computed(() => (cs.value.by_type || []).slice(0, 6).map((t, i) => ({
      label: t.key, value: t.count, color: PALETTE[i % PALETTE.length],
    })));

    const stageBars = computed(() => (cs.value.by_stage || []).slice(0, 8).map((t) => ({
      label: t.key, value: t.count,
    })));

    const quick = [
      { icon: '', key: 'cases', label: '新建案件' },
      { icon: '', key: 'clients', label: '新建客户' },
      { icon: '', key: 'vault', label: '新建笔记' },
      { icon: '', key: 'revenue', label: '登记收费' },
    ];

    function go(view) { store.view = view; }

    function openDoc(path) {
      api.post('/api/archive/open', { path }).catch((e) => toastErr(e.message));
    }

    return {
      d, loading, ov, cs, greet, dateText, trendData, trendLabels,
      typeDonut, stageBars, quick, go, openDoc, activity, cv,
      phase, phaseText, clock,
      fmtSize, fmtMoney, fmtMoneyShort, relTime, dueLabel, fileIcon,
    };
  },
  template: `
<div class="view home-view">
  <!-- 随时间变化的天空背景（夜空有流星划过） -->
  <section :class="['sky', 'sky-' + phase]">
    <canvas class="sky-cv" ref="cv"></canvas>
    <div class="sky-orb"></div>
    <div class="sky-ridge"></div>
    <div class="sky-inner">
      <div class="row between wrap" style="gap:12px">
        <div>
          <h1 class="sky-hi">{{ greet }}</h1>
          <div class="sky-sub">{{ dateText }} · 全部数据仅存储于本机</div>
        </div>
        <div class="row gap-2">
          <button class="btn btn-ghost-light" @click="go('cases')">新建案件</button>
          <button class="btn btn-ghost-light" @click="go('revenue')">登记收费</button>
          <button class="btn btn-light" @click="go('vault')">打开档案库</button>
        </div>
      </div>
      <div class="sky-meta">
        <span class="sky-chip">{{ phaseText }}</span>
        <span class="sky-clock">{{ clock }}</span>
      </div>
    </div>
  </section>

  <div class="home-body">
    <div v-if="loading" class="empty"><div class="spinner"></div><div class="t">加载中…</div></div>

    <template v-else>
      <!-- 核心指标 -->
      <div class="grid g-4 sec">
        <div class="stat accent">
          <div class="stat-ico"></div>
          <div class="k">档案总数</div>
          <div class="v">{{ ov.files }}<small>份</small></div>
          <div class="d">本月新增 <b class="up">+{{ ov.new_files_month }}</b> · 近7日打开 {{ ov.opens_week }}</div>
        </div>
        <div class="stat blue">
          <div class="stat-ico"></div>
          <div class="k">在手案件</div>
          <div class="v">{{ cs.ongoing }}<small>件</small></div>
          <div class="d">累计 {{ cs.total }} 件 · 本月 {{ cs.new_month }} 件 · 已结 {{ cs.closed }}</div>
        </div>
        <div class="stat green">
          <div class="stat-ico"></div>
          <div class="k">创收合计</div>
          <div class="v">¥{{ fmtMoneyShort(cs.fee_total) }}</div>
          <div class="d">已回款 ¥{{ fmtMoneyShort(cs.fee_paid) }} · 待回 <b class="down">¥{{ fmtMoneyShort(cs.fee_outstanding) }}</b></div>
        </div>
        <div class="stat purple">
          <div class="stat-ico"></div>
          <div class="k">发票归档</div>
          <div class="v">{{ ov.invoices }}<small>份</small></div>
          <div class="d">邮箱自动收取 · 本地留存</div>
        </div>
      </div>

      <div class="grid g-main sec">
        <!-- 使用统计 -->
        <div class="card">
          <div class="card-h">
            <div><h3>使用趋势</h3><div class="sub">近 14 天档案打开与新增</div></div>
            <span class="badge badge-accent">共 {{ trendData.reduce((a,b)=>a+b,0) }} 次</span>
          </div>
          <Sparkline :data="trendData" :height="62" :labels="trendLabels" />
          <div class="row between tiny dim mt-2">
            <span>{{ trendLabels[0] }}</span><span>{{ trendLabels[trendLabels.length-1] }}</span>
          </div>
          <div class="divider"></div>
          <div class="grid g-3" style="gap:12px">
            <div><div class="tiny dim">笔记/双链</div><div class="num" style="font-size:17px;font-weight:650">{{ ov.notes }} / {{ ov.links }}</div></div>
            <div><div class="tiny dim">生成文书</div><div class="num" style="font-size:17px;font-weight:650">{{ ov.docs }}</div></div>
            <div><div class="tiny dim">客户数</div><div class="num" style="font-size:17px;font-weight:650">{{ ov.clients }}</div></div>
          </div>
        </div>

        <!-- 案件统计 -->
        <div class="card">
          <div class="card-h"><h3>案件类型分布</h3><span class="sub">共 {{ cs.total }} 件</span></div>
          <Donut :data="typeDonut" :size="116" :thickness="14"
                 :center-text="String(cs.total)" center-sub="案件总数" />
          <div class="divider"></div>
          <div class="row gap-2 wrap">
            <span v-for="r in (cs.by_risk||[])" :key="r.key" class="badge"
                  :class="{'badge-danger': r.key==='高', 'badge-warn': r.key==='中', 'badge-success': r.key==='低'}">
              {{ r.key }}风险 {{ r.count }}
            </span>
          </div>
        </div>
      </div>

      <div class="grid g-2 sec">
        <!-- 最近打开 -->
        <div class="card">
          <div class="card-h">
            <div><h3>最近打开</h3><div class="sub">继续未完成的工作</div></div>
            <button class="btn btn-sm btn-ghost" @click="go('vault')">全部 ›</button>
          </div>
          <div v-if="!(d.recent_open||[]).length" class="empty" style="padding:24px">
            <div class="ico">◇</div><div class="t">暂无记录</div>
          </div>
          <div v-else>
            <div v-for="f in d.recent_open" :key="f.rel_path" class="li" @click="openDoc(f.rel_path)">
              <div class="li-ico">{{ fileIcon(f.rel_path) }}</div>
              <div class="li-main">
                <div class="li-t ellip">{{ f.title }}</div>
                <div class="li-s">{{ f.category }} · {{ fmtSize(f.size) }} · 打开 {{ f.open_count }} 次</div>
              </div>
              <span class="tiny dim">{{ relTime(f.last_open) }}</span>
            </div>
          </div>
        </div>

        <!-- 最近添加 -->
        <div class="card">
          <div class="card-h">
            <div><h3>最近添加</h3><div class="sub">最新入库的档案</div></div>
            <button class="btn btn-sm btn-ghost" @click="go('vault')">全部 ›</button>
          </div>
          <div v-if="!(d.recent_add||[]).length" class="empty" style="padding:24px">
            <div class="ico">◇</div><div class="t">暂无记录</div>
          </div>
          <div v-else>
            <div v-for="f in d.recent_add" :key="f.rel_path" class="li" @click="openDoc(f.rel_path)">
              <div class="li-ico">{{ fileIcon(f.rel_path) }}</div>
              <div class="li-main">
                <div class="li-t ellip">{{ f.title }}</div>
                <div class="li-s">{{ f.category }} · {{ fmtSize(f.size) }}</div>
              </div>
              <span class="tiny dim">{{ relTime(f.created) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="grid g-main sec">
        <!-- 到期提醒 -->
        <div class="card">
          <div class="card-h">
            <div><h3>到期提醒</h3><div class="sub">未来 30 天内的办案节点与待办</div></div>
            <button class="btn btn-sm btn-ghost" @click="go('remind')">提醒中心 ›</button>
          </div>
          <div v-if="!(d.due||[]).length" class="empty" style="padding:24px">
            <div class="ico">◇</div><div class="t">近期无到期事项</div>
          </div>
          <div v-else>
            <div v-for="r in d.due" :key="r.id" class="li">
              <div class="li-ico" :style="{ background: r.urgency==='逾期' ? 'var(--danger-lo)' : r.urgency==='临近'||r.urgency==='今天' ? 'var(--warn-lo)' : 'var(--bg-4)', color: r.urgency==='逾期' ? 'var(--danger)' : r.urgency==='临近'||r.urgency==='今天' ? 'var(--warn)' : 'var(--text-2)' }">
                ·
              </div>
              <div class="li-main">
                <div class="li-t ellip">{{ r.title }}</div>
                <div class="li-s">{{ r.due }} · <span :class="dueLabel(r.due).cls">{{ dueLabel(r.due).text || '待办' }}</span></div>
              </div>
              <span class="badge" :class="{'badge-danger': r.level==='高'}">{{ r.kind }}</span>
            </div>
          </div>
        </div>

        <!-- 阶段分布 + 动态 -->
        <div class="card">
          <div class="card-h"><h3>案件阶段</h3></div>
          <BarChart :data="stageBars" horizontal unit=" 件" />
          <div class="divider"></div>
          <div class="card-h" style="margin-bottom:8px"><h3>最近动态</h3></div>
          <div v-if="!activity.length" class="empty" style="padding:16px"><div class="t">暂无动态</div></div>
          <div v-else style="max-height:190px;overflow:auto">
            <div v-for="(a, i) in activity.slice(0, 12)" :key="i" class="row gap-2" style="padding:5px 0;border-bottom:1px solid var(--border)">
              <span class="badge" style="flex:none">{{ a.kind }}</span>
              <span class="grow ellip small" :title="a.title">{{ a.title }}</span>
              <span class="tiny dim" style="flex:none">{{ a.at ? a.at.slice(5,10) : '' }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 快捷入口 -->
      <div class="card">
        <div class="card-h"><h3>快捷操作</h3></div>
        <div class="grid g-4" style="gap:10px">
          <button v-for="q in quick" :key="q.key" class="btn btn-lg" @click="go(q.key)" style="justify-content:flex-start">
            {{ q.label }}
          </button>
          <button class="btn btn-lg" @click="go('invoice')" style="justify-content:flex-start">
            收取发票
          </button>
          <button class="btn btn-lg" @click="go('calendar')" style="justify-content:flex-start">
            日程日历
          </button>
          <button class="btn btn-lg" @click="go('graph')" style="justify-content:flex-start">
            关系图谱
          </button>
          <button class="btn btn-lg" @click="go('settings')" style="justify-content:flex-start">
            系统设置
          </button>
        </div>
      </div>
    </template>
  </div>
</div>`,
};
