// MCP 任务中转服务器 — 内建 CDP 连接，零外部依赖
// 监听 localhost:5200，持久化任务到 ./tasks/ 目录
// 合并 CDP Proxy 后: fill_engine.py 直接调 localhost:5200 即可操作浏览器

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TASKS_DIR = path.join(__dirname, 'tasks');
const MAPPINGS_DIR = path.join(__dirname, 'mappings');
const CACHE_DIR = path.join(__dirname, 'cache', 'images');
const CACHE_MAIN = path.join(CACHE_DIR, 'mainThumb');
const CACHE_DETAIL = path.join(CACHE_DIR, 'detail');
const PORT = 5200;

// ====== 配置加载 (从 config.json 读取) ======
function loadConfig() {
  const configPath = path.join(MAPPINGS_DIR, 'config.json');
  const defaults = {
    llm: { api_url: '', api_key: '', model_id: '' },
    browsers: [
      { name: 'Edge', cdp_port: 9222, inspect_url: 'edge://inspect', path: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe' },
      { name: 'Chrome', cdp_port: 49727, inspect_url: 'chrome://inspect/#devices', path: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' }
    ]
  };
  try {
    if (fs.existsSync(configPath)) {
      const raw = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
      return { ...defaults, ...raw };
    }
  } catch (e) {
    console.error(`[Config] 读取失败: ${e.message}`);
  }
  return defaults;
}

const CONFIG = loadConfig();
const BROWSERS = CONFIG.browsers || [];
const PYTHON_CMD = process.env.PYTHON_CMD || CONFIG.python || 'python';
const MAX_TASKS = Math.max(1, parseInt(CONFIG.max_tasks) || 5);

// 确保目录存在
[TASKS_DIR, CACHE_MAIN, CACHE_DETAIL].forEach(dir => {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
});

// ====== 工具函数 ======

function json(res, data, status = 200) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type'
  });
  res.end(JSON.stringify(data, null, 2));
}

function readBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => {
      try { resolve(JSON.parse(body)); }
      catch { resolve(null); }
    });
    req.on('error', (err) => {
      console.error(`[MCP] readBody error: ${err.message}`);
      resolve(null);
    });
  });
}

function readBodyRaw(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => resolve(body));
    req.on('error', () => resolve(''));
  });
}

