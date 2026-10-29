// Regenerates the API schema from the Django code, then the TypeScript types from the schema.
// `--check` regenerates and fails if the committed files differ (used in CI, ARCH §4).
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const web = join(dirname(fileURLToPath(import.meta.url)), '..')
const api = join(web, '..', 'api')
const schemaFile = join(api, 'openapi.yaml')
const typesFile = join(web, 'src', 'api', 'schema.d.ts')
const check = process.argv.includes('--check')

const read = (f) => { try { return readFileSync(f, 'utf8') } catch { return '' } }
const python = process.env.PYTHON ?? (process.platform === 'win32'
  ? join(api, '.venv', 'Scripts', 'python.exe') : join(api, '.venv', 'bin', 'python'))
const pythonCommand = process.env.CI ? 'python' : python
const generatedTypes = join(web, 'node_modules/openapi-typescript/bin/cli.js')

if (check) {
  // Checks must be read-only: generate both artifacts outside the checkout, then compare.
  const temp = mkdtempSync(join(tmpdir(), 'greenlit-api-check-'))
  const tempSchema = join(temp, 'openapi.yaml')
  const tempTypes = join(temp, 'schema.d.ts')
  try {
    execFileSync(pythonCommand,
      ['manage.py', 'spectacular', '--file', tempSchema, '--validate'], { cwd: api, stdio: 'inherit' })
    execFileSync(process.execPath,
      [generatedTypes, tempSchema, '-o', tempTypes], { cwd: web, stdio: 'inherit' })

    if (read(schemaFile) !== read(tempSchema) || read(typesFile) !== read(tempTypes)) {
      console.error('API schema or generated types are out of date. Run `pnpm gen:api` and review the changes.')
      process.exitCode = 1
    }
  } finally {
    rmSync(temp, { recursive: true, force: true })
  }
} else {
  execFileSync(pythonCommand,
    ['manage.py', 'spectacular', '--file', schemaFile, '--validate'], { cwd: api, stdio: 'inherit' })
  // No shell, and absolute paths keep folders with spaces working.
  execFileSync(process.execPath,
    [generatedTypes, schemaFile, '-o', typesFile], { cwd: web, stdio: 'inherit' })
}
