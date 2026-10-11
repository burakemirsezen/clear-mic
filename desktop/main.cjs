const { app, BrowserWindow, ipcMain, Tray, Menu, nativeImage, shell } = require('electron');
const { spawn } = require('node:child_process');
const readline = require('node:readline');
const path = require('node:path');
const fs = require('node:fs');
app.disableHardwareAcceleration();

const testing = process.argv.includes('--ui-test');
if (testing && !process.env.CLEARMIC_DATA_DIR) process.env.CLEARMIC_DATA_DIR = path.join(__dirname, '.test', 'data');
const dataDir = process.env.CLEARMIC_DATA_DIR || path.join(process.env.LOCALAPPDATA, 'ClearMic');
fs.mkdirSync(path.join(dataDir, 'logs'), { recursive: true });
function log(value) { fs.appendFileSync(path.join(dataDir, 'logs', 'desktop.log'), `${new Date().toISOString()} ${value}\n`); }
let window, tray, child, settings = {}, serial = 0, quitting = false, lastState = 'stopped';
const pending = new Map();
let resolveReady, rejectReady;
const ready = new Promise((resolve, reject) => { resolveReady = resolve; rejectReady = reject; });
ready.catch(() => {});

function show() { if (window) { window.show(); window.restore(); window.focus(); } }
function publish(message) { if (window && !window.isDestroyed() && (message.event !== 'status' || window.isVisible())) window.webContents.send('audio:event', message); }
function request(action, value) {
  return ready.then(() => new Promise((resolve, reject) => {
    if (!child || child.killed) return reject(new Error('The audio service is unavailable. Restart Clear Mic.'));
    const id = ++serial;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('Audio service response timed out.')); }, 12000);
    pending.set(id, { resolve, reject, timer });
    child.stdin.write(JSON.stringify({ id, action, value }) + '\n', error => {
      if (error) { clearTimeout(timer); pending.delete(id); reject(error); }
    });
  }));
}
function fail(message) {
  log(message); rejectReady(new Error(message)); publish({ event: 'fatal', message });
  for (const entry of pending.values()) { clearTimeout(entry.timer); entry.reject(new Error(message)); }
  pending.clear();
}
function startBackend() {
  const root = path.resolve(__dirname, '..');
  const exe = app.isPackaged ? path.join(process.resourcesPath, 'ClearMicAudio', 'ClearMicAudio.exe') : path.join(root, '.venv', 'Scripts', 'python.exe');
  const args = app.isPackaged ? [] : ['-u', path.join(root, 'backend.py')];
  child = spawn(exe, args, { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: process.env });
  child.on('error', error => fail(error.message));
  child.stderr.on('data', chunk => log(chunk.toString()));
  child.stdin.on('error', error => { if (!quitting) fail(error.message); });
  readline.createInterface({ input: child.stdout }).on('line', line => {
    let message;
    try { message = JSON.parse(line); } catch { log('Invalid audio service response'); return; }
    if (message.event === 'ready') { settings = message.snapshot.settings; resolveReady(message.snapshot); }
    if (message.id && pending.has(message.id)) {
      const entry = pending.get(message.id); pending.delete(message.id); clearTimeout(entry.timer);
      if (message.error) entry.reject(new Error(message.error)); else entry.resolve(message.result);
    } else if (message.event) {
      publish(message);
      if (message.event === 'status') {
        const state = message.stats.status;
        if (state !== lastState) { lastState = state; if (tray) tray.setToolTip(`Clear Mic · ${state === 'running' ? 'Microphone on' : 'Microphone off'}`); }
      }
      if (message.event === 'fatal') fail(message.message);
    }
  });
  child.on('exit', (code) => { if (!quitting) fail(`Audio service stopped (${code}). Restart Clear Mic.`); });
}
async function quit(exitCode = 0) {
  if (quitting) return;
  quitting = true;
  if (!child) { app.exit(exitCode); return; }
  try { await request('quit'); } catch {}
  if (child && child.exitCode === null) {
    await Promise.race([new Promise(resolve => child.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 4000))]);
    if (child.exitCode === null) child.kill();
  }
  if (exitCode) app.exit(exitCode); else app.quit();
}
function senderIsApp(event) { return window && event.sender === window.webContents; }
ipcMain.handle('audio:request', async (event, action, value) => {
  if (!senderIsApp(event)) throw new Error('Invalid caller');
  if (!['snapshot','configure','refresh','start','stop','record','play','stop_playback'].includes(action)) throw new Error('Unknown action');
  const result = await request(action, value);
  if (action === 'configure') settings = result;
  if (action === 'snapshot' || action === 'refresh') settings = result.settings;
  return result;
});
ipcMain.handle('app:action', async (event, action, value) => {
  if (!senderIsApp(event)) throw new Error('Invalid caller');
  if (action === 'boot') {
    const snapshot = await ready;
    return { ...snapshot, version: app.getVersion(), launch_at_login: app.getLoginItemSettings({ path: process.execPath, args: ['--tray'] }).openAtLogin };
  }
  if (action === 'minimize') window.minimize();
  else if (action === 'close') window.close();
  else if (action === 'quit') quit();
  else if (action === 'folder') { const error = await shell.openPath(dataDir); if (error) throw new Error(error); }
  else if (action === 'source') await shell.openExternal('https://github.com/burakemirsezen/clear-mic');
  else if (action === 'login') {
    if (!app.isPackaged) throw new Error('Sign-in launch is available in the packaged app.');
    app.setLoginItemSettings({ openAtLogin: Boolean(value), path: process.execPath, args: ['--tray'] });
    return app.getLoginItemSettings({ path: process.execPath, args: ['--tray'] }).openAtLogin;
  } else throw new Error('Unknown app action');
  return true;
});