function generateId() {
  return `task_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function saveTask(task) {
  const file = path.join(TASKS_DIR, `${task.id}.json`);
  try {
    fs.writeFileSync(file, JSON.stringify(task, null, 2), 'utf-8');
  } catch (e) {
    console.error(`[MCP] 保存任务失败: ${e.message}`);
  }
}

function loadTask(id) {
  const file = path.join(TASKS_DIR, `${id}.json`);
  if (fs.existsSync(file)) {
    return JSON.parse(fs.readFileSync(file, 'utf-8'));
  }
  return null;
}

function listTasks(statusFilter) {
  const files = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
  const tasks = files.map(f => {
    try { return JSON.parse(fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8')); }
    catch { return null; }
  }).filter(Boolean);

  if (statusFilter) {
    return tasks.filter(t => t.status === statusFilter);
  }
  return tasks;
}

// ====== 清理过期的任务 + 缓存图片 ======

/** 清理超过 MAX_TASKS 的最旧任务及其关联缓存 */
function cleanupOldTasks() {
  let files;
  try {
    files = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
  } catch { return; }
  if (files.length <= MAX_TASKS) return; // 没超限，不动

  // 按 created_at 排序，保留最近的 MAX_TASKS 条
  const taskList = files.map(f => {
    try {
      const data = JSON.parse(fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8'));
      return { file: f, created_at: data.created_at || '1970-01-01', data };
    } catch { return null; }
  }).filter(Boolean);
  taskList.sort((a, b) => (a.created_at < b.created_at ? -1 : 1));

  const toDelete = taskList.slice(0, taskList.length - MAX_TASKS);
  if (toDelete.length === 0) return;

  console.log(`[MCP] 任务上限 ${MAX_TASKS}, 当前 ${files.length} 条, 清理 ${toDelete.length} 条旧任务`);
  let deletedTasks = 0;
  for (const entry of toDelete) {
    // 删除任务 JSON
    const taskPath = path.join(TASKS_DIR, entry.file);
    try { fs.unlinkSync(taskPath); deletedTasks++; } catch (e) { console.error(`[MCP] 删除旧任务 ${entry.file} 失败: ${e.message}`); }

    // 删除关联的缓存图片
    const data = entry.data;
    const mainLocal = data.images_mainThumb_local || [];
    const detailLocal = data.images_detail_local || [];
    for (const imgPath of [...mainLocal, ...detailLocal]) {
      try { if (fs.existsSync(imgPath)) { fs.unlinkSync(imgPath); } } catch {}
    }
  }
  // 额外清理孤立缓存: 删除所有无任务引用的 cache 图片文件
  purgeOrphanedCache();
  if (deletedTasks > 0) console.log(`[MCP] 已清理 ${deletedTasks} 条旧任务及关联缓存`);
}

/** 删除 cache/ 下没有任何任务引用的孤立图片 */
function purgeOrphanedCache() {
  // 收集所有任务引用的图片路径
  const referenced = new Set();
  try {
    const taskFiles = fs.readdirSync(TASKS_DIR).filter(f => f.endsWith('.json'));
    for (const f of taskFiles) {
      try {
        const data = JSON.parse(fs.readFileSync(path.join(TASKS_DIR, f), 'utf-8'));
        const mainLocal = data.images_mainThumb_local || [];
        const detailLocal = data.images_detail_local || [];
        for (const p of [...mainLocal, ...detailLocal]) referenced.add(p);
      } catch {}
    }
  } catch { return; }

  let purged = 0;
  for (const dir of [CACHE_MAIN, CACHE_DETAIL]) {
    try {
      if (!fs.existsSync(dir)) continue;
      const files = fs.readdirSync(dir);
      for (const f of files) {
        const fullPath = path.join(dir, f);
        if (!referenced.has(fullPath)) {
          try { fs.unlinkSync(fullPath); purged++; } catch {}
        }
      }
    } catch {}
  }
  // 也清理 cache/images/ 根目录的散落文件
  try {
    if (fs.existsSync(CACHE_DIR)) {
      for (const f of fs.readdirSync(CACHE_DIR)) {
        if (f === 'mainThumb' || f === 'detail') continue;
        const fullPath = path.join(CACHE_DIR, f);
        if (!referenced.has(fullPath)) {
          try { fs.unlinkSync(fullPath); purged++; } catch {}
        }
      }
    }
  } catch {}
  if (purged > 0) console.log(`[MCP] 已清理 ${purged} 个孤立缓存文件`);
}

// ====== 图片缓存管理 ======

function clearImageCache() {
  let total = 0;
  for (const dir of [CACHE_MAIN, CACHE_DETAIL]) {
    try {
      if (!fs.existsSync(dir)) continue;
      const files = fs.readdirSync(dir);
      for (const f of files) {
        try { fs.unlinkSync(path.join(dir, f)); total++; }
        catch (e) { console.error(`[MCP] 删除缓存失败: ${f}`, e.message); }
      }
    } catch (e) { console.error(`[MCP] 清理目录失败 ${dir}: ${e.message}`); }
  }
  try {
    if (fs.existsSync(CACHE_DIR)) {
      const files = fs.readdirSync(CACHE_DIR);
      for (const f of files) {
        if (f === 'mainThumb' || f === 'detail') continue;
        try { fs.unlinkSync(path.join(CACHE_DIR, f)); total++; }
        catch (e) { /* ignore */ }
      }
    }
  } catch (e) { /* ignore */ }
  if (total > 0) console.log(`[MCP] 已清除 ${total} 张缓存图片`);
}

async function downloadImageTo(url, index, targetDir) {
  const ext = url.match(/\.(jpg|jpeg|png|webp|gif|bmp)/i)?.[1] || 'jpg';
  let basename = '';
  try {
    basename = new URL(url).pathname.split('/').pop() || `img_${index}`;
    basename = basename.replace(/[<>:"/\\|?*]/g, '_');
    if (!basename.includes('.')) basename += `.${ext}`;
  } catch {
    basename = `img_${String(index).padStart(3, '0')}.${ext}`;
  }
  const localPath = path.join(targetDir, basename);
  try {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), 15000);
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(t);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const buffer = Buffer.from(await response.arrayBuffer());
    fs.writeFileSync(localPath, buffer);
    console.log(`[MCP] 图片已缓存: ${path.basename(targetDir)}/${basename} (${buffer.length} bytes)`);
    return localPath;
  } catch (e) {
    console.error(`[MCP] 图片下载失败 [${index}]: ${url.slice(0, 80)} — ${e.message}`);
    return null;
  }
}

async function cacheImagesSeparated(mainThumbUrls, detailUrls) {
  clearImageCache();
  const mainResults = [];
  const detailResults = [];
  for (let i = 0; i < mainThumbUrls.length; i++) {
    const localPath = await downloadImageTo(mainThumbUrls[i], i, CACHE_MAIN);
    if (localPath) mainResults.push(localPath);
  }
  for (let i = 0; i < detailUrls.length; i++) {
    const localPath = await downloadImageTo(detailUrls[i], i, CACHE_DETAIL);
    if (localPath) detailResults.push(localPath);
  }
  console.log(`[MCP] 缓存完成: 主图${mainResults.length}/${mainThumbUrls.length} 详情${detailResults.length}/${detailUrls.length}`);
  return { mainThumb: mainResults, detail: detailResults };
}

// ====== 内建 CDP 连接 (支持多浏览器, 配置自 config.json) ======

let ws = null;
let cmdId = 0;
const pending = new Map();
const sessions = new Map();
const eventListeners = new Map();
let cdpConnected = false;
let cdpLastError = null;
let cdpRetryCount = 0;
let cdpLastAttempt = null;
/** 当前连接的浏览器信息 (name, port) */
let connectedBrowser = null;
/** 各浏览器的检测结果 (name -> { reachable, error }) */
const browserStatus = new Map();

/** 探测浏览器 CDP 端口是否可达 */
async function probeBrowser(browser) {
  const port = browser.cdp_port;
  const name = browser.name;
  try {
    const result = await tryPort(port);
    if (result) {
      browserStatus.set(name, { reachable: true, wsUrl: result.wsUrl, error: null });
      return result.wsUrl;
    }
  } catch (e) { /* 尝试下一个 */ }

  // 配置端口失败 → 尝试 auto_scan（扫描常见端口）
  if (browser.auto_scan) {
    const scanPorts = browser.scan_ports || [9222, 9229, 9230, 49727];
    console.log(`[CDP] ${name} 端口 ${port} 不可达，正扫描 ${scanPorts.join(', ')} ...`);
    for (const sp of scanPorts) {
      if (sp === port) continue;
      try {
        const result = await tryPort(sp);
        if (result) {
          console.log(`[CDP] ${name} 在端口 ${sp} 检测到`);
          browserStatus.set(name, { reachable: true, wsUrl: result.wsUrl, error: null });
          return result.wsUrl;
        }
      } catch (e) { /* 继续 */ }
    }
  }

  browserStatus.set(name, { reachable: false, wsUrl: null, error: '所有端口不可达' });
  return null;
}

/** 尝试连接指定端口 */
async function tryPort(port) {
  const versionResp = await new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}/json/version`, { timeout: 1500 }, (res) => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(d));
    }).on('error', reject);
  });
  const version = JSON.parse(versionResp);
  const wsUrl = version.webSocketDebuggerUrl || `ws://127.0.0.1:${port}/devtools/browser`;
  return { wsUrl, version };
}

