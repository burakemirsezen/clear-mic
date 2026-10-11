const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('clearMic', {
  request: (action, value) => ipcRenderer.invoke('audio:request', action, value),
  app: (action, value) => ipcRenderer.invoke('app:action', action, value),
  subscribe: callback => { const listener = (_, message) => callback(message); ipcRenderer.on('audio:event', listener); return () => ipcRenderer.removeListener('audio:event', listener); }
});
