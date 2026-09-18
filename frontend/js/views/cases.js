/* 案件管理：列表 / 详情 / 新建（含非诉业务与律师费） */
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue';
import { api, store, fmtMoney, dueLabel, daysLeft, downloadUrl, relTime } from '../core.js';
import { toast, toastOk, toastErr, modal, confirm, openCtx } from '../ui.js';
import { ProgressRing, Donut, PALETTE } from '../charts.js';

/* ============================ 案件类型：可搜索 + 关键词推荐下拉 ============================ */
// 业务别名：根据已填「案由/项目名称」给出接近的类型推荐
const TYPE_ALIASES = {
  '婚姻家庭': ['离婚', '结婚', '夫妻', '抚养', '扶养', '赡养', '收养', '彩礼', '同居', '探望', '监护', '家暴'],
  '继承纠纷': ['继承', '遗嘱', '遗产', '遗赠', '法定继承'],
  '劳动争议': ['劳动', '工伤', '辞退', '解雇', '工资', '加班', '竞业', '社保', '确认劳动关系', '经济补偿'],
  '合同纠纷': ['合同', '违约', '服务', '承揽', '委托', '租赁纠纷', '定金'],
  '买卖合同纠纷': ['买卖', '货款', '供货', '购销', '订单'],
  '民间借贷': ['借款', '借条', '欠条', '利息', '欠钱', '借贷'],
  '金融借款': ['信用卡', '银行贷款', '金融借款', '逾期贷款'],
  '侵权责任纠纷': ['侵权', '损害', '交通事故', '受伤', '打架', '医疗事故', '名誉', '隐私', '产品责任'],
  '房屋买卖/租赁': ['房屋', '买房', '卖房', '租房', '租赁', '商品房', '物业', '业主', '相邻'],
  '建设工程': ['工程', '施工', '工程款', '包工头', '分包'],
  '公司股权纠纷': ['公司', '股权', '股东', '出资', '分红', '知情权'],
  '知识产权': ['商标', '专利', '著作权', '版权', '商业秘密', '不正当竞争'],
  '票据纠纷': ['票据', '汇票', '支票', '本票'],
  '破产重整': ['破产', '重整', '债权人会议'],
  '仲裁案件': ['仲裁', '仲裁委'],
  '执行案件': ['执行', '强制执行', '查封', '失信'],
  '刑事辩护': ['刑事', '诈骗', '盗窃', '故意伤害', '危险驾驶', '取保'],
  '行政诉讼': ['行政', '行政处罚', '行政复议', '强拆', '政府信息公开'],
  '常年法律顾问': ['法律顾问', '常年顾问', '常法'],
  '合同审查与起草': ['合同审查', '审查合同', '起草合同', '合同起草'],
  '公司设立与变更': ['设立公司', '注册公司', '工商变更', '公司变更'],
  '股权架构设计': ['股权架构', '股权设计', '持股平台'],
  '投融资并购': ['并购', '投融资', '收购', '重组并购'],
  '尽职调查': ['尽职调查', '尽调', '法律尽调'],
  '增资扩股': ['增资', '扩股', '融资入股'],
  '改制重组': ['改制', '国企改革', '企业重组'],
  '劳动人事合规': ['用工合规', '人事合规', '员工手册', '规章制度合规'],
  '规章制度制定': ['规章制度', '员工制度', '制度制定'],
  '知识产权布局': ['知识产权布局', '专利布局', '商标布局'],
  '商标/专利申请': ['商标申请', '专利申请', '注册商标', '申请专利'],
  '税务筹划': ['税务', '税收筹划', '节税'],
  '法律意见书': ['法律意见', '意见书', '专项意见'],
  '律师函/催告函': ['律师函', '催告函', '催款函', '警告函'],
  '谈判与调解': ['谈判', '调解', '和解谈判'],
  '发债与上市': ['上市', '发债', 'IPO', '债券发行'],
  '私募基金': ['私募基金', '基金备案', '募投'],
  '破产清算（管理人）': ['破产清算', '清算', '管理人'],
  '合规体系建设': ['合规体系', '合规建设', '反垄断合规'],
  '数据合规与个人信息保护': ['数据合规', '个人信息保护', '数据安全', '个保法'],
  '涉外法律服务': ['涉外', '跨境', '外资', '英文合同'],
  '公证与见证': ['公证', '见证', '律师见证'],
  '法律培训': ['培训', '法律讲座', '普法'],
  '家族财富管理': ['家族财富', '财富传承', '家族信托'],
};

function bigramSet(s) {
  const set = new Set();
  s = (s || '').toLowerCase().replace(/\s+/g, '');
  for (let i = 0; i < s.length - 1; i++) set.add(s.slice(i, i + 2));
  return set;
}
function typeScore(t, text) {
  if (!text) return 0;
  let s = 0;
  const q = text.toLowerCase();
  if (q.includes(t.name.toLowerCase())) s += 12;
  const gq = bigramSet(q), gn = bigramSet(t.name);
  let hit = 0; gn.forEach((g) => { if (gq.has(g)) hit++; });
  s += hit * 1.4;
  (TYPE_ALIASES[t.name] || []).forEach((k) => { if (q.includes(k.toLowerCase())) s += 6; });
  return s;
}

