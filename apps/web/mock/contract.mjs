// Contract validation for the mock engine: validates responses and SSE frames against
// engine/exemplar/contracts/api.yaml (+ schemas/*.json). Needs the dev-only deps `ajv` and `yaml`.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const CONTRACT_DIR = path.resolve(HERE, '../../../engine/exemplar/contracts')
const ROOT = 'https://exemplar.test/api'

const ptr = (s) => s.replace(/~/g, '~0').replace(/\//g, '~1')

export async function loadContract() {
  const [{ parse }, { default: Ajv2020 }] = await Promise.all([import('yaml'), import('ajv/dist/2020.js')])
  const api = parse(fs.readFileSync(path.join(CONTRACT_DIR, 'api.yaml'), 'utf8'))
  const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false, validateSchema: false })
  for (const name of ['Trace', 'Rule', 'Label']) {
    const schema = JSON.parse(fs.readFileSync(path.join(CONTRACT_DIR, 'schemas', `${name}.json`), 'utf8'))
    schema.$id = `https://exemplar.test/schemas/${name}.json`
    ajv.addSchema(schema)
  }
  const doc = JSON.parse(JSON.stringify(api).replaceAll('./schemas/', 'https://exemplar.test/schemas/'))
  doc.$id = ROOT
  ajv.addSchema(doc)

  const cache = new Map()
  const compile = (pointer) => {
    if (!cache.has(pointer)) cache.set(pointer, ajv.compile({ $ref: `${ROOT}#${pointer}` }))
    return cache.get(pointer)
  }

  /** Validate a JSON response. `template` uses api.yaml's {param} syntax. Returns error strings. */
  function validateResponse(method, template, status, body) {
    const op = doc.paths?.[template]?.[method.toLowerCase()]
    if (!op) return [`no such operation in api.yaml: ${method} ${template}`]
    let resp = op.responses?.[String(status)]
    let base = `/paths/${ptr(template)}/${method.toLowerCase()}/responses/${status}`
    if (!resp && status >= 400) {
      // api.yaml documents only some error statuses; any error must still look like {error, code}.
      const validateErr = compile('/components/schemas/Error')
      return validateErr(body) ? [] : validateErr.errors.map((e) => `${e.instancePath || '/'} ${e.message}`)
    }
    if (!resp) return [`status ${status} is not documented for ${method} ${template}`]
    if (resp.$ref) {
      base = resp.$ref.replace(/^#/, '')
      resp = base.split('/').slice(1).reduce((o, k) => o?.[k.replace(/~1/g, '/').replace(/~0/g, '~')], doc)
    }
    const schema = resp?.content?.['application/json']?.schema
    if (!schema) return [] // 202/204/302 etc: nothing to validate
    const validate = compile(`${base}/content/application~1json/schema`)
    if (validate(body)) return []
    return validate.errors.slice(0, 6).map((e) => `${e.instancePath || '/'} ${e.message} ${JSON.stringify(e.params)}`)
  }

  function validateComponent(name, body) {
    const validate = compile(`/components/schemas/${name}`)
    if (validate(body)) return []
    return validate.errors.slice(0, 6).map((e) => `${e.instancePath || '/'} ${e.message} ${JSON.stringify(e.params)}`)
  }

  const operations = []
  for (const [p, methods] of Object.entries(doc.paths)) {
    for (const m of Object.keys(methods)) operations.push({ method: m.toUpperCase(), path: p, id: methods[m].operationId })
  }
  return { validateResponse, validateComponent, operations }
}
