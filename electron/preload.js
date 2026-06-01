const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  setZoom: (factor) => ipcRenderer.send('set-zoom', factor),
});

// Safe external-link opener. Renderer code calls window.shell.openExternal(url);
// we forward it to the main process over IPC, which owns `shell` (it isn't exposed
// to a sandboxed preload). We refuse anything that isn't an absolute https URL here
// too — main re-checks — blocking http://, javascript:, file:, etc.
contextBridge.exposeInMainWorld('shell', {
  openExternal: (url) => {
    if (typeof url === 'string' && url.startsWith('https://')) {
      ipcRenderer.send('open-external', url);
    }
  },
});
