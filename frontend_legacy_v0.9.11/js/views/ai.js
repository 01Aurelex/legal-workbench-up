/* AI 助手：统一对话 · 上传文档处理 · 调用本地文档 · 全文搜索 · 流式输出 */
import { ref, reactive, computed, onMounted, nextTick } from 'vue';
import { api, store, md, esc, relTime } from '../core.js';
import { toast, toastOk, toastErr, modal, prompt, confirm } from '../ui.js';

export default {
  name: 'AiView',
  setup() {
    const sessions = ref([]);
    const current = ref(null);
    const messages = ref([]);
    const input = ref('');
    const streaming = ref(false);
    const model = ref('');
    const hub = ref(null);            // { status, providers, quick }
    const refs = ref([]);             // 挂载的本地文档路径
    const docs = ref([]);             // 本次上传的文档 [{name,text}]
    const notes = ref([]);
    const logEl = ref(null);
    const showCtx = ref(false);
    const ctxKeyword = ref('');
    const elapsed = ref(0);
    const lastEvidence = ref([]);
    // 全文搜索
    const searchQ = ref('');
    const searchResults = ref([]);
    const searching = ref(false);
    const showSearch = ref(false);
    const uploading = ref(false);
    const fileInput = ref(null);

    async function loadHub() {
      try { hub.value = await api.get('/api/ai/hub-status'); model.value = model.value || hub.value.status.model; }
      catch (e) { toastErr(e.message); }
    }

    async function loadSessions() {
      sessions.value = (await api.get('/api/ai/sessions')).sessions;
    }

    async function openSession(s) {
      current.value = s;
      messages.value = (await api.get('/api/ai/sessions/' + s.id)).messages;
      model.value = s.model || model.value;
      scroll();
    }

    async function newSession() {
      const s = (await api.post('/api/ai/sessions', { model: model.value })).session;
      await loadSessions();
      await openSession(s);
    }

    async function delSession(s) {
      const okd = await confirm({ title: '删除会话', danger: true, okText: '删除',
        message: `确定删除会话「${s.title}」及其全部消息？` });
      if (!okd) return;
      await api.del('/api/ai/sessions/' + s.id);
      if (current.value?.id === s.id) { current.value = null; messages.value = []; }
      loadSessions();
    }

    async function renameSession(s) {
      const t = await prompt({ title: '重命名会话', label: '会话名称', value: s.title });
      if (!t) return;
      await api.patch('/api/ai/sessions/' + s.id, { title: t });
      loadSessions();
      if (current.value?.id === s.id) current.value.title = t;
    }

    function scroll() {
      nextTick(() => {
        if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight;
      });
    }

    /* ---------- 上传文档 ---------- */
    function pickFile() { fileInput.value?.click(); }
    async function onFile(ev) {
      const f = ev.target.files?.[0];
      ev.target.value = '';
      if (!f) return;
      uploading.value = true;
      try {
        const fd = new FormData();
        fd.append('file', f);
        fd.append('save_to_vault', '材料');
        const r = await api.upload('/api/ai/upload', fd);
        docs.value.push({ name: r.name, text: r.text, rel_path: r.rel_path });
        toastOk(`已解析「${r.name}」（${r.engine}，${r.text.length} 字）${r.rel_path ? '，原件已存入档案库材料' : ''}`);
      } catch (e) { toastErr(e.message); }
      uploading.value = false;
    }
    function removeDoc(i) { docs.value.splice(i, 1); }

    /* ---------- 全文搜索本地文档 ---------- */
    async function runSearch() {
      const q = searchQ.value.trim();
      if (!q) return;
      searching.value = true;
      try {
        const r = await api.get('/api/ai/search?q=' + encodeURIComponent(q));
        searchResults.value = r.hits || [];
      } catch (e) { toastErr(e.message); }
      searching.value = false;
    }
    function mountResult(h) {
      if (!refs.value.includes(h.rel_path)) refs.value.push(h.rel_path);
      toastOk(`已挂载「${h.title}」作为上下文`);
    }

    /* ---------- 发送 ---------- */
    async function send() {
      const q = input.value.trim();
      if (!q || streaming.value) return;
      if (!current.value) await newSession();

      input.value = '';
      messages.value.push({ role: 'user', content: q, docs: docs.value.slice() });
      const ai = { role: 'assistant', content: '', streaming: true, evidence: [] };
      messages.value.push(ai);
      streaming.value = true;
      elapsed.value = 0;
      const t0 = Date.now();
      const timer = setInterval(() => { elapsed.value = ((Date.now() - t0) / 1000).toFixed(1); }, 100);

      try {
        await api.stream('/api/ai/stream', {
          session_id: current.value.id, question: q, refs: refs.value,
          docs: docs.value.map((d) => ({ name: d.name, text: d.text })), model: model.value,
        }, (ev) => {
          if (ev.type === 'meta') {
            ai.evidence = ev.evidence || [];
            lastEvidence.value = ev.evidence || [];
          } else if (ev.type === 'delta') {
            ai.content += ev.text || '';
            scroll();
          } else if (ev.type === 'done') {
            ai.content = ev.text || ai.content;
            ai.elapsed = ev.elapsed;
          } else if (ev.type === 'error') {
            ai.content = '（提示）' + (ev.error || '模型服务不可用');
            toastErr(ev.error || '请求失败');
          }
        });
      } catch (e) {
        ai.content = '（提示）' + e.message;
      }
      clearInterval(timer);
      ai.streaming = false;
      streaming.value = false;
      docs.value = [];   // 上传的文档仅作用于本次对话，避免累积污染后续提问
      scroll();
      loadSessions();
    }

    function onKey(e) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    }

    async function useQuick(a) {
      const sel = window.getSelection()?.toString()?.trim();
      const last = [...messages.value].reverse().find((m) => m.role === 'assistant' && m.content);
      const body = sel || (last ? last.content.slice(0, 3000) : '');
      if (!body) return toastErr('请先上传文档、挂载本地资料，或在页面上选中一段文字');
      input.value = a.prompt + body;
      await nextTick();
      document.querySelector('.chat-input-box textarea')?.focus();
    }

    async function loadNotes() {
      try { notes.value = (await api.get('/api/archive/table?limit=400')).rows; }
      catch { notes.value = []; }
    }

    const filteredNotes = computed(() => {
      const k = ctxKeyword.value.trim().toLowerCase();
      if (!k) return notes.value.slice(0, 60);
      return notes.value.filter((n) => n.rel_path.toLowerCase().includes(k)
        || (n.title || '').toLowerCase().includes(k)).slice(0, 60);
    });

    function toggleRef(path) {
      const i = refs.value.indexOf(path);
      if (i >= 0) refs.value.splice(i, 1); else refs.value.push(path);
    }

    const rendered = (m) => md(m.content);

    async function applySettings() {
      if (!current.value) return;
      await api.patch('/api/ai/sessions/' + current.value.id, { model: model.value });
    }

    onMounted(async () => {
      await loadHub();
      await loadSessions();
      await loadNotes();
      if (sessions.value.length) openSession(sessions.value[0]);
    });

    return {
      sessions, current, messages, input, streaming, model, hub, refs, docs,
      showCtx, ctxKeyword, filteredNotes, elapsed, logEl, fileInput, uploading,
      searchQ, searchResults, searching, showSearch,
      openSession, newSession, delSession, renameSession, send, onKey,
      useQuick, toggleRef, rendered, applySettings, loadHub, pickFile, onFile,
      removeDoc, runSearch, mountResult,
      quick: computed(() => hub.value?.quick || []),
      models: computed(() => hub.value?.status?.models || []),
      online: computed(() => hub.value?.status?.reachable),
      relTime,
    };
  },
  template: `
<div class="view flat">
  <div class="chat-layout">
    <!-- 会话列表 -->
    <div class="chat-side">
      <div style="padding:12px;border-bottom:1px solid var(--border)">
        <button class="btn btn-primary" style="width:100%" @click="newSession()">新建对话</button>
      </div>
      <div class="chat-list">
        <div v-for="s in sessions" :key="s.id" :class="['chat-item', current?.id===s.id?'active':'']"
             @click="openSession(s)" @contextmenu.prevent="renameSession(s)">
          <div class="t">{{ s.title }}</div>
          <div class="m">{{ relTime(s.updated) }}</div>
        </div>
        <div v-if="!sessions.length" class="empty" style="padding:20px">
          <div class="t tiny">暂无会话</div></div>
      </div>
      <div style="padding:10px;border-top:1px solid var(--border)" class="col gap-2">
        <div class="row between tiny">
          <span class="dim">模型服务</span>
          <span :class="['badge', online ? 'badge-success' : 'badge-warn']">
            {{ online ? '已连接' : '未连接' }}</span>
        </div>
        <select class="select" style="height:28px;font-size:12px" v-model="model" @change="applySettings()">
          <option :value="model">{{ model || '默认模型' }}</option>
          <option v-for="m in models" :key="m" :value="m">{{ m }}</option>
        </select>
        <div class="tiny dim" style="line-height:1.5">
          未连接时仍可检索法律库与档案库；在「设置 → AI 模型」中配置本机 Ollama 或兼容端点。
        </div>
      </div>
    </div>

    <!-- 对话区 -->
    <div class="chat-main">
      <div class="tabbar">
        <div class="tab active">AI 助手</div>
        <div class="row gap-2" style="margin-left:auto">
          <button class="btn btn-sm" @click="showSearch = !showSearch">搜索本地文档</button>
          <button class="btn btn-sm" @click="showCtx = !showCtx">
            本地资料 <span class="badge" v-if="refs.length">{{ refs.length }}</span></button>
          <button class="btn btn-sm btn-ghost" v-if="current" @click="delSession(current)">删除会话</button>
        </div>
      </div>

      <!-- 全文搜索面板 -->
      <div v-if="showSearch" style="border-bottom:1px solid var(--border);background:var(--bg-1);padding:12px 16px;max-height:260px;overflow:auto">
        <div class="row gap-2 mb-2">
          <input class="input grow" style="height:30px" placeholder="搜索本地档案库文档（含正文内容）…"
                 v-model="searchQ" @keyup.enter="runSearch()" />
          <button class="btn btn-sm btn-primary" @click="runSearch()">{{ searching ? '搜索中…' : '搜索' }}</button>
        </div>
        <div v-if="searchResults.length" class="col" style="gap:4px">
          <div v-for="h in searchResults" :key="h.rel_path" class="li" style="padding:8px 10px">
            <div class="li-main">
              <div class="li-t ellip">{{ h.title }} <span class="badge badge-primary">{{ h.ftype }}</span></div>
              <div class="li-s clamp2">{{ h.snippet }}</div>
            </div>
            <button class="btn btn-sm" @click="mountResult(h)">挂载</button>
          </div>
        </div>
        <div v-else-if="!searching" class="tiny dim">输入关键词搜索本地档案库正文，命中后可「挂载」供 AI 引用。</div>
      </div>

      <!-- 本地资料抽屉 -->
      <div v-if="showCtx" style="border-bottom:1px solid var(--border);background:var(--bg-1);padding:12px 16px;max-height:230px;overflow:auto">
        <div class="row between mb-2">
          <b class="small">挂载本地资料作为上下文（仅本机读取）</b>
          <input class="input" style="width:200px;height:26px" placeholder="筛选笔记/案件…" v-model="ctxKeyword" />
        </div>
        <div class="row gap-2 wrap">
          <span v-for="n in filteredNotes" :key="n.rel_path"
                :class="['chip', refs.includes(n.rel_path) ? 'on' : '']"
                @click="toggleRef(n.rel_path)" :title="n.rel_path">
            {{ n.title }}
          </span>
          <span v-if="!filteredNotes.length" class="tiny dim">无匹配档案</span>
        </div>
      </div>

      <!-- 已上传文档条 -->
      <div v-if="docs.length" style="border-bottom:1px solid var(--border);background:var(--bg-1);padding:8px 16px" class="col gap-1">
        <div v-for="(d, i) in docs" :key="i" class="row between" style="font-size:12.5px">
          <span><b>{{ d.name }}</b> <span class="tiny dim">{{ d.text.length }} 字</span></span>
          <button class="btn btn-sm btn-ghost" @click="removeDoc(i)">移除</button>
        </div>
      </div>

      <div class="chat-log" ref="logEl">
        <div class="chat-inner">
          <div v-if="!messages.length" class="empty" style="padding:60px 20px">
            <div class="ico" style="font-size:34px">◇</div>
            <div class="t">有什么可以帮你的？</div>
            <div class="d">
              上传文档按你的要求处理（归纳、审查、起草、改写、翻译…），
              或挂载/搜索本地档案库资料，AI 会结合本地法律库自动作答。
            </div>
            <div class="row gap-2 wrap mt-3" style="justify-content:center">
              <span v-for="q in quick" :key="q.key" class="chip" @click="useQuick(q)">{{ q.label }}</span>
            </div>
          </div>

          <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
            <div class="av">{{ m.role === 'user' ? '我' : 'AI' }}</div>
            <div class="bubble">
              <div class="who">{{ m.role === 'user' ? '我' : (model || 'AI 助手') }}</div>
              <div v-if="m.role==='user' && m.docs?.length" class="tiny dim" style="margin-bottom:6px">
                附件：{{ m.docs.map(d => d.name).join('、') }}
              </div>
              <div v-if="m.role==='assistant' && m.streaming && !m.content" class="typing"><i></i><i></i><i></i></div>
              <div v-else class="txt md-body" v-html="rendered(m)"></div>
              <div v-if="m.streaming && elapsed" class="tiny dim mt-2">生成中… {{ elapsed }}s</div>
              <div v-else-if="m.elapsed" class="tiny dim mt-2">{{ m.elapsed }}s</div>
              <div v-if="m.evidence?.length" class="evidence">
                <div class="eh">引用依据（本地检索）</div>
                <div v-for="(e, j) in m.evidence" :key="j" class="ei">
                  · {{ e.law }} {{ e.article === e.law ? '' : '· ' + e.article }}
                  <span v-if="e.text && e.text.length < 90">— {{ e.text }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input-wrap">
        <div class="chat-input-box">
          <input ref="fileInput" type="file" hidden
                 accept=".md,.txt,.docx,.doc,.pdf,.png,.jpg,.jpeg,.bmp,.webp"
                 @change="onFile" />
          <div class="ci-top">
            <button class="chat-add spot" :disabled="uploading" @click="pickFile()"
                    title="上传文档（支持 Word/PDF/TXT/Markdown/图片，本地解析后随问题一起发送）">
              {{ uploading ? '…' : '＋' }}</button>
            <textarea v-model="input" placeholder="输入问题，Enter 发送，Shift+Enter 换行；点左侧 ＋ 上传文档…"
                      @keydown="onKey"></textarea>
          </div>
          <div class="ci-foot">
            <div class="row gap-1 wrap grow">
              <span v-for="q in quick.slice(0, 4)" :key="q.key" class="chip" @click="useQuick(q)">{{ q.label }}</span>
            </div>
            <span class="tiny dim" v-if="refs.length">{{ refs.length }} 个上下文</span>
            <span class="tiny dim" v-else-if="docs.length">{{ docs.length }} 个文档</span>
            <button class="btn btn-primary" :disabled="streaming || !input.trim()" @click="send()">
              <span v-if="streaming" class="spinner"></span>{{ streaming ? '生成中' : '发送' }}
            </button>
          </div>
        </div>
        <div class="tiny dim" style="max-width:820px;margin:6px auto 0">
          AI 输出仅供参考，须经执业律师独立判断后使用；法律问题优先依据本地法律库原文，无依据会明确说明。
        </div>
      </div>
    </div>
  </div>
</div>`,
};
