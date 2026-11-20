import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { delimiter, dirname, join, resolve } from 'node:path'
import { createConnection } from 'node:net'
import { fileURLToPath } from 'node:url'

const port = Number(process.env.PY_STREMIO_API_PORT ?? 8765)
const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const executable = process.platform === 'win32' ? 'py-stremio-api.exe' : 'py-stremio-api'
const localBins = [
  join(repositoryRoot, 'venv', process.platform === 'win32' ? 'Scripts' : 'bin', executable),
  join(repositoryRoot, '.venv', process.platform === 'win32' ? 'Scripts' : 'bin', executable),
]
const apiCommand = process.env.PY_STREMIO_API_BIN ?? localBins.find(existsSync) ?? executable
const api = spawn(apiCommand, [], {
  cwd: repositoryRoot,
  stdio: 'inherit',
  env: {
    ...process.env,
    PYTHONPATH: [repositoryRoot, process.env.PYTHONPATH].filter(Boolean).join(delimiter),
    PY_STREMIO_API_RELOAD: 'true',
  },
})
let vite
let apiError
let stopping = false

api.once('error', (error) => {
  apiError = error
})

const shutdown = (exitCode = 0) => {
  if (stopping) return
  stopping = true
  process.exitCode = exitCode
  api.kill('SIGTERM')
  vite?.kill('SIGTERM')
}

process.once('SIGINT', () => shutdown(130))
process.once('SIGTERM', () => shutdown(143))

api.once('exit', (code) => {
  if (!stopping) {
    console.error(`py-stremio-api exited${code === null ? '' : ` with code ${code}`}.`)
    shutdown(code ?? 1)
  }
})

const apiIsReady = () => new Promise((resolve) => {
  const socket = createConnection({ host: '127.0.0.1', port })
  socket.once('connect', () => {
    socket.destroy()
    resolve(true)
  })
  socket.once('error', () => {
    socket.destroy()
    resolve(false)
  })
})

let ready = false
for (let attempt = 0; attempt < 80 && !stopping; attempt += 1) {
  if (apiError || api.exitCode !== null) break
  if (await apiIsReady()) {
    ready = true
    break
  }
  await new Promise((resolve) => setTimeout(resolve, 250))
}

if (!ready) {
  if (apiError?.code === 'ENOENT') {
    console.error('py-stremio-api was not found. Activate the project environment or set PY_STREMIO_API_BIN.')
    console.error("Install the API extra from the project root with: python -m pip install -e '.[api]'")
  } else if (!stopping) {
    console.error(`The API did not start on 127.0.0.1:${port}. Check its startup output above.`)
  }
  shutdown(1)
} else if (!stopping) {
  vite = spawn('vite', [], { stdio: 'inherit' })
  vite.once('error', (error) => {
    console.error(`Could not start Vite: ${error.message}`)
    shutdown(1)
  })
  vite.once('exit', (code) => shutdown(code ?? 1))
}
