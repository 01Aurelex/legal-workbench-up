/* UI 服务：Toast / 模态框 / 右键菜单 / 确认框 / 命令面板 */
import { createApp, reactive, h, ref, computed, nextTick } from 'vue';

const state = reactive({
  toasts: [],
  modal: null,          // { title, comp, props, size, resolve }
  ctx: null,            // { x, y, items }
  cmdk: null,           // { items, placeholder }
});

let seed = 0;

/* ========================= Toast ========================= */
export function toast(msg, type = '') {
  const id = ++seed;
  state.toasts.push({ id, msg, type });
  setTimeout(() => {
    const i = state.toasts.findIndex((t) => t.id === id);
    if (i >= 0) state.toasts.splice(i, 1);
  }, type === 'err' ? 4200 : 2600);
}
export const toastOk = (m) => toast(m, 'ok');
export const toastErr = (m) => toast(m, 'err');

/* ========================= 模态框 ========================= */
/**
 * 打开模态框。comp 为 Vue 组件，通过 emit('submit', data) 提交、emit('cancel') 取消。
 * @returns Promise<any> 提交的数据；取消为 null
 */
export function modal({ title, comp, props = {}, size = '' }) {
  return new Promise((resolve) => {
    state.modal = { title, comp, props, size, resolve, done: false };
  });
}

export function closeModal(result = null) {
  if (state.modal && !state.modal.done) {
    state.modal.done = true;
    state.modal.resolve(result);
    state.modal = null;
  }
}

/* ========================= 确认框 ========================= */
export function confirm({ title = '确认操作', message = '', danger = false, okText = '确定' }) {
  return modal({
    title,
    size: '',
    comp: {
      setup() {
        return { message, danger, okText };
      },
      emits: ['submit', 'cancel'],
      template: `
        <div style="font-size:13.5px;line-height:1.7;color:var(--text-2)">{{ message }}</div>
        <div class="modal-f" style="margin:20px -20px -20px">
          <button class="btn" @click="$emit('cancel')">取消</button>
          <button :class="['btn', danger ? 'btn-danger' : 'btn-primary']" @click="$emit('submit', true)">{{ okText }}</button>
        </div>`,
    },
  });
}

export function prompt({ title = '输入', label = '', value = '', placeholder = '' }) {
  return modal({
    title,
    comp: {
      setup() {
        const v = ref(value);
        return { v, label, placeholder };
      },
      emits: ['submit', 'cancel'],
      template: `
        <div class="field">
          <label v-if="label">{{ label }}</label>
          <input class="input" v-model="v" :placeholder="placeholder" @keyup.enter="$emit('submit', v)" ref="ipt" />
        </div>
        <div class="modal-f" style="margin:20px -20px -20px">
          <button class="btn" @click="$emit('cancel')">取消</button>
          <button class="btn btn-primary" @click="$emit('submit', v)">确定</button>
        </div>`,
      mounted() { this.$refs.ipt?.focus(); this.$refs.ipt?.select(); },
    },
  });
}

/* ========================= 右键菜单 ========================= */
export function openCtx(event, items) {
  event.preventDefault();
  event.stopPropagation();
  state.ctx = { x: event.clientX, y: event.clientY, items };
}
export function closeCtx() { state.ctx = null; }

/* ========================= 命令面板 ========================= */
export function openCommand(items) {
  return new Promise((resolve) => {
    state.cmdk = { items, resolve };
  });
}
export function closeCommand(v = null) {
  if (state.cmdk) { state.cmdk.resolve(v); state.cmdk = null; }
}

