/**
 * screenshot.js - 阶段三：Playwright 自动化截图（框架自适应，登录可选）
 *
 * 用法（playwright 已全局安装于本机，无需再装）:
 *   1. 复制 screenshot-config.json 为实际配置，填入登录信息与截图清单
 *   2. node screenshot.js screenshot-config.json
 *   注意: require('playwright') 依赖 NODE_PATH（已写入 ~/.zshenv）
 *   若浏览器缺失: npx playwright install chromium
 *
 * 登录（可选）:
 *   - 不需要登录: loginUrl: null，脚本跳过登录直接导航
 *   - 需要登录: loginUrl 填【精确登录页 URL】（如 https://host:port/login），
 *     httpAuth/formAuth 按实际认证方式配置
 *   - 建议提前在系统侧关闭文字/图形验证码校验，避免阻塞自动化
 *
 * 前端框架自适应:
 *   - 配置中 framework 字段为用户主动声明（优先）: vanilla | elementui | antd | layui
 *   - 未声明(null)时自动探测页面特征，探测结果输出到日志供人工核对
 *   - 探测失败回退 vanilla 并输出 warning
 */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

/* ============ 选择器策略表（按框架） ============ */
const FRAMEWORKS = {
  // 原生 HTML：dl>dt(一级) / dl>dd>a(二级)，三级为内容区 <a>
  vanilla: {
    top: (t) => `dl dt:has-text("${t}")`,
    sub: (t) => `dl dd a:has-text("${t}")`,
    tab: (t) => `a:has-text("${t}")`,
    scrollArea: ['.rightContentScrollArea', '[class*="content"]'],
  },
  // Vue + ElementUI
  elementui: {
    top: (t) => `.el-submenu__title:has-text("${t}")`,
    sub: (t) => `.el-menu-item:has-text("${t}")`,
    tab: (t) => `.el-tabs__item:has-text("${t}")`,
    scrollArea: ['.el-main', '[class*="content"]'],
  },
  // Ant Design（React/Vue）
  antd: {
    top: (t) => `.ant-menu-submenu-title:has-text("${t}")`,
    sub: (t) => `.ant-menu-item:has-text("${t}")`,
    tab: (t) => `.ant-tabs-tab:has-text("${t}")`,
    scrollArea: ['.ant-layout-content', '[class*="content"]'],
  },
  // layui
  layui: {
    top: (t) => `.layui-nav-item:has-text("${t}")`,
    sub: (t) => `.layui-nav-child a:has-text("${t}")`,
    tab: (t) => `.layui-tab-title li:has-text("${t}")`,
    scrollArea: ['.layui-body', '[class*="content"]'],
  },
};

/* ============ 框架探测 ============ */
async function detectFramework(page) {
  const fw = await page.evaluate(() => {
    const has = (sel) => !!document.querySelector(sel);
    const app = document.querySelector('#app');
    const vue2 = app && ('__vue__' in app);
    const vue3 = app && ('__vue_app__' in app);
    const react = has('[data-reactroot]') || !!(window.React || window.__REACT_DEVTOOLS_GLOBAL_HOOK__);
    if (has('.el-menu') || has('.el-tabs') || vue2 || vue3) return 'elementui';
    if (has('.ant-menu') || has('.ant-tabs') || react) return 'antd';
    if (has('.layui-nav') || has('.layui-tab') || window.layui) return 'layui';
    if (has('dl.menu_left') || has('dl > dt')) return 'vanilla';
    return null;
  });
  return fw;
}

/* ============ 通用工具 ============ */
function cfg() {
  return JSON.parse(fs.readFileSync(process.argv[2] || 'screenshot-config.json', 'utf-8'));
}

async function login(page, config) {
  if (!config.loginUrl) {
    console.log('loginUrl 为空，跳过登录');
    return;
  }
  // 精确定位登录页
  await page.goto(config.loginUrl, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(2000);

  if (config.formAuth) {
    const { username, password } = config.formAuth;
    const userSel = '#username, input[name="username"], input[type="text"]';
    const passSel = '#password, input[name="password"], input[type="password"]';
    if (await page.locator(userSel).count() > 0 && await page.locator(passSel).count() > 0) {
      await page.fill(userSel, username);
      await page.fill(passSel, password);
      await page.press(passSel, 'Enter'); // 部分系统登录页无 <button>，回车触发
      await page.waitForTimeout(3000);
      await page.waitForLoadState('networkidle');
      console.log('表单登录完成, URL:', page.url());
      return;
    }
  }
  console.log('未检测到登录表单（可能已登录或为 Basic 认证）');
}

async function clickMenu(page, fw, top, sub) {
  if (top) {
    await page.click(FRAMEWORKS[fw].top(top));
    await page.waitForTimeout(500);
  }
  if (sub) {
    await page.click(FRAMEWORKS[fw].sub(sub));
    await page.waitForTimeout(2000);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);
  }
}

async function clickTab(page, fw, tabText) {
  const tab = page.locator(FRAMEWORKS[fw].tab(tabText)).first();
  if (await tab.count() > 0) {
    await tab.click();
    await page.waitForTimeout(2000);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);
  }
}

