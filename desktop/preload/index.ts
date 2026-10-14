import { contextBridge, ipcRenderer } from 'electron'
import type { BackendState, Settings, TraderBridge } from '../shared/ipc.ts'

const bridge: TraderBridge & { windowControl(a: 'minimize' | 'maximize' | 'close'): void; onMaximized(cb: (m: boolean) => void): () => void } = {
  get: path => ipcRenderer.invoke('api:get', path),
  post: (path, body) => ipcRenderer.invoke('api:post', path, body ?? {}),
  backendState: () => ipcRenderer.invoke('backend:state'),
  backendRestart: () => ipcRenderer.invoke('backend:restart'),
  backendLogs: () => ipcRenderer.invoke('backend:logs'),
  onBackendState: cb => {
    const fn = (_e: unknown, s: BackendState) => cb(s)
    ipcRenderer.on('backend:state', fn)
    return () => ipcRenderer.removeListener('backend:state', fn)
  },
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (patch: Partial<Settings>) => ipcRenderer.invoke('settings:set', patch),
  pickFolder: () => ipcRenderer.invoke('dialog:pickFolder'),
  openPath: p => ipcRenderer.invoke('shell:openPath', p),
  windowControl: a => ipcRenderer.send('window:control', a),
  onMaximized: cb => {
    const fn = (_e: unknown, m: boolean) => cb(m)
    ipcRenderer.on('window:maximized', fn)
    return () => ipcRenderer.removeListener('window:maximized', fn)
  }
}

contextBridge.exposeInMainWorld('trader', bridge)
