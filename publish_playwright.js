#!/usr/bin/env node
/**
 * Pinterest AutoPin - Playwright Version
 * 连接已登录的 Chrome 执行 Pinterest 自动发布
 */

const http = require('http');
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { classifyPinterestLoginState, isPinterestCreateRoute, isPinterestHost } = require('./pinterest_login_state');

// 配置
const CDP_PORT = 9222;
const DEFAULT_PIN_CREATION_URL = process.env.PINTEREST_AUTOPIN_CREATION_URL || 'https://www.pinterest.com/pin-creation-tool/';
const DEFAULT_CHROME_ARGS = [
  '--disable-blink-features=AutomationControlled'
];

const GREEN = '\x1b[32m';
const YELLOW = '\x1b[33m';
const RED = '\x1b[31m';
const NC = '\x1b[0m';

function logInfo(msg) { console.log(`${GREEN}[INFO]${NC} ${msg}`); }
function logWarn(msg) { console.log(`${YELLOW}[WARN]${NC} ${msg}`); }
function logError(msg) { console.log(`${RED}[ERROR]${NC} ${msg}`); }

function writeStructuredResult(filePath, payload) {
  if (!filePath) return;
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
}

function parseBoardName(board) {
  const [fullName = '', alias = ''] = String(board || '')
    .split('|')
    .map(part => part.trim());
  const searchText = alias || fullName;
  const candidates = [fullName, alias].filter(Boolean);
  return { fullName, alias, searchText, candidates };
}

function boardMatches(buttonText, board) {
  if (!buttonText) return false;
  const { candidates } = parseBoardName(board);
  return candidates.some(candidate => buttonText.includes(candidate));
}

function normalizeText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function normalizeSearch(value) {
  return normalizeText(value).toLowerCase();
}

function validateCreationUrl(value) {
  const creationUrl = value || DEFAULT_PIN_CREATION_URL;
  let parsed;
  try {
    parsed = new URL(creationUrl);
  } catch (_error) {
    throw new Error(`creationUrl 必须是绝对 URL: ${creationUrl}`);
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`creationUrl 必须是 http(s) URL: ${creationUrl}`);
  }
  if (!isPinterestHost(parsed.hostname)) {
    throw new Error(`creationUrl 必须是 Pinterest 域名: ${creationUrl}`);
  }
  if (!isPinterestCreateRoute(parsed.toString())) {
    throw new Error(`creationUrl 必须指向 Pinterest 创建页面: ${creationUrl}`);
  }
  return parsed.toString();
}

async function setElementText(handle, value) {
  return handle.evaluate((el, text) => {
    const normalize = raw => String(raw || '').replace(/\s+/g, ' ').trim();
    const dispatch = target => {
      ['input', 'change'].forEach(evt => {
        target.dispatchEvent(new Event(evt, { bubbles: true, cancelable: true }));
      });
    };
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const isTextInput =
      tag === 'textarea' ||
      (tag === 'input' && !['file', 'checkbox', 'radio', 'hidden', 'submit', 'button'].includes(String(el.type || '').toLowerCase()));

    if (isTextInput) {
      el.focus();
      try {
        const proto = tag === 'textarea'
          ? window.HTMLTextAreaElement.prototype
          : window.HTMLInputElement.prototype;
        const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
        if (nativeSetter) {
          nativeSetter.call(el, text);
        } else {
          el.value = text;
        }
      } catch (_error) {
        el.value = text;
      }
      dispatch(el);
      return {
        success: el.value === text,
        value: el.value,
        method: tag
      };
    }

    if (el.isContentEditable || role === 'textbox') {
      el.focus();
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      selection.removeAllRanges();
      selection.addRange(range);
      document.execCommand('insertText', false, text);
      dispatch(el);
      return {
        success: normalize(el.textContent).includes(normalize(text)),
        value: el.textContent || '',
        method: el.isContentEditable ? 'contenteditable' : 'role=textbox'
      };
    }

    return { success: false, value: '', method: 'unsupported' };
  }, value);
}

async function fillFirstVisibleInput(page, selectors, value) {
  for (const selector of selectors) {
    const handles = await page.$$(selector);
    for (const handle of handles) {
      const visible = await handle.isVisible().catch(() => false);
      if (!visible) continue;
      const result = await setElementText(handle, value).catch(() => ({ success: false }));
      if (result.success) {
        return selector;
      }
    }
  }
  return '';
}

async function fillTextControlByHints(page, hints, value) {
  const result = await page.evaluate(({ hints, value }) => {
    const normalize = raw => String(raw || '').replace(/\s+/g, ' ').trim();
    const search = raw => normalize(raw).toLowerCase();
    const hintValues = hints.map(search).filter(Boolean);
    const isVisible = el => Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const isTextControl = el => {
      const tag = el.tagName.toLowerCase();
      if (tag === 'textarea') return true;
      if (tag === 'input') {
        return !['file', 'checkbox', 'radio', 'hidden', 'submit', 'button'].includes(String(el.type || '').toLowerCase());
      }
      return el.isContentEditable || el.getAttribute('role') === 'textbox';
    };
    const candidateText = el => {
      const attrs = [
        el.id,
        el.getAttribute('name'),
        el.getAttribute('placeholder'),
        el.getAttribute('aria-label'),
        el.getAttribute('data-test-id')
      ];
      const parent = el.closest('[data-test-id], label, div, section, form');
      return {
        direct: search(attrs.filter(Boolean).join(' ')),
        context: search([el.textContent, parent?.textContent].filter(Boolean).join(' '))
      };
    };
    const scoreFor = el => {
      const text = candidateText(el);
      let score = 0;
      for (const hint of hintValues) {
        if (text.direct.includes(hint)) score += 10;
        if (text.context.includes(hint)) score += 1;
      }
      return score;
    };
    const controls = Array.from(document.querySelectorAll('textarea, input, [contenteditable="true"], [role="textbox"]'))
      .filter(el => isVisible(el) && isTextControl(el))
      .map(el => ({ el, score: scoreFor(el) }))
      .filter(item => item.score > 0)
      .sort((a, b) => b.score - a.score);

    const dispatch = target => {
      ['input', 'change'].forEach(evt => {
        target.dispatchEvent(new Event(evt, { bubbles: true, cancelable: true }));
      });
    };
    const write = el => {
      const tag = el.tagName.toLowerCase();
      if (tag === 'textarea' || tag === 'input') {
        el.focus();
        try {
          const proto = tag === 'textarea'
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
          const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
          if (nativeSetter) nativeSetter.call(el, value);
          else el.value = value;
        } catch (_error) {
          el.value = value;
        }
        dispatch(el);
        return el.value === value;
      }
      el.focus();
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(el);
      selection.removeAllRanges();
      selection.addRange(range);
      document.execCommand('insertText', false, value);
      dispatch(el);
      return normalize(el.textContent).includes(normalize(value));
    };

    for (const { el, score } of controls) {
      if (write(el)) {
        return {
          success: true,
          selector: el.getAttribute('data-test-id') || el.id || el.getAttribute('aria-label') || el.tagName,
          score
        };
      }
    }
    return { success: false };
  }, { hints, value });

  if (result.success) {
    return result.selector || 'hinted text control';
  }
  return '';
}