function scrollAreaLocator(page, fw) {
  for (const sel of FRAMEWORKS[fw].scrollArea) {
    const loc = page.locator(sel).first();
    if (loc.count()) return loc;
  }
  return null;
}

/** 多轮滚动触发懒加载，返回最终 scrollHeight */
async function scrollToLoadAll(page, area) {
  let scrollHeight = await area.evaluate((el) => el.scrollHeight);
  const clientHeight = await area.evaluate((el) => el.clientHeight) || 600;
  for (let pass = 0; pass < 3; pass++) {
    const prev = scrollHeight;
    for (let i = 0; i <= Math.ceil(scrollHeight / clientHeight); i++) {
      await area.evaluate((el, pos) => { el.scrollTop = pos; }, i * clientHeight);
      await page.waitForTimeout(800);
    }
    scrollHeight = await area.evaluate((el) => el.scrollHeight);
    if (scrollHeight === prev) break;
  }
  await area.evaluate((el) => { el.scrollTop = 0; });
  await page.waitForTimeout(500);
  return scrollHeight;
}

/** 探测底栏元素（版权/操作区），返回其相对内容区顶部的 top */
async function getBottomBarTop(page, area) {
  const candidates = ['.bottomCopy', '.bottom-bar', '.bottomActionArear', '.footer', '[class*="copyright"]', '.page-footer'];
  return await page.evaluate(({ candidates }) => {
    const area = document.querySelector('.rightContentScrollArea') || document.querySelector('[class*="content"]');
    if (!area) return null;
    const areaRect = area.getBoundingClientRect();
    for (const sel of candidates) {
      const el = document.querySelector(sel);
      if (!el) continue;
      const cr = el.getBoundingClientRect();
      if (cr.height > 0 && cr.width > 0) {
        const relTop = cr.top - areaRect.top;
        if (relTop > 0 && relTop < area.scrollHeight) return Math.round(relTop);
      }
    }
    return area.scrollHeight; // 未找到底栏，按内容全高
  }, { candidates });
}

/** 动态调整视口 + clip 裁剪（排除底栏），保存完整长截图 */
async function takeScreenshot(page, area, filename, outDir) {
  const filepath = path.join(outDir, filename);
  const sh = await area.evaluate((el) => el.scrollHeight);
  const areaPos = await area.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), vpH: window.innerHeight };
  });

  // 视口动态撑高：顶栏偏移 + 内容高 + 底栏高
  const bottomTop = await getBottomBarTop(page, area);
  const targetVp = areaPos.y + sh + 60;
  if (targetVp > areaPos.vpH) {
    await page.setViewportSize({ width: 1920, height: Math.ceil(targetVp) });
    await page.waitForTimeout(800);
  }

  // 重新取位置（视口变化后坐标可能变化）
  const pos = await area.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width) };
  });
  const clipBottom = bottomTop && bottomTop < sh ? bottomTop : sh;

  await page.screenshot({
    path: filepath,
    clip: { x: pos.x, y: pos.y, width: pos.width, height: Math.round(clipBottom) },
  });
  console.log(`  Saved: ${filepath} (${pos.width}x${Math.round(clipBottom)})`);
}

/* ============ 主流程 ============ */
(async () => {
  const config = cfg();
  const outDir = path.join(process.cwd(), config.screenshotDir || 'screenshot');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({
    headless: true,
    ignoreHTTPSErrors: true,
  });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1920, height: 1080 },
    httpCredentials: config.httpAuth || undefined,
  });
  const page = await context.newPage();

  // 登录（可选）：无 loginUrl 则跳过
  if (config.loginUrl) {
    await login(page, config);
  } else {
    await page.goto(config.baseUrl, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(2000);
    console.log('跳过登录, URL:', page.url());
  }

  // 框架解析：用户声明 > 自动探测 > 回退 vanilla
  let fw = config.framework;
  if (!fw) {
    fw = await detectFramework(page);
    console.log(`[框架探测] 检测到: ${fw || '未知'}`);
    if (!fw) {
      console.warn('[WARNING] 未能识别前端框架，回退 vanilla 策略。建议在配置中主动声明 framework。');
      fw = 'vanilla';
    }
  } else {
    if (!FRAMEWORKS[fw]) throw new Error(`未知框架: ${fw}，可选: ${Object.keys(FRAMEWORKS).join(', ')}`);
    console.log(`[框架声明] 使用: ${fw}`);
  }

  for (const t of config.targets) {
    console.log(`\n=== ${t.section}-${t.label} ===`);
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.waitForTimeout(300);

    await clickMenu(page, fw, t.menu[0], t.menu[1]);
    if (t.tab) await clickTab(page, fw, t.tab);
    console.log(`  URL: ${page.url()}`);

    const area = scrollAreaLocator(page, fw);
    if (!area) {
      console.log('  [WARNING] 未找到滚动内容区，改用整页截图');
      await page.screenshot({ path: path.join(outDir, `${t.section}-${t.label}.png`), fullPage: true });
      continue;
    }
    await scrollToLoadAll(page, area);
    await takeScreenshot(page, area, `${t.section}-${t.label}.png`, outDir);
  }

  await browser.close();
  console.log('\nDone!');
})();
