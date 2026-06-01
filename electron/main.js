const { app, BrowserWindow, dialog, Menu, ipcMain, shell } = require('electron');
const { spawn } = require('child_process');
const http  = require('http');
const path  = require('path');

const PORT       = 8765;
const HEALTH_URL = `http://localhost:${PORT}/health`;

// PyInstaller produces tradenexus.exe on Windows, tradenexus everywhere else.
const EXE_NAME = process.platform === 'win32' ? 'tradenexus.exe' : 'tradenexus';

// In a packaged build, electron-builder places extraResources beside app.asar.
// In dev, the PyInstaller exe sits in dist/ relative to the project root.
const EXE = app.isPackaged
  ? path.join(process.resourcesPath, EXE_NAME)
  : path.join(__dirname, '..', 'dist', EXE_NAME);

let win    = null;
let server = null;

// ── Server lifecycle ──────────────────────────────────────────────────────────

function spawnServer() {
  console.log('[electron] spawning', EXE);
  server = spawn(EXE, [], { stdio: 'pipe' });

  server.stdout.on('data', d => process.stdout.write(`[py] ${d}`));
  server.stderr.on('data', d => process.stderr.write(`[py] ${d}`));

  server.on('exit', (code, signal) => {
    if (signal !== 'SIGTERM' && code !== 0 && code !== null) {
      console.error(`[electron] server exited unexpectedly (code=${code})`);
    }
  });
}

function killServer() {
  if (server && !server.killed) {
    console.log('[electron] stopping server');
    server.kill('SIGTERM');
    server = null;
  }
}

// ── Health polling ────────────────────────────────────────────────────────────

function waitForServer(timeoutMs = 30_000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeoutMs;

    function poll() {
      const req = http.get(HEALTH_URL, res => {
        res.resume(); // drain
        if (res.statusCode === 200) return resolve();
        schedule();
      });
      req.on('error', schedule);
      req.setTimeout(1000, () => { req.destroy(); schedule(); });
    }

    function schedule() {
      if (Date.now() >= deadline) return reject(new Error('Server did not respond within 30 s.'));
      setTimeout(poll, 500);
    }

    poll();
  });
}

// ── Window ────────────────────────────────────────────────────────────────────

function createWindow() {
  Menu.setApplicationMenu(null);

  win = new BrowserWindow({
    width:  1280,
    height: 820,
    show:   false,
    title:  'TradeNexus',
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  win.loadFile(path.join(__dirname, '..', 'frontend', 'index.html'));
  win.once('ready-to-show', () => win.show());
  win.on('closed', () => { win = null; });
}

// ── App events ────────────────────────────────────────────────────────────────

ipcMain.on('set-zoom', (event, factor) => {
  event.sender.setZoomFactor(Math.max(0.5, Math.min(3.0, Number(factor))));
});

// Open external links in the user's default browser. The renderer asks via IPC
// because `shell` is unavailable in a sandboxed preload — the main process is the
// only place it lives. https-only is enforced here (the real trust boundary).
ipcMain.on('open-external', (_event, url) => {
  if (typeof url === 'string' && url.startsWith('https://')) {
    shell.openExternal(url);
  }
});

app.whenReady().then(async () => {
  spawnServer();

  try {
    await waitForServer();
  } catch (err) {
    killServer();
    await dialog.showErrorBox(
      'TradeNexus — startup error',
      `The server failed to start:\n\n${err.message}\n\nCheck that ${EXE} exists and port ${PORT} is free.`,
    );
    app.exit(1);
    return;
  }

  createWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (win === null) createWindow();
});

app.on('before-quit', killServer);

// Belt-and-suspenders: clean up if the process is killed externally
process.on('SIGINT',  () => { killServer(); app.quit(); });
process.on('SIGTERM', () => { killServer(); app.quit(); });