async function clickFirstButtonByLabels(page, labels) {
  return page.evaluate((labels) => {
    const normalize = raw => String(raw || '').replace(/\s+/g, ' ').trim().toLowerCase();
    const labelValues = labels.map(normalize).filter(Boolean);
    const isVisible = el => Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    const isDisabled = el => el.disabled || el.getAttribute('aria-disabled') === 'true';
    const textFor = el => normalize([
      el.textContent,
      el.getAttribute('aria-label'),
      el.getAttribute('data-test-id'),
      el.getAttribute('title')
    ].filter(Boolean).join(' '));
    const buttons = Array.from(document.querySelectorAll('button, [role="button"], [data-test-id]'));
    for (const btn of buttons) {
      if (!isVisible(btn) || isDisabled(btn)) continue;
      const text = textFor(btn);
      if (labelValues.some(label => text.includes(label))) {
        btn.click();
        return {
          success: true,
          label: btn.textContent?.trim() || btn.getAttribute('aria-label') || btn.getAttribute('data-test-id') || btn.tagName
        };
      }
    }
    return { success: false };
  }, labels);
}

async function readStoryboardDescription(page) {
  return page.evaluate(() => {
    const root = document.querySelector('[data-test-id="storyboard-description-field-container"]');
    const start = root?.querySelector('[role="button"]') || root;
    const fiberKey = Object.keys(start || {}).find(key => key.startsWith('__reactFiber'));
    let fiber = fiberKey ? start[fiberKey] : null;
    const findEditorProps = (node) => {
      if (!node) return null;
      const props = node.memoizedProps || node.pendingProps || {};
      if (
        props &&
        typeof props.onChange === 'function' &&
        Object.prototype.hasOwnProperty.call(props, 'initialText') &&
        Object.prototype.hasOwnProperty.call(props, 'editorRef')
      ) {
        return props;
      }
      return findEditorProps(node.child) || findEditorProps(node.sibling);
    };

    while (fiber) {
      const props = findEditorProps(fiber);
      if (props) {
        return String(props.initialText || '');
      }
      fiber = fiber.return;
    }
    return '';
  });
}

async function fillStoryboardDescription(page, description) {
  const reactResult = await page.evaluate((desc) => {
    const root = document.querySelector('[data-test-id="storyboard-description-field-container"]');
    const start = root?.querySelector('[role="button"]') || root;
    const fiberKey = Object.keys(start || {}).find(key => key.startsWith('__reactFiber'));
    let fiber = fiberKey ? start[fiberKey] : null;
    const findEditorProps = (node) => {
      if (!node) return null;
      const props = node.memoizedProps || node.pendingProps || {};
      if (
        props &&
        typeof props.onChange === 'function' &&
        Object.prototype.hasOwnProperty.call(props, 'initialText') &&
        Object.prototype.hasOwnProperty.call(props, 'editorRef')
      ) {
        return props;
      }
      return findEditorProps(node.child) || findEditorProps(node.sibling);
    };

    while (fiber) {
      const props = findEditorProps(fiber);
      if (props) {
        props.onFocus?.();
        props.onChange({ text: desc, mentions: [] });
        return { success: true, method: 'storyboard react editor' };
      }
      fiber = fiber.return;
    }
    return { success: false, reason: 'storyboard description editor props not found' };
  }, description);

  if (!reactResult.success) {
    return reactResult;
  }

  await page.waitForTimeout(500);
  const currentTitle = await page.locator('#storyboard-selector-title').first().inputValue().catch(() => '');
  if (currentTitle) {
    const titleInput = page.locator('#storyboard-selector-title').first();
    await titleInput.fill(`${currentTitle} `).catch(() => {});
    await page.waitForTimeout(250);
    await titleInput.fill(currentTitle).catch(() => {});
  } else {
    await page.locator('#WebsiteField').first().click({ force: true }).catch(() => {});
  }
  await page.waitForTimeout(1200);

  const writtenText = await readStoryboardDescription(page).catch(() => '');
  return {
    success: writtenText === description,
    method: reactResult.method,
    length: writtenText.length,
    reason: writtenText === description ? '' : 'storyboard description did not confirm through React state'
  };
}

async function waitForPinterestCreateOrLogin(page, timeout = 15000) {
  await page.waitForFunction(() => {
    const bodyText = document.body?.innerText || '';
    const url = window.location.href;
    const loginWall =
      /\/login/i.test(url) ||
      /log in|sign up|登录|注册|ログイン|登録/i.test(bodyText);
    const hasCreateSurface = Boolean(
      document.querySelector('input[type="file"]') ||
      document.querySelector('textarea[placeholder="Add your title"]') ||
      document.querySelector('textarea[data-test-id="pin-draft-title"]') ||
      document.querySelector('[data-test-id*="pin-draft"]') ||
      document.querySelector('[data-test-id*="media"]') ||
      document.querySelector('[contenteditable="true"]') ||
      document.querySelector('[role="textbox"]')
    );
    return loginWall || hasCreateSurface;
  }, null, { timeout }).catch(() => {});
}

