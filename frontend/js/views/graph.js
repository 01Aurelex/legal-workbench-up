/* 关系图谱：稳定力导向布局 + 画布平移/缩放 + 节点拖拽 */
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { api, store } from '../core.js';
import { toast, toastErr } from '../ui.js';

const GROUP_META = {
  client: { name: '客户', color: '#A6C5D6', r: 9 },
  case: { name: '案件', color: '#C6B38A', r: 11 },
  cause: { name: '案由', color: '#A8A0C8', r: 8 },
  material: { name: '材料', color: '#D9A9BE', r: 6 },
  doc: { name: '文书', color: '#8FB69C', r: 6 },
  note: { name: '笔记', color: '#8A97A3', r: 6 },
  law: { name: '法条', color: '#D2AE6E', r: 7 },
};

export default {
  name: 'GraphView',
  setup() {
    const canvas = ref(null);
    const wrap = ref(null);
    const loading = ref(true);
    const stats = reactive({ nodes: 0, edges: 0 });
    const search = ref('');
    const visible = reactive({});   // group -> bool
    const tip = reactive({ show: false, x: 0, y: 0, title: '', sub: '' });
    const selectedId = ref(null);

    Object.keys(GROUP_META).forEach((k) => (visible[k] = true));

    let ctx = null, W = 0, H = 0, dpr = 1;
    let nodes = [], edges = [], byId = new Map();
    let raf = 0;
    let alpha = 1;
    const cam = { x: 0, y: 0, scale: 1 };
    let dragging = null;       // {node, offsetX, offsetY}
    let panning = null;        // {sx, sy, camx, camy}
    let hovered = null;
    let moved = false;

    /* ------------ 布局：确定性初始 + 衰减力导向 ------------ */
    function seedLayout(list) {
      // 按类型分簇的确定性初始布局，避免随机导致的每次重排跳动
      const groups = [...new Set(list.map((n) => n.group))];
      list.forEach((n, i) => {
        const gi = groups.indexOf(n.group);
        const ang = (gi / groups.length) * Math.PI * 2;
        const cx = Math.cos(ang) * 190;
        const cy = Math.sin(ang) * 190;
        const inAng = (i / Math.max(list.length, 1)) * Math.PI * 2 * 7;
        const rad = 30 + (i % 9) * 17;
        n.x = cx + Math.cos(inAng) * rad;
        n.y = cy + Math.sin(inAng) * rad;
        n.vx = 0; n.vy = 0;
        n.mass = 1;
      });
    }

    function tick() {
      alpha *= 0.985;                 // 逐步收敛，避免长时间抖动
      const a = Math.max(alpha, 0.02);
      const n = nodes.length;

      // 斥力（O(n²)，本地档案量级足够快）
      for (let i = 0; i < n; i++) {
        const p = nodes[i];
        for (let j = i + 1; j < n; j++) {
          const q = nodes[j];
          let dx = q.x - p.x, dy = q.y - p.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { d2 = 1; dx = (Math.random() - .5); dy = (Math.random() - .5); }
          if (d2 > 360000) continue;             // 超过 600px 不再计算
          const d = Math.sqrt(d2);
          const f = (2600 * a) / d2;
          const fx = (dx / d) * f, fy = (dy / d) * f;
          p.vx -= fx / p.mass; p.vy -= fy / p.mass;
          q.vx += fx / q.mass; q.vy += fy / q.mass;
        }
      }

      // 引力（弹簧）
      for (const e of edges) {
        const p = byId.get(e.from), q = byId.get(e.to);
        if (!p || !q) continue;
        const dx = q.x - p.x, dy = q.y - p.y;
        const d = Math.hypot(dx, dy) || 1;
        const target = 118;
        const f = (d - target) * 0.012 * a;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        p.vx += fx / p.mass; p.vy += fy / p.mass;
        q.vx -= fx / q.mass; q.vy -= fy / q.mass;
      }

      // 向心力 + 阻尼积分
      for (const p of nodes) {
        if (p === dragging?.node) { p.vx = 0; p.vy = 0; continue; }
        p.vx -= p.x * 0.0016 * a;
        p.vy -= p.y * 0.0016 * a;
        p.vx *= 0.82; p.vy *= 0.82;
        const sp = Math.hypot(p.vx, p.vy);
        const MAX = 14;
        if (sp > MAX) { p.vx = (p.vx / sp) * MAX; p.vy = (p.vy / sp) * MAX; }
        p.x += p.vx; p.y += p.vy;
      }
    }

    /* ------------ 绘制 ------------ */
    const toScreen = (wx, wy) => ({
      x: (wx - cam.x) * cam.scale + W / 2,
      y: (wy - cam.y) * cam.scale + H / 2,
    });
    const toWorld = (sx, sy) => ({
      x: (sx - W / 2) / cam.scale + cam.x,
      y: (sy - H / 2) / cam.scale + cam.y,
    });

    function draw() {
      if (!ctx || !canvas.value) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);

      // 网格背景
      const grid = 40 * cam.scale;
      if (grid > 12) {
        ctx.strokeStyle = getComputedStyle(document.documentElement)
          .getPropertyValue('--grid-line').trim() || 'rgba(255,255,255,.04)';
        ctx.lineWidth = 1;
        const ox = ((-cam.x * cam.scale + W / 2) % grid + grid) % grid;
        const oy = ((-cam.y * cam.scale + H / 2) % grid + grid) % grid;
        ctx.beginPath();
        for (let x = ox; x < W; x += grid) { ctx.moveTo(x, 0); ctx.lineTo(x, H); }
        for (let y = oy; y < H; y += grid) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
        ctx.stroke();
      }

      const showNodes = nodes.filter((x) => visible[x.group] !== false);
      const showSet = new Set(showNodes.map((x) => x.id));
      const kw = search.value.trim().toLowerCase();
      const focus = hovered?.id || selectedId.value;

      // 边
      ctx.lineWidth = 1 * Math.max(cam.scale, .5);
      for (const e of edges) {
        const p = byId.get(e.from), q = byId.get(e.to);
        if (!p || !q || !showSet.has(p.id) || !showSet.has(q.id)) continue;
        const a = toScreen(p.x, p.y), b = toScreen(q.x, q.y);
        const rel = focus && (p.id === focus || q.id === focus);
        ctx.strokeStyle = rel ? 'rgba(166,197,214,.85)' : 'rgba(196,210,222,.16)';
        ctx.lineWidth = (rel ? 1.8 : 1) * Math.max(cam.scale, .6);
        if (rel) { ctx.shadowColor = 'rgba(166,197,214,.5)'; ctx.shadowBlur = 6; }
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        ctx.shadowBlur = 0;
      }

      // 节点
      for (const p of showNodes) {
        const s = toScreen(p.x, p.y);
        const meta = GROUP_META[p.group] || GROUP_META.note;
        const r = meta.r * cam.scale * (p.id === focus ? 1.28 : 1);
        if (s.x < -60 || s.x > W + 60 || s.y < -60 || s.y > H + 60) continue;

        const hit = kw && p.label.toLowerCase().includes(kw);
        const dim = kw && !hit;

        ctx.globalAlpha = dim ? 0.22 : 1;
        if (p.id === focus || hit) {
          ctx.beginPath(); ctx.arc(s.x, s.y, r + 7, 0, Math.PI * 2);
          ctx.fillStyle = 'rgba(166,197,214,.13)'; ctx.fill();
        }
        ctx.beginPath(); ctx.arc(s.x, s.y, r, 0, Math.PI * 2);
        ctx.shadowColor = meta.color; ctx.shadowBlur = p.id === focus ? 18 : 9;
        ctx.fillStyle = meta.color; ctx.fill();
        ctx.shadowBlur = 0;
        ctx.lineWidth = 2 * Math.max(cam.scale, .6);
        ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--bg-1').trim() || '#0A1120';
        ctx.stroke();

        // 标签
        if (cam.scale > 0.55) {
          const fs = Math.min(12.5 * cam.scale, 15);
          ctx.font = `${p.group === 'case' || p.group === 'client' ? 600 : 400} ${fs}px "PingFang SC","Microsoft YaHei UI",sans-serif`;
          ctx.textAlign = 'center'; ctx.textBaseline = 'top';
          const label = p.label.length > 14 ? p.label.slice(0, 13) + '…' : p.label;
          const tw = ctx.measureText(label).width;
          ctx.fillStyle = 'rgba(5,12,24,.74)';
          ctx.fillRect(s.x - tw / 2 - 3, s.y + r + 3, tw + 6, fs + 4);
          ctx.fillStyle = dim ? 'rgba(157,176,206,.6)' : '#EAF1FF';
          ctx.fillText(label, s.x, s.y + r + 5);
        }
        ctx.globalAlpha = 1;
      }
    }

    let stopped = false;
    function loop() {
      if (stopped) return;
      if (!ctx || !canvas.value || !document.body.contains(canvas.value)) {
        raf = requestAnimationFrame(loop);
        return;
      }
      if (alpha > 0.004 || dragging || panning) tick();
      draw();
      raf = requestAnimationFrame(loop);
    }

    function resize() {
      const el = wrap.value; if (!el) return;
      dpr = window.devicePixelRatio || 1;
      W = el.clientWidth; H = el.clientHeight;
      const c = canvas.value;
      c.width = W * dpr; c.height = H * dpr;
      c.style.width = W + 'px'; c.style.height = H + 'px';
      ctx = c.getContext('2d');
    }

    function fitView() {
      const show = nodes.filter((x) => visible[x.group] !== false);
      if (!show.length) { cam.x = 0; cam.y = 0; cam.scale = 1; return; }
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const p of show) {
        x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
        x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
      }
      const pad = 70;
      const sx = W / Math.max(x1 - x0, 1), sy = H / Math.max(y1 - y0, 1);
      cam.scale = Math.min(Math.min(sx, sy) * 0.86, 1.6);
      cam.x = (x0 + x1) / 2; cam.y = (y0 + y1) / 2;
    }

    function nodeAt(sx, sy) {
      for (let i = nodes.length - 1; i >= 0; i--) {
        const p = nodes[i];
        if (visible[p.group] === false) continue;
        const s = toScreen(p.x, p.y);
        const r = (GROUP_META[p.group]?.r || 6) * cam.scale + 4;
        if (Math.hypot(s.x - sx, s.y - sy) <= r) return p;
      }
      return null;
    }

    /* ------------ 事件 ------------ */
    function onDown(e) {
      const rect = canvas.value.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      moved = false;
      const hit = nodeAt(sx, sy);
      if (hit) {
        const w = toWorld(sx, sy);
        dragging = { node: hit, dx: hit.x - w.x, dy: hit.y - w.y };
        alpha = Math.max(alpha, 0.35);
      } else {
        panning = { sx, sy, cx: cam.x, cy: cam.y };
      }
      canvas.value.classList.add('grabbing');
    }

    function onMove(e) {
      const rect = canvas.value.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      if (dragging) {
        moved = true;
        const w = toWorld(sx, sy);
        dragging.node.x = w.x + dragging.dx;
        dragging.node.y = w.y + dragging.dy;
        dragging.node.vx = 0; dragging.node.vy = 0;
        alpha = Math.max(alpha, 0.3);
        return;
      }
      if (panning) {
        moved = true;
        cam.x = panning.cx - (sx - panning.sx) / cam.scale;
        cam.y = panning.cy - (sy - panning.sy) / cam.scale;
        return;
      }
      const hit = nodeAt(sx, sy);
      if (hit !== hovered) {
        hovered = hit;
        if (hit) {
          tip.show = true; tip.x = sx + 14; tip.y = sy + 14;
          tip.title = hit.label; tip.sub = (GROUP_META[hit.group]?.name || '') + ' · ' + hit.label;
        } else tip.show = false;
      } else if (hit) {
        tip.x = sx + 14; tip.y = sy + 14;
      }
    }

    function onUp() {
      if (dragging) { if (!moved) openNode(dragging.node); dragging = null; }
      else if (panning && !moved) { selectedId.value = null; }
      panning = null;
      canvas.value?.classList.remove('grabbing');
    }

    function onWheel(e) {
      e.preventDefault();
      const rect = canvas.value.getBoundingClientRect();
      const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
      const before = toWorld(sx, sy);
      const k = Math.exp(-e.deltaY * 0.0014);
      cam.scale = Math.min(Math.max(cam.scale * k, 0.16), 4.2);
      const after = toWorld(sx, sy);
      cam.x += before.x - after.x;
      cam.y += before.y - after.y;
    }

    function zoomBy(k) {
      cam.scale = Math.min(Math.max(cam.scale * k, 0.16), 4.2);
    }

    function openNode(n) {
      selectedId.value = n.id;
      // 案由/法条为派生节点，仅高亮选中，不跳转档案库
      if (n.group === 'cause' || n.group === 'law') return;
      store.view = 'vault';
      store.pendingNote = n.id;
    }

    /* ------------ 数据 ------------ */
    async function load() {
      loading.value = true;
      try {
        const d = await api.get('/api/graph');
        nodes = (d.nodes || []).map((n) => ({ ...n }));
        byId = new Map(nodes.map((n) => [n.id, n]));
        edges = (d.edges || []).filter((e) => byId.has(e.from) && byId.has(e.to));
        const deg = new Map();
        edges.forEach((e) => { deg.set(e.from, (deg.get(e.from) || 0) + 1); deg.set(e.to, (deg.get(e.to) || 0) + 1); });
        nodes.forEach((n) => { n.mass = 1 + (deg.get(n.id) || 0) * 0.32; });
        seedLayout(nodes);
        stats.nodes = nodes.length; stats.edges = edges.length;
        alpha = 1;
        await nextTick();
        resize(); fitView();
        // 预热：先跑 120 帧让布局基本稳定，避免用户看到剧烈抖动
        for (let i = 0; i < 120; i++) tick();
        draw();
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }

    function relayout() {
      seedLayout(nodes); cam.scale = 1; cam.x = 0; cam.y = 0; alpha = 1;
      for (let i = 0; i < 120; i++) tick();
      fitView();
    }

    let ro = null;
    onMounted(async () => {
      await load();
      ro = new ResizeObserver(() => { if (stopped) return; resize(); draw(); });
      if (wrap.value) ro.observe(wrap.value);
      window.addEventListener('mousemove', onMove);
      window.addEventListener('mouseup', onUp);
      loop();
    });

    onBeforeUnmount(() => {
      stopped = true;
      cancelAnimationFrame(raf);
      ro?.disconnect();
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    });

    const legend = computed(() => Object.entries(GROUP_META).map(([k, v]) => ({
      key: k, ...v, on: visible[k] !== false,
      count: nodes.filter((n) => n.group === k).length,
    })));

    return {
      canvas, wrap, loading, stats, search, legend, visible, tip,
      onDown, onMove, onWheel, zoomBy, fitView, relayout, load,
      scaleText: computed(() => Math.round(cam.scale * 100) + '%'),
      GROUP_META,
    };
  },
  template: `
<div class="view flat">
  <div class="tabbar">
    <div class="tab active">关系图谱</div>
    <div class="row gap-2" style="margin-left:auto;padding:5px 0">
      <input class="input" style="width:180px;height:28px" placeholder="搜索节点高亮…" v-model="search" />
      <span class="tiny dim">{{ stats.nodes }} 节点 · {{ stats.edges }} 关系</span>
      <button class="btn btn-sm" @click="fitView()">适应画布</button>
      <button class="btn btn-sm" @click="relayout()">重新布局</button>
      <button class="btn btn-sm" @click="load()">刷新</button>
    </div>
  </div>

  <div class="graph-wrap" ref="wrap">
    <canvas ref="canvas" class="graph-canvas"
            @mousedown="onDown" @wheel="onWheel"></canvas>

    <div v-if="loading" class="abs-fill center" style="display:flex">
      <div class="empty"><div class="spinner"></div><div class="t">正在构建关系网络…</div></div>
    </div>

    <div v-if="!loading && !stats.nodes" class="abs-fill" style="display:grid;place-items:center">
      <div class="empty">
        <div class="ico">◇</div><div class="t">暂无可展示的关系</div>
        <div class="d">在笔记中使用 [[双链]] 语法关联客户、案件与材料后，这里会生成关系网络</div>
      </div>
    </div>

    <div class="graph-legend">
      <div class="tiny dim" style="font-weight:600;margin-bottom:2px">节点类型（点击显隐）</div>
      <div v-for="g in legend" :key="g.key" class="lg" @click="visible[g.key] = !visible[g.key]"
           :style="{ opacity: g.on ? 1 : .4 }">
        <span class="dot" :style="{ background: g.color }"></span>
        <span>{{ g.name }}</span>
        <span class="dim" style="margin-left:auto">{{ g.count }}</span>
      </div>
    </div>

    <div class="graph-tools">
      <button @click="zoomBy(1.25)" title="放大">＋</button>
      <button @click="zoomBy(0.8)" title="缩小">－</button>
      <button @click="fitView()" title="适应画布">适应</button>
      <button class="btn btn-sm" @click="relayout()" title="重新布局">重新布局</button>
    </div>

    <div style="position:absolute;left:14px;top:14px;z-index:5" class="tiny dim">
      拖拽节点调整位置 · 滚轮缩放 · 空白处拖拽平移 · 单击节点打开
    </div>

    <div v-if="tip.show" class="graph-tip" :style="{ left: tip.x+'px', top: tip.y+'px' }">
      <div style="font-weight:600">{{ tip.title }}</div>
      <div class="dim">{{ tip.sub }}</div>
    </div>
  </div>
</div>`,
};