/** 连接到指定浏览器的 CDP WebSocket */
async function connectToBrowser(browser, wsUrl) {
  const name = browser.name;
  const port = browser.cdp_port;
  return new Promise((resolve, reject) => {
    let wss;
    try {
      wss = new WebSocket(wsUrl);
    } catch (e) {
      return reject(new Error(`创建 WebSocket 失败: ${e.message}`));
    }

    const onOpen = () => {
      ws = wss;
      connectedBrowser = { name, port };
      console.log(`[CDP] 已连接 ${name} (端口 ${port})`);
      cdpConnected = true;
      cdpLastError = null;
      cdpRetryCount = 0;
      cleanup();
      resolve();
    };
    const onError = (e) => {
      cleanup();
      cdpConnected = false;
      reject(new Error(`${name} WebSocket 连接失败: ${e.message || e}`));
    };
    const onClose = () => {
      console.log(`[CDP] ${connectedBrowser?.name || '浏览器'} 连接断开`);
      ws = null;
      cdpConnected = false;
      sessions.clear();
      connectedBrowser = null;
    };
    function cleanup() {
      wss.removeEventListener?.('open', onOpen);
      wss.removeEventListener?.('error', onError);
    }

    wss.addEventListener('open', onOpen);
    wss.addEventListener('error', onError);
    wss.addEventListener('close', onClose);
    wss.addEventListener('message', (evt) => {
      const msg = JSON.parse(typeof evt.data === 'string' ? evt.data : evt.data.toString());
      if (msg.method === 'Target.attachedToTarget') {
        const { sessionId, targetInfo } = msg.params;
        sessions.set(targetInfo.targetId, sessionId);
      }
      if (msg.method && !msg.id && eventListeners.has(msg.method)) {
        const listeners = eventListeners.get(msg.method);
        eventListeners.delete(msg.method);
        for (const { resolve: r, timer: t } of listeners) {
          clearTimeout(t);
          r(msg);
        }
        return;
      }
      if (msg.id && pending.has(msg.id)) {
        const { resolve: r, timer: t } = pending.get(msg.id);
        clearTimeout(t);
        pending.delete(msg.id);
        r(msg);
      }
    });
  });
}

function sendCDP(method, params = {}, sessionId = null) {
  return new Promise((resolve, reject) => {
    if (!ws || ws.readyState !== 1) { // 1 = WebSocket.OPEN
      return reject(new Error('CDP WebSocket 未连接'));
    }
    const id = ++cmdId;
    const msg = { id, method, params };
    if (sessionId) msg.sessionId = sessionId;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('CDP 命令超时: ' + method));
    }, 30000);
    pending.set(id, { resolve, timer });
    ws.send(JSON.stringify(msg));
  });
}

async function ensureSession(targetId) {
  if (sessions.has(targetId)) return sessions.get(targetId);
  const resp = await sendCDP('Target.attachToTarget', { targetId, flatten: true });
  if (resp.result?.sessionId) {
    const sid = resp.result.sessionId;
    sessions.set(targetId, sid);
    return sid;
  }
  throw new Error('attach 失败: ' + JSON.stringify(resp.error));
}

/** 尝试连接可用浏览器: 按优先级逐个探测, 成功的第一个即停 */
async function connectCDP(force = false) {
  if (!force && ws && ws.readyState === 1) return;
  cdpLastAttempt = new Date().toISOString();
  cdpConnected = false;

  if (BROWSERS.length === 0) {
    cdpLastError = '未配置浏览器 (config.json > browsers 为空)';
    throw new Error(cdpLastError);
  }

  const probes = BROWSERS.map(b => probeBrowser(b));
  await Promise.all(probes);
  const reachable = BROWSERS.filter(b => browserStatus.get(b.name)?.reachable);

  if (reachable.length === 0) {
    const details = BROWSERS.map(b => {
      const s = browserStatus.get(b.name);
      return `${b.name} (端口 ${b.cdp_port}): ${s ? s.error : '未检测'}`;
    }).join('; ');
    cdpLastError = `未检测到可用浏览器: ${details}\n请确认 ${BROWSERS.map(b => b.inspect_url || (b.name + ' 远程调试')).join(' 或 ')} 已勾选"允许远程调试"`;
    throw new Error(cdpLastError);
  }

  // 按配置优先级连接第一个可达浏览器
  for (const browser of BROWSERS) {
    const status = browserStatus.get(browser.name);
    if (status?.reachable) {
      try {
        await connectToBrowser(browser, status.wsUrl);
        return;
      } catch (e) {
        console.error(`[CDP] 连接 ${browser.name} 失败: ${e.message}`);
      }
    }
  }

  cdpLastError = '所有可达浏览器连接均失败';
  throw new Error(cdpLastError);
}

async function waitForCDPEvent(method, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      if (eventListeners.has(method)) {
        eventListeners.delete(method);
      }
      reject(new Error('等待 CDP 事件超时: ' + method));
    }, timeoutMs);
    const listener = { resolve, timer };
    if (eventListeners.has(method)) {
      eventListeners.get(method).push(listener);
    } else {
      eventListeners.set(method, [listener]);
    }
  });
}