async function detectPinterestCreateState(page) {
  return page.evaluate(() => {
    const bodyText = document.body?.innerText || '';
    const url = window.location.href;
    const loginWall =
      /\/login/i.test(url) ||
      /log in|sign up|登录|注册|ログイン|登録/i.test(bodyText);
    const hasCreateSurface = Boolean(
      document.querySelector('input[type="file"]') ||
      document.querySelector('textarea[placeholder="Add your title"]') ||
      document.querySelector('textarea[data-test-id="pin-draft-title"]') ||
      document.querySelector('[data-test-id*="pin-draft"]') ||
      document.querySelector('[data-test-id*="media"]') ||
      document.querySelector('[contenteditable="true"]') ||
      document.querySelector('[role="textbox"]')
    );
    return { url, loginWall, hasCreateSurface };
  });
}

function fetchJson(url, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, (res) => {
      if (res.statusCode !== 200) {
        res.resume();
        reject(new Error(`CDP discovery returned HTTP ${res.statusCode}`));
        return;
      }

      let body = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => {
        body += chunk;
      });
      res.on('end', () => {
        try {
          resolve(JSON.parse(body));
        } catch (e) {
          reject(new Error(`CDP discovery returned invalid JSON: ${e.message}`));
        }
      });
    });

    req.setTimeout(timeoutMs, () => {
      req.destroy(new Error(`CDP discovery timed out after ${timeoutMs}ms`));
    });
    req.on('error', reject);
  });
}

async function resolveBrowserEndpointUrl() {
  const versionUrl = `http://127.0.0.1:${CDP_PORT}/json/version`;
  const payload = await fetchJson(versionUrl);
  if (!payload.webSocketDebuggerUrl) {
    throw new Error(`CDP discovery at ${versionUrl} did not return webSocketDebuggerUrl`);
  }
  const endpointUrl = `http://127.0.0.1:${CDP_PORT}`;
  logInfo(`🔗 使用动态 CDP endpoint: ${endpointUrl}`);
  return endpointUrl;
}

async function createBrowserSession(chromeProfile) {
  if (chromeProfile) {
    const userDataDir = path.resolve(chromeProfile);
    fs.mkdirSync(userDataDir, { recursive: true });
    logInfo(`🔗 使用 Chrome profile: ${userDataDir}`);
    const context = await chromium.launchPersistentContext(userDataDir, {
      channel: 'chrome',
      headless: false,
      viewport: null,
      args: DEFAULT_CHROME_ARGS
    });
    return {
      context,
      pageCount: () => context.pages().length,
      close: () => context.close()
    };
  }

  logInfo(`🔗 未提供 Chrome profile，尝试连接本地 CDP ${CDP_PORT}...`);
  const browserEndpointUrl = await resolveBrowserEndpointUrl();
  const browser = await chromium.connectOverCDP(browserEndpointUrl);
  const contexts = browser.contexts();
  const context = contexts[0];
  if (!context) {
    await browser.close().catch(() => {});
    throw new Error('CDP Chrome 未返回可用浏览器上下文');
  }
  return {
    context,
    pageCount: () => context.pages().length,
    close: () => browser.close()
  };
}

function pinterestPageScore(page) {
  const currentUrl = page.url() || '';
  if (currentUrl === 'about:blank') return 10;

  try {
    const parsed = new URL(currentUrl);
    if (!isPinterestHost(parsed.hostname)) return 0;
    if (isPinterestCreateRoute(currentUrl)) return 40;
    return 30;
  } catch (_error) {
    return 0;
  }
}

async function getPinterestAutomationPage(context) {
  const pages = context.pages().filter(page => !page.isClosed());
  const reusable = pages
    .map((page, index) => ({ page, index, score: pinterestPageScore(page) }))
    .filter(candidate => candidate.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)[0];

  if (reusable) {
    logInfo(`📍 复用已有标签页: ${reusable.page.url() || 'about:blank'}`);
    await reusable.page.bringToFront().catch((e) => {
      logWarn(`切换到复用标签页失败，尝试继续: ${e.message}`);
    });
    return reusable.page;
  }

  logInfo('📍 未找到可复用标签页，创建一个新标签页...');
  const page = await context.newPage();
  await page.bringToFront().catch((e) => {
    logWarn(`切换到新标签页失败，尝试继续: ${e.message}`);
  });
  return page;
}

async function openPinBuilder(page, options = {}) {
  const { waitUntil = 'networkidle', resetDraft = false, creationUrl = DEFAULT_PIN_CREATION_URL } = options;
  if (resetDraft && page.url() !== 'about:blank') {
    await page.goto('about:blank', {
      waitUntil: 'domcontentloaded',
      timeout: 10000
    }).catch((e) => {
      logWarn(`清理旧页面状态超时，尝试继续: ${e.message}`);
    });
  }

  await page.goto(creationUrl || DEFAULT_PIN_CREATION_URL, {
    waitUntil,
    timeout: 30000
  });
}

function randomDelay(min = 2, max = 5) {
  return new Promise(resolve => setTimeout(resolve, (Math.floor(Math.random() * (max - min + 1)) + min) * 1000));
}

async function checkPinterestLogin(chromeProfile, creationUrl = DEFAULT_PIN_CREATION_URL) {
  let browserSession;

  console.log('='.repeat(60));
  console.log('Pinterest AutoPin - Login Check');
  console.log('='.repeat(60));

  try {
    browserSession = await createBrowserSession(chromeProfile);
    const page = await getPinterestAutomationPage(browserSession.context);
    await openPinBuilder(page, { waitUntil: 'domcontentloaded', creationUrl }).catch((e) => {
      logWarn(`导航超时，尝试继续: ${e.message}`);
    });
    await waitForPinterestCreateOrLogin(page);

    const state = await detectPinterestCreateState(page);

    const loginState = classifyPinterestLoginState(state);
    if (!loginState.ok) {
      throw new Error(loginState.reason);
    }

    const result = {
      ok: true,
      mode: 'check-login',
      finalUrl: state.url,
      completedAt: new Date().toISOString()
    };
    logInfo('✅ Pinterest 登录态可用');
    writeStructuredResult(RESULT_JSON_PATH, result);
    return result;
  } finally {
    if (browserSession) {
      await browserSession.close().catch((e) => {
        logWarn(`关闭浏览器连接失败: ${e.message}`);
      });
    }
  }
}

