/* 设置：通用 / 功能排序 / 案件类型 / 集成 / 系统（已去除授权激活，全部功能直接使用） */
import { ref, reactive, computed, onMounted, watch } from 'vue';
import { api, store, setTheme, toggleSidebar } from '../core.js';
import { toast, toastOk, toastErr, confirm, prompt } from '../ui.js';

/* 已下线的功能（AI 助手 / 接案笔录）：导航与设置中一并剔除 */
const HIDDEN_KEYS = new Set(['ai', 'intake']);

const TABS = [
  { key: 'general', name: '通用', icon: '' },
  { key: 'nav', name: '功能排序', icon: '' },
  { key: 'types', name: '案件类型', icon: '' },
  { key: 'integrate', name: '集成与通知', icon: '' },
  { key: 'system', name: '系统与审计', icon: '' },
];

export default {
  name: 'SettingsView',
  setup() {
    const tab = ref('general');
    const cfg = ref(null);
    const nav = ref([]);
    const types = ref([]);
    const audit = ref([]);
    const loading = ref(true);
    const saving = ref(false);
    const scheduler = ref(null);
    const dataDir = ref('');
    const dragIdx = ref(-1);
    const newType = reactive({ name: '', category: '自定义' });
    const folders = ref([]);

    const form = reactive({
      feishu: {}, wechat: {}, invoice: {}, bitable: {}, mail: {}, security: {}, ui: {},
    });

    async function load() {
      loading.value = true;
      try {
        const [s, n, t, a] = await Promise.all([
          api.get('/api/settings'), api.get('/api/nav'), api.get('/api/case-types'),
          api.get('/api/audit'),
        ]);
        cfg.value = s.settings;
        scheduler.value = s.scheduler;
        nav.value = (s.settings.nav || n.items).filter((x) => !HIDDEN_KEYS.has(x.key));
        types.value = t.types;
        audit.value = a.lines.slice(-120).reverse();
        Object.assign(form, {
          feishu: { ...s.settings.feishu }, wechat: { ...s.settings.wechat },
          invoice: { ...s.settings.invoice }, bitable: { ...s.settings.bitable },
          mail: { ...s.settings.mail },
          security: { ...s.settings.security },
          ui: { ...(s.settings.ui || {}) },
        });
        dataDir.value = (await api.get('/api/data/dir')).data_dir;
      } catch (e) { toastErr(e.message); }
      loading.value = false;
    }
    onMounted(load);

    /* ---------- 保存 ---------- */
    async function saveAll() {
      saving.value = true;
      try {
        await api.post('/api/settings', {
          feishu: { ...form.feishu, app_secret: form.feishu.app_secret || '' },
          wechat: { ...form.wechat, appsecret: form.wechat.appsecret || '' },
          invoice: { ...form.invoice, password: form.invoice.password || '' },
          bitable: form.bitable, mail: { ...form.mail, password: form.mail.password || '' },
          security: form.security, ui: form.ui,
        });
        toastOk('设置已保存（密钥仅加密存于本机）');
        load();
      } catch (e) { toastErr(e.message); }
      saving.value = false;
    }

    async function saveNav() {
      await api.post('/api/nav', { items: nav.value });
      toastOk('功能顺序已保存');
    }
    async function resetNav() {
      nav.value = (await api.post('/api/nav/reset', {})).items;
      toastOk('已恢复默认顺序');
    }

    /* ---------- 拖拽排序 ---------- */
    function onDragStart(i) { dragIdx.value = i; }
    function onDragOver(e, i) { e.preventDefault(); }
    function onDrop(i) {
      if (dragIdx.value < 0 || dragIdx.value === i) return;
      const item = nav.value.splice(dragIdx.value, 1)[0];
      nav.value.splice(i, 0, item);
      dragIdx.value = -1;
      saveNav();
    }
    function move(i, dir) {
      const j = i + dir;
      if (j < 0 || j >= nav.value.length) return;
      const t = nav.value[i]; nav.value[i] = nav.value[j]; nav.value[j] = t;
      saveNav();
    }
    function toggleNav(item) { item.enabled = !item.enabled; saveNav(); }

    /* ---------- 案件类型 ---------- */
    async function addType() {
      if (!newType.name.trim()) return toastErr('请输入类型名称');
      try {
        await api.post('/api/case-types', { ...newType });
        newType.name = '';
        toastOk('已新增案件类型');
        load();
      } catch (e) { toastErr(e.message); }
    }
    async function delType(t) {
      if (t.builtin) return toastErr('内置类型不可删除，可选择停用');
      const okd = await confirm({ title: '删除类型', danger: true, okText: '删除',
        message: `确定删除案件类型「${t.name}」？已使用该类型的案件不受影响。` });
      if (!okd) return;
      await api.del('/api/case-types/' + t.id);
      toastOk('已删除'); load();
    }
    async function toggleType(t) {
      await api.patch('/api/case-types/' + t.id, { enabled: !t.enabled });
      load();
    }
    async function renameType(t) {
      const n = await prompt({ title: '重命名类型', label: '类型名称', value: t.name });
      if (!n || n === t.name) return;
      await api.patch('/api/case-types/' + t.id, { name: n });
      toastOk('已重命名'); load();
    }

    /* ---------- 集成测试 ---------- */
    async function testWechat() {
      try {
        const r = await api.post('/api/wechat/test-send', { content: '【测试】法岩律师工作台微信提醒通道已连通。' });
        toastOk(r.ok ? '微信返回成功，请注意查收' : '发送失败：' + (r.error || JSON.stringify(r.resp)));
      } catch (e) { toastErr(e.message); }
    }
    async function syncBitable() {
      const r = await api.post('/api/bitable/sync', { dataset: 'archive' });
      if (r.ok) toastOk(`已同步 ${r.written} 行到飞书多维表格`);
      else toastErr(r.error || '同步失败');
      load();
    }
    async function seedDemo() {
      const r = await api.post('/api/demo/seed', {});
      toastOk(`演示数据已载入：${r.created.join('、') || '已存在'}`);
      load();
    }
    async function openDataDir() {
      await api.post('/api/archive/open-folder', { path: '' });
      toast('已打开档案库目录');
    }
    async function rescan() {
      const r = await api.post('/api/registry/sync', {});
      toastOk(`档案总表已刷新：新增 ${r.added}，更新 ${r.updated}`);
    }

    return {
      TABS, tab, cfg, nav, types, audit, loading, saving, form,
      scheduler, dataDir, newType, dragIdx,
      saveAll, saveNav, resetNav, onDragStart, onDragOver, onDrop, move, toggleNav,
      addType, delType, toggleType, renameType,
      testWechat, syncBitable, seedDemo, openDataDir, rescan, load,
      setTheme, toggleSidebar, store,
      theme: computed(() => store.theme),
    };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div><h1>设置</h1><div class="desc">本地优先：所有配置与密钥仅加密存于本机，未启用的集成不发起任何外网请求</div></div>
    <div class="actions">
      <button class="btn" @click="load()">刷新</button>
      <button class="btn btn-primary" :disabled="saving" @click="saveAll()">
        <span v-if="saving" class="spinner"></span>保存设置</button>
    </div>
  </div>

  <div class="row gap-2 wrap sec">
    <span v-for="t in TABS" :key="t.key" :class="['chip', tab===t.key?'on':'']" @click="tab=t.key">
      {{ t.name }}</span>
  </div>

  <div v-if="loading" class="empty"><div class="spinner"></div></div>

  <!-- 通用 -->
  <div v-else-if="tab==='general'" class="grid g-2">
    <div class="card">
      <div class="panel-title">外观</div>
      <div class="col-3">
        <div class="field"><label>主题</label>
          <div class="seg">
            <button :class="theme==='dark'?'on':''" @click="setTheme('dark')">深色</button>
            <button :class="theme==='light'?'on':''" @click="setTheme('light')">浅色</button>
          </div></div>
        <div class="field"><label>侧边栏</label>
          <button class="btn" @click="toggleSidebar()">切换展开 / 收起</button></div>
        <div class="field full"><label>首页招呼词</label>
          <input class="input" v-model="form.ui.greeting"
                 placeholder="留空则按时段自动（凌晨好 / 早上好 / 中午好 / 下午好 / 晚上好）" />
          <div class="tiny dim mt-1">自定义首页顶部问候语，例如「早上好，张律师」</div></div>
      </div>
    </div>
    <div class="card">
      <div class="panel-title">本地数据</div>
      <table class="kv-table">
        <tr><td>数据目录</td><td class="mono tiny" style="word-break:break-all">{{ dataDir }}</td></tr>
      </table>
      <div class="row gap-2 mt-3">
        <button class="btn btn-sm" @click="openDataDir()">打开档案库</button>
        <button class="btn btn-sm" @click="rescan()">重建档案总表</button>
      </div>
      <div class="tiny dim mt-3">整个目录拷走即迁移，删除即卸载；不写注册表、不写用户目录。</div>
    </div>
    <div class="card">
      <div class="panel-title">演示数据</div>
      <p class="small muted mb-3">一键创建示例客户与案件（一个劳动争议诉讼 + 一个常年法律顾问非诉），用于快速体验完整流程。</p>
      <button class="btn" @click="seedDemo()">载入演示数据</button>
    </div>
    <div class="card">
      <div class="panel-title">安全</div>
      <div class="col-3">
        <label class="checkbox"><input type="checkbox" v-model="form.security.audit" /><span>启用操作审计日志</span></label>
        <div class="field"><label>自动锁定（分钟）</label>
          <input class="input" type="number" v-model="form.security.lock_after_minutes" /></div>
        <div class="tiny dim">服务仅绑定 127.0.0.1，随机令牌 + Host 白名单防 DNS-rebind。</div>
      </div>
    </div>
  </div>

  <!-- 功能排序 -->
  <div v-else-if="tab==='nav'" class="card" style="max-width:620px">
    <div class="card-h">
      <div><h3>功能排序</h3><div class="sub">拖拽条目调整顺序，点击开关隐藏/显示功能</div></div>
      <button class="btn btn-sm" @click="resetNav()">恢复默认</button>
    </div>
    <div v-for="(item, i) in nav" :key="item.key"
         :class="['nav-item', dragIdx===i ? 'dragging' : '']"
         draggable="true"
         @dragstart="onDragStart(i)" @dragover="onDragOver($event, i)" @drop="onDrop(i)"
         style="border:1px solid var(--border);margin-bottom:5px;background:var(--bg-1)">
      <span class="grip">⠿</span>
      <span class="lbl">{{ item.name }}</span>
      <button class="btn btn-sm btn-ghost" @click="move(i, -1)">上移</button>
      <button class="btn btn-sm btn-ghost" @click="move(i, 1)">下移</button>
      <label class="switch" @click.stop>
        <input type="checkbox" :checked="item.enabled" @change="toggleNav(item)" />
        <span class="track"></span>
      </label>
    </div>
  </div>

  <!-- 案件类型 -->
  <div v-else-if="tab==='types'" class="grid g-main">
    <div class="card">
      <div class="card-h"><h3>案件类型</h3>
        <span class="sub">{{ types.length }} 个类型（内置 43 项，含非诉业务 25 项）</span></div>
      <div class="tbl-wrap" style="max-height:540px">
        <table class="tbl">
          <thead><tr><th>类型名称</th><th>业务类别</th><th>流程模板</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="t in types" :key="t.id">
              <td><b>{{ t.name }}</b>
                <span v-if="!t.builtin" class="badge badge-cyan" style="margin-left:5px">自定义</span></td>
              <td><span class="badge" :class="t.category==='非诉业务'?'badge-cyan':'badge-purple'">{{ t.category }}</span></td>
              <td class="tiny dim mono">{{ t.flow }}</td>
              <td>
                <span :class="['badge', t.enabled ? 'badge-success' : '']">
                  {{ t.enabled ? '启用' : '停用' }}</span>
              </td>
              <td class="row gap-1">
                <button class="btn btn-sm btn-ghost" @click="renameType(t)">重命名</button>
                <button class="btn btn-sm btn-ghost" @click="toggleType(t)">{{ t.enabled ? '停用' : '启用' }}</button>
                <button class="btn btn-sm btn-ghost" v-if="!t.builtin" @click="delType(t)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="panel-title">新增自定义类型</div>
      <div class="field mb-3"><label>类型名称</label>
        <input class="input" v-model="newType.name" placeholder="如：数据出境合规、债券发行" /></div>
      <div class="field mb-3"><label>业务类别</label>
        <select class="select" v-model="newType.category">
          <option>非诉业务</option><option>诉讼仲裁</option><option>自定义</option></select></div>
      <button class="btn btn-primary" style="width:100%" @click="addType()">＋ 新增类型</button>
      <div class="divider"></div>
      <div class="tiny dim" style="line-height:1.7">
        · 诉讼仲裁类自动套用《民事诉讼法》期限倒排引擎；<br>
        · 非诉业务类按流程模板推进（如常年法律顾问、并购、尽调、合规体系）；<br>
        · 自定义类型默认走「非诉通用流程」，可在创建后按需调整；<br>
        · 内置类型不可删除，可停用后新增同名自定义类型替代。
      </div>
    </div>
  </div>

  <!-- 集成 -->
  <div v-else-if="tab==='integrate'" class="grid g-2">
    <div class="card">
      <div class="card-h"><h3>飞书开放平台</h3>
        <span :class="['badge', cfg?.feishu?.enabled ? 'badge-success' : '']">
          {{ cfg?.feishu?.enabled ? '已启用' : '未启用' }}</span></div>
      <div class="fgrid">
        <div class="field full"><label class="checkbox">
          <input type="checkbox" v-model="form.feishu.enabled" /><span>启用飞书集成</span></label></div>
        <div class="field"><label>App ID</label><input class="input" v-model="form.feishu.app_id" /></div>
        <div class="field"><label>App Secret</label>
          <input class="input" type="password" v-model="form.feishu.app_secret"
                 :placeholder="cfg?.feishu?.app_secret_saved ? '已保存，留空则不修改' : '加密保存于本机'" /></div>
        <div class="field full"><label>云文档目标文件夹 token</label>
          <input class="input" v-model="form.feishu.folder_token" /></div>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h3>飞书多维表格</h3>
        <button class="btn btn-sm" @click="syncBitable()">立即同步档案总表</button></div>
      <p class="small muted mb-3">把「档案总表 / 案件表 / 客户表 / 创收表 / 提醒表」一键同步到飞书多维表格。
        首次同步会自动创建多维表格与数据表。</p>
      <div class="field mb-3"><label>多维表格 App Token（留空自动创建）</label>
        <input class="input" v-model="form.bitable.app_token" /></div>
      <div class="tiny dim">上次同步：{{ cfg?.bitable?.last_sync || '从未' }} ·
        未配置飞书凭据时可先使用档案库页的「导出 CSV」。</div>
    </div>

    <div class="card">
      <div class="card-h"><h3>微信公众号提醒</h3>
        <span :class="['badge', cfg?.wechat?.enabled ? 'badge-success' : '']">
          {{ cfg?.wechat?.enabled ? '已启用' : '未启用' }}</span></div>
      <div class="fgrid">
        <div class="field full"><label class="checkbox">
          <input type="checkbox" v-model="form.wechat.enabled" /><span>启用微信提醒</span></label></div>
        <div class="field full"><label class="checkbox">
          <input type="checkbox" v-model="form.wechat.sandbox" /><span>使用测试号沙盒（零资质联调）</span></label></div>
        <div class="field"><label>AppID</label><input class="input" v-model="form.wechat.appid" /></div>
        <div class="field"><label>AppSecret</label>
          <input class="input" type="password" v-model="form.wechat.appsecret"
                 :placeholder="cfg?.wechat?.appsecret_saved ? '已保存，留空则不修改' : ''" /></div>
        <div class="field"><label>发送通道</label>
          <select class="select" v-model="form.wechat.send_mode">
            <option value="kf">客服消息（48小时互动内，最简单）</option>
            <option value="template">服务号模板消息（需认证服务号）</option>
            <option value="subscribe">一次性订阅消息</option></select></div>
        <div class="field"><label>默认接收人 OpenID</label>
          <input class="input" v-model="form.wechat.default_openid" /></div>
        <div class="field full"><label>模板 ID（template / subscribe 通道）</label>
          <input class="input" v-model="form.wechat.template_id" /></div>
      </div>
      <button class="btn btn-sm mt-3" @click="testWechat()">发送一条测试消息</button>
    </div>

    <div class="card">
      <div class="card-h"><h3>邮件提醒（SMTP）</h3>
        <span :class="['badge', cfg?.mail?.enabled ? 'badge-success' : '']">
          {{ cfg?.mail?.enabled ? '已启用' : '未启用' }}</span></div>
      <p class="small muted mb-3">日程到期可通过邮件提醒（QQ/163 等邮箱在设置中开启 SMTP 并获取授权码）。</p>
      <div class="fgrid">
        <div class="field full"><label class="checkbox">
          <input type="checkbox" v-model="form.mail.enabled" /><span>启用邮件提醒</span></label></div>
        <div class="field"><label>SMTP 服务器</label><input class="input" v-model="form.mail.smtp_host" placeholder="smtp.qq.com" /></div>
        <div class="field"><label>端口</label><input class="input" type="number" v-model="form.mail.smtp_port" /></div>
        <div class="field"><label>发件邮箱</label><input class="input" v-model="form.mail.username" /></div>
        <div class="field"><label>授权码</label>
          <input class="input" type="password" v-model="form.mail.password"
                 :placeholder="cfg?.mail?.password_saved ? '已保存，留空则不修改' : ''" /></div>
        <div class="field"><label>默认收件人</label><input class="input" v-model="form.mail.to_addr" placeholder="you@example.com" /></div>
        <div class="field"><label>发件人名称</label><input class="input" v-model="form.mail.from_name" /></div>
      </div>
    </div>

    <div class="card">
      <div class="card-h"><h3>发票邮箱（IMAP）</h3>
        <span :class="['badge', cfg?.invoice?.enabled ? 'badge-success' : '']">
          {{ cfg?.invoice?.enabled ? '已启用' : '未启用' }}</span></div>
      <div class="fgrid">
        <div class="field full"><label class="checkbox">
          <input type="checkbox" v-model="form.invoice.enabled" /><span>启用邮箱自动收取</span></label></div>
        <div class="field"><label>IMAP 服务器</label><input class="input" v-model="form.invoice.imap_host" /></div>
        <div class="field"><label>端口</label><input class="input" type="number" v-model="form.invoice.imap_port" /></div>
        <div class="field"><label>邮箱账号</label><input class="input" v-model="form.invoice.username" /></div>
        <div class="field"><label>授权码</label>
          <input class="input" type="password" v-model="form.invoice.password"
                 :placeholder="cfg?.invoice?.password_saved ? '已保存，留空则不修改' : ''" /></div>
        <div class="field"><label>回溯天数</label><input class="input" type="number" v-model="form.invoice.days" /></div>
        <div class="field"><label>轮询间隔（分钟）</label>
          <input class="input" type="number" v-model="form.invoice.interval_minutes" /></div>
        <div class="field full"><label>识别关键词</label><input class="input" v-model="form.invoice.keywords" /></div>
      </div>
      <div class="tiny dim mt-3">详细收取与推送设置在「发票管理 → 邮箱设置」页，两处共用同一配置。</div>
    </div>
  </div>

  <!-- 系统 -->
  <div v-else class="grid g-2">
    <div class="card">
      <div class="card-h"><h3>后台任务</h3></div>
      <div v-for="t in (scheduler?.tasks || [])" :key="t.name" class="row between"
           style="padding:6px 0;border-bottom:1px solid var(--border)">
        <div>
          <div style="font-weight:600;font-size:13px">{{ t.name }}</div>
          <div class="tiny dim">每 {{ Math.round(t.interval/60) }} 分钟 · 上次 {{ t.last_run || '未运行' }}</div>
        </div>
        <span :class="['badge', t.ok===false ? 'badge-danger' : t.ok ? 'badge-success' : '']">
          {{ t.ok===false ? '异常' : t.ok ? '正常' : '待运行' }}</span>
      </div>
      <div v-if="!(scheduler?.tasks||[]).length" class="tiny dim">调度器未启动</div>
    </div>
    <div class="card">
      <div class="card-h"><h3>安全设计</h3></div>
      <div class="small muted" style="line-height:1.9">
        · 服务仅监听 <code class="mono">127.0.0.1</code>，局域网与公网均不可访问；<br>
        · 随机访问令牌，Tauri 外壳由进程注入、不落盘；<br>
        · Host 白名单防 DNS-rebind 攻击；<br>
        · 飞书 / 微信 / 邮箱密钥经 Fernet 加密后仅存本机；<br>
        · 未启用的集成不发起任何外网请求；<br>
        · 全部敏感操作写入审计日志。
      </div>
    </div>
    <div class="card" style="grid-column:1/-1">
      <div class="card-h"><h3>审计日志</h3><span class="sub">最近 {{ audit.length }} 条</span></div>
      <pre style="max-height:300px;overflow:auto;font-size:11.5px;line-height:1.7;color:var(--text-2);font-family:var(--font-mono)">{{ audit.join('\\n') || '暂无日志' }}</pre>
    </div>
  </div>
</div>`,
};