/* ========================= UI 宿主组件 ========================= */
const UIHost = {
  setup() {
    const ctxStyle = computed(() => {
      if (!state.ctx) return {};
      const w = 190, h = Math.min(state.ctx.items.length * 32 + 12, 460);
      const x = Math.min(state.ctx.x, window.innerWidth - w - 8);
      const y = Math.min(state.ctx.y, window.innerHeight - h - 8);
      return { left: x + 'px', top: y + 'px' };
    });

    const cmdQuery = ref('');
    const cmdIdx = ref(0);
    const cmdList = computed(() => {
      if (!state.cmdk) return [];
      const q = cmdQuery.value.trim().toLowerCase();
      if (!q) return state.cmdk.items.slice(0, 40);
      return state.cmdk.items.filter((i) =>
        (i.title + ' ' + (i.sub || '') + ' ' + (i.keywords || '')).toLowerCase().includes(q)
      ).slice(0, 40);
    });

    function cmdKey(e) {
      const n = cmdList.value.length;
      if (e.key === 'ArrowDown') { cmdIdx.value = (cmdIdx.value + 1) % n; e.preventDefault(); }
      else if (e.key === 'ArrowUp') { cmdIdx.value = (cmdIdx.value - 1 + n) % n; e.preventDefault(); }
      else if (e.key === 'Enter') {
        const it = cmdList.value[cmdIdx.value];
        if (it) { closeCommand(it); }
        e.preventDefault();
      } else if (e.key === 'Escape') { closeCommand(); }
    }

    function cmdOpened(el) {
      el?.querySelector('input')?.focus();
      cmdQuery.value = '';
      cmdIdx.value = 0;
    }

    return { state, closeModal, closeCtx, ctxStyle, cmdQuery, cmdIdx, cmdList, cmdKey, cmdOpened, closeCommand };
  },
  template: `
    <div>
      <!-- Toast -->
      <div class="toasts">
        <TransitionGroup name="pop">
          <div v-for="t in state.toasts" :key="t.id" :class="['toast', t.type]">
            <span>{{ t.msg }}</span>
          </div>
        </TransitionGroup>
      </div>

      <!-- 模态框 -->
      <Transition name="fade">
        <div v-if="state.modal" class="mask" @click.self="closeModal(null)">
          <div :class="['modal', state.modal.size]">
            <div class="modal-h">
              <h3>{{ state.modal.title }}</h3>
              <button class="tbtn tbtn-close" @click="closeModal(null)" aria-label="关闭">×</button>
            </div>
            <div class="modal-b">
              <component
                :is="state.modal.comp"
                v-bind="state.modal.props"
                @submit="closeModal($event)"
                @cancel="closeModal(null)" />
            </div>
          </div>
        </div>
      </Transition>

      <!-- 右键菜单 -->
      <Transition name="fade">
        <div v-if="state.ctx" class="ctx" :style="ctxStyle" @contextmenu.prevent>
          <template v-for="(it, i) in state.ctx.items" :key="i">
            <div v-if="it.sep" class="ctx-sep"></div>
            <div v-else :class="['ctx-item', it.danger ? 'danger' : '']" @click="it.onClick && it.onClick(); closeCtx()">
              <span class="ci-ico" v-if="it.icon">{{ it.icon }}</span>
              <span>{{ it.label }}</span>
              <span v-if="it.hint" class="ci-key">{{ it.hint }}</span>
            </div>
          </template>
        </div>
      </Transition>
      <div v-if="state.ctx" style="position:fixed;inset:0;z-index:199" @click="closeCtx()" @contextmenu.prevent="closeCtx()"></div>

      <!-- 命令面板 -->
      <Transition name="fade">
        <div v-if="state.cmdk" class="mask" style="align-items:flex-start;padding-top:11vh" @click.self="closeCommand()">
          <div class="cmdk" :ref="cmdOpened">
            <input class="cmdk-in" v-model="cmdQuery" placeholder="搜索功能、案件、文书…  Esc 关闭" @keydown="cmdKey" />
            <div class="cmdk-list">
              <div v-for="(it, i) in cmdList" :key="i"
                   :class="['cmdk-item', i === cmdIdx ? 'sel' : '']"
                   @click="closeCommand(it)" @mouseenter="cmdIdx = i">
                <span class="ci-t">{{ it.title }}</span>
                <span class="ci-s">{{ it.sub || '' }}</span>
              </div>
              <div v-if="!cmdList.length" class="empty" style="padding:26px">
                <div class="t">无匹配结果</div>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>`,
};

export function mountUI() {
  const host = document.createElement('div');
  document.body.appendChild(host);
  createApp(UIHost).mount(host);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (state.ctx) closeCtx();
      else if (state.cmdk) closeCommand();
      else if (state.modal) closeModal(null);
    }
  });
}

export { state as uiState };