// 压缩图片到最大宽度
function compressImage(imagePath, maxWidth = 2000) {
  try {
    // 获取图片宽度
    const widthOutput = execFileSync(
      'sips',
      ['-g', 'pixelWidth', imagePath],
      { encoding: 'utf8' }
    );
    const widthMatch = widthOutput.match(/pixelWidth:\s*(\d+)/);
    const width = widthMatch ? parseInt(widthMatch[1], 10) : 0;
    
    if (width <= maxWidth) {
      logInfo(`图片宽度: ${width}px，无需压缩`);
      return imagePath;
    }
    
    logInfo(`图片宽度: ${width}px > ${maxWidth}px，压缩中...`);
    
    // 创建临时文件
    const ext = path.extname(imagePath);
    const tempPath = imagePath.replace(ext, '_compressed.jpg');
    
    // 压缩图片
    execFileSync(
      'sips',
      ['-Z', String(maxWidth), imagePath, '--out', tempPath],
      { stdio: 'pipe' }
    );
    
    logInfo(`✅ 压缩完成: ${width}px → ${maxWidth}px`);
    return tempPath;
  } catch (e) {
    logWarn(`压缩失败: ${e.message}`);
    return imagePath;
  }
}

async function publishPin(options) {
  const { images = [], title, board, link, description, chromeProfile, creationUrl = DEFAULT_PIN_CREATION_URL } = options;
  // Backward compat: flat image/altText → images array
  const resolvedImages = images.length > 0
    ? images
    : (options.image ? [{ path: options.image, altText: options.altText || '' }] : []);
  const isCarousel = resolvedImages.length > 1;
  let browserSession;

  console.log('='.repeat(60));
  console.log(`Pinterest AutoPin - Playwright${isCarousel ? ` (Carousel: ${resolvedImages.length} images)` : ''}`);
  console.log('='.repeat(60));

  for (const img of resolvedImages) {
    if (!fs.existsSync(img.path)) {
      throw new Error(`图片不存在: ${img.path}`);
    }
  }

  logInfo(`图片: ${resolvedImages.map(img => path.basename(img.path)).join(', ')}`);
  logInfo(`标题: ${title}`);
  logInfo(`链接: ${link || '(无)'}`);

  if ((TEST_MODE || FINAL_MODE) && !board) {
    throw new Error('测试模式和发布模式必须提供 board，避免发布到错误的 Board');
  }

  // 压缩图片
  const compressedImages = resolvedImages.map(img => ({
    ...img,
    compressedPath: compressImage(img.path, 2000)
  }));
  
  logInfo(`🔗 打开 Chrome...`);
  
  try {
    browserSession = await createBrowserSession(chromeProfile);

    logInfo('✅ 已连接');

    const ctx = browserSession.context;

    logInfo(`当前 ${browserSession.pageCount()} 个页面`);

    const page = await getPinterestAutomationPage(ctx);

    // 导航到 Pinterest 创建页面
    logInfo('📍 打开 Pinterest 创建页面...');
    try {
      await openPinBuilder(page, { waitUntil: 'networkidle', resetDraft: true, creationUrl });
    } catch (e) {
      logWarn(`导航超时，尝试继续...`);
    }
    await randomDelay(3);

    logInfo(`📄 页面: ${page.url()?.substring(0, 50)}`);
    await waitForPinterestCreateOrLogin(page);
    const createState = await detectPinterestCreateState(page);
    const loginState = classifyPinterestLoginState(createState);
    if (!loginState.ok) {
      throw new Error(loginState.reason);
    }

    // 步骤 1: 上传图片
    const filePaths = compressedImages.map(img => img.compressedPath);
    logInfo(`\n📤 步骤 1: 上传图片 (${filePaths.length} 张)...`);

    // 先尝试清除已上传的图片（如果有）
    let uploadSuccess = false;
    try {
      const removeBtn = await page.$('[data-test-id="remove-image"], button[aria-label*="Remove"], button[aria-label*="Delete"], button[aria-label*="remove"], button[aria-label*="delete"]');
      if (removeBtn) {
        await removeBtn.click();
        await randomDelay(1);
        logInfo('🗑️ 已清除旧图片');
      }
    } catch (e) {
      // 忽略错误，继续上传
    }

    let attempts = 0;
    const maxAttempts = 3;

    while (!uploadSuccess && attempts < maxAttempts) {
      attempts++;
      logInfo(`📤 上传尝试 ${attempts}/${maxAttempts}...`);

      const fileInput = await page.$('input[type="file"]');
      if (fileInput) {
        await fileInput.setInputFiles(filePaths);
        logInfo(`✅ 文件已选择: ${filePaths.map(f => path.basename(f)).join(', ')}`);
        await randomDelay(isCarousel ? 5 : 3);

        const newImage = await page.$(
          'img[src^="blob:"], img[data-test-id="pin-image"], [data-test-id="story-pin-image-block"] img, [data-test-id*="image"] img, img[src*="pinimg.com"]'
        );
        if (newImage) {
          uploadSuccess = true;
          logInfo(`✅ 图片上传成功${isCarousel ? ` (轮播 ${filePaths.length} 张)` : ''}`);
        }
      } else {
        logWarn('⚠️ 未找到文件上传 input，尝试点击上传区域...');

        const uploadArea = await page.$('[data-test-id*="media"], div[class*="upload"], div[role="button"]');
        if (uploadArea) {
          try {
            await uploadArea.click();
            await randomDelay(2);
          } catch (e) {
            logWarn(`点击失败: ${e.message}`);
          }
        }
      }

      if (!uploadSuccess) {
        await randomDelay(2);
      }
    }

    if (!uploadSuccess) {
      throw new Error('图片上传失败，终止发布');
    }

    // 步骤 2: 填写标题
    if (title) {
      logInfo('\n📝 步骤 2: 填写标题...');

      let titleWritten = false;
      const titleSelectors = [
        'textarea[id^="pin-draft-title"]',
        'textarea[data-test-id="pin-draft-title"]',
        '[data-test-id="pin-draft-title"] textarea',
        '[data-test-id*="title"] textarea',
        '[data-test-id*="title"] [contenteditable="true"]',
        '[data-test-id*="title"] [role="textbox"]',
        'textarea[placeholder="Add your title"]',
        'input[placeholder="Add your title"]',
        '[contenteditable="true"][aria-label*="title" i]',
        '[role="textbox"][aria-label*="title" i]',
        'textarea[placeholder*="タイトル"]',
        'textarea[aria-label*="タイトル"]',
        'input[placeholder*="タイトル"]',
        'input[aria-label*="タイトル"]',
        '[contenteditable="true"][aria-label*="タイトル"]',
        '[role="textbox"][aria-label*="タイトル"]',
        'textarea[placeholder*="标题"]',
        'textarea[aria-label*="标题"]',
        'input[placeholder*="标题"]',
        'input[aria-label*="标题"]',
        '[contenteditable="true"][aria-label*="标题"]',
        '[role="textbox"][aria-label*="标题"]'
      ];

      const titleSelector = await fillFirstVisibleInput(page, titleSelectors, title) ||
        await fillTextControlByHints(page, ['pin-draft-title', 'title', 'タイトル', '标题', '標題'], title);
      if (titleSelector) {
        titleWritten = true;
        logInfo(`✅ 标题已填写 (${titleSelector})`);
      }

      if (!titleWritten) {
        throw new Error('标题未能确认写入，终止发布');
      }
    }

    // 步骤 3: 填写链接
    if (link) {
      logInfo('\n🔗 步骤 3: 填写链接...');

      let linkWritten = false;
      const linkSelectors = [
        'textarea[id^="pin-draft-link"]',
        'textarea[data-test-id="pin-draft-link"]',
        '[data-test-id="pin-draft-link"] textarea',
        '[data-test-id*="link"] textarea',
        '[data-test-id*="link"] input',
        '[data-test-id*="link"] [contenteditable="true"]',
        '[data-test-id*="link"] [role="textbox"]',
        'textarea[placeholder="Add a destination link"]',
        'input[placeholder="Add a destination link"]',
        '[contenteditable="true"][aria-label*="link" i]',
        '[role="textbox"][aria-label*="link" i]',
        'textarea[placeholder*="リンク"]',
        'textarea[aria-label*="リンク"]',
        'textarea[placeholder*="链接"]',
        'textarea[aria-label*="链接"]',
        'input[placeholder*="リンク"]',
        'input[aria-label*="リンク"]',
        'input[placeholder*="链接"]',
        'input[aria-label*="链接"]'
      ];

      const linkSelector = await fillFirstVisibleInput(page, linkSelectors, link) ||
        await fillTextControlByHints(page, ['pin-draft-link', 'destination link', 'link', 'リンク', '保存先リンク', '链接', '連結'], link);
      if (linkSelector) {
        linkWritten = true;
        logInfo(`✅ 链接已填写 (${linkSelector})`);
      }

      if (!linkWritten) {
        throw new Error('链接未能确认写入，终止发布');
      }
    }

    // 步骤 4: 选择 Board
    if (board) {
      logInfo(`\n📋 步骤 4: 选择 Board (${board})...`);
      const boardInfo = parseBoardName(board);
      const boardCandidates = Array.from(new Set([
        boardInfo.searchText,
        ...boardInfo.candidates
      ].filter(Boolean)));
      let boardSelected = false;

      // 检查 Board 是否已选择
      const boardButtonSelectors = [
        '[data-test-id="board-dropdown-select-button"]',
        '[data-test-id*="board"][role="button"]',
        'button[data-test-id*="board"]',
        'button[aria-label*="Board"]',
        'button[aria-label*="ボード"]',
        'button[aria-label*="保存先"]',
        'button[aria-label*="图板"]',
        'button[aria-label*="圖板"]',
        'div[role="button"][aria-label*="Board"]',
        'div[role="button"][aria-label*="ボード"]',
        'div[role="button"][aria-label*="保存先"]',
        'div[role="button"][aria-label*="图板"]',
        'div[role="button"][aria-label*="圖板"]'
      ];
      const currentBoard = await page.$(boardButtonSelectors.join(', '));
      if (currentBoard) {
        const btnText = await currentBoard.textContent() || '';
        if (boardMatches(btnText, board)) {
          boardSelected = true;
          logInfo(`✅ Board 已选择: ${btnText.substring(0, 50)}`);
        } else {
          // 点击 Board 选择器
          const boardBtn = await page.$(boardButtonSelectors.join(', '));
          if (boardBtn) {
            try {
              await boardBtn.click({ timeout: 5000 });
              logInfo('✅ 已点击 Board 选择器');
            } catch {
              logWarn('点击 Board 选择器超时，尝试继续...');
            }
            await randomDelay(1);

            // 搜索 Board
            const searchInputSelector = await fillFirstVisibleInput(page, [
              'input[placeholder*="Search"]',
              'input[aria-label*="Search"]',
              'input[placeholder*="検索"]',
              'input[aria-label*="検索"]',
              'input[placeholder*="搜索"]',
              'input[aria-label*="搜索"]',
              'input[role="combobox"]',
              'input[type="text"]'
            ], boardInfo.searchText);
            if (searchInputSelector) {
              logInfo(`✅ 已搜索 Board (${searchInputSelector})`);
              await randomDelay(1);

              // 选择 Board
              for (const candidate of boardCandidates) {
                const boardItem = page.getByText(candidate, { exact: false }).first();
                if (await boardItem.isVisible().catch(() => false)) {
                  await boardItem.click();
                  await randomDelay(1);
                  const updatedBoard = await page.$(boardButtonSelectors.join(', '));
                  const updatedText = updatedBoard ? await updatedBoard.textContent() || '' : '';
                  boardSelected = boardMatches(updatedText, board);
                  if (boardSelected) {
                    logInfo(`✅ 已选择 Board: ${updatedText.substring(0, 50)}`);
                  }
                  break;
                }
              }
            }
          }
        }
      } else {
        const clickResult = await clickFirstButtonByLabels(page, [
          'board',
          'select board',
          'choose board',
          'ボード',
          '保存先',
          '图板',
          '圖板',
          '选择看板',
          '選擇看板'
        ]);
        if (clickResult.success) {
          logInfo(`✅ 已点击 Board 选择器 (${clickResult.label})`);
          await randomDelay(1);

          const searchInputSelector = await fillFirstVisibleInput(page, [
            'input[placeholder*="Search"]',
            'input[aria-label*="Search"]',
            'input[placeholder*="検索"]',
            'input[aria-label*="検索"]',
            'input[placeholder*="搜索"]',
            'input[aria-label*="搜索"]',
            'input[role="combobox"]',
            'input[type="text"]'
          ], boardInfo.searchText);
          if (searchInputSelector) {
            logInfo(`✅ 已搜索 Board (${searchInputSelector})`);
            await randomDelay(1);

            for (const candidate of boardCandidates) {
              const boardItem = page.getByText(candidate, { exact: false }).first();
              if (await boardItem.isVisible().catch(() => false)) {
                await boardItem.click();
                await randomDelay(1);
                const updatedBoard = await page.$(boardButtonSelectors.join(', '));
                const updatedText = updatedBoard ? await updatedBoard.textContent() || '' : '';
                boardSelected = boardMatches(updatedText, board) || updatedText.includes(candidate);
                if (boardSelected) {
                  logInfo(`✅ 已选择 Board: ${updatedText.substring(0, 50) || candidate}`);
                }
                break;
              }
            }
          }
        }
      }

      if (!boardSelected) {
        throw new Error(`未能确认 Board 已选中: ${board}`);
      }
    }

    // 步骤 5: 填写描述 (重要：使用 evaluate 方法，2026-02-13 验证有效!)
    if (description) {
      logInfo('\n📝 步骤 5: 填写描述...');

      try {
        await clickFirstButtonByLabels(page, [
          'description',
          'add description',
          'add details',
          '説明',
          '詳細説明',
          '描述',
          '添加详细描述',
          '新增詳細說明'
        ]).catch(() => ({ success: false }));
        await randomDelay(1);

        const storyboardResult = await fillStoryboardDescription(page, description).catch((e) => ({
          success: false,
          reason: e.message
        }));

        const descSelector = storyboardResult.success
          ? storyboardResult.method
          : await fillFirstVisibleInput(page, [
          '[data-test-id="storyboard-description-field-container"] .public-DraftEditor-content',
          '[data-test-id="storyboard-description-field-container"] .DraftEditor-content',
          '[data-test-id="comment-editor-container"] .public-DraftEditor-content',
          '[data-test-id="comment-editor-container"] .DraftEditor-content',
          '[data-test-id="editor-with-mentions"] .public-DraftEditor-content',
          '[data-test-id="editor-with-mentions"] .DraftEditor-content',
          '[data-test-id*="description"] textarea',
          '[data-test-id*="description"] [contenteditable="true"]',
          '[data-test-id*="description"] [role="textbox"]',
          '.public-DraftEditor-content',
          '.DraftEditor-content',
          'textarea[placeholder*="description" i]',
          'textarea[aria-label*="description" i]',
          'textarea[placeholder*="説明"]',
          'textarea[aria-label*="説明"]',
          'textarea[placeholder*="描述"]',
          'textarea[aria-label*="描述"]'
        ], description) || await fillTextControlByHints(page, [
          'storyboard-description',
          'comment-editor',
          'editor-with-mentions',
          'description',
          'add description',
          '説明',
          '描述',
          '添加详细描述',
          '詳細說明'
        ], description);

        const descResult = descSelector
          ? { success: true, selector: descSelector, length: description.length }
          : await page.evaluate((desc) => {
            const el = document.querySelector('.public-DraftEditor-content') || document.querySelector('.DraftEditor-content');
            if (!el) {
              return { success: false, reason: 'description editor not found' };
            }

            el.focus();
            const sel = window.getSelection();
            const range = document.createRange();
            range.selectNodeContents(el);
            range.collapse(false);
            sel.removeAllRanges();
            sel.addRange(range);
            document.execCommand('insertText', false, desc);
            const text = el.textContent || '';
            const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim();
            return {
              success: normalizeText(text).includes(normalizeText(desc)),
              length: text.length,
              selector: 'DraftEditor fallback'
            };
          }, description);

        if (!descResult.success) {
          throw new Error(storyboardResult.reason || descResult.reason || 'description editor did not accept text');
        }

        logInfo(`✅ 描述已填写 (${descResult.selector || 'description editor'}, ${descResult.length || description.length} 字符)`);
      } catch (e) {
        throw new Error(`描述填写失败: ${e.message}`);
      }
    }

    // 步骤 6: 添加 Alt Text
    const altTexts = compressedImages.map(img => img.altText).filter(Boolean);
    if (altTexts.length > 0) {
      logInfo(`\n🖼️ 步骤 6: 添加 Alt Text (${altTexts.length} 条)...`);

      await clickFirstButtonByLabels(page, [
        'more options',
        'その他のオプション',
        '更多选项',
        '更多選項'
      ]).catch(() => ({ success: false }));
      await randomDelay(1);

      const altSelectors = [
        '#storyboardAltText',
        'textarea[id^="pin-draft-alttext"]',
        'textarea[data-test-id*="alt"]',
        '[data-test-id*="alt"] textarea',
        '[data-test-id*="alt"] input[type="text"]',
        '[data-test-id*="alt"] [contenteditable="true"]',
        '[data-test-id*="alt"] [role="textbox"]',
        'textarea[placeholder*="视觉"]',
        'textarea[placeholder*="視覺"]',
        'textarea[placeholder*="alt" i]',
        'textarea[aria-label*="alt" i]',
        'textarea[placeholder*="代替"]',
        'textarea[aria-label*="代替"]',
        'textarea[placeholder*="替代"]',
        'textarea[aria-label*="替代"]'
      ];

      const altHints = [
        'alt text', 'alternative text', 'pin-draft-alttext',
        '代替テキスト', '代替', '替代文本', '替代文字'
      ];

      const altAddLabels = [
        'add alt', 'alt text', '代替テキスト', '代替テキストを追加',
        '替代文字', '替代文本', '添加替代文本', '新增替代文字'
      ];

      async function fillOneAltText(altValue) {
        const needClickButton = await page.evaluate(() => {
          const ta = document.querySelector('#storyboardAltText, textarea[id^="pin-draft-alttext"], textarea[data-test-id*="alt"], [data-test-id*="alt"] textarea');
          return !ta;
        });
        if (needClickButton) {
          const clickResult = await page.evaluate((labels) => {
            const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const matches = value => { const text = normalize(value); return labels.some(label => text.includes(normalize(label))); };
            const btns = document.querySelectorAll('button, div[role="button"]');
            for (const btn of btns) {
              if (matches(btn.textContent) || matches(btn.getAttribute('aria-label'))) { btn.click(); return true; }
            }
            return false;
          }, altAddLabels);
          if (clickResult) await randomDelay(1);
        }
        const selector = await fillFirstVisibleInput(page, altSelectors, altValue)
          || await fillTextControlByHints(page, altHints, altValue);
        if (selector) return { success: true, length: altValue.length, selector };
        return await page.evaluate((alt) => {
          const ta = document.querySelector('#storyboardAltText, textarea[id^="pin-draft-alttext"], textarea[data-test-id*="alt"], [data-test-id*="alt"] textarea');
          if (!ta) return { success: false };
          try { Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(ta, alt); } catch (_e) { ta.value = alt; }
          ['input', 'change'].forEach(evt => ta.dispatchEvent(new Event(evt, { bubbles: true, cancelable: true })));
          return { success: ta.value === alt, length: ta.value.length, selector: 'textarea fallback' };
        }, altValue);
      }

      if (!isCarousel) {
        const altResult = await fillOneAltText(altTexts[0]);
        if (altResult.success) {
          logInfo(`✅ Alt Text 已填写 (${altResult.selector || 'alt text'}, ${altResult.length} 字符)`);
        } else {
          throw new Error('Alt Text 未能确认写入，终止发布');
        }
      } else {
        // Carousel: try to set alt text per image by clicking each carousel thumbnail
        const carouselThumbs = await page.$$('[data-test-id*="carousel"] [role="button"], [data-test-id*="carousel-card"], [data-test-id*="storyboard-page"]');
        if (carouselThumbs.length >= altTexts.length) {
          for (let idx = 0; idx < altTexts.length; idx++) {
            if (!altTexts[idx]) continue;
            try {
              await carouselThumbs[idx].click();
              await randomDelay(1);
              const altResult = await fillOneAltText(altTexts[idx]);
              if (altResult.success) {
                logInfo(`✅ 图 ${idx + 1} Alt Text 已填写 (${altResult.length} 字符)`);
              } else {
                logWarn(`⚠️ 图 ${idx + 1} Alt Text 未能写入，需手动补填`);
              }
            } catch (e) {
              logWarn(`⚠️ 图 ${idx + 1} Alt Text 设置失败: ${e.message}`);
            }
          }
        } else {
          // Fallback: fill first alt text into the visible field
          logWarn(`⚠️ 未找到轮播缩略图 (期望 ${altTexts.length}，找到 ${carouselThumbs.length})，填写第 1 张 Alt Text`);
          const altResult = await fillOneAltText(altTexts[0]);
          if (altResult.success) {
            logInfo(`✅ 图 1 Alt Text 已填写，其余 ${altTexts.length - 1} 张需手动补填`);
          } else {
            logWarn('⚠️ Alt Text 未能写入，需全部手动补填');
          }
        }
      }
    }

    await randomDelay(2);

    // 步骤 7: 发布
    if (FINAL_MODE) {
      logInfo('\n🚀 步骤 7: 发布...');

      // 使用 evaluate 点击 Publish 按钮
      const publishResult = await page.evaluate(() => {
        const publishLabels = ['Publish', '公開', '公開する', '投稿', '发布', '發佈'];
        const normalize = value => String(value || '').replace(/\s+/g, ' ').trim().toLowerCase();
        const matchesPublish = value => {
          const text = normalize(value);
          return publishLabels.some(label => text === normalize(label));
        };
        const isDisabled = (el) => {
          return el.disabled || el.getAttribute('aria-disabled') === 'true';
        };

        // 查找主要发布按钮，兼容英文、日文和中文界面。
        const divBtns = document.querySelectorAll('button, div[role="button"]');
        for (const div of divBtns) {
          const text = div.textContent?.trim();
          if (matchesPublish(text) || matchesPublish(div.getAttribute('aria-label'))) {
            if (isDisabled(div)) {
              return { success: false, reason: 'Publish button is disabled' };
            }
            div.click();
            return { success: true, method: 'div[role="button"]' };
          }
        }

        // 查找任何包含 "Publish" 的元素
        const allElements = document.querySelectorAll('*');
        for (const el of allElements) {
          if (matchesPublish(el.textContent) || matchesPublish(el.getAttribute('aria-label'))) {
            if (isDisabled(el)) {
              return { success: false, reason: 'Publish button is disabled' };
            }
            el.click();
            return { success: true, method: 'any element', tag: el.tagName };
          }
        }

        return { success: false };
      });

      if (publishResult.success) {
        logInfo(`✅ 已点击发布按钮 (${publishResult.method})`);
      } else {
        throw new Error(`${publishResult.reason || '未找到 Publish 按钮'}，终止发布`);
      }

      await page.waitForURL(/\/pin\//, { timeout: 15000 }).catch(() => null);
      await randomDelay(1);
    }

    // 获取最终 Pin URL
    let finalUrl = page.url();

    if (FINAL_MODE) {
      try {
        // 等待发布完成
        await page.waitForTimeout(1000);
        finalUrl = page.url();

        // 检查当前 URL - 如果包含 pin 路径就直接用
        if (finalUrl.includes('/pin/')) {
          console.log(`📝 从当前 URL 获取: ${finalUrl}`);
        } else {
          // 尝试查找页面上的 Pin 链接
          const pinLinks = await page.$$('a[href*="/pin/"]');
          for (const link of pinLinks) {
            const href = await link.getAttribute('href');
            if (href && href.includes('/pin/')) {
              finalUrl = href.startsWith('http') ? href : 'https://www.pinterest.com' + href;
              console.log(`📝 从链接获取 Pin URL: ${finalUrl}`);
              break;
            }
          }

          // 如果还是找不到，尝试点击 "See your Pin" 按钮
          if (!finalUrl.includes('/pin/')) {
            const seePinBtn = await page.locator('button:has-text("See your Pin"), button:has-text("View your Pin")').first();
            if (await seePinBtn.isVisible().catch(() => false)) {
              console.log(`📝 点击 "See your Pin" 按钮...`);
              await seePinBtn.click();
              await page.waitForTimeout(2000);
              finalUrl = page.url();
            }
          }
        }

        if (!finalUrl.includes('/pin/')) {
          throw new Error(`未能确认发布后的 Pin URL，当前页面: ${finalUrl}`);
        }

        console.log(`📝 最终 Pin URL: ${finalUrl}`);
      } catch (e) {
        throw new Error(`发布后确认失败: ${e.message}`);
      }
    }

    console.log('\n' + '='.repeat(60));
    logInfo(TEST_MODE ? '🧪 测试完成 - 请检查内容是否正确' : '✅ 完成');
    console.log(`  URL: ${finalUrl}`);
    console.log('='.repeat(60));

    // 保存 Pin URL 到临时文件 (供 scheduler 使用)
    if (FINAL_MODE && pinData) {
      const urlFile = '/tmp/published_pin_url.txt';
      fs.writeFileSync(urlFile, finalUrl);
      console.log(`📝 Pin URL saved to: ${urlFile}`);
    }

    const result = {
      ok: true,
      mode: FINAL_MODE ? 'final' : TEST_MODE ? 'test' : 'interactive',
      images: resolvedImages.map(img => img.path),
      isCarousel,
      title,
      board,
      link,
      finalUrl,
      completedAt: new Date().toISOString()
    };
    writeStructuredResult(RESULT_JSON_PATH, result);
    return result;
  } finally {
    if (browserSession) {
      await browserSession.close().catch((e) => {
        logWarn(`关闭浏览器连接失败: ${e.message}`);
      });
    }
  }
}

// 解析参数
const args = {};
let i = 0;
while (i < process.argv.length) {
  if (process.argv[i].startsWith('--')) {
    const key = process.argv[i].slice(2);
    const val = process.argv[i + 1];
    if (val && !val.startsWith('--')) {
      args[key] = val;
      i += 2;
    } else {
      args[key] = true;
      i += 1;
    }
  } else i++;
}

// 支持从 JSON 文件读取参数 (解决命令行参数长度限制)
let pinData = null;
const inputPath = args.input || args.json;
if (inputPath) {
  try {
    const jsonPath = inputPath;
    if (fs.existsSync(jsonPath)) {
      pinData = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
      console.log(`✅ 从 JSON 文件加载数据: ${jsonPath}`);
    }
  } catch (e) {
    logError(`读取 JSON 文件失败: ${e.message}`);
  }
}

if (!pinData && args.data) {
  try {
    if (fs.existsSync(args.data)) {
      pinData = JSON.parse(fs.readFileSync(args.data, 'utf8'));
      console.log(`✅ 从 data 文件加载数据: ${args.data}`);
    } else {
      pinData = JSON.parse(args.data);
      console.log('✅ 从内联 JSON 加载数据');
    }
  } catch (e) {
    logError(`读取 data 参数失败: ${e.message}`);
  }
}

const TEST_MODE = args.test || false;
const FINAL_MODE = args.final || false;
const CHECK_LOGIN_MODE = args['check-login'] || args.checkLogin || false;
const RESULT_JSON_PATH = args['result-json'] || '';

if (TEST_MODE) {
  console.log('\n🧪 测试模式 - 只填写内容，不发布\n');
}

if (FINAL_MODE) {
  console.log('\n🚀 最终发布模式\n');
}

// 从 JSON 或命令行参数获取 pin 数据
// images[] array (new format) or flat image/altText (backward compat)
let images = [];
if (Array.isArray(pinData?.images) && pinData.images.length > 0) {
  images = pinData.images.map(img => ({
    path: String(img.path || ''),
    altText: String(img.altText || img.alt_text || '')
  }));
} else {
  const flatImage = pinData?.image || args.image;
  const flatAltText = pinData?.altText || pinData?.alt_text || args['alt-text'] || '';
  if (flatImage) {
    images = [{ path: flatImage, altText: flatAltText }];
  }
}
const title = pinData?.title || args.title;
const board = pinData?.board || args.board || '';
const link = pinData?.link || args.link || '';
const description = pinData?.description || args.description || '';
const chromeProfile = pinData?.chromeProfile || pinData?.chrome_profile || args['chrome-profile'] || args.chromeProfile || '';
let creationUrl;
try {
  creationUrl = validateCreationUrl(
    pinData?.creationUrl || pinData?.creation_url || args['creation-url'] || args.creationUrl || DEFAULT_PIN_CREATION_URL
  );
} catch (err) {
  logError(`错误: ${err.message}`);
  writeStructuredResult(RESULT_JSON_PATH, {
    ok: false,
    error: err.message,
    completedAt: new Date().toISOString()
  });
  process.exit(1);
}

if (CHECK_LOGIN_MODE) {
  checkPinterestLogin(chromeProfile, creationUrl).catch(err => {
    logError(`错误: ${err.message}`);
    writeStructuredResult(RESULT_JSON_PATH, {
      ok: false,
      mode: 'check-login',
      error: err.message,
      completedAt: new Date().toISOString()
    });
    process.exit(1);
  });
} else if (!images.length || !title) {
  logError('缺少参数: --image (或 images[]), --title');
  console.log('\n用法:');
  console.log('  命令行: node publish_playwright.js --image <图片> --title <标题> --description <描述> --final');
  console.log('  JSON文件: node publish_playwright.js --input <json文件> --final');
  writeStructuredResult(RESULT_JSON_PATH, {
    ok: false,
    error: '缺少参数: images/image, title',
    images,
    title,
    completedAt: new Date().toISOString()
  });
  process.exit(1);
} else if ((TEST_MODE || FINAL_MODE) && !board) {
  logError('缺少参数: --board');
  writeStructuredResult(RESULT_JSON_PATH, {
    ok: false,
    error: '测试模式和发布模式必须提供 board',
    images,
    title,
    board,
    link,
    completedAt: new Date().toISOString()
  });
  process.exit(1);
} else {
  publishPin({
    images,
    title,
    board,
    link,
    description,
    chromeProfile,
    creationUrl
  }).catch(err => {
    logError(`错误: ${err.message}`);
    writeStructuredResult(RESULT_JSON_PATH, {
      ok: false,
      error: err.message,
      images,
      title,
      board,
      link,
      completedAt: new Date().toISOString()
    });
    process.exit(1);
  });
}
