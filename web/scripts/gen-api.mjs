// Regenerates the API schema from the Django code, then the TypeScript types from the schema.
// `--check` regenerates and fails if the committed files differ (used in CI, ARCH §4).
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const web = join(dirname(fileURLToPath(import.meta.url)), '..')
const api = join(web, '..', 'api')
const schemaFile = join(api, 'openapi.yaml')
const typesFile = join(web, 'src', 'api', 'schema.d.ts')
const check = process.argv.includes('--check')

const read = (f) => { try { return readFileSync(f, 'utf8') } catch { return '' } }
const before = [read(schemaFile), read(typesFile)]

const python = process.env.PYTHON ?? (process.platform === 'win32'
  ? join(api, '.venv', 'Scripts', 'python.exe') : join(api, '.venv', 'bin', 'python'))
execFileSync(process.env.CI ? 'python' : python,
  ['manage.py', 'spectacular', '--file', 'openapi.yaml', '--validate'], { cwd: api, stdio: 'inherit' })
// No shell, and paths relative to `web`, so folders with spaces in their names work.
execFileSync(process.execPath,
  ['node_modules/openapi-typescript/bin/cli.js', '../api/openapi.yaml', '-o', 'src/api/schema.d.ts'],
  { cwd: web, stdio: 'inherit' })

const after = [read(schemaFile), read(typesFile)]
if (check && (before[0] !== after[0] || before[1] !== after[1])) {
  console.error('API schema or generated types are out of date. Run `pnpm gen:api` and commit.')
  process.exit(1)
}
