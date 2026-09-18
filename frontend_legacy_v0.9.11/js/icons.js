/* 线性 SVG 图标体系 ·「北欧序章」
   统一规格：24×24 viewBox / 1.6px 描边 / 圆角线帽 / currentColor。
   用法一（组件）：import { Icon } from '../icons.js' → <Icon name="home" :size="16"/>
   用法二（字符串）：import { svgIcon } from '../icons.js' → v-html="svgIcon('home')" */

const P = {
  /* 导航 */
  home: '<path d="M3.5 10.5 12 3.5l8.5 7"/><path d="M5.5 9.8V20a.8.8 0 0 0 .8.8h11.4a.8.8 0 0 0 .8-.8V9.8"/><path d="M9.5 20.5v-5.5h5v5.5"/>',
  cases: '<rect x="3.5" y="7.5" width="17" height="12" rx="2"/><path d="M8.5 7.5V6a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v1.5"/><path d="M3.5 12.5h17"/>',
  intake: '<path d="M12.5 20h8"/><path d="M16.8 3.7a2.05 2.05 0 0 1 2.9 2.9L7.4 18.9 3.5 20l1.1-3.9Z"/>',
  clients: '<circle cx="12" cy="8" r="3.6"/><path d="M4.8 20c1.3-3.3 4-5.2 7.2-5.2s5.9 1.9 7.2 5.2"/>',
  vault: '<path d="M3.5 6.5a2 2 0 0 1 2-2h3.8l2.2 2.5h7a2 2 0 0 1 2 2v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z"/>',
  graph: '<circle cx="6.5" cy="6" r="2.4"/><circle cx="17.5" cy="7.5" r="2.4"/><circle cx="12" cy="17.5" r="2.4"/><path d="M8.7 7 15.3 7.4M7.6 8.2l3.2 7M16.4 9.6l-3.3 5.7"/>',
  revenue: '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 8.3 12 12.5l3.7-4.2"/><path d="M12 12.5V17"/><path d="M9.2 14.6h5.6"/>',
  invoice: '<path d="M6 3.5h12V20l-2.4-1.6L13.2 20 12 19.2 10.8 20l-2.4-1.6L6 20Z"/><path d="M9.2 8h5.6M9.2 11.5h5.6"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 9.8h17"/><path d="M8 3v3.6M16 3v3.6"/>',
  timer: '<circle cx="12" cy="13" r="7.5"/><path d="M12 9.8V13l2.4 1.8"/><path d="M9.5 2.8h5"/>',
  ai: '<path d="M12 4.2 13.8 8.8 18.5 10.5 13.8 12.2 12 16.8 10.2 12.2 5.5 10.5 10.2 8.8Z"/><path d="M18.3 15.8l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8Z"/>',
  remind: '<path d="M6 16v-4.8a6 6 0 0 1 12 0V16l1.6 2.6H4.4Z"/><path d="M10 21a2.1 2.1 0 0 0 4 0"/>',
  settings: '<path d="M4 7.2h9.4M17.8 7.2H20"/><circle cx="15.6" cy="7.2" r="2.2"/><path d="M4 16.8h3.4M11.8 16.8H20"/><circle cx="9.6" cy="16.8" r="2.2"/>',
  about: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11.2v5"/><path d="M12 7.6v.3"/>',

  /* 动作 / 通用 */
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-3.8-3.8"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M18.7 5.3 17 7M7 17l-1.7 1.7"/>',
  moon: '<path d="M20 13.6A8.2 8.2 0 1 1 10.4 4 6.6 6.6 0 0 0 20 13.6Z"/>',
  mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="m4.5 7.5 7.5 5.6 7.5-5.6"/>',
  heart: '<path d="M12 20s-7.4-4.5-9.2-8.9A5.1 5.1 0 0 1 12 6.6a5.1 5.1 0 0 1 9.2 4.5C19.4 15.5 12 20 12 20Z"/>',
  qr: '<path d="M4 4h6v6H4ZM14 4h6v6h-6ZM4 14h6v6H4Z"/><path d="M14 14h2.6v2.6H14ZM17.4 17.4H20V20h-2.6ZM14 19.6v.4M19.6 14h.4"/>',
  scale: '<path d="M12 3.5V20M8 20.5h8"/><path d="M4.5 6.5h15"/><path d="M6.5 6.5 4 12.8a2.9 2.9 0 0 0 5 0L6.5 6.5ZM17.5 6.5 15 12.8a2.9 2.9 0 0 0 5 0l-2.5-6.3Z"/>',
  doc: '<path d="M6 3.5h7.5L19 9v11.5H6Z"/><path d="M13.2 3.5V9H19"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  send: '<path d="M20.5 3.5 10.8 13.2"/><path d="M20.5 3.5 14 20.8l-3.2-7.6-7.3-3.4Z"/>',
  grip: '<path d="M9 5.5h.3M15 5.5h.3M9 12h.3M15 12h.3M9 18.5h.3M15 18.5h.3"/>',
  collapseL: '<path d="m11 6-6 6 6 6M18 6l-6 6 6 6"/>',
  collapseR: '<path d="m13 6 6 6-6 6M6 6l6 6-6 6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  chevronD: '<path d="m6 9.5 6 6 6-6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  shield: '<path d="M12 3.5 5 6v5.5c0 4.4 3 7.6 7 9 4-1.4 7-4.6 7-9V6Z"/><path d="m9 11.8 2.2 2.2 4-4.2"/>',
  book: '<path d="M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5Z"/><path d="M5 19.5A1.5 1.5 0 0 1 6.5 18H19v3H6.5A1.5 1.5 0 0 1 5 19.5Z"/>',
};

export function svgIcon(name, size = 16) {
  const d = P[name] || P.about;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" `
    + `stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" `
    + `aria-hidden="true">${d}</svg>`;
}

export const Icon = {
  name: 'Icon',
  props: { name: { type: String, required: true }, size: { type: [Number, String], default: 16 } },
  computed: { svg() { return svgIcon(this.name, this.size); } },
  template: `<span class="icon" v-html="svg"></span>`,
};
