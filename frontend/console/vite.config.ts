import { createHash } from 'node:crypto'
import { readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join, relative } from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

function sha256(path: string) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true })
    .sort((a, b) => a.name.localeCompare(b.name))
    .flatMap((entry) => {
      const path = join(dir, entry.name)
      return entry.isDirectory() ? walk(path) : [path]
    })
}

function provenancePlugin(): Plugin {
  return {
    name: 'console-static-provenance',
    closeBundle() {
      const outDir = '../../src/trade_trace/console/static/app'
      const sourceFiles = [
        'src/main.tsx',
        'src/routeCatalog.ts',
        'src/routeCatalog.json',
        '../../src/trade_trace/console/route_catalog.json',
        'package.json',
        'package-lock.json',
        'vite.config.ts'
      ]
      const assetFiles = walk(outDir)
        .filter((path) => !path.endsWith('provenance.json'))
        .sort((a, b) => relative(outDir, a).localeCompare(relative(outDir, b)))
      const payload = {
        schema: 1,
        generated_by: 'npm --prefix frontend/console run build',
        source_hashes: Object.fromEntries(sourceFiles.map((path) => [path, sha256(path)])),
        asset_hashes: Object.fromEntries(assetFiles.map((path) => [relative(outDir, path), sha256(path)]))
      }
      writeFileSync(join(outDir, 'provenance.json'), `${JSON.stringify(payload, null, 2)}\n`)
    }
  }
}

export default defineConfig({
  plugins: [react(), provenancePlugin()],
  build: {
    outDir: '../../src/trade_trace/console/static/app',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/console.js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name][extname]'
      }
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/status': 'http://127.0.0.1:8765'
    }
  }
})