async function waitForPageLoad(sessionId, timeoutMs = 15000) {
  try { await sendCDP('Page.enable', { enableFileChooserOpenedEvent: true }, sessionId); } catch { /* ignore */ }
  return new Promise((resolve) => {
    let resolved = false;
    const done = (result) => {
      if (resolved) return;
      resolved = true;
      clearTimeout(timer);
      clearInterval(checkInterval);
      resolve(result);
    };
    const timer = setTimeout(() => done('timeout'), timeoutMs);
    const checkInterval = setInterval(async () => {
      try {
        const resp = await sendCDP('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true }, sessionId);
        if (resp.result?.result?.value === 'complete') done('complete');
      } catch { /* ignore */ }
    }, 500);
  });
}

// ====== autoResolve: py 脚本填表 ======
async function autoResolve(task) {
  const taskFile = path.join(TASKS_DIR, `${task.id}.json`);
  const py = PYTHON_CMD;
  const engine = path.join(__dirname, 'fill_engine.py');

  console.log(`[MCP] 自动 resolve: ${task.id}`);
  try {
    const result = await new Promise((resolve) => {
      const child = spawn(py, ['-u', engine, taskFile, '--skip-nav'], {
        cwd: __dirname,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe']  // 不用 inherit，手动 pipe stderr
      });
      let stdout = '';
      child.stdout.on('data', (d) => { stdout += d.toString(); });
      child.stderr.on('data', (d) => { process.stderr.write(d); });
      const timer = setTimeout(() => { child.kill(); resolve({ code: -2, stdout }); }, 120000);
      child.on('close', (code) => { clearTimeout(timer); resolve({ code, stdout }); });
      child.on('error', (err) => { clearTimeout(timer); resolve({ code: -1, stdout: '' }); });
    });

    const output = result.stdout || '';
    let parsed;
    try {
      const trimmed = output.trim();
      const jsonStart = trimmed.indexOf('{');
      if (jsonStart >= 0) parsed = JSON.parse(trimmed.slice(jsonStart));
    } catch { parsed = null; }

    if (parsed && parsed.success && !parsed.need_ai) {
      task.status = 'completed';
      task.completed_at = new Date().toISOString();
      task.result = { ...parsed, method: 'auto_script' };
      saveTask(task);
      console.log(`[MCP] 自动 resolve 成功: ${task.id}`);
    } else if (parsed && parsed.success && parsed.ai_required && parsed.ai_required.length > 0) {
      task.status = 'partial';
      task.partial_result = parsed;
      task.ai_required = parsed.ai_required;
      saveTask(task);
      console.log(`[MCP] 自动 resolve 部分: ${task.id}, 需 LLM: ${parsed.ai_required.map(f => f.field).join(', ')}`);
      await callLLM(task);
    } else {
      task.status = 'partial';
      task.ai_required = [];
      task.partial_result = parsed || { error: 'script_failed' };
      saveTask(task);
      console.log(`[MCP] 自动 resolve 失败: ${task.id}`);
    }
  } catch (e) {
    console.error(`[MCP] 自动 resolve 异常: ${task.id} - ${e.message}`);
  }

  // 同步触发 pending 映射解析 (用 stdio:'inherit' 直接输出到控制台)
  await resolveMappingsInBackground();
}

async function resolveMappingsInBackground() {
  const pendingFile = path.join(MAPPINGS_DIR, 'pending_mappings.json');
  console.log('[MCP] ═══════ 检查 pending ═══════');
  let hasPending = false;
  let pendingCount = 0;
  try {
    const raw = fs.readFileSync(pendingFile, 'utf8');
    const arr = JSON.parse(raw);
    pendingCount = arr.filter(e => !e.resolved).length;
    hasPending = pendingCount > 0;
    console.log(`[MCP] pending 文件: ${arr.length}条, 未解析${pendingCount}条`);
  } catch (e) {
    console.log(`[MCP] pending 文件读取失败: ${e.message}`);
    return;
  }
  if (!hasPending) {
    console.log('[MCP] pending 为空, 跳过解析');
    return;
  }

  console.log('[MCP] ═══════ LLM 解析开始 ═══════');
  try {
    const py = PYTHON_CMD;
    const script = path.join(__dirname, 'scripts', 'resolve_mappings.py');
    await new Promise((resolve, reject) => {
      const child = spawn(py, ['-u', script], {
        cwd: __dirname,
        env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONDONTWRITEBYTECODE: '1', PYTHONUNBUFFERED: '1' },
        stdio: ['ignore', 'pipe', 'pipe']
      });
      child.stdout.on('data', (d) => { console.log(d.toString().trim()); });
      child.stderr.on('data', (d) => { console.log(d.toString().trim()); });
      child.on('close', (code) => {
        console.log(`[MCP] ═══════ LLM 解析完成 (code=${code}) ═══════`);
        resolve();
      });
      child.on('error', (err) => {
        console.error(`[MCP] LLM 解析启动失败: ${err.message}`);
        reject(err);
      });
    });
  } catch (e) {
    console.error(`[MCP] 后台 pending 解析异常: ${e.message}`);
  }
}

// ====== LLM 补填 (CDP 自引用: localhost:5200) ======

let _llmAvailable = false;
let LLM_API = '';
let LLM_KEY = '';
let LLM_MODEL = '';

function loadLLMConfig() {
  const llmCfg = CONFIG.llm || {};
  LLM_API = (llmCfg.api_url || '').trim();
  LLM_KEY = (llmCfg.api_key || '').trim();
  LLM_MODEL = (llmCfg.model_id || '').trim();
  _llmAvailable = !!LLM_API;
  if (!_llmAvailable) {
    console.log('[LLM] api_url 为空, LLM 补填功能已禁用');
  } else {
    console.log(`[LLM] 已配置: ${LLM_API} (模型: ${LLM_MODEL})`);
  }
}
loadLLMConfig();

function buildPrompt(task) {
  const fields = task.ai_required || [];
  const fieldList = fields.map(f =>
    `- ${f.field}: 填入值="${f.value}", selector类型=${f.selector_type}`
  ).join('\n');
  return `你是京东秒送商品发布表单的自动填写助手。当前页面已经通过脚本填入了部分字段，以下字段需要你补填：

${fieldList}

请为每个字段生成 CDP eval 的 JavaScript 代码来填入表单，返回格式为 JSON 数组：
[
  {"field":"商品品牌","js":"(function(){...})()"},
  ...
]

规则：
1. 当前页面 URL: ${task.target_url}
2. 可通过 CDP eval 执行任意 JS 来操控表单
3. 商品品牌 是 dj-cascader 级联选择器，需要先点击输入框展开下拉，搜索关键词，再点击匹配项
4. 店内分类 是 jd-select 下拉选择器，操作方式类似
5. Formily form 实例预缓存在 window.__wb_form
6. 只生成缺失字段的 JS，已填好的字段不要动
7. 不要点保存/提交按钮
8. 只输出 JSON 数组，不要其他内容`;
}

