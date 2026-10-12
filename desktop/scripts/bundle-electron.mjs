// Bundles the Electron main process (ESM) and the preload script (CJS, required by sandboxed preloads).
import { build } from 'esbuild'

const dev = process.argv.includes('--dev')
const common = { bundle: true, platform: 'node', target: 'node22', external: ['electron'], sourcemap: dev, logLevel: 'info' }

await build({ ...common, entryPoints: ['electron/main.ts'], outfile: 'dist/electron/main.mjs', format: 'esm' })
await build({ ...common, entryPoints: ['preload/index.ts'], outfile: 'dist/electron/preload.cjs', format: 'cjs' })
