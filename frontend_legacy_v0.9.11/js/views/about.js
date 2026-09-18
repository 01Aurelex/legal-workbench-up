/* 关于我 · 开发者信息与联系/赞赏入口（二维码按需展示，不直接平铺） */
import { ref } from 'vue';
import { modal } from '../ui.js';
import { Icon, svgIcon } from '../icons.js';

/* 二维码展示弹层：白底卡片承载码图，保证扫码识别率 */
function qrModal(title, items) {
  modal({
    title,
    size: 'lg',
    comp: {
      setup: () => ({ items }),
      template: `
        <div class="qr-grid">
          <figure v-for="q in items" :key="q.src" class="qr-card">
            <div class="qr-img"><img :src="q.src" :alt="q.name" draggable="false"></div>
            <figcaption>
              <div class="qr-name">{{ q.name }}</div>
              <div class="qr-desc">{{ q.desc }}</div>
            </figcaption>
          </figure>
        </div>
        <div class="qr-tip">使用手机相机或对应 App 扫码识别</div>`,
    },
  });
}

export default {
  name: 'AboutView',
  components: { Icon },
  setup() {
    const ver = 'v0.9.11';

    function contact() {
      qrModal('联系我', [
        { src: 'assets/about/qr_mp.png', name: '微信公众号', desc: '法岩 OPC 法律助手 · 产品动态与更新' },
        { src: 'assets/about/qr_wechat.png', name: '个人微信', desc: '添加好友 · 反馈建议与合作交流' },
      ]);
    }
    function reward() {
      qrModal('赞赏支持', [
        { src: 'assets/about/qr_alipay.png', name: '支付宝', desc: '扫码付款 · 支持信用卡与花呗' },
        { src: 'assets/about/qr_reward.png', name: '微信赞赏码', desc: '谢谢各位大佬 · 每一份支持都是动力' },
      ]);
    }

    return { ver, contact, reward, svgIcon };
  },
  template: `
<div class="view">
  <div class="page-head">
    <div>
      <h1>关于我</h1>
      <div class="desc">法岩律师工作台 · 独立开发者作品</div>
    </div>
  </div>

  <!-- 品牌卡 -->
  <div class="card about-hero sec">
    <div class="about-mark">法岩</div>
    <div class="grow">
      <h2 style="font-size:20px">法岩律师工作台</h2>
      <div class="small muted mt-1">为独立执业律师打造的本地化一体工作台：案件、档案、财务、日程与本地 AI，数据全部留存本机。</div>
      <div class="row gap-2 mt-3 wrap">
        <span class="badge badge-primary">{{ ver }} 测试版</span>
        <span class="badge badge-accent badge-dot">本机运行 · 仅 127.0.0.1</span>
        <span class="badge badge-success">零云端上传</span>
      </div>
    </div>
  </div>

  <!-- 两个入口按钮 -->
  <div class="grid g-2 sec">
    <button class="card about-act spot" @click="contact()">
      <span class="about-act-ico"><Icon name="mail" :size="20"/></span>
      <span class="about-act-t">联系我</span>
      <span class="about-act-d">微信公众号 · 个人微信</span>
      <span class="about-act-go">查看二维码 ›</span>
    </button>
    <button class="card about-act spot" @click="reward()">
      <span class="about-act-ico gold"><Icon name="heart" :size="20"/></span>
      <span class="about-act-t">赞赏</span>
      <span class="about-act-d">支付宝 · 微信赞赏码</span>
      <span class="about-act-go">支持一下 ›</span>
    </button>
  </div>

  <!-- 说明 -->
  <div class="card">
    <div class="card-h"><h3>关于这个软件</h3></div>
    <div class="small muted" style="line-height:2">
      本软件由一名法律人独立设计并开发，秉持「零成本、全本地、可离线」的原则：
      不依赖任何付费云服务，不收集任何使用数据。若它对你的执业有所帮助，
      欢迎通过「联系我」交流建议，或通过「赞赏」支持持续迭代。
    </div>
  </div>
</div>`,
};
