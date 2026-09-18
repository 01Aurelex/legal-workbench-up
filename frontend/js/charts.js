/* 纯 SVG 图表组件（零依赖），跟随设计系统配色 */
import { computed } from 'vue';

const PALETTE = ['var(--accent)', 'var(--primary)', 'var(--purple)', 'var(--success)',
  'var(--cyan)', 'var(--warn)', 'var(--danger)', '#7E8EAD'];

/** 迷你折线/面积图 */
export const Sparkline = {
  props: {
    data: { type: Array, default: () => [] },
    height: { type: Number, default: 40 },
    color: { type: String, default: 'var(--accent)' },
    area: { type: Boolean, default: true },
    labels: { type: Array, default: () => [] },
  },
  setup(props) {
    const W = 100;
    const pts = computed(() => {
      const d = props.data.map((v) => Number(v) || 0);
      if (!d.length) return [];
      const max = Math.max(...d, 1);
      const min = Math.min(...d, 0);
      const span = max - min || 1;
      return d.map((v, i) => ({
        x: d.length === 1 ? W / 2 : (i / (d.length - 1)) * W,
        y: props.height - 3 - ((v - min) / span) * (props.height - 8),
        v,
      }));
    });
    const line = computed(() => pts.value.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' '));
    const areaPath = computed(() => {
      if (!pts.value.length) return '';
      return `M0,${props.height} L${pts.value[0].x.toFixed(2)},${pts.value[0].y.toFixed(2)} ` +
        pts.value.slice(1).map((p) => `L${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') +
        ` L${W},${props.height} Z`;
    });
    const gid = 'sg' + Math.random().toString(36).slice(2, 8);
    return { pts, line, areaPath, W, gid };
  },
  template: `
    <svg :viewBox="\`0 0 \${W} \${height}\`" preserveAspectRatio="none"
         :style="{ width:'100%', height: height + 'px', display:'block' }">
      <defs>
        <linearGradient :id="gid" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" :stop-color="color" stop-opacity=".28" />
          <stop offset="100%" :stop-color="color" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path v-if="area" :d="areaPath" :fill="\`url(#\${gid})\`" />
      <polyline :points="line" fill="none" :stroke="color" stroke-width="1.6"
                stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
      <circle v-for="(p, i) in pts" :key="i" :cx="p.x" :cy="p.y" r="1.6" :fill="color">
        <title v-if="labels[i]">{{ labels[i] }}：{{ p.v }}</title>
      </circle>
    </svg>`,
};

/** 柱状图 */
export const BarChart = {
  props: {
    data: { type: Array, default: () => [] },   // [{label, value, color?}]
    height: { type: Number, default: 180 },
    horizontal: { type: Boolean, default: false },
    unit: { type: String, default: '' },
  },
  setup(props) {
    const max = computed(() => Math.max(...props.data.map((d) => Number(d.value) || 0), 1));
    const bars = computed(() => props.data.map((d, i) => ({
      label: d.label,
      value: Number(d.value) || 0,
      color: d.color || PALETTE[i % PALETTE.length],
      pct: ((Number(d.value) || 0) / max.value) * 100,
    })));
    return { bars, max };
  },
  template: `
    <div v-if="horizontal" class="col" style="gap:7px">
      <div v-for="(b, i) in bars" :key="i" class="chart-row" style="padding:0">
        <div class="cr-name ellip" :title="b.label">{{ b.label }}</div>
        <div class="cr-bar"><i :style="{ width: (b.pct || 1) + '%', background: b.color }"></i></div>
        <div class="cr-val">{{ b.value }}{{ unit }}</div>
      </div>
      <div v-if="!bars.length" class="empty" style="padding:16px"><div class="t">暂无数据</div></div>
    </div>
    <div v-else style="display:flex;align-items:flex-end;gap:6px" :style="{ height: height + 'px' }">
      <div v-for="(b, i) in bars" :key="i" style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;height:100%;gap:5px">
        <div :title="\`\${b.label}: \${b.value}\${unit}\`"
             :style="{ height: Math.max(b.pct, 2) + '%', background: b.color, borderRadius:'4px 4px 0 0', transition:'height .5s cubic-bezier(.16,1,.3,1)' }"></div>
      </div>
      <div v-if="!bars.length" class="empty" style="width:100%"><div class="t">暂无数据</div></div>
    </div>`,
};

/** 环形图 */
export const Donut = {
  props: {
    data: { type: Array, default: () => [] },   // [{label, value}]
    size: { type: Number, default: 128 },
    thickness: { type: Number, default: 15 },
    centerText: { type: String, default: '' },
    centerSub: { type: String, default: '' },
  },
  setup(props) {
    const total = computed(() => props.data.reduce((s, d) => s + (Number(d.value) || 0), 0));
    const r = computed(() => (props.size - props.thickness) / 2);
    const c = computed(() => 2 * Math.PI * r.value);
    const segs = computed(() => {
      let acc = 0;
      const t = total.value || 1;
      return props.data.map((d, i) => {
        const v = Number(d.value) || 0;
        const seg = {
          label: d.label, value: v,
          color: d.color || PALETTE[i % PALETTE.length],
          dash: (v / t) * c.value,
          offset: -acc,
        };
        acc += (v / t) * c.value;
        return seg;
      });
    });
    return { segs, total, r, c };
  },
  template: `
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <div style="position:relative;flex:none" :style="{ width: size+'px', height: size+'px' }">
        <svg :width="size" :height="size" :viewBox="\`0 0 \${size} \${size}\`" style="transform:rotate(-90deg)">
          <circle :cx="size/2" :cy="size/2" :r="r" fill="none" stroke="var(--bg-3)" :stroke-width="thickness" />
          <circle v-for="(s, i) in segs" :key="i"
                  :cx="size/2" :cy="size/2" :r="r" fill="none"
                  :stroke="s.color" :stroke-width="thickness"
                  :stroke-dasharray="\`\${s.dash} \${c - s.dash}\`"
                  :stroke-dashoffset="s.offset" stroke-linecap="butt">
            <title>{{ s.label }}：{{ s.value }}</title>
          </circle>
        </svg>
        <div style="position:absolute;inset:0;display:grid;place-content:center;text-align:center">
          <div style="font-size:19px;font-weight:680;letter-spacing:-.02em">{{ centerText || total }}</div>
          <div style="font-size:10.5px;color:var(--text-3)">{{ centerSub }}</div>
        </div>
      </div>
      <div class="col" style="gap:4px;flex:1;min-width:120px">
        <div v-for="(s, i) in segs" :key="i" class="row" style="gap:7px;font-size:12px">
          <span class="dot" :style="{ width:'8px',height:'8px',borderRadius:'50%',background:s.color,flex:'none' }"></span>
          <span class="grow ellip" style="color:var(--text-2)">{{ s.label }}</span>
          <b class="num" style="font-weight:600">{{ s.value }}</b>
        </div>
        <div v-if="!segs.length" class="dim tiny">暂无数据</div>
      </div>
    </div>`,
};

/** 进度环 */
export const ProgressRing = {
  props: {
    value: { type: Number, default: 0 },
    size: { type: Number, default: 46 },
    thickness: { type: Number, default: 4 },
    color: { type: String, default: 'var(--accent)' },
  },
  setup(props) {
    const r = computed(() => (props.size - props.thickness) / 2);
    const c = computed(() => 2 * Math.PI * r.value);
    const dash = computed(() => (Math.min(Math.max(props.value, 0), 100) / 100) * c.value);
    return { r, c, dash };
  },
  template: `
    <div class="progress-ring" :style="{ width: size+'px', height: size+'px' }">
      <svg :width="size" :height="size" style="transform:rotate(-90deg)">
        <circle :cx="size/2" :cy="size/2" :r="r" fill="none" stroke="var(--bg-3)" :stroke-width="thickness" />
        <circle :cx="size/2" :cy="size/2" :r="r" fill="none" :stroke="color" :stroke-width="thickness"
                :stroke-dasharray="\`\${dash} \${c - dash}\`" stroke-linecap="round"
                style="transition:stroke-dasharray .6s cubic-bezier(.16,1,.3,1)" />
      </svg>
      <div class="pr-t">{{ Math.round(value) }}%</div>
    </div>`,
};

/** 横向堆叠/对比条 */
export const CompareBars = {
  props: { data: { type: Array, default: () => [] } },  // [{label, items:[{name,value,color}]}]
  setup(props) {
    const totals = computed(() => props.data.map((d) =>
      d.items.reduce((s, i) => s + (Number(i.value) || 0), 0)));
    return { totals };
  },
  template: `
    <div class="col" style="gap:9px">
      <div v-for="(row, i) in data" :key="i">
        <div class="row between tiny mb-2">
          <span style="color:var(--text-2)">{{ row.label }}</span>
          <b class="num">{{ totals[i] }}</b>
        </div>
        <div style="display:flex;height:8px;border-radius:999px;overflow:hidden;background:var(--bg-3)">
          <div v-for="(it, j) in row.items" :key="j"
               :style="{ width: (totals[i] ? it.value/totals[i]*100 : 0)+'%', background: it.color }"
               :title="it.name + '：' + it.value"></div>
        </div>
      </div>
    </div>`,
};

export { PALETTE };
