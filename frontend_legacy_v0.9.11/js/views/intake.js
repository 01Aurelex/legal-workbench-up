/* 接案笔录（v0.9.8）：录音/导入 → 本地转写 → 角色校对 → 要素提取 → 生成 Word 笔录 */
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue';
import { api, bootstrap } from '../core.js';
import { toast, toastOk, toastErr, confirm } from '../ui.js';

const ROLES = [
  { k: 'lawyer', n: '律师' },
  { k: 'client', n: '当事人' },
  { k: 'other', n: '其他' },
];
const roleName = (k) => ({ lawyer: '律师', client: '当事人', other: '其他' }[k] || '其他');

function emptyMeta() {
  return { client: '', gender: '', id_no: '', phone: '', address: '', work_unit: '',
    cause: '', claims: '', facts: '', evidence: '', materials: '', risk_notes: '',
    lawyer: '', recorder: '', location: '' };
}
function fmtDuration(sec) {
  sec = Math.round(sec || 0);
  const m = String(Math.floor(sec / 60)).padStart(2, '0');
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}

export default {
  name: 'IntakeView',
  setup() {
    /* ---------- 录音前信息 ---------- */
    const head = reactive({ client: '', lawyer: '', recorder: '', location: '' });

    /* ---------- 录音状态 ---------- */
    const recState = ref('idle');           // idle | recording | paused | processing
    const recSeconds = ref(0);
    const level = ref(0);
    let mediaStream = null, mediaRec = null, chunks = [], timerId = null, rafId = null, audioCtx = null;
    const startedAtIso = ref('');
    const fileInput = ref(null);

    /* ---------- 转写结果 / 校对 ---------- */
    const draftId = ref(0);
    const turns = ref([]);
    const meta = reactive(emptyMeta());
    const engines = reactive({ role: '', fact: '', stt: '' });
    const genState = ref('');               // '' | generating | done
    const lastDocx = ref('');
    const history = ref([]);

    const hasDraft = computed(() => draftId.value > 0);
    const roleColor = (k) => ({ lawyer: 'badge-primary', client: 'badge-accent', other: 'badge' }[k] || 'badge');

    /* ================= 录音 ================= */
    function tick() { recSeconds.value += 1; }
    function startMeter() {
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const src = audioCtx.createMediaStreamSource(mediaStream);
        const an = audioCtx.createAnalyser();
        an.fftSize = 256;
        src.connect(an);
        const buf = new Uint8Array(an.frequencyBinCount);
        const loop = () => {
          an.getByteFrequencyData(buf);
          let v = 0;
          for (let i = 0; i < buf.length; i++) v += buf[i];
          level.value = Math.min(1, v / buf.length / 90);
          rafId = requestAnimationFrame(loop);
        };
        loop();
      } catch { /* 电平表不影响录音主流程 */ }
    }

    async function startRecord() {
      if (!navigator.mediaDevices?.getUserMedia) {
        toastErr('当前环境不支持麦克风录音，可使用「导入音频文件」');
        return;
      }
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (e) {
        toastErr('无法获取麦克风权限：' + (e.message || e) + '，请在浏览器/系统设置中允许后重试，或改用导入音频');
        return;
      }
      chunks = [];
      const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
        .find((m) => MediaRecorder.isTypeSupported?.(m)) || '';
      mediaRec = new MediaRecorder(mediaStream, mime ? { mimeType: mime } : undefined);
      mediaRec.ondataavailable = (e) => { if (e.data?.size) chunks.push(e.data); };
      mediaRec.onstop = onRecordStop;
      startedAtIso.value = new Date().toISOString();
      mediaRec.start(250);
      recSeconds.value = 0;
      timerId = setInterval(tick, 1000);
      startMeter();
      recState.value = 'recording';
      toastOk('已开始录音，谈话内容仅保存在本机');
    }

    function pauseRecord() {
      if (!mediaRec) return;
      if (mediaRec.state === 'recording') { mediaRec.pause(); recState.value = 'paused'; clearInterval(timerId); }
      else { mediaRec.resume(); recState.value = 'recording'; timerId = setInterval(tick, 1000); }
    }

    function stopRecord() {
      if (!mediaRec) return;
      recState.value = 'processing';
      clearInterval(timerId);
      if (rafId) cancelAnimationFrame(rafId);
      try { mediaStream?.getTracks().forEach((t) => t.stop()); } catch { /* ignore */ }
      try { audioCtx?.close(); } catch { /* ignore */ }
      mediaRec.stop();
    }

    async function onRecordStop() {
      const blob = new Blob(chunks, { type: mediaRec.mimeType || 'audio/webm' });
      chunks = [];
      if (blob.size < 800) { toastErr('录音时长过短，未生成有效音频'); resetRecorder(); return; }
      const ext = (blob.type.includes('ogg') ? '.ogg' : blob.type.includes('mp4') ? '.m4a' : '.webm');
      await uploadAndTranscribe(new File([blob], `intake_${Date.now()}${ext}`, { type: blob.type }));
    }

    function pickFile() { fileInput.value?.click(); }
    async function onFilePick(e) {
      const f = e.target.files?.[0];
      e.target.value = '';
      if (!f) return;
      startedAtIso.value = new Date().toISOString();
      await uploadAndTranscribe(f);
    }

    async function uploadAndTranscribe(file) {
      recState.value = 'processing';
      const fd = new FormData();
      fd.append('file', file);
      fd.append('started_at', startedAtIso.value || new Date().toISOString());
      fd.append('client', head.client);
      fd.append('lawyer', head.lawyer);
      fd.append('recorder', head.recorder);
      fd.append('location', head.location);
      try {
        const r = await api.upload('/api/intake/transcribe', fd);
        if (!r.ok && !(r.turns || []).length) { toastErr(r.error || '转写失败'); resetRecorder(); return; }
        draftId.value = r.id;
        applyResult(r);
        if (r.error) toastErr('录音已保存，但转写未成功：' + r.error + '，可点「重新转写分析」重试');
        else toastOk(`转写完成，共 ${turns.value.length} 段，请校对角色与内容`);
      } catch (e) { toastErr(e.message); resetRecorder(); }
      recState.value = 'idle';
    }

    function applyResult(r) {
      turns.value = (r.turns || []).map((t) => ({ ...t }));
      Object.assign(meta, emptyMeta(), r.meta || {});
      head.client = meta.client || head.client;
      head.lawyer = meta.lawyer || head.lawyer;
      head.recorder = meta.recorder || head.recorder;
      head.location = meta.location || head.location;
      engines.role = r.role_engine || '';
      engines.fact = r.fact_engine || '';
      engines.stt = r.engine || '';
      genState.value = '';
      lastDocx.value = '';
    }

    function resetRecorder() {
      recState.value = 'idle';
      recSeconds.value = 0;
      level.value = 0;
    }

    /* ================= 校对编辑 ================= */
    function cycleRole(t) {
      const order = ['lawyer', 'client', 'other'];
      t.role = order[(order.indexOf(t.role) + 1) % 3];
    }
    function setRoleAll(role) { turns.value.forEach((t) => (t.role = role)); }
    function removeTurn(i) { turns.value.splice(i, 1); }
    function addTurn() { turns.value.push({ role: 'client', start: 0, end: 0, text: '' }); }
    function moveTurn(i, d) {
      const j = i + d;
      if (j < 0 || j >= turns.value.length) return;
      const arr = turns.value;
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }

    async function reAnalyze() {
      if (!draftId.value) { toastErr('请先录音或导入音频'); return; }
      const old = recState.value;
      recState.value = 'processing';
      try {
        const r = await api.post('/api/intake/retranscribe', { id: draftId.value });
        if (!r.ok) { toastErr(r.error || '重新分析失败'); return; }
        applyResult(r);
        toastOk('已重新转写并完成角色区分、要素提取');
      } catch (e) { toastErr(e.message); } finally { recState.value = old === 'processing' ? 'idle' : old; }
    }

    /* ================= 生成 Word ================= */
    async function generate() {
      if (!draftId.value) { toastErr('暂无转写内容'); return; }
      meta.client = meta.client || head.client;
      meta.lawyer = meta.lawyer || head.lawyer;
      meta.recorder = meta.recorder || head.recorder;
      meta.location = meta.location || head.location;
      genState.value = 'generating';
      try {
        const r = await api.post('/api/intake/generate', {
          id: draftId.value, meta: { ...meta }, turns: turns.value,
        });
        if (!r.ok) { toastErr(r.error || '生成失败'); return; }
        genState.value = 'done';
        lastDocx.value = r.docx_name;
        toastOk('接案笔录 Word 已生成并归档');
        loadHistory();
      } catch (e) { toastErr(e.message); } finally { genState.value = genState.value === 'generating' ? '' : genState.value; }
    }

    async function openRec(target) {
      if (!draftId.value) return;
      const r = await api.post('/api/intake/open', { id: draftId.value, target });
      if (!r.ok) toastErr(r.error || '打开失败');
    }

    /* ================= 历史 ================= */
    async function loadHistory() {
      try {
        const r = await api.get('/api/intake/list');
        history.value = r.rows || [];
      } catch (e) {
        // 首屏令牌竞态时延迟重试一次
        setTimeout(async () => {
          try { const r = await api.get('/api/intake/list'); history.value = r.rows || []; }
          catch { /* 静默，用户可手动刷新 */ }
        }, 600);
      }
    }
    async function editRow(row) {
      const r = await api.get(`/api/intake/get?id=${row.id}`);
      if (!r.ok) { toastErr(r.error); return; }
      draftId.value = r.record.id;
      turns.value = r.record.turns || [];
      Object.assign(meta, emptyMeta(), r.record.meta || {});
      Object.assign(head, {
        client: r.record.client || meta.client, lawyer: r.record.lawyer || meta.lawyer,
        recorder: r.record.recorder || meta.recorder, location: r.record.location || meta.location,
      });
      lastDocx.value = r.record.docx_path ? r.record.docx_path.split('/').pop() : '';
      genState.value = r.record.status === 'done' ? 'done' : '';
      window.scrollTo({ top: 0, behavior: 'smooth' });
      toast('已载入该笔录，可继续校对后重新生成');
    }
    async function openRow(row, target) {
      const r = await api.post('/api/intake/open', { id: row.id, target });
      if (!r.ok) toastErr(r.error);
    }
    async function delRow(row) {
      const ok = await confirm({ title: '删除接案笔录', danger: true, okText: '删除',
        message: `确定删除「${row.client || '未命名'} · ${row.started_at || ''}」吗？将同时删除本地录音、转写稿与 Word 笔录，此操作不可恢复。` });
      if (!ok) return;
      const r = await api.post('/api/intake/delete', { id: row.id, delete_files: true });
      if (r.ok) { toastOk('已删除'); if (draftId.value === row.id) newDraft(); loadHistory(); }
      else toastErr(r.error);
    }
    function newDraft() {
      draftId.value = 0; turns.value = []; Object.assign(meta, emptyMeta());
      genState.value = ''; lastDocx.value = '';
    }

    let autoTimer = null;
    onMounted(() => { bootstrap().then(loadHistory).catch(loadHistory); });
    onBeforeUnmount(() => {
      clearInterval(timerId); clearInterval(autoTimer);
      try { mediaStream?.getTracks().forEach((t) => t.stop()); } catch { /* ignore */ }
    });

    return {
      head, recState, recSeconds, level, draftId, turns, meta, engines, genState,
      lastDocx, history, hasDraft, ROLES, roleName, roleColor, fmtDuration, fileInput,
      startRecord, pauseRecord, stopRecord, pickFile, onFilePick,
      cycleRole, setRoleAll, removeTurn, addTurn, moveTurn, reAnalyze,
      generate, openRec, loadHistory, editRow, openRow, delRow, newDraft,
    };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div>
      <h1>接案笔录</h1>
      <div class="desc">全程本机录音转写 · 智能区分律师/当事人 · 按律协接待谈话笔录规范生成可编辑 Word</div>
    </div>
    <div class="actions">
      <button class="btn" @click="newDraft" v-if="hasDraft">＋ 新建一份</button>
      <button class="btn" @click="loadHistory">刷新</button>
    </div>
  </div>

  <div class="grid g-main">
    <div class="col-4">
      <!-- 1. 接待信息与录音 -->
      <div class="card">
        <div class="card-h"><h3>一、接待信息与录音</h3><span class="sub">录音仅保存在本机 data/vault</span></div>
        <div class="fgrid">
          <div class="field"><label>当事人</label><input class="input" v-model="head.client" placeholder="姓名 / 单位名称" /></div>
          <div class="field"><label>接待律师</label><input class="input" v-model="head.lawyer" /></div>
          <div class="field"><label>记录人</label><input class="input" v-model="head.recorder" /></div>
          <div class="field"><label>接待地点</label><input class="input" v-model="head.location" placeholder="如：律所三号会议室" /></div>
        </div>

        <div class="intake-rec mt-4">
          <template v-if="recState==='idle'">
            <button class="btn btn-primary btn-lg" @click="startRecord">开始录音</button>
            <button class="btn btn-lg" @click="pickFile">导入音频文件转写</button>
            <input ref="fileInput" type="file" accept="audio/*,.webm,.wav,.mp3,.m4a,.ogg,.aac,.flac,.mp4"
                   style="display:none" @change="onFilePick" />
            <span class="field-hint">支持麦克风直录（webm/opus）或导入手机录音笔文件（wav/mp3/m4a 等）</span>
          </template>
          <template v-else-if="recState==='processing'">
            <span class="spinner"></span>
            <span>正在本地转写并分析角色、提取要素，长录音可能需要数分钟，请勿关闭页面…</span>
          </template>
          <template v-else>
            <div class="intake-live">
              <span class="rec-dot" :class="{paused:recState==='paused'}"></span>
              <span class="mono" style="font-size:22px">{{ fmtDuration(recSeconds) }}</span>
              <span class="intake-meter"><i :style="{width:Math.round(level*100)+'%'}"></i></span>
              <button class="btn" @click="pauseRecord">{{ recState==='paused' ? '继续' : '暂停' }}</button>
              <button class="btn btn-primary" @click="stopRecord">结束并转写</button>
            </div>
          </template>
        </div>
      </div>

      <!-- 2. 转写校对 -->
      <div class="card" v-if="hasDraft">
        <div class="card-h">
          <h3>二、谈话内容校对</h3>
          <div class="row-3">
            <span class="badge" v-if="engines.role">角色区分：{{ engines.role==='llm' ? '本地大模型' : '启发式（未连模型）' }}</span>
            <button class="btn btn-sm" @click="reAnalyze" :disabled="recState==='processing'">重新转写分析</button>
          </div>
        </div>
        <div class="row-3 mb-3 wrap">
          <span class="small muted">点击角色标签可在 律师/当事人/其他 间切换，文字可直接修改：</span>
          <button class="btn btn-sm btn-ghost" @click="setRoleAll('lawyer')">全部标为律师</button>
          <button class="btn btn-sm btn-ghost" @click="setRoleAll('client')">全部标为当事人</button>
          <button class="btn btn-sm btn-ghost" @click="addTurn">＋ 增补一段</button>
        </div>
        <div class="intake-turns">
          <div v-for="(t,i) in turns" :key="i" class="intake-turn">
            <div class="intake-turn-h">
              <button class="badge" :class="roleColor(t.role)" @click="cycleRole(t)">{{ roleName(t.role) }}</button>
              <span class="dim tiny mono">{{ fmtDuration(t.start) }}–{{ fmtDuration(t.end) }}</span>
              <span style="margin-left:auto" class="row">
                <button class="tbtn" title="上移" @click="moveTurn(i,-1)">上移</button>
                <button class="tbtn" title="下移" @click="moveTurn(i,1)">下移</button>
                <button class="tbtn tbtn-close" title="删除本段" @click="removeTurn(i)">×</button>
              </span>
            </div>
            <textarea class="textarea" rows="2" v-model="t.text"></textarea>
          </div>
          <div v-if="!turns.length" class="empty"><div class="d">没有识别出文字，可点「增补一段」手工补记</div></div>
        </div>
      </div>

      <!-- 3. 要素归纳 -->
      <div class="card" v-if="hasDraft">
        <div class="card-h"><h3>三、笔录要素（{{ engines.fact==='llm' ? '本地大模型已预填' : '未连接模型，请手工填写' }}）</h3></div>
        <div class="fgrid">
          <div class="field"><label>当事人姓名/名称</label><input class="input" v-model="meta.client" /></div>
          <div class="field"><label>性别</label><input class="input" v-model="meta.gender" /></div>
          <div class="field"><label>联系电话</label><input class="input" v-model="meta.phone" /></div>
          <div class="field"><label>证件号码</label><input class="input" v-model="meta.id_no" /></div>
          <div class="field"><label>工作单位</label><input class="input" v-model="meta.work_unit" /></div>
          <div class="field"><label>案由/咨询事项</label><input class="input" v-model="meta.cause" /></div>
          <div class="field full"><label>住址/住所地</label><input class="input" v-model="meta.address" /></div>
          <div class="field full"><label>主要事实经过</label><textarea class="textarea" rows="3" v-model="meta.facts"></textarea></div>
          <div class="field full"><label>现有证据</label><textarea class="textarea" rows="2" v-model="meta.evidence" placeholder="多项以分号分隔"></textarea></div>
          <div class="field full"><label>当事人诉求</label><textarea class="textarea" rows="2" v-model="meta.claims"></textarea></div>
          <div class="field full"><label>需补充材料</label><textarea class="textarea" rows="2" v-model="meta.materials"></textarea></div>
          <div class="field full"><label>本案特别风险提示</label><textarea class="textarea" rows="2" v-model="meta.risk_notes"></textarea></div>
        </div>

        <div class="row-3 mt-4 wrap">
          <button class="btn btn-primary btn-lg" @click="generate" :disabled="genState==='generating'">
            {{ genState==='generating' ? '正在生成…' : '生成接案笔录 Word' }}
          </button>
          <button class="btn" v-if="genState==='done'" @click="openRec('docx')">打开 Word 笔录</button>
          <button class="btn" v-if="genState==='done'" @click="openRec('audio')">打开录音原件</button>
          <button class="btn" v-if="genState==='done'" @click="openRec('transcript')">打开转写稿</button>
          <span class="small muted" v-if="lastDocx">已归档：{{ lastDocx }}</span>
        </div>
      </div>
    </div>

    <!-- 历史记录 -->
    <div class="col-3">
      <div class="card card-elev">
        <div class="card-h"><h3>历史接案笔录</h3><span class="sub">{{ history.length }} 份</span></div>
        <div class="intake-hist">
          <div v-for="r in history" :key="r.id" class="intake-hrow" @click="editRow(r)">
            <div class="li-t ellip">{{ r.client || '未命名当事人' }}</div>
            <div class="tiny dim">{{ r.started_at || r.created }}</div>
            <div class="row-3 mt-1">
              <span :class="['badge', r.status==='done'?'badge-success':'badge-warn']">
                {{ r.status==='done' ? '已生成' : '待生成' }}
              </span>
              <span class="tiny dim">{{ Math.round(r.duration||0) }}s</span>
            </div>
            <div class="intake-hact" @click.stop>
              <button class="btn btn-sm" @click="openRow(r,'docx')" :disabled="!r.docx_path">Word</button>
              <button class="btn btn-sm" @click="openRow(r,'audio')">录音</button>
              <button class="btn btn-sm btn-danger" @click="delRow(r)">删除</button>
            </div>
          </div>
          <div v-if="!history.length" class="empty"><div class="d">还没有接案笔录</div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-h"><h3>规范依据</h3></div>
        <div class="small muted" style="line-height:1.9">
          笔录要素参照全国律协律师执业行为规范及各地律协民事业务操作指引：时间地点人物、
          当事人身份信息、案情事实、现有证据、诉求、律师分析与风险告知、需补充材料、阅后签名。
          生成的 Word 完全可编辑，签字栏已预留。
        </div>
      </div>
    </div>
  </div>
</div>`,
};