const TypeCombobox = {
  props: { modelValue: String, types: Array, cause: String, category: String },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const open = ref(false);
    const query = ref('');
    const hi = ref(0);
    const root = ref(null);

    const scored = (list, text) => list.map((t) => ({ t, s: typeScore(t, text) }))
      .sort((a, b) => b.s - a.s || (a.t.sort || 0) - (b.t.sort || 0));

    // 下拉列表：输入关键字时按关键词过滤；未输入时按案由推荐度排序，分组标题保留
    const items = computed(() => {
      const all = props.types || [];
      const q = query.value.trim().toLowerCase();
      let list = all;
      if (q) list = all.filter((t) => t.name.toLowerCase().includes(q));
      const text = q || (props.cause || '').trim();
      const ranked = scored(list, text);
      // 标注推荐分（仅在无搜索词、案由非空时标记）
      const recSet = new Set();
      if (!q && (props.cause || '').trim()) {
        scored(all, props.cause).filter((x) => x.s >= 6).slice(0, 3)
          .forEach((x) => recSet.add(x.t.name));
      }
      // 按类别分组并保持推荐优先
      const groups = [];
      const push = (arr) => arr.forEach(({ t, s }) => {
        let g = groups.find((x) => x.cat === t.category);
        if (!g) { g = { cat: t.category, rows: [] }; groups.push(g); }
        g.rows.push({ t, rec: recSet.has(t.name), s });
      });
      push(ranked.filter((x) => recSet.has(x.t.name)));
      push(ranked.filter((x) => !recSet.has(x.t.name)));
      return groups;
    });
    const flat = computed(() => items.value.flatMap((g) => g.rows));

    // 案由变化时的快捷推荐（最多 3 个）
    const suggestions = computed(() => {
      const text = (props.cause || '').trim();
      if (!text || props.modelValue) return [];
      return scored(props.types || [], text).filter((x) => x.s >= 6).slice(0, 3).map((x) => x.t);
    });

    function onInput(e) { query.value = e.target.value || ''; open.value = true; hi.value = 0; }
    function onFocus() { open.value = true; }
    function toggle() { open.value = !open.value; if (open.value) { hi.value = 0; } }
    function pick(name) { emit('update:modelValue', name); query.value = ''; open.value = false; }
    function onKey(e) {
      if (!open.value) { if (e.key === 'ArrowDown' || e.key === 'Enter') { open.value = true; e.preventDefault(); } return; }
      const n = flat.value.length;
      if (e.key === 'ArrowDown') { e.preventDefault(); hi.value = Math.min(n - 1, hi.value + 1); scrollHi(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); hi.value = Math.max(0, hi.value - 1); scrollHi(); }
      else if (e.key === 'Enter') { e.preventDefault(); const row = flat.value[hi.value]; if (row) pick(row.t.name); }
      else if (e.key === 'Escape') { open.value = false; }
    }
    function scrollHi() {
      setTimeout(() => root.value?.querySelector('.combo-item.hi')?.scrollIntoView({ block: 'nearest' }), 0);
    }
    function onDocClick(e) { if (root.value && !root.value.contains(e.target)) open.value = false; }
    onMounted(() => document.addEventListener('mousedown', onDocClick));
    onBeforeUnmount(() => document.removeEventListener('mousedown', onDocClick));

    return { open, query, hi, items, flat, suggestions, root, toggle, pick, onKey, onInput, onFocus };
  },
  template: `
  <div class="combo" ref="root">
    <div class="combo-box">
      <input class="input" :value="query || modelValue || ''" placeholder="输入关键字搜索，或按案由匹配推荐"
             @input="onInput" @focus="onFocus" @keydown="onKey" />
      <span class="combo-caret" @click="toggle"></span>
    </div>
    <div v-if="suggestions.length" class="combo-chips">
      <span class="tiny dim">推荐</span>
      <span v-for="t in suggestions" :key="t.id" class="chip chip-rec" @click.stop="pick(t.name)">{{ t.name }}</span>
    </div>
    <div v-if="open" class="combo-pop">
      <div class="combo-list">
        <template v-for="g in items" :key="g.cat">
          <div class="combo-group">{{ g.cat }}</div>
          <div v-for="(row,idx) in g.rows" :key="row.t.id"
               :class="['combo-item', row.t.name===modelValue?'sel':'', flat.findIndex(x=>x.t.id===row.t.id)===hi?'hi':'']"
               @mouseenter="hi=flat.findIndex(x=>x.t.id===row.t.id)" @click="pick(row.t.name)">
            <span>{{ row.t.name }}</span>
            <span v-if="row.rec" class="combo-rec-tag">推荐</span>
          </div>
        </template>
        <div v-if="!flat.length" class="combo-empty">无匹配类型，可在「设置 → 案件类型」中自行添加</div>
      </div>
    </div>
  </div>`,
};
// Vue3 ESM 生命周期已在文件顶部统一引入

/* ============================ 案件表单组件 ============================ */
const CaseForm = {
  components: { TypeCombobox },
  props: { types: Array, clients: Array, initial: Object },
  emits: ['submit', 'cancel'],
  setup(props) {
    const f = reactive({
      client: '', cause: '', case_type: '', case_category: '诉讼仲裁',
      court: '', stage: '', case_no: '', opponent: '',
      procedure: '普通程序', contact_date: '', filing_date: '',
      hearing_date: '', judgment_date: '', judgment_eff_date: '',
      fee_amount: '', fee_method: '银行转账', fee_received: false,
      subject_amount: '', risk_level: '中', priority: '普通', tags: '',
      ...(props.initial || {}),
    });
    const stages = ref([]);
    const flow = ref('civil_flow');
    const guard = ref(null);          // 案由规则校验结果 {guard}
    const isNonlit = computed(() => f.case_category === '非诉业务' || flow.value.startsWith('nonlit'));
    const grouped = computed(() => {
      const g = {};
      (props.types || []).forEach((t) => (g[t.category] ||= []).push(t));
      return g;
    });

    async function onTypeChange() {
      const t = (props.types || []).find((x) => x.name === f.case_type);
      if (!t) return;
      f.case_category = t.category;
      flow.value = t.flow || 'civil_flow';
      try {
        const d = await api.get('/api/case-types/flow?flow=' + encodeURIComponent(flow.value));
        stages.value = d.options || [];
        f.stage = d.options?.[0] || '';
      } catch { stages.value = []; }
      checkGuard();
    }

    let guardTimer = null;
    async function checkGuard() {
      clearTimeout(guardTimer);
      const type = f.case_type, cause = f.cause;
      if (!cause.trim()) { guard.value = null; return; }
      guardTimer = setTimeout(async () => {
        try {
          const d = await api.get('/api/case/check-cause?case_type=' + encodeURIComponent(type)
            + '&cause=' + encodeURIComponent(cause));
          guard.value = d;
        } catch { guard.value = null; }
      }, 400);
    }
    watch(() => f.case_type, onTypeChange);
    watch(() => f.cause, checkGuard);
    onMounted(() => { if (f.case_type) onTypeChange(); });

    const allStages = ['委托', '立案', '审理前准备', '开庭审理', '裁判', '二审', '执行', '结案'];
    const today = new Date().toISOString().slice(0, 10);

    return {
      f, grouped, stages, isNonlit, allStages, today, flow, guard,
      submit: () => { if (!f.client || !f.cause) return toastErr('客户与案由必填'); },
    };
  },
  template: `
<div class="fgrid">
  <div class="field">
    <label>客户 *</label>
    <input class="input" v-model="f.client" list="clientList" placeholder="输入或选择客户" />
    <datalist id="clientList"><option v-for="c in clients" :key="c" :value="c" /></datalist>
  </div>
  <div class="field">
    <label>案由 / 项目名称 *</label>
    <input class="input" v-model="f.cause" placeholder="如：劳动争议 / 常年法律顾问" />
  </div>

  <div class="field full" v-if="guard">
    <div v-if="!guard.guard.consistent" class="hint-warn" style="font-size:12px;line-height:1.6">
      注意：{{ guard.guard.warnings.join(' ') }}
      <span class="dim">（当前将按：{{ guard.guard.timeline_kind }}）</span>
    </div>
    <div v-else class="tiny dim" style="font-size:12px">
      分类一致 · {{ guard.guard.timeline_kind }}
    </div>
  </div>

  <div class="field">
    <label>案件类型 <span class="tiny dim">（可搜索 / 关键词推荐）</span></label>
    <TypeCombobox v-model="f.case_type" :types="types" :cause="f.cause" :category="f.case_category" />
  </div>
  <div class="field">
    <label>业务类别</label>
    <select class="select" v-model="f.case_category">
      <option>诉讼仲裁</option><option>非诉业务</option><option>自定义</option>
    </select>
  </div>

  <div class="field">
    <label>{{ isNonlit ? '服务阶段' : '当前阶段' }}</label>
    <select class="select" v-model="f.stage">
      <option v-for="s in (isNonlit && stages.length ? stages : allStages)" :key="s" :value="s">{{ s }}</option>
    </select>
  </div>
  <div class="field">
    <label>{{ isNonlit ? '委托方主体' : '管辖机构' }}</label>
    <input class="input" v-model="f.court" :placeholder="isNonlit ? '如：某某科技有限公司' : '如：惠州市惠城区人民法院'" />
  </div>

  <div class="field">
    <label>案号 / 项目号</label>
    <input class="input" v-model="f.case_no" placeholder="选填" />
  </div>
  <div class="field">
    <label>对方当事人</label>
    <input class="input" v-model="f.opponent" placeholder="选填" />
  </div>

  <template v-if="!isNonlit">
    <div class="field">
      <label>程序</label>
      <select class="select" v-model="f.procedure">
        <option>普通程序</option><option>简易程序</option><option>小额诉讼</option>
      </select>
    </div>
  </template>

  <div class="field">
    <label>{{ isNonlit ? '启动日期' : '委托日期' }}</label>
    <input class="input" type="date" v-model="f.contact_date" :max="today" />
  </div>
  <template v-if="!isNonlit">
    <div class="field"><label>立案日期</label><input class="input" type="date" v-model="f.filing_date" /></div>
    <div class="field"><label>开庭日期</label><input class="input" type="date" v-model="f.hearing_date" /></div>
    <div class="field"><label>判决日期</label><input class="input" type="date" v-model="f.judgment_date" /></div>
    <div class="field"><label>生效日期</label><input class="input" type="date" v-model="f.judgment_eff_date" /></div>
  </template>

  <div class="divider full" style="margin:4px 0"></div>

  <div class="field">
    <label>律师费（元）</label>
    <input class="input" type="number" step="0.01" v-model="f.fee_amount" placeholder="0.00" />
  </div>
  <div class="field">
    <label>收费方式</label>
    <select class="select" v-model="f.fee_method">
      <option>银行转账</option><option>现金</option><option>微信</option>
      <option>支付宝</option><option>支票</option><option>风险代理</option><option>其他</option>
    </select>
  </div>
  <div class="field full">
    <label class="checkbox">
      <input type="checkbox" v-model="f.fee_received" />
      <span class="small">已收到该笔律师费（勾选后计入创收管理的实际回款）</span>
    </label>
  </div>

  <div class="field">
    <label>标的额（元）</label>
    <input class="input" type="number" step="0.01" v-model="f.subject_amount" placeholder="0.00" />
  </div>
  <div class="field">
    <label>风险等级</label>
    <select class="select" v-model="f.risk_level"><option>低</option><option>中</option><option>高</option></select>
  </div>
  <div class="field">
    <label>优先级</label>
    <select class="select" v-model="f.priority"><option>低</option><option selected>普通</option><option>高</option><option>紧急</option></select>
  </div>
  <div class="field">
    <label>标签</label>
    <input class="input" v-model="f.tags" placeholder="逗号分隔，如：重点,疑难" />
  </div>

  <div class="modal-f full" style="margin:10px -20px -20px">
    <button class="btn" @click="$emit('cancel')">取消</button>
    <button class="btn btn-primary" @click="$emit('submit', f)">创建案件</button>
  </div>
</div>`,
};