async function executeCDP(targetId, js) {
  const resp = await fetch(`http://127.0.0.1:${PORT}/eval?target=${targetId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    body: js
  });
  const data = await resp.json();
  return data.value || data.error || 'unknown';
}

async function callLLM(task) {
  if (!_llmAvailable) {
    console.log(`[MCP] LLM: api_url 为空, 跳过 LLM 补填`);
    task.status = 'completed';
    task.completed_at = new Date().toISOString();
    saveTask(task);
    return;
  }
  const fields = task.ai_required || [];
  if (fields.length === 0) {
    console.log(`[MCP] LLM: 无需补填字段`);
    task.status = 'completed';
    task.completed_at = new Date().toISOString();
    saveTask(task);
    return;
  }

  console.log(`[MCP] LLM: 开始补填 ${fields.map(f => f.field).join(', ')}`);
  const prompt = buildPrompt(task);

  try {
    const resp = await fetch(LLM_API, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${LLM_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        model: LLM_MODEL,
        messages: [
          { role: 'system', content: '你是京东秒送填表助手，只输出 JSON。' },
          { role: 'user', content: prompt }
        ],
        max_tokens: 8000
      })
    });

    const data = await resp.json();
    const content = data?.choices?.[0]?.message?.content || '';
    console.log(`[MCP] LLM 响应: ${content.slice(0, 300)}`);

    let commands = [];
    try {
      const jsonMatch = content.match(/\[[\s\S]*\]/);
      if (jsonMatch) commands = JSON.parse(jsonMatch[0]);
    } catch (e) {
      console.error(`[MCP] LLM 响应解析失败: ${e.message}`);
    }

    // 获取 JD tab
    const tabsResp = await sendCDP('Target.getTargets');
    const tabs = tabsResp.result?.targetInfos || [];
    const jdTab = tabs.find(t => t.url && t.url.includes('store.jddj.com'));
    const targetId = jdTab ? jdTab.targetId : '';

    for (const cmd of commands) {
      console.log(`[MCP] LLM 执行: ${cmd.field}`);
      try {
        const result = await executeCDP(targetId, cmd.js);
        console.log(`[MCP]   => ${JSON.stringify(result).slice(0, 100)}`);
        if (!task.llm_result) task.llm_result = {};
        task.llm_result[cmd.field] = result;
      } catch (e) {
        console.error(`[MCP] LLM 执行失败 [${cmd.field}]: ${e.message}`);
      }
    }

    task.status = 'completed';
    task.completed_at = new Date().toISOString();
    task.result = { ...(task.result || {}), method: 'script+llm', llm_fields: fields.map(f => f.field) };
    saveTask(task);
    console.log(`[MCP] LLM 补填完成: ${task.id}`);
  } catch (e) {
    console.error(`[MCP] LLM 调用异常: ${e.message}`);
  }
}

// ====== CDP HTTP 端点处理 ======

async function handleCDPEndpoint(req, url, q, body) {
  // 先检查连通性，断连则自动重试
  try {
    await connectCDP();
  } catch (e) {
    return { error: `CDP 连接失败: ${e.message}`, cdp_error: cdpLastError, hint: '请确保 Edge 已开启远程调试 (edge://inspect → Remote debugging)' };
  }

  // GET /targets
  if (url.pathname === '/targets') {
    const resp = await sendCDP('Target.getTargets');
    const pages = (resp.result?.targetInfos || []).filter(t => t.type === 'page');
    return pages;
  }

  // POST /new (body=URL)
  if (url.pathname === '/new') {
    const targetUrl = (body || '').trim() || 'about:blank';
    const resp = await sendCDP('Target.createTarget', { url: targetUrl, background: true });
    const targetId = resp.result.targetId;
    if (targetUrl !== 'about:blank') {
      try {
        const sid = await ensureSession(targetId);
        await waitForPageLoad(sid);
      } catch { /* ignore */ }
    }
    return { targetId };
  }

  // GET /close?target=xxx
  if (url.pathname === '/close') {
    const resp = await sendCDP('Target.closeTarget', { targetId: q.target });
    sessions.delete(q.target);
    return resp.result || { closed: true };
  }

  // POST /navigate?target=xxx (body=URL)
  if (url.pathname === '/navigate') {
    const targetUrl = (body || '').trim();
    const sid = await ensureSession(q.target);
    const resp = await sendCDP('Page.navigate', { url: targetUrl }, sid);
    await waitForPageLoad(sid);
    return resp.result;
  }

  // POST /activate?target=xxx — 激活标签页 (防止后台点击失效)
  if (url.pathname === '/activate') {
    const sid = await ensureSession(q.target);
    await sendCDP('Target.activateTarget', { targetId: q.target });
    return { ok: true };
  }

  // POST /eval?target=xxx (body=JS)
  if (url.pathname === '/eval') {
    const sid = await ensureSession(q.target);
    const expr = body || q.expr || 'document.title';
    const resp = await sendCDP('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true }, sid);
    if (resp.result?.result?.value !== undefined) {
      return { value: resp.result.result.value };
    } else if (resp.result?.exceptionDetails) {
      return { error: resp.result.exceptionDetails.text };
    }
    return resp.result;
  }

  // POST /click?target=xxx (body=CSS selector)
  if (url.pathname === '/click') {
    const sid = await ensureSession(q.target);
    const selector = body;
    if (!selector) return { error: 'POST body 需要 CSS 选择器' };
    const selectorJson = JSON.stringify(selector);
    const js = `(() => {
      const el = document.querySelector(${selectorJson});
      if (!el) return { error: '未找到元素: ' + ${selectorJson} };
      el.scrollIntoView({ block: 'center' });
      el.click();
      return { clicked: true, tag: el.tagName, text: (el.textContent || '').slice(0, 100) };
    })()`;
    const resp = await sendCDP('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true }, sid);
    if (resp.result?.result?.value) {
      const val = resp.result.result.value;
      if (val.error) return val;
      return val;
    }
    return resp.result;
  }

  // POST /clickXY?target=xxx (body: {x, y})
  if (url.pathname === '/clickXY') {
    const sid = await ensureSession(q.target);
    const coords = typeof body === 'object' ? body : JSON.parse(body || '{}');
    if (typeof coords.x !== 'number' || typeof coords.y !== 'number') {
      return { error: '需要 {"x":number,"y":number}' };
    }
    await sendCDP('Input.dispatchMouseEvent', { type: 'mousePressed', x: coords.x, y: coords.y, button: 'left', clickCount: 1 }, sid);
    await sendCDP('Input.dispatchMouseEvent', { type: 'mouseReleased', x: coords.x, y: coords.y, button: 'left', clickCount: 1 }, sid);
    return { clicked: true, x: coords.x, y: coords.y };
  }

  // POST /hover?target=xxx (body: {x, y}) — 模拟鼠标悬停
  if (url.pathname === '/hover') {
    const sid = await ensureSession(q.target);
    const coords = typeof body === 'object' ? body : JSON.parse(body || '{}');
    if (typeof coords.x !== 'number' || typeof coords.y !== 'number') {
      return { error: '需要 {"x":number,"y":number}' };
    }
    await sendCDP('Input.dispatchMouseEvent', { type: 'mouseMoved', x: coords.x, y: coords.y }, sid);
    return { hovered: true, x: coords.x, y: coords.y };
  }

  // POST /setFiles?target=xxx (body: {selector, files, iframeSelector?})
  if (url.pathname === '/setFiles') {
    const sid = await ensureSession(q.target);
    const fbody = typeof body === 'object' ? body : JSON.parse(body || '{}');
    if (!fbody.selector || !fbody.files) return { error: '需要 selector 和 files 字段' };
    await sendCDP('DOM.enable', {}, sid);
    let rootNodeId = null;
    if (fbody.iframeSelector) {
      // 解决iframe内元素: 先获取iframe的contentDocument作为query根
      const iframeResp = await sendCDP('Runtime.evaluate', {
        expression: `document.querySelector('${fbody.iframeSelector}').contentDocument`,
        returnByValue: false
      }, sid);
      if (iframeResp.result?.result?.objectId) {
        const nodeResp = await sendCDP('DOM.requestNode', { objectId: iframeResp.result.result.objectId }, sid);
        rootNodeId = nodeResp.result?.nodeId;
      }
    }
    if (!rootNodeId) {
      const doc = await sendCDP('DOM.getDocument', {}, sid);
      rootNodeId = doc.result.root.nodeId;
    }
    const node = await sendCDP('DOM.querySelector', { nodeId: rootNodeId, selector: fbody.selector }, sid);
    if (!node.result?.nodeId) return { error: '未找到元素: ' + fbody.selector };
    await sendCDP('DOM.setFileInputFiles', { nodeId: node.result.nodeId, files: fbody.files }, sid);
    return { success: true, files: fbody.files.length };
  }

  // POST /uploadFiles?target=xxx (body: {triggerSelector, files})
  if (url.pathname === '/uploadFiles') {
    const sid = await ensureSession(q.target);
    const ubody = typeof body === 'object' ? body : JSON.parse(body || '{}');
    if (!ubody.files || !ubody.files.length) return { error: '需要 files 数组' };
    const triggerSel = ubody.triggerSelector || '.dj-upload-upload-btn';

    // Step 1: 滚动到上传区域 + 点击外层按钮打开弹窗
    const posRes = await sendCDP('Runtime.evaluate', {
      expression: `(function(){
        var btn=document.querySelector('${triggerSel.replace(/'/g,"\\'")}');
        if(!btn)return'NB';
        btn.scrollIntoView({block:'center'});
        var r=btn.getBoundingClientRect();
        return JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)});
      })()`,
      returnByValue: true
    }, sid);
    let coords = null;
    try { coords = JSON.parse(posRes.result?.result?.value || ''); } catch {}
    if (!coords) return { error: '未找到按钮: ' + triggerSel };

    await sendCDP('Input.dispatchMouseEvent', { type: 'mousePressed', x: coords.x, y: coords.y, button: 'left', clickCount: 1 }, sid);
    await sendCDP('Input.dispatchMouseEvent', { type: 'mouseReleased', x: coords.x, y: coords.y, button: 'left', clickCount: 1 }, sid);

    // 轮询等待弹窗出现 (最多 5s)
    let dialogReady = false;
    for (let t = 0; t < 20; t++) {
      await new Promise(r => setTimeout(r, 250));
      const cr = await sendCDP('Runtime.evaluate', {
        expression: "(function(){var d=document.querySelector('.jd-upload');return d&&d.offsetParent?'vis':'hid'})()",
        returnByValue: true
      }, sid);
      if (cr.result?.result?.value === 'vis') { dialogReady = true; break; }
    }
    if (!dialogReady) return { error: '上传弹窗未出现', success: false };

    // Step 2: hook + click 弹窗内 file input → setFiles → change → 点确定
    await sendCDP('Runtime.evaluate', {
      expression: `(function(){
        if(!window.__cdpUploadHooked){
          var o=HTMLInputElement.prototype.click;
          HTMLInputElement.prototype.click=function(){
            if(this.type==='file'){window.__cdpFileInput=this;return;}
            return o.call(this);
          };
          window.__cdpUploadHooked=true;window.__cdpOrigClick=o;
        }
        var fi=document.querySelector('.jd-upload input[type=file]');
        if(fi){fi.click();return'OK'}return'NF';
      })()`,
      returnByValue: true
    }, sid);
    await new Promise(r => setTimeout(r, 600));

    await sendCDP('DOM.enable', {}, sid);
    const doc = await sendCDP('DOM.getDocument', {}, sid);
    const node = await sendCDP('DOM.querySelector', { nodeId: doc.result.root.nodeId, selector: '.jd-upload input[type=file]' }, sid);
    if (!node.result?.nodeId) return { error: '未找到弹窗内的文件输入', success: false };

    await sendCDP('DOM.setFileInputFiles', { nodeId: node.result.nodeId, files: ubody.files }, sid);
    await sendCDP('Runtime.evaluate', {
      expression: "var fi=document.querySelector('.jd-upload input[type=file]');if(fi){fi.dispatchEvent(new Event('change',{bubbles:true,composed:true}));return'ok:'+fi.files.length}return'nf'",
      returnByValue: true
    }, sid);

    // 等上传完成: 先等 3s, 然后每秒尝试点确定, button disabled 时跳过
    await new Promise(r => setTimeout(r, 2000));
    let okClicked = false;
    for (let w = 0; w < 20; w++) {
      await new Promise(r => setTimeout(r, 500));
      const check = await sendCDP('Runtime.evaluate', {
        expression: "(function(){var b=document.querySelector('.jd-button--primary');if(!b)return'no_btn';if(b.disabled)return'disabled';b.click();return'ok'})()",
        returnByValue: true
      }, sid);
      if (check.result?.result?.value === 'ok') {
        okClicked = true; break;
      }
    }

    return { success: true, okClicked, files: ubody.files.length };
  }

  // GET /screenshot?target=xxx&file=/path
  if (url.pathname === '/screenshot') {
    const sid = await ensureSession(q.target);
    const format = q.format || 'png';
    const resp = await sendCDP('Page.captureScreenshot', { format, quality: format === 'jpeg' ? 80 : undefined }, sid);
    if (q.file) {
      fs.writeFileSync(q.file, Buffer.from(resp.result.data, 'base64'));
      return { saved: q.file };
    }
    return { data: resp.result.data, format };
  }

  // GET /info?target=xxx
  if (url.pathname === '/info') {
    const sid = await ensureSession(q.target);
    const resp = await sendCDP('Runtime.evaluate', {
      expression: 'JSON.stringify({title: document.title, url: location.href, ready: document.readyState})',
      returnByValue: true
    }, sid);
    return JSON.parse(resp.result?.result?.value || '{}');
  }

  return null; // not a CDP endpoint
}

// ====== HTTP 路由 ======

const server = http.createServer(async (req, res) => {
  // CORS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type'
    });
    res.end();
    return;
  }

  const url = new URL(req.url, `http://localhost:${PORT}`);
  const q = Object.fromEntries(url.searchParams);

  // ====== MCP 端点 ======

  // GET /health
  if (req.method === 'GET' && url.pathname === '/health') {
    const diagnostics = [];
    if (!cdpConnected && cdpLastError) {
      diagnostics.push(cdpLastError);
    }

    // 构造各浏览器状态对象
    const browserStates = {};
    for (const b of BROWSERS) {
      const s = browserStatus.get(b.name);
      browserStates[b.name] = {
        port: b.cdp_port,
        reachable: s ? s.reachable : null,
        error: s ? s.error : null
      };
    }

    return json(res, {
      ok: true,
      uptime: process.uptime(),
      cdp: {
        connected: cdpConnected,
        connected_browser: connectedBrowser,
        error: cdpLastError,
        retryCount: cdpRetryCount,
        lastAttempt: cdpLastAttempt
      },
      browsers: browserStates,
      diagnostics: diagnostics.length > 0 ? diagnostics : undefined,
      hint: cdpConnected ? null :
        'CDP 未连接。请确保至少一个浏览器已开启远程调试:\n' +
        '  Edge:   打开 edge://inspect → 左侧 Remote debugging → 勾选 "Allow remote debugging for this browser instance"\n' +
        '  Chrome: 打开 chrome://inspect/#devices → 确认 Server running 状态'
    });
  }

  // POST /reconnect (手动触发 CDP 重连)
  if (req.method === 'POST' && url.pathname === '/reconnect') {
    const oldWs = ws;
    if (oldWs) { try { oldWs.close(); } catch {} }
    ws = null;
    sessions.clear();
    connectedBrowser = null;
    browserStatus.clear();
    try {
      await connectCDP(true);
      return json(res, { ok: true, connected: true, connected_browser: connectedBrowser, message: 'CDP 已重新连接' });
    } catch (e) {
      return json(res, {
        ok: false, connected: false, error: cdpLastError,
        hint: '请确保至少一个浏览器已开启远程调试:\n  Edge: edge://inspect → Remote debugging\n  Chrome: chrome://inspect/#devices'
      }, 503);
    }
  }

  // GET /pending
  if (req.method === 'GET' && url.pathname === '/pending') {
    const tasks = listTasks('pending');
    tasks.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    return json(res, { count: tasks.length, tasks });
  }

  // GET /tasks
  if (req.method === 'GET' && url.pathname === '/tasks') {
    const status = url.searchParams.get('status') || null;
    const tasks = listTasks(status);
    tasks.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    return json(res, { count: tasks.length, tasks });
  }

  // POST /submit
  if (req.method === 'POST' && url.pathname === '/submit') {
    const body = await readBody(req);
    if (!body || !body.product) {
      return json(res, { error: '缺少 product 字段' }, 400);
    }
    const taskId = generateId();
    const imageUrls = body.images || [];
    const mainThumbUrls = body.images_mainThumb || [];
    const detailUrls = body.images_detail || [];
    const task = {
      id: taskId, status: 'pending', source: body.source || 'midea',
      product: body.product,
      images_original: imageUrls, images_mainThumb: mainThumbUrls, images_detail: detailUrls,
      images_mainThumb_local: [], images_detail_local: [],
      target_site: body.target_site || 'unknown', target_url: body.target_url || '',
      created_at: new Date().toISOString(), completed_at: null, error: null
    };
    saveTask(task);
    cleanupOldTasks(); // 新任务创建后清理旧任务+缓存
    console.log(`[MCP] 新任务: ${task.id} → ${task.target_site} (主图${mainThumbUrls.length}张, 详情${detailUrls.length}张)`);
    json(res, { success: true, task_id: task.id, task }, 201);

    if (mainThumbUrls.length > 0 || detailUrls.length > 0) {
      cacheImagesSeparated(mainThumbUrls, detailUrls).then(({ mainThumb, detail }) => {
        task.images_mainThumb_local = mainThumb;
        task.images_detail_local = detail;
        saveTask(task);
        console.log(`[MCP] 任务 ${task.id} 图片缓存完成`);
        autoResolve(task);
      }).catch(e => {
        console.error(`[MCP] 任务 ${task.id} 图片缓存异常: ${e.message}`);
      });
    }
    return;
  }

  // POST /resolve/:id
  if (req.method === 'POST' && url.pathname.startsWith('/resolve/')) {
    const taskId = url.pathname.split('/')[2];
    const task = loadTask(taskId);
    if (!task) return json(res, { error: '任务不存在' }, 404);
    const taskFile = path.join(TASKS_DIR, `${taskId}.json`);

    try {
      const py = PYTHON_CMD;
      const engine = path.join(__dirname, 'fill_engine.py');
      const result = await new Promise((resolve) => {
        const child = spawn(py, ['-u', engine, taskFile], {
          cwd: __dirname,
          env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
          stdio: ['ignore', 'pipe', 'pipe']
        });
        let stdout = '', stderr = '';
        child.stdout.on('data', (d) => { stdout += d.toString(); });
        child.stderr.on('data', (d) => { stderr += d.toString(); process.stderr.write(d); });
        const timer = setTimeout(() => { child.kill(); resolve({ code: -2, stdout, stderr: 'timeout' }); }, 120000);
        child.on('close', (code) => { clearTimeout(timer); resolve({ code, stdout, stderr }); });
        child.on('error', (err) => { clearTimeout(timer); resolve({ code: -1, stdout: '', stderr: err.message }); });
      });

      const output = result.stdout || '';
      const errOut = result.stderr || '';
      console.log(`[MCP] fill_engine (exit ${result.code}) stdoutLen=${output.length}`);
      if (errOut) console.log(`[MCP] fill_engine stderr: ${errOut.slice(0, 200)}...`);
      let parsed;
      try {
        // compact JSON: single line, starts with {
        const trimmed = output.trim();
        const jsonStart = trimmed.indexOf('{');
        if (jsonStart >= 0) parsed = JSON.parse(trimmed.slice(jsonStart));
        console.log(`[MCP] JSON parse: ok, keys=${Object.keys(parsed||{}).join(',')}`);
      } catch (e) {
        console.log(`[MCP] JSON parse error: ${e.message.slice(0, 100)}`);
        parsed = null;
      }

      if (parsed && parsed.success && !parsed.need_ai) {
        task.status = 'completed';
        task.completed_at = new Date().toISOString();
        task.result = { ...parsed, method: 'script' };
        saveTask(task);
        return json(res, { success: true, method: 'script', task });
      }
      if (parsed && parsed.success && parsed.ai_required && parsed.ai_required.length > 0) {
        task.status = 'partial';
        task.partial_result = parsed;
        task.ai_required = parsed.ai_required;
        saveTask(task);
        return json(res, { partial_success: true, filled: parsed.filled, ai_required: parsed.ai_required, unmapped_params: parsed.unmapped_params || [], screenshot: parsed.screenshot, task });
      }
      return json(res, { success: false, need_ai: true, task, reason: parsed?.reason || 'script_failed', unmapped_params: parsed?.unmapped_params || [], script_error: parsed?.error || '' }, 200);
    } catch (e) {
      return json(res, { success: false, need_ai: true, task, reason: 'engine_error', script_error: e.message }, 200);
    }
  }

  // POST /complete/:id
  if (req.method === 'POST' && url.pathname.startsWith('/complete/')) {
    const taskId = url.pathname.split('/')[2];
    const body = await readBody(req);
    const task = loadTask(taskId);
    if (!task) return json(res, { error: '任务不存在' }, 404);
    task.status = 'completed';
    task.completed_at = new Date().toISOString();
    task.result = body?.result || null;
    saveTask(task);
    return json(res, { success: true, task });
  }

  // POST /fail/:id
  if (req.method === 'POST' && url.pathname.startsWith('/fail/')) {
    const taskId = url.pathname.split('/')[2];
    const body = await readBody(req);
    const task = loadTask(taskId);
    if (!task) return json(res, { error: '任务不存在' }, 404);
    task.status = 'failed';
    task.error = body?.error || '未知错误';
    task.completed_at = new Date().toISOString();
    saveTask(task);
    return json(res, { success: true, task });
  }

  // DELETE /task/:id
  if (req.method === 'DELETE' && url.pathname.startsWith('/task/')) {
    const taskId = url.pathname.split('/')[2];
    const file = path.join(TASKS_DIR, `${taskId}.json`);
    if (fs.existsSync(file)) { fs.unlinkSync(file); return json(res, { success: true }); }
    return json(res, { error: '任务不存在' }, 404);
  }

  // ====== CDP 端点 (与 MCP 端点共享端口) ======

  // CDP endpoints that need a raw body
  const cdpMethods = ['/targets', '/new', '/close', '/navigate', '/eval', '/click', '/clickXY', '/hover', '/setFiles', '/uploadFiles', '/screenshot', '/info', '/activate'];
  if (cdpMethods.includes(url.pathname)) {
    try {
      const rawBody = await readBodyRaw(req);
      const parsedBody = rawBody ? (() => { try { return JSON.parse(rawBody); } catch { return rawBody; } })() : null;
      const result = await handleCDPEndpoint(req, url, q, parsedBody);

      if (url.pathname === '/screenshot' && q.file) {
        // file saved, return JSON
        return json(res, result);
      }
      if (url.pathname === '/screenshot' && !q.file && result?.data) {
        // return raw image
        res.setHeader('Content-Type', 'image/' + (q.format || 'png'));
        res.end(Buffer.from(result.data, 'base64'));
        return;
      }
      return json(res, result);
    } catch (e) {
      return json(res, { error: e.message }, 500);
    }
  }

  // 404
  json(res, { error: 'Not found' }, 404);
});

