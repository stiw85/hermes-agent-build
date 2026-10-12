import { app } from 'electron'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { Settings } from '../shared/ipc.ts'

const DEFAULTS: Settings = {
  mode: 'spawn',
  projectDir: process.env.HT_PROJECT_DIR || path.join(os.homedir(), 'hermes-trader'),
  command: process.env.HT_COMMAND || '',
  attachUrl: 'http://127.0.0.1:8765',
  attachTokenFile: ''
}

function file(): string {
  return path.join(app.getPath('userData'), 'settings.json')
}

export function loadSettings(): Settings {
  try {
    const raw = JSON.parse(fs.readFileSync(file(), 'utf8')) as Partial<Settings>
    return sanitize({ ...DEFAULTS, ...raw })
  } catch {
    return { ...DEFAULTS }
  }
}

function sanitize(s: Settings): Settings {
  return {
    mode: s.mode === 'attach' ? 'attach' : 'spawn',
    projectDir: String(s.projectDir || DEFAULTS.projectDir),
    command: String(s.command || ''),
    attachUrl: String(s.attachUrl || DEFAULTS.attachUrl),
    attachTokenFile: String(s.attachTokenFile || '')
  }
}

export function saveSettings(patch: Partial<Settings>): Settings {
  const next = sanitize({ ...loadSettings(), ...patch })
  fs.mkdirSync(path.dirname(file()), { recursive: true })
  fs.writeFileSync(file(), JSON.stringify(next, null, 2))
  return next
}