/* ============================ 一键导入案件 ============================ */
const CaseImportDialog = {
  props: { types: Array },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const folder = ref('');
    const scanning = ref(false);
    const committing = ref(false);
    const groups = ref([]);
    const move = ref(false);
    const result = ref(null);
    const skippedUi = ref(0);

    const groupedTypes = computed(() => {
      const g = {};
      (props.types || []).forEach((t) => (g[t.category] ||= []).push(t));
      return g;
    });

    async function doScan() {
      const dir = (folder.value || '').trim();
      if (!dir) return toastErr('请输入要导入的文件夹路径');
      scanning.value = true; result.value = null; groups.value = [];
      try {
        const r = await api.post('/api/cases/import-scan', { folder: dir });
        groups.value = r.groups || [];
        if (!groups.value.length) toast('未发现可导入的文件');
      } catch (e) { toastErr(e.message); }
      scanning.value = false;
    }

    function onTypeChange(g) {
      const t = (props.types || []).find((x) => x.name === g.case_type);
      if (t) g.case_category = t.category;
    }

    async function doCommit() {
      skippedUi.value = groups.value.filter((g) => g.skip).length;
      const list = groups.value.filter((g) => !g.skip && (g.client || '').trim() && (g.cause || '').trim());
      if (!list.length) return toastErr('请至少保留一个有效分组（客户与案由必填）');
      committing.value = true;
      try {
        const r = await api.post('/api/cases/import-commit', {
          folder: (folder.value || '').trim(), move: move.value,
          groups: list.map((g) => ({ base: g.base, client: g.client.trim(), cause: g.cause.trim(),
            case_type: g.case_type, case_category: g.case_category, opponent: g.opponent })),
        });
        result.value = r;
        toastOk(`导入完成：建案 ${r.created_cases} · 建档 ${r.created_clients} · 归档 ${r.archived} 份`);
      } catch (e) { toastErr(e.message); }
      committing.value = false;
    }

    return { folder, scanning, committing, groups, move, result, skippedUi,
             groupedTypes, doScan, doCommit, onTypeChange };
  },
  template: `
<div>
  <div class="import-src row gap-2">
    <input class="input grow" v-model="folder" placeholder="输入本地文件夹绝对路径，如 D:\\案卷资料\\2026"
           @keyup.enter="doScan" />
    <button class="btn btn-primary" :disabled="scanning" @click="doScan">
      <span v-if="scanning" class="spinner"></span>{{ scanning ? '扫描中…' : '扫描并按规则归类' }}
    </button>
  </div>

  <div v-if="groups.length" class="tiny dim" style="margin:8px 0">
    {{ '已按关键词规则归类，请逐项人工核对' }}
    ｜ 共识别 {{ groups.length }} 组 · 可逐项修改后确认导入
  </div>

  <div v-if="groups.length" class="import-groups">
    <div v-for="(g, i) in groups" :key="g.key" :class="['import-group', g.skip ? 'off' : '']">
      <div class="row between">
        <label class="checkbox">
          <input type="checkbox" v-model="g.skip" /><span>
            <b>{{ g.source_name }}</b>
            <span class="tiny dim"> · {{ g.file_count }} 个文件</span>
            <span v-if="g.existing_client" class="badge badge-warn">客户已存在</span>
            <span v-if="g.existing_case" class="badge badge-primary">案件已存在</span>
          </span>
        </label>
      </div>
      <div class="fgrid" style="margin-top:8px">
        <div class="field"><label>客户名称 *</label>
          <input class="input" v-model="g.client" /></div>
        <div class="field"><label>案由 *</label>
          <input class="input" v-model="g.cause" /></div>
        <div class="field"><label>案件类型</label>
          <select class="select" v-model="g.case_type" @change="onTypeChange(g)">
            <optgroup v-for="(arr, cat) in groupedTypes" :key="cat" :label="cat">
              <option v-for="t in arr" :key="t.id" :value="t.name">{{ t.name }}</option>
            </optgroup>
            <option v-if="g.case_type && !types.some(t=>t.name===g.case_type)" :value="g.case_type">{{ g.case_type }}</option>
          </select></div>
        <div class="field"><label>业务类别</label>
          <select class="select" v-model="g.case_category">
            <option>诉讼仲裁</option><option>非诉业务</option><option>自定义</option>
          </select></div>
        <div class="field full"><label>对方当事人</label>
          <input class="input" v-model="g.opponent" placeholder="选填" /></div>
      </div>
    </div>
  </div>

  <div v-if="result" class="import-summary" style="margin-top:12px">
    <div class="cell"><div class="n">{{ result.created_cases }}</div><div class="k">新建案件</div></div>
    <div class="cell"><div class="n">{{ result.created_clients }}</div><div class="k">新建客户</div></div>
    <div class="cell"><div class="n">{{ result.archived }}</div><div class="k">归档文件</div></div>
    <div class="cell"><div class="n">{{ result.skipped + skippedUi }}</div><div class="k">跳过分组</div></div>
  </div>

  <div class="modal-f" style="margin:16px -20px -20px">
    <label v-if="groups.length && !result" class="checkbox" style="margin-right:auto">
      <input type="checkbox" v-model="move" /><span>移动原文件（默认复制，原文件保留）</span>
    </label>
    <button class="btn" @click="$emit('cancel')">{{ result ? '关闭' : '取消' }}</button>
    <button v-if="!result" class="btn btn-primary" :disabled="committing" @click="doCommit">
      <span v-if="committing" class="spinner"></span>{{ committing ? '导入中…' : '确认导入' }}
    </button>
    <button v-else class="btn btn-primary" @click="$emit('submit', true)">完成</button>
  </div>
</div>`,
};