// ====== 启动 ======

process.on('uncaughtException', (err) => {
  console.error(`[MCP] 未捕获异常: ${err.message}`);
});
process.on('unhandledRejection', (reason) => {
  console.error(`[MCP] 未处理的Promise拒绝: ${reason?.message || reason}`);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[MCP] 任务服务器 + 内建 CDP: http://127.0.0.1:${PORT}`);
  console.log(`[MCP] 已合并 CDP Proxy 功能，无需额外代理进程`);
  console.log(`[MCP] 端点: POST /submit | GET /pending | POST /complete/:id`);
  console.log(`[MCP] CDP: GET /targets | POST /eval | POST /clickXY | POST /uploadFiles | etc.`);

  // 启动时自动探测并连接浏览器
  connectCDP().catch(async (e) => {
    console.error(`[CDP] 初始连接失败: ${e.message}`);
    console.log(`[CDP] 没有检测到可用浏览器，将自动打开浏览器调试配置页面...`);

    // 尝试打开第一个浏览器的 inspect 页面 (方便用户开启远程调试)
    const defaultBrowser = BROWSERS[0];
    if (defaultBrowser) {
      try {
        const inspectUrl = defaultBrowser.inspect_url; // e.g. "edge://inspect"
        const browserPath = defaultBrowser.path;
        if (browserPath) {
          // Windows: 用 msedge.exe 打开 edge://inspect
          spawn(browserPath, [inspectUrl], { detached: true, stdio: 'ignore' }).unref();
          console.log(`[CDP] 已自动打开 ${defaultBrowser.name} 调试配置页: ${inspectUrl}`);
          console.log(`[CDP] 请在打开的页面中勾选 "Allow remote debugging..." 然后刷新此页面`);
        }
      } catch (openErr) {
        console.error(`[CDP] 打开浏览器失败: ${openErr.message}`);
      }
    }
  });
});

process.on('SIGTERM', () => { server.close(); process.exit(0); });
process.on('SIGINT', () => { server.close(); process.exit(0); });