if (!testing && !app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', show);
  app.whenReady().then(async () => {
    app.setAppUserModelId('org.clearmic.desktop');
    startBackend();
    const iconPath = app.isPackaged ? path.join(process.resourcesPath, 'assets', 'clear-mic.ico') : path.join(__dirname, '..', 'assets', 'clear-mic.ico');
    window = new BrowserWindow({ width: 1060, height: 780, minWidth: 850, minHeight: 620, frame: false, backgroundColor: '#101316', show: false, title: 'Clear Mic', icon: iconPath,
      webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, spellcheck: false } });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    window.webContents.on('render-process-gone', (event, details) => log(`Renderer stopped: ${details.reason}`));
    window.on('close', event => { if (!quitting && settings.minimize_to_tray && tray) { event.preventDefault(); window.hide(); } else if (!quitting) { event.preventDefault(); quit(); } });
    window.once('ready-to-show', () => { if (testing || !process.argv.includes('--tray')) window.show(); });
    tray = new Tray(nativeImage.createFromPath(iconPath));
    tray.setToolTip('Clear Mic · Microphone off');
    tray.setContextMenu(Menu.buildFromTemplate([
      { label: 'Open Clear Mic', click: show },
      { type: 'separator' },
      { label: 'Start microphone', click: () => request('start').catch(error => { publish({ event: 'error', message: error.message }); show(); }) },
      { label: 'Stop microphone', click: () => request('stop').catch(error => publish({ event: 'error', message: error.message })) },
      { type: 'separator' }, { label: 'Quit Clear Mic', click: quit }
    ]));
    tray.on('double-click', show);
    await window.loadFile(path.join(__dirname, 'index.html'));
    try {
      const snapshot = await ready;
      if (snapshot.settings.auto_start && !testing) await request('start');
      if (testing) {
        const testDir = process.env.CLEARMIC_TEST_DIR || path.join(__dirname, '.test');
        fs.mkdirSync(testDir, { recursive: true });
        await new Promise(resolve => setTimeout(resolve, 600));
        const checks = await window.webContents.executeJavaScript('window.runUiChecks()');
        window.setSize(850, 620);
        await new Promise(resolve => setTimeout(resolve, 200));
        const small = await window.webContents.executeJavaScript('window.checkLayout()');
        checks.smallWindow = small;
        checks.pass = checks.pass && small.every(page => page.noHorizontalOverflow);
        window.setSize(1060, 780);
        for (const page of ['microphone','voice','settings']) {
          await window.webContents.executeJavaScript(`window.selectPage('${page}')`);
          await new Promise(resolve => setTimeout(resolve, 200));
          const image = await window.webContents.capturePage(); fs.writeFileSync(path.join(testDir, `${page}.png`), image.toPNG());
        }
        fs.writeFileSync(path.join(testDir, 'checks.json'), JSON.stringify(checks, null, 2));
        if (!checks.pass) throw new Error('Interface checks failed');
        await quit();
      }
    } catch (error) { fail(error.message); if (testing) await quit(1); }
  }).catch(error => { log(error.stack); app.exit(1); });
}
app.on('before-quit', event => { if (!quitting) { event.preventDefault(); quit(); } });
app.on('activate', show);