/* ============================ 模板文书库（起诉状/答辩状/诉讼保全） ============================ */
const DocTplDialog = {
  props: { casePath: String, cases: Array },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const all = ref([]);                 // 全量模板
    const matched = ref([]);             // 按案件推荐
    const groups = ref({});              // 分组统计
    const q = ref('');
    const activeCat = ref('');           // '' 全部 / 分类名 / 诉讼保全
    const selCase = ref(props.casePath || '');
    const previewId = ref(0);
    const previewText = ref('');
    const previewBusy = ref(false);
    const busyId = ref(0);
    const done = ref([]);                // 本次会话已生成的模板 id
    let loaded = false;

    const caseOpts = computed(() => (props.cases || []).map((c) => ({
      value: c.rel_path, label: `${c.client} · ${c.cause}${c.case_type ? '（' + c.case_type + '）' : ''}`,
    })));
    const curCase = computed(() => selCase.value || props.casePath || '');

    const catChips = computed(() => {
      const chips = [{ key: '', label: '全部' }];
      const zs = (groups.value['起诉状答辩状'] || []);
      const totalZs = zs.reduce((s, g) => s + g.count, 0);
      chips.push({ key: '起诉状答辩状', label: `起诉状/答辩状 ${totalZs}` });
      zs.forEach((g) => chips.push({ key: g.category, label: `${g.category.replace(/^\d+\./, '')} ${g.count}` }));
      const bq = (groups.value['诉讼保全'] || []).reduce((s, g) => s + g.count, 0);
      if (bq) chips.push({ key: '诉讼保全', label: `诉讼保全 ${bq}` });
      return chips;
    });

    const shown = computed(() => {
      let list = all.value;
      if (activeCat.value === '起诉状答辩状') list = list.filter((t) => t.grp === '起诉状答辩状');
      else if (activeCat.value) list = list.filter((t) =>
        t.category === activeCat.value || (activeCat.value === '诉讼保全' && t.grp === '诉讼保全'));
      const kw = q.value.trim().toLowerCase();
      if (kw) list = list.filter((t) =>
        `${t.name} ${t.cause} ${t.kind} ${t.category}`.toLowerCase().includes(kw));
      return list;
    });

    async function loadLib() {
      try {
        const r = await api.get('/api/doc-templates');
        all.value = r.templates || []; groups.value = r.groups || {};
        loaded = true;
      } catch (e) { toastErr(e.message); }
    }

    async function loadRec() {
      matched.value = [];
      if (!curCase.value) return;
      try {
        const r = await api.get('/api/doc-templates/recommend?path=' + encodeURIComponent(curCase.value));
        matched.value = (r.matched || []).slice(0, 8);
      } catch (e) { /* 推荐失败不阻塞浏览 */ }
    }

    async function onCaseChange() { await loadRec(); previewId.value = 0; }

    async function togglePreview(t) {
      if (previewId.value === t.id) { previewId.value = 0; return; }
      previewId.value = t.id; previewText.value = ''; previewBusy.value = true;
      try {
        const r = await api.get('/api/doc-templates/preview?id=' + t.id);
        previewText.value = r.text || '（模板无可提取文本）';
      } catch (e) { previewText.value = '预览失败：' + e.message; }
      previewBusy.value = false;
    }

    async function gen(t) {
      if (!curCase.value) return toastErr('请先选择案件');
      if (!loaded) return;
      busyId.value = t.id;
      try {
        const r = await api.post('/api/doc-templates/gen', { id: t.id, case_path: curCase.value });
        done.value.push(t.id);
        toastOk('已生成：' + r.filename);
      } catch (e) { toastErr(e.message); }
      busyId.value = 0;
    }

    function genAllRecommended() {
      matched.value.filter((t) => !t.is_example && !done.value.includes(t.id))
        .forEach((t) => gen(t));
    }

    loadLib();
    loadRec();

    return { all, matched, groups, q, activeCat, selCase, caseOpts, curCase, catChips, shown,
             previewId, previewText, previewBusy, busyId, done,
             onCaseChange, togglePreview, gen, genAllRecommended };
  },
  template: `
<div>
  <div v-if="!casePath" class="field" style="margin-bottom:10px">
    <label>选择案件（生成的文书将归入该案件目录并按规则命名）</label>
    <select class="select" v-model="selCase" @change="onCaseChange">
      <option value="">— 请选择案件 —</option>
      <option v-for="o in caseOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>
  </div>

  <!-- 按案件推荐 -->
  <div v-if="matched.length" class="tpl-rec">
    <div class="row between" style="margin-bottom:6px">
      <div class="tiny dim">根据本案案由/类型推荐（含诉讼保全）</div>
      <button class="btn btn-sm btn-primary" @click="genAllRecommended()">一键生成推荐模板</button>
    </div>
    <div class="tpl-row" v-for="m in matched" :key="'rec' + m.id">
      <div class="grow">
        <b>{{ m.name }}</b>
        <span v-if="m.is_example" class="badge">实例</span>
        <span class="tiny dim"> {{ m.why }}</span>
      </div>
      <button class="btn btn-sm" :disabled="busyId === m.id" @click="gen(m)">
        {{ done.includes(m.id) ? '已生成' : '生成' }}</button>
    </div>
  </div>

  <!-- 全库浏览 -->
  <div class="row gap-2 wrap" style="margin:10px 0 8px">
    <input class="input" style="width:250px" v-model="q"
           placeholder="搜索：案由 / 文书类型，如 离婚、答辩状、保全…" />
    <span v-for="c in catChips" :key="c.key" :class="['chip', activeCat === c.key ? 'on' : '']"
          @click="activeCat = c.key">{{ c.label }}</span>
  </div>

  <div class="tpl-list">
    <div v-for="t in shown" :key="t.id" class="tpl-item">
      <div class="row between">
        <div class="grow ellip" :title="t.name">
          <b>{{ t.name }}</b>
          <span class="badge badge-primary" style="margin-left:6px">{{ t.kind }}</span>
          <span v-if="t.is_example" class="badge">实例</span>
        </div>
        <div class="row gap-1">
          <button class="btn btn-sm" @click="togglePreview(t)">
            {{ previewId === t.id ? '收起' : '预览' }}</button>
          <button class="btn btn-sm btn-primary" :disabled="!curCase || busyId === t.id" @click="gen(t)">
            <span v-if="busyId === t.id" class="spinner"></span>
            {{ done.includes(t.id) ? '已生成' : '生成' }}</button>
        </div>
      </div>
      <div v-if="previewId === t.id" class="tpl-preview">
        <span v-if="previewBusy" class="spinner"></span>
        <pre v-else>{{ previewText }}</pre>
      </div>
    </div>
    <div v-if="!shown.length" class="empty" style="padding:22px">
      <div class="t">{{ all.length ? '无匹配模板' : '模板库加载中…' }}</div>
    </div>
  </div>

  <div class="modal-f" style="margin:14px -20px -20px">
    <span class="tiny dim" style="margin-right:auto">模板为填空式示范文本，生成后请在 Word 中补全当事人等信息</span>
    <button class="btn" @click="$emit('cancel')">关闭</button>
  </div>
</div>`,
};

