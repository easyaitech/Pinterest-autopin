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
const { classifyPinterestLoginState } = require('./pinterest_login_state');

// 配置
const CDP_PORT = 9222;
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

async function resolveBrowserWsUrl() {
  const versionUrl = `http://127.0.0.1:${CDP_PORT}/json/version`;
  const payload = await fetchJson(versionUrl);
  if (!payload.webSocketDebuggerUrl) {
    throw new Error(`CDP discovery at ${versionUrl} did not return webSocketDebuggerUrl`);
  }
  logInfo(`🔗 使用动态 CDP URL: ${payload.webSocketDebuggerUrl}`);
  return payload.webSocketDebuggerUrl;
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
  const browserWsUrl = await resolveBrowserWsUrl();
  const browser = await chromium.connectOverCDP({
    wsEndpoint: browserWsUrl
  });
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

function randomDelay(min = 2, max = 5) {
  return new Promise(resolve => setTimeout(resolve, (Math.floor(Math.random() * (max - min + 1)) + min) * 1000));
}

async function checkPinterestLogin(chromeProfile) {
  let browserSession;

  console.log('='.repeat(60));
  console.log('Pinterest AutoPin - Login Check');
  console.log('='.repeat(60));

  try {
    browserSession = await createBrowserSession(chromeProfile);
    const page = await browserSession.context.newPage();
    await page.goto('https://www.pinterest.com/pin-builder/', {
      waitUntil: 'domcontentloaded',
      timeout: 30000
    }).catch((e) => {
      logWarn(`导航超时，尝试继续: ${e.message}`);
    });
    await page.waitForFunction(() => {
      const bodyText = document.body?.innerText || '';
      const url = window.location.href;
      const loginWall =
        /\/login/i.test(url) ||
        /log in|sign up|登录|注册/i.test(bodyText);
      const hasCreateSurface = Boolean(
        document.querySelector('input[type="file"]') ||
        document.querySelector('textarea[placeholder="Add your title"]') ||
        document.querySelector('textarea[data-test-id="pin-draft-title"]') ||
        document.querySelector('[data-test-id*="media"]')
      );
      return loginWall || hasCreateSurface;
    }, null, { timeout: 15000 }).catch(() => {});

    const state = await page.evaluate(() => {
      const bodyText = document.body?.innerText || '';
      const url = window.location.href;
      const loginWall =
        /\/login/i.test(url) ||
        /log in|sign up|登录|注册/i.test(bodyText);
      const hasCreateSurface = Boolean(
        document.querySelector('input[type="file"]') ||
        document.querySelector('textarea[placeholder="Add your title"]') ||
        document.querySelector('textarea[data-test-id="pin-draft-title"]') ||
        document.querySelector('[data-test-id*="media"]')
      );
      return { url, loginWall, hasCreateSurface };
    });

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
  const { image, title, board, link, description, altText, chromeProfile } = options;
  let browserSession;
  
  console.log('='.repeat(60));
  console.log('Pinterest AutoPin - Playwright');
  console.log('='.repeat(60));
  
  if (!fs.existsSync(image)) {
    throw new Error(`图片不存在: ${image}`);
  }
  
  logInfo(`图片: ${image}`);
  logInfo(`标题: ${title}`);
  logInfo(`链接: ${link || '(无)'}`);

  if ((TEST_MODE || FINAL_MODE) && !board) {
    throw new Error('测试模式和发布模式必须提供 board，避免发布到错误的 Board');
  }
  
  // 压缩图片
  const compressedImage = compressImage(image, 2000);
  
  logInfo(`🔗 打开 Chrome...`);
  
  try {
    browserSession = await createBrowserSession(chromeProfile);

    logInfo('✅ 已连接');

    // 创建新页面（每次都打开全新的 Pin Builder）
    const ctx = browserSession.context;

    logInfo(`当前 ${browserSession.pageCount()} 个页面`);

    // 创建全新标签页
    logInfo('📍 创建新标签页...');
    const page = await ctx.newPage();

    // 导航到 pin-builder
    logInfo('📍 打开 Pin Builder...');
    try {
      await page.goto('https://www.pinterest.com/pin-builder/', {
        waitUntil: 'networkidle',
        timeout: 30000
      });
    } catch (e) {
      logWarn(`导航超时，尝试继续...`);
    }
    await randomDelay(3);

    logInfo(`📄 页面: ${page.url()?.substring(0, 50)}`);

    // 步骤 1: 上传图片
    logInfo('\n📤 步骤 1: 上传图片...');

    // 每次都重新上传图片，不要跳过！
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

    // 尝试查找文件上传 input
    let attempts = 0;
    const maxAttempts = 3;

    while (!uploadSuccess && attempts < maxAttempts) {
      attempts++;
      logInfo(`📤 上传尝试 ${attempts}/${maxAttempts}...`);

      const fileInput = await page.$('input[type="file"]');
      if (fileInput) {
        await fileInput.setInputFiles(compressedImage);
        logInfo(`✅ 文件已选择: ${path.basename(compressedImage)}`);
        await randomDelay(3);

        // 验证图片是否上传成功
        const newImage = await page.$('img[src^="blob:"], img[data-test-id="pin-image"]');
        if (newImage) {
          uploadSuccess = true;
          logInfo('✅ 图片上传成功');
        }
      } else {
        logWarn('⚠️ 未找到文件上传 input，尝试点击上传区域...');

        // 点击上传触发区域
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
        'textarea[placeholder="Add your title"]',
        'textarea[id^="pin-draft-title"]',
        'textarea[data-test-id="pin-draft-title"]'
      ];

      for (const selector of titleSelectors) {
        const titleInput = await page.$(selector);
        if (titleInput) {
          await titleInput.fill(title);
          const value = await titleInput.inputValue().catch(() => '');
          titleWritten = value === title;
          if (titleWritten) {
            logInfo(`✅ 标题已填写 (${selector})`);
            break;
          }
        }
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
        'textarea[placeholder="Add a destination link"]',
        'textarea[id^="pin-draft-link"]',
        'textarea[data-test-id="pin-draft-link"]'
      ];

      for (const selector of linkSelectors) {
        const linkInput = await page.$(selector);
        if (linkInput) {
          await linkInput.fill(link);
          const value = await linkInput.inputValue().catch(() => '');
          linkWritten = value === link;
          if (linkWritten) {
            logInfo(`✅ 链接已填写 (${selector})`);
            break;
          }
        }
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
      const currentBoard = await page.$('div[data-test-id="board-dropdown-select-button"]');
      if (currentBoard) {
        const btnText = await currentBoard.textContent() || '';
        if (boardMatches(btnText, board)) {
          boardSelected = true;
          logInfo(`✅ Board 已选择: ${btnText.substring(0, 50)}`);
        } else {
          // 点击 Board 选择器
          const boardBtn = await page.$('div[data-test-id="board-dropdown-select-button"]');
          if (boardBtn) {
            try {
              await boardBtn.click({ timeout: 5000 });
              logInfo('✅ 已点击 Board 选择器');
            } catch {
              logWarn('点击 Board 选择器超时，尝试继续...');
            }
            await randomDelay(1);

            // 搜索 Board
            const searchInput = await page.$('input[placeholder*="Search"]');
            if (searchInput) {
              await searchInput.fill(boardInfo.searchText);
              await randomDelay(1);

              // 选择 Board
              for (const candidate of boardCandidates) {
                const boardItem = page.getByText(candidate, { exact: false }).first();
                if (await boardItem.isVisible().catch(() => false)) {
                  await boardItem.click();
                  await randomDelay(1);
                  const updatedBoard = await page.$('div[data-test-id="board-dropdown-select-button"]');
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
      }

      if (!boardSelected) {
        throw new Error(`未能确认 Board 已选中: ${board}`);
      }
    }

    // 步骤 5: 填写描述 (重要：使用 evaluate 方法，2026-02-13 验证有效!)
    if (description) {
      logInfo('\n📝 步骤 5: 填写描述...');

      try {
        const descResult = await page.evaluate((desc) => {
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
            length: text.length
          };
        }, description);

        if (!descResult.success) {
          throw new Error(descResult.reason || 'description editor did not accept text');
        }

        logInfo(`✅ 描述已填写 (${descResult.length || description.length} 字符)`);
      } catch (e) {
        throw new Error(`描述填写失败: ${e.message}`);
      }
    }

    // 步骤 6: 添加 Alt Text
    if (altText) {
      logInfo('\n🖼️ 步骤 6: 添加 Alt Text...');

      // 1. 检查 Alt Text 输入框是否存在，不存在则点击按钮
      const needClickButton = await page.evaluate(() => {
        const ta = document.querySelector('textarea[id^="pin-draft-alttext"]');
        return !ta;
      });

      if (needClickButton) {
        // 点击 Add alt text 按钮
        const clickResult = await page.evaluate(() => {
          const btns = document.querySelectorAll('button');
          for (const btn of btns) {
            if (btn.textContent?.trim().toLowerCase().includes('add alt')) {
              btn.click();
              return true;
            }
          }
          return false;
        });

        if (clickResult) {
          logInfo('✅ 已点击 Add alt text 按钮');
          await randomDelay(2);
        } else {
          logWarn('⚠️ 未找到 Add alt text 按钮');
        }
      }

      // 2. 填写 Alt Text
      const altResult = await page.evaluate((alt) => {
        const ta = document.querySelector('textarea[id^="pin-draft-alttext"]');
        if (ta) {
          // 使用原生 setter 更新 React 状态
          try {
            const nativeSetter = Object.getOwnPropertyDescriptor(
              window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            nativeSetter.call(ta, alt);
          } catch (e) {
            ta.value = alt;
          }

          // 触发事件
          ['input', 'change'].forEach(evt => {
            ta.dispatchEvent(new Event(evt, { bubbles: true, cancelable: true }));
          });

          return { success: ta.value === alt, length: ta.value.length };
        }
        return { success: false };
      }, altText);

      if (altResult.success) {
        logInfo(`✅ Alt Text 已填写 (${altResult.length} 字符)`);
      } else {
        throw new Error('Alt Text 未能确认写入，终止发布');
      }
    }

    await randomDelay(2);

    // 步骤 7: 发布
    if (FINAL_MODE) {
      logInfo('\n🚀 步骤 7: 发布...');

      // 使用 evaluate 点击 Publish 按钮
      const publishResult = await page.evaluate(() => {
        const isDisabled = (el) => {
          return el.disabled || el.getAttribute('aria-disabled') === 'true';
        };

        // 查找 div[role="button"] 且 text="Publish"
        const divBtns = document.querySelectorAll('div[role="button"]');
        for (const div of divBtns) {
          const text = div.textContent?.trim();
          if (text === 'Publish') {
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
          if (el.textContent?.trim() === 'Publish') {
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
      image,
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
const image = pinData?.image || args.image;
const title = pinData?.title || args.title;
const board = pinData?.board || args.board || '';
const link = pinData?.link || args.link || '';
const description = pinData?.description || args.description || '';
const altText = pinData?.altText || pinData?.alt_text || args['alt-text'] || '';
const chromeProfile = pinData?.chromeProfile || pinData?.chrome_profile || args['chrome-profile'] || args.chromeProfile || '';

if (CHECK_LOGIN_MODE) {
  checkPinterestLogin(chromeProfile).catch(err => {
    logError(`错误: ${err.message}`);
    writeStructuredResult(RESULT_JSON_PATH, {
      ok: false,
      mode: 'check-login',
      error: err.message,
      completedAt: new Date().toISOString()
    });
    process.exit(1);
  });
} else if (!image || !title) {
  logError('缺少参数: --image, --title');
  console.log('\n用法:');
  console.log('  命令行: node publish_playwright.js --image <图片> --title <标题> --description <描述> --final');
  console.log('  JSON文件: node publish_playwright.js --input <json文件> --final');
  writeStructuredResult(RESULT_JSON_PATH, {
    ok: false,
    error: '缺少参数: --image, --title',
    image,
    title,
    completedAt: new Date().toISOString()
  });
  process.exit(1);
} else if ((TEST_MODE || FINAL_MODE) && !board) {
  logError('缺少参数: --board');
  writeStructuredResult(RESULT_JSON_PATH, {
    ok: false,
    error: '测试模式和发布模式必须提供 board',
    image,
    title,
    board,
    link,
    completedAt: new Date().toISOString()
  });
  process.exit(1);
} else {
  publishPin({
    image: image,
    title: title,
    board: board,
    link: link,
    description: description,
    altText: altText,
    chromeProfile: chromeProfile
  }).catch(err => {
    logError(`错误: ${err.message}`);
    writeStructuredResult(RESULT_JSON_PATH, {
      ok: false,
      error: err.message,
      image,
      title,
      board,
      link,
      completedAt: new Date().toISOString()
    });
    process.exit(1);
  });
}