/* ============================ 要素式文书表单（v0.9.10 起覆盖全部示范文本） ============================ */
const DocTplFormDialog = {
  props: { casePath: String, cases: Array },
  emits: ['submit', 'cancel'],
  setup(props, { emit }) {
    const all = ref([]);
    const selCase = ref(props.casePath || '');
    const tplId = ref(0);
    const schema = ref(null);
    const values = reactive({});
    const busy = ref(false);
    const expanded = reactive({});
    const tplKw = ref('');

    const caseOpts = computed(() => (props.cases || []).map((c) => ({
      value: c.rel_path, label: `${c.client} · ${c.cause}${c.case_type ? '（' + c.case_type + '）' : ''}`,
    })));

    // v0.9.10：全部起诉状/答辩状/申请书示范文本均支持要素式填写（示例文本除外）
    const shownTpls = computed(() => {
      const kw = tplKw.value.trim();
      return all.value.filter((t) => !kw || (t.name || '').includes(kw));
    });

    function resetValues() {
      Object.keys(values).forEach((k) => delete values[k]);
    }

    async function loadTemplates() {
      try {
        const r = await api.get('/api/doc-templates');
        all.value = (r.templates || []).filter(
          (t) => t.grp === '起诉状答辩状' && !t.is_example && t.kind !== '其他');
        if (all.value.length && !tplId.value) {
          tplId.value = all.value[0].id;
          await loadSchema();
        }
      } catch (e) { toastErr(e.message); }
    }

    async function loadSchema() {
      if (!tplId.value) { schema.value = null; return; }
      try {
        const r = await api.get('/api/doc-templates/form-schema?id=' + tplId.value);
        schema.value = r;
        resetValues();
        (r.sections || []).forEach((sec, idx) => {
          expanded[idx] = true;   // 分组默认全部展开，输入控件完整可见
          sec.fields.forEach((f) => {
            values[f.key] = f.type === 'check' ? [] : '';
          });
        });
      } catch (e) { toastErr(e.message); }
    }

    function setRadio(key, val) { values[key] = val; }
    function toggleCheck(key, opt) {
      const arr = Array.isArray(values[key]) ? values[key] : [];
      const i = arr.indexOf(opt);
      if (i >= 0) arr.splice(i, 1); else arr.push(opt);
      values[key] = [...arr];
    }

    async function submit() {
      if (!selCase.value) return toastErr('请选择案件');
      if (!tplId.value) return toastErr('请选择模板');
      busy.value = true;
      try {
        const r = await api.post('/api/doc-templates/gen-filled', {
          id: tplId.value, case_path: selCase.value, values: { ...values },
        });
        toastOk('已生成：' + r.filename);
        emit('submit', r);
      } catch (e) { toastErr(e.message); }
      busy.value = false;
    }

    onMounted(loadTemplates);

    return {
      all, selCase, tplId, schema, values, busy, expanded, caseOpts,
      tplKw, shownTpls, loadSchema, setRadio, toggleCheck, submit,
    };
  },
  template: `
<div>
  <div v-if="!casePath" class="field" style="margin-bottom:10px">
    <label>选择案件</label>
    <select class="select" v-model="selCase">
      <option value="">— 请选择案件 —</option>
      <option v-for="o in caseOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>
  </div>

  <div class="field" style="margin-bottom:10px">
    <label>选择模板 / 案由（共 {{ all.length }} 份示范文本，可输入关键字筛选）</label>
    <input class="input" v-model="tplKw" placeholder="输入案由或文书类型筛选，如：买卖、答辩、强制执行"
           style="margin-bottom:8px" />
    <select class="select" v-model="tplId" @change="loadSchema" size="1">
      <option v-for="t in shownTpls" :key="t.id" :value="t.id">{{ t.name }}</option>
    </select>
  </div>

  <div v-if="schema && schema.sections.length" class="tpl-form">
    <div v-for="(sec, idx) in schema.sections" :key="idx" class="tpl-form-sec">
      <div class="tpl-form-sec-h" @click="expanded[idx] = !expanded[idx]">
        <b>{{ sec.title }}</b>
        <span class="acc-caret" :class="expanded[idx]?'open':''"></span>
      </div>
      <div v-show="expanded[idx]" class="tpl-form-sec-b">
        <div v-for="f in sec.fields" :key="f.key" :class="['tpl-form-field', f.type==='textarea'?'full':'']">
          <label>{{ f.label }}</label>
          <template v-if="f.type === 'text'">
            <input class="input" v-model="values[f.key]" :placeholder="f.label" />
          </template>
          <template v-else-if="f.type === 'date'">
            <input class="input" type="date" v-model="values[f.key]" />
          </template>
          <template v-else-if="f.type === 'textarea'">
            <textarea class="input" v-model="values[f.key]" rows="3" :placeholder="f.label" style="width:100%"></textarea>
          </template>
          <template v-else-if="f.type === 'radio'">
            <div class="tpl-radio-group">
              <span v-for="opt in f.options" :key="opt"
                    :class="['tpl-radio', values[f.key] === opt ? 'on' : '']"
                    @click="setRadio(f.key, opt)">
                <span :class="['opt-mark', values[f.key] === opt ? 'on' : '']"></span>{{ opt }}
              </span>
            </div>
          </template>
          <template v-else-if="f.type === 'check'">
            <div class="tpl-radio-group">
              <span v-for="opt in f.options" :key="opt"
                    :class="['tpl-radio', (values[f.key] || []).includes(opt) ? 'on' : '']"
                    @click="toggleCheck(f.key, opt)">
                <span :class="['opt-mark', (values[f.key] || []).includes(opt) ? 'on' : '']"></span>{{ opt }}
              </span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>

  <div v-else-if="schema" class="empty" style="padding:20px">
    <div class="t">{{ schema.note || '当前模板暂未识别到要素式字段' }}</div>
  </div>

  <div class="modal-f" style="margin:14px -20px -20px">
    <span class="tiny dim" style="margin-right:auto">生成后保留原始表格与格式，仅替换文字</span>
    <button class="btn" @click="$emit('cancel')">取消</button>
    <button class="btn btn-primary" :disabled="busy || !selCase || !tplId" @click="submit">
      <span v-if="busy" class="spinner"></span>{{ busy ? '生成中…' : '生成 Word' }}</button>
  </div>
</div>`,
};

/* ============================ 主视图 ============================ */
export default {
  name: 'CasesView',
  components: { CaseForm, CaseImportDialog, DocTplDialog, DocTplFormDialog, ProgressRing, Donut },
  setup() {
    const cases = ref([]);
    const types = ref([]);
    const groupedTypes = ref({});
    const clients = ref([]);
    const loading = ref(true);
    const mode = ref('card');           // card | table
    const detail = ref(null);
    const filter = reactive({ keyword: '', category: '', stage: '' });
    const feeModal = ref(false);
    const formOpen = ref(false);         // v0.9.9 要素式文书独立整页
    const formCasePath = ref('');
    const feeForm = reactive({ amount: '', fee_date: new Date().toISOString().slice(0, 10),
                               method: '银行转账', note: '', invoice_no: '' });

    const clientNames = computed(() => clients.value.map((c) => c.title));

    async function load() {
      loading.value = true;
      try {
        const [a, b, c] = await Promise.all([
          api.get('/api/cases'), api.get('/api/case-types'), api.get('/api/clients'),
        ]);
        cases.value = a.cases;
        types.value = b.types;
        groupedTypes.value = b.grouped;
        clients.value = c.clients;
        store.cases = a.cases;
        store.types = b.types;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(async () => {
      await load();
      if (store.pendingCase) {
        const p = store.pendingCase; store.pendingCase = null;
        openCase(p);
      }
    });
    watch(() => store.pendingCase, (v) => {
      if (v) { const p = v; store.pendingCase = null; openCase(p); }
    });

    const filtered = computed(() => {
      let r = cases.value;
      if (filter.category) r = r.filter((x) => (x.case_category || '') === filter.category);
      if (filter.stage) r = r.filter((x) => (x.stage || '') === filter.stage);
      if (filter.keyword) {
        const k = filter.keyword.toLowerCase();
        r = r.filter((x) => `${x.client}${x.cause}${x.case_no}${x.court}${x.case_type}`.toLowerCase().includes(k));
      }
      return r;
    });

    const stats = computed(() => {
      const total = cases.value.length;
      const byCat = {};
      cases.value.forEach((c) => { byCat[c.case_category || '未分类'] = (byCat[c.case_category || '未分类'] || 0) + 1; });
      return {
        total,
        overdue: cases.value.reduce((s, c) => s + (c.alert || 0), 0),
        fee: cases.value.reduce((s, c) => s + (Number(c.fee_amount) || 0), 0),
        paid: cases.value.reduce((s, c) => s + (Number(c.fee_paid) || 0), 0),
        donut: Object.entries(byCat).map(([k, v], i) => ({ label: k, value: v, color: PALETTE[i % PALETTE.length] })),
      };
    });

    async function newCase() {
      const data = await modal({ title: '新建案件', comp: CaseForm, size: 'lg',
        props: { types: types.value, clients: clientNames.value } });
      if (!data) return;
      try {
        await api.post('/api/cases', data);
        toastOk('案件已创建');
        await load();
      } catch (e) { toastErr(e.message); }
    }

    async function importCases() {
      const data = await modal({ title: '一键导入案件', comp: CaseImportDialog, size: 'lg',
        props: { types: types.value } });
      if (data) await load();
    }

    async function openTplLib(casePath) {
      const data = await modal({ title: '模板文书库 · 一键生成', comp: DocTplDialog, size: 'lg',
        props: { casePath: casePath || '', cases: cases.value } });
      if (data && detail.value) openCase(detail.value.path);
      return data;
    }

    function openTplForm(casePath) {
      // v0.9.9：由弹窗改为独立整页，长表单输入框/下拉可完全展开操作
      formCasePath.value = casePath || '';
      formOpen.value = true;
    }
    function closeTplForm(done) {
      formOpen.value = false;
      if (done && detail.value) openCase(detail.value.path);
    }

    async function openCase(path) {
      try {
        detail.value = await api.get('/api/case/detail?path=' + encodeURIComponent(path));
      } catch (e) { toastErr(e.message); }
    }
    const back = () => { detail.value = null; };

    async function genDoc(item) {
      const r = await api.post('/api/case/gen-doc',
        { case_path: detail.value.path, doc_type: item.doc_type, basis: item.basis });
      toastOk('已生成：' + r.filename);
      openCase(detail.value.path);
    }
    async function genAll() {
      const r = await api.post('/api/case/gen-all', { case_path: detail.value.path });
      toastOk(`已生成 ${r.made.length} 份空白文书`);
      openCase(detail.value.path);
    }
    async function syncFs(path) {
      try { const r = await api.post('/api/feishu/sync', { path }); toastOk(r.ok ? '已同步飞书' : r.error); }
      catch (e) { toastErr(e.message); }
    }

    const metaPatch = reactive({});
    async function saveMeta() {
      const r = await api.post('/api/case/update-meta', { path: detail.value.path, patch: metaPatch });
      toastOk('已更新，期限已重算');
      Object.keys(metaPatch).forEach((k) => delete metaPatch[k]);
      openCase(detail.value.path);
      load();
    }
    function setMeta(k, v) { metaPatch[k] = v; }

    async function addFee() {
      const r = await api.post('/api/revenue/records', {
        record_type: '律师费', case_path: detail.value.path,
        client: detail.value.frontmatter?.客户 || '',
        title: (detail.value.frontmatter?.案由 || '律师费') + '·律师费',
        amount: Number(feeForm.amount) || 0, fee_date: feeForm.fee_date,
        method: feeForm.method, note: feeForm.note, invoice_no: feeForm.invoice_no,
      });
      toastOk('已登记律师费 ' + fmtMoney(r.row.amount));
      feeModal.value = false;
      feeForm.amount = ''; feeForm.note = ''; feeForm.invoice_no = '';
      openCase(detail.value.path);
      load();
    }

    function caseMenu(ev, c) {
      openCtx(ev, [
        { icon: '', label: '查看详情', onClick: () => openCase(c.rel_path) },
        { icon: '', label: '编辑案件笔记', onClick: () => { store.view = 'vault'; store.pendingNote = c.rel_path; } },
        { icon: '', label: '登记律师费', onClick: () => openCase(c.rel_path).then(() => (feeModal.value = true)) },
        { sep: true },
        { icon: '', label: '打开本地文档', onClick: () => api.post('/api/archive/open', { path: c.rel_path }) },
      ]);
    }

    const tlClass = (t) => {
      const s = t.status || '';
      if (s.includes('逾期')) return 'overdue';
      if (s.includes('进行中') || s.includes('临近')) return 'current';
      if (s.includes('已完成')) return 'done';
      return '';
    };

    return {
      cases, filtered, loading, mode, detail, filter, types, groupedTypes,
      stats, newCase, importCases, openTplLib, openTplForm, openCase, back, genDoc, genAll, syncFs, saveMeta, setMeta,
      feeModal, feeForm, addFee, caseMenu, tlClass, load,
      formOpen, formCasePath, closeTplForm,
      fmtMoney, dueLabel, daysLeft, downloadUrl, relTime,
    };
  },
  template: `
<!-- ============ 要素式文书 · 独立整页（v0.9.9） ============ -->
<div class="view flat tpl-form-page" v-if="formOpen">
  <div class="page-head">
    <div class="row gap-3">
      <button class="btn btn-sm" @click="closeTplForm(false)">返回</button>
      <div>
        <h1>要素式文书</h1>
        <div class="desc">按案由逐项填写要素，全部输入框与选项完整展开；生成结果为保留原始格式的 Word 文档</div>
      </div>
    </div>
  </div>
  <div class="tpl-form-page-b">
    <DocTplFormDialog :key="formCasePath || 'none'" :case-path="formCasePath" :cases="cases"
                      @cancel="closeTplForm(false)" @submit="closeTplForm(true)" />
  </div>
</div>

<div class="view" v-else-if="!detail">
  <div class="page-head">
    <div>
      <h1>案件管理</h1>
      <div class="desc">诉讼业务按《民事诉讼法》自动倒排法定期限；非诉业务按流程模板推进并匹配交付清单</div>
    </div>
    <div class="actions">
      <div class="seg">
        <button :class="mode==='card'?'on':''" @click="mode='card'">卡片</button>
        <button :class="mode==='table'?'on':''" @click="mode='table'">表格</button>
      </div>
      <button class="btn" @click="load()">刷新</button>
      <button class="btn" @click="importCases()">一键导入</button>
      <button class="btn" @click="openTplLib()">模板文书</button>
      <button class="btn" @click="openTplForm()">要素式文书</button>
      <button class="btn btn-primary" @click="newCase()">新建案件</button>
    </div>
  </div>

  <div class="grid g-4 sec">
    <div class="stat blue"><div class="stat-ico"></div><div class="k">案件总数</div>
      <div class="v">{{ stats.total }}<small>件</small></div><div class="d">诉讼与非诉全量</div></div>
    <div class="stat red"><div class="stat-ico"></div><div class="k">逾期节点</div>
      <div class="v">{{ stats.overdue }}<small>个</small></div><div class="d">需立即处理</div></div>
    <div class="stat green"><div class="stat-ico"></div><div class="k">合同金额</div>
      <div class="v">¥{{ (stats.fee||0).toLocaleString() }}</div><div class="d">律师费合计</div></div>
    <div class="stat accent"><div class="stat-ico"></div><div class="k">已回款</div>
      <div class="v">¥{{ (stats.paid||0).toLocaleString() }}</div>
      <div class="d">待回款 ¥{{ ((stats.fee||0)-(stats.paid||0)).toLocaleString() }}</div></div>
  </div>

  <div class="row gap-2 wrap sec">
    <input class="input" style="width:230px" placeholder="搜索客户/案由/案号…" v-model="filter.keyword" />
    <span :class="['chip', !filter.category?'on':'']" @click="filter.category=''">全部</span>
    <span v-for="(v,k) in groupedTypes" :key="k" :class="['chip', filter.category===k?'on':'']"
          @click="filter.category = filter.category===k ? '' : k">{{ k }} {{ (stats.donut.find(d=>d.label===k)||{}).value || '' }}</span>
  </div>

  <div v-if="loading" class="empty"><div class="spinner"></div></div>

  <!-- 卡片视图 -->
  <div v-else-if="mode==='card'" class="grid g-auto">
    <div v-for="c in filtered" :key="c.rel_path" class="card" style="cursor:pointer"
         @click="openCase(c.rel_path)" @contextmenu="caseMenu($event, c)">
      <div class="row between mb-2">
        <span class="badge" :class="c.case_category==='非诉业务' ? 'badge-cyan' : 'badge-purple'">
          {{ c.case_type || c.case_category || '未分类' }}
        </span>
        <span v-if="c.alert" class="badge badge-danger badge-dot">逾期 {{ c.alert }}</span>
        <span v-else-if="c.warning" class="badge badge-warn badge-dot">临近 {{ c.warning }}</span>
        <span v-else class="badge badge-success badge-dot">正常</span>
      </div>
      <h3 style="font-size:15.5px">{{ c.client }} · {{ c.cause }}</h3>
      <div class="tiny dim mt-1 ellip">{{ c.court || '未填写机构' }} ｜ {{ c.case_no || '无编号' }}</div>
      <div class="row gap-2 wrap mt-3">
        <span class="badge">{{ c.stage }}</span>
        <span class="badge" :class="{'badge-danger': c.priority==='紧急','badge-warn':c.priority==='高'}">{{ c.priority || '普通' }}</span>
        <span class="badge" :class="{'badge-danger': c.risk_level==='高','badge-success':c.risk_level==='低'}">{{ c.risk_level || '中' }}风险</span>
      </div>
      <div class="divider" style="margin:11px 0"></div>
      <div class="row between">
        <div>
          <div class="tiny dim">律师费</div>
          <div class="num" style="font-weight:650">¥{{ (c.fee_amount||0).toLocaleString() }}</div>
        </div>
        <div style="text-align:center">
          <div class="tiny dim">流程</div>
          <div class="num" style="font-weight:650">{{ c.flow_progress }}%</div>
        </div>
        <div style="text-align:right">
          <div class="tiny dim">下一节点</div>
          <div class="num small">{{ c.next_due || '—' }}</div>
        </div>
      </div>
      <div class="bar mt-3"><i :style="{ width: c.flow_progress + '%' }"></i></div>
    </div>
    <div v-if="!filtered.length" class="empty" style="grid-column:1/-1">
      <div class="ico">◇</div><div class="t">暂无案件</div>
      <div class="d">点击右上角「新建案件」开始，业务类型可选诉讼仲裁或非诉业务</div>
    </div>
  </div>

  <!-- 表格视图 -->
  <div v-else class="tbl-wrap">
    <table class="tbl">
      <thead><tr>
        <th>案件</th><th>类型</th><th>客户</th><th>阶段</th><th>管辖/机构</th>
        <th class="num">律师费</th><th class="num">已收</th><th>下一节点</th><th>状态</th><th>操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="c in filtered" :key="c.rel_path" @click="openCase(c.rel_path)" style="cursor:pointer">
          <td><b>{{ c.cause }}</b></td>
          <td><span class="badge">{{ c.case_type || '—' }}</span></td>
          <td>{{ c.client }}</td>
          <td>{{ c.stage }}</td>
          <td class="dim">{{ c.court || '—' }}</td>
          <td class="num">¥{{ (c.fee_amount||0).toLocaleString() }}</td>
          <td class="num">¥{{ (c.fee_paid||0).toLocaleString() }}</td>
          <td class="small">{{ c.next_due || '—' }}</td>
          <td>
            <span v-if="c.alert" class="badge badge-danger">逾期 {{ c.alert }}</span>
            <span v-else-if="c.warning" class="badge badge-warn">临近 {{ c.warning }}</span>
            <span v-else class="badge badge-success">正常</span>
          </td>
          <td><button class="btn btn-sm" @click.stop="openCase(c.rel_path)">详情</button></td>
        </tr>
        <tr v-if="!filtered.length"><td colspan="10"><div class="empty"><div class="t">暂无案件</div></div></td></tr>
      </tbody>
    </table>
  </div>
</div>

<!-- ============ 案件详情 ============ -->
<div class="view" v-else>
  <div class="page-head">
    <div class="row gap-3">
      <button class="btn btn-sm" @click="back()">返回</button>
      <div>
        <h1>{{ detail.frontmatter.客户 }} · {{ detail.frontmatter.案由 }}</h1>
        <div class="desc">
          <span class="badge" :class="detail.frontmatter.业务类别==='非诉业务'?'badge-cyan':'badge-purple'">
            {{ detail.frontmatter.案件类型 || detail.frontmatter.业务类别 }}
          </span>
          {{ detail.frontmatter.管辖法院 || '' }} ｜ {{ detail.frontmatter.案号 || '未编号' }}
          ｜ 流程 {{ detail.flow }}
        </div>
      </div>
    </div>
    <div class="actions">
      <button class="btn" @click="genAll()">一键生成必备文书</button>
      <button class="btn" @click="openTplLib(detail.path)">模板文书</button>
      <button class="btn" @click="openTplForm(detail.path)">要素式文书</button>
      <button class="btn btn-primary" @click="feeModal = true">登记律师费</button>
    </div>
  </div>

  <div class="grid g-main sec">
    <div class="card">
      <div class="card-h"><h3>流程节点</h3>
        <span class="sub">{{ detail.timeline.length }} 个节点 · 自动倒排</span></div>
      <div class="timeline">
        <div v-for="t in detail.timeline" :key="t.key" :class="['tl-item', tlClass(t)]">
          <div class="tl-t">
            {{ t.name }}
            <span class="badge" :class="(t.status||'').includes('逾期') ? 'badge-danger' : (t.status||'').includes('临近')||(t.status||'').includes('进行中') ? 'badge-warn' : (t.status||'').includes('已完成') ? 'badge-success' : ''">
              {{ t.status }}
            </span>
          </div>
          <div class="tl-m">节点日期：{{ t.due || '待填锚点日期' }} ｜ 依据：{{ t.basis }}</div>
          <div class="tl-note">{{ t.note }}</div>
          <div class="tl-files"><span v-for="d in t.deliverables" :key="d">{{ d }}</span></div>
        </div>
      </div>
    </div>

    <div class="col-4">
      <div class="card">
        <div class="card-h"><h3>案件信息</h3>
          <button class="btn btn-sm btn-primary" @click="saveMeta()">保存</button></div>
        <table class="kv-table">
          <tr><td>阶段</td><td>
            <select class="select" :value="detail.frontmatter.阶段"
                    @change="setMeta('阶段', $event.target.value)">
              <option v-for="s in detail.stage_options" :key="s" :value="s">{{ s }}</option>
            </select></td></tr>
          <tr><td>对方</td><td><input class="input" :value="detail.frontmatter.对方当事人"
            @change="setMeta('对方当事人', $event.target.value)" /></td></tr>
          <tr><td>律师费</td><td><input class="input" type="number" :value="detail.frontmatter.律师费"
            @change="setMeta('律师费', $event.target.value)" /></td></tr>
          <tr><td>收费方式</td><td><input class="input" :value="detail.frontmatter.收费方式"
            @change="setMeta('收费方式', $event.target.value)" /></td></tr>
          <tr><td>标的额</td><td><input class="input" type="number" :value="detail.frontmatter.标的额"
            @change="setMeta('标的额', $event.target.value)" /></td></tr>
          <tr v-if="detail.frontmatter.业务类别 !== '非诉业务'">
            <td>委托日期</td><td><input class="input" type="date" :value="detail.frontmatter.委托日期"
              @change="setMeta('委托日期', $event.target.value)" /></td></tr>
          <tr v-if="detail.frontmatter.业务类别 !== '非诉业务'">
            <td>立案日期</td><td><input class="input" type="date" :value="detail.frontmatter.立案日期"
              @change="setMeta('立案日期', $event.target.value)" /></td></tr>
          <tr v-if="detail.frontmatter.业务类别 !== '非诉业务'">
            <td>开庭日期</td><td><input class="input" type="date" :value="detail.frontmatter.开庭日期"
              @change="setMeta('开庭日期', $event.target.value)" /></td></tr>
          <tr v-if="detail.frontmatter.业务类别 !== '非诉业务'">
            <td>判决日期</td><td><input class="input" type="date" :value="detail.frontmatter.判决日期"
              @change="setMeta('判决日期', $event.target.value)" /></td></tr>
        </table>
      </div>

      <div class="card">
        <div class="card-h"><h3>创收情况</h3>
          <button class="btn btn-sm" @click="feeModal = true">＋</button></div>
        <div class="row gap-4">
          <ProgressRing :value="detail.fee.progress" :size="60" :thickness="5" />
          <div class="grow col" style="gap:3px">
            <div class="row between small"><span class="dim">合同金额</span><b>¥{{ (detail.fee.contract_amount||0).toLocaleString() }}</b></div>
            <div class="row between small"><span class="dim">已回款</span><b style="color:var(--success)">¥{{ (detail.fee.received||0).toLocaleString() }}</b></div>
            <div class="row between small"><span class="dim">待回款</span><b style="color:var(--danger)">¥{{ (detail.fee.outstanding||0).toLocaleString() }}</b></div>
          </div>
        </div>
        <div class="divider" style="margin:11px 0"></div>
        <div v-for="r in detail.fee.records" :key="r.id" class="row between small" style="padding:3px 0">
          <span>{{ r.fee_date }} · {{ r.title }}</span>
          <b>¥{{ (r.amount||0).toLocaleString() }}</b>
        </div>
        <div v-if="!detail.fee.records.length" class="tiny dim">尚未登记收付款记录</div>
      </div>
    </div>
  </div>

  <div class="grid g-2 sec">
    <div class="card">
      <div class="card-h"><h3>文件清单</h3><span class="sub">按阶段与法律依据匹配</span></div>
      <div class="tbl-wrap" style="max-height:420px">
        <table class="tbl">
          <thead><tr><th>阶段</th><th>文件</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="(it, i) in detail.checklist" :key="i">
              <td class="dim small">{{ it.stage }}</td>
              <td>{{ it.doc_type }}</td>
              <td>
                <span class="badge" :class="it.need_level==='必备'?'badge-danger':'badge-primary'">{{ it.need_level }}</span>
                <span v-if="it.generated" class="badge badge-success">已生成</span>
                <span v-else class="badge badge-warn">待生成</span>
              </td>
              <td>
                <button v-if="!it.generated" class="btn btn-sm" @click="genDoc(it)">生成</button>
                <span v-else class="dim small">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h3>已生成文书</h3><span class="sub">{{ detail.docs.length }} 份</span></div>
      <div v-if="!detail.docs.length" class="empty" style="padding:24px">
        <div class="ico">◇</div><div class="t">尚未生成文书</div>
      </div>
      <div v-for="d in detail.docs" :key="d.id" class="li">
        <div class="li-ico">·</div>
        <div class="li-main">
          <div class="li-t ellip" :title="d.filename">{{ d.filename }}</div>
          <div class="li-s">{{ d.created }} · {{ d.doc_type }}</div>
        </div>
        <span class="badge" :class="d.sync_state==='一致'?'badge-success':'badge-danger'">{{ d.sync_state }}</span>
        <button class="btn btn-sm" @click="window.open(downloadUrl(d.rel_path))">下载</button>
        <button class="btn btn-sm" @click="syncFs(d.rel_path)">飞书</button>
      </div>
    </div>
  </div>

  <!-- 登记律师费 -->
  <div v-if="feeModal" class="mask" @click.self="feeModal=false">
    <div class="modal">
      <div class="modal-h"><h3>登记律师费</h3><button class="tbtn tbtn-close" @click="feeModal=false">×</button></div>
      <div class="modal-b fgrid">
        <div class="field"><label>金额（元）</label>
          <input class="input" type="number" step="0.01" v-model="feeForm.amount" placeholder="0.00" /></div>
        <div class="field"><label>收款日期</label>
          <input class="input" type="date" v-model="feeForm.fee_date" /></div>
        <div class="field"><label>收付方式</label>
          <select class="select" v-model="feeForm.method">
            <option>银行转账</option><option>现金</option><option>微信</option>
            <option>支付宝</option><option>支票</option><option>其他</option></select></div>
        <div class="field"><label>发票号</label>
          <input class="input" v-model="feeForm.invoice_no" placeholder="选填" /></div>
        <div class="field full"><label>备注</label>
          <input class="input" v-model="feeForm.note" placeholder="如：首期款 / 尾款" /></div>
      </div>
      <div class="modal-f">
        <button class="btn" @click="feeModal=false">取消</button>
        <button class="btn btn-primary" @click="addFee()">确认登记</button>
      </div>
    </div>
  </div>
</div>`,
};
