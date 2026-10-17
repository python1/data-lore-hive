#!/usr/bin/env node
// Builds dist/index.html: one self-contained file with the app, its worker and styles inlined,
// so it works from GitHub Pages or saved to disk (file://) without loading anything else.
// A tiny module bundler: each module becomes a function scope; only the import/export forms
// used in this repo are accepted, anything else fails the build rather than being guessed at.
// The Content-Security-Policy allows exactly the inlined script and style (by hash), blob:
// workers and data: images, and forbids every network request.
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
// Sources may be checked out with CRLF (core.autocrlf on Windows); the page is the same either way.
const text = (file) => readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const IMPORT = /^import \{([^}]*)\} from '([^']+)';[ \t]*$/;
const EXPORT_DECL = /^export (?:async )?(?:function\*? |const |let |class )([A-Za-z_$][\w$]*)/;
const EXPORT_LIST = /^export \{([^}]*)\};?[ \t]*$/;

export function bundle(entry) {
  const ids = new Map();
  const out = [];
  const visit = (file, chain) => {
    if (ids.has(file)) return ids.get(file);
    if (chain.includes(file)) throw new Error(`import cycle: ${[...chain, file].map((f) => relative(here, f)).join(' -> ')}`);
    const lines = text(file).split('\n');
    const exported = [];
    const body = lines.map((line, i) => {
      const where = `${relative(here, file)}:${i + 1}`;
      let m;
      if ((m = IMPORT.exec(line))) {
        const dep = visit(resolve(dirname(file), m[2]), [...chain, file]);
        const names = m[1].split(',').map((s) => s.trim()).filter(Boolean).map((s) => s.replace(/^(\w+) as (\w+)$/, '$1: $2'));
        return `const { ${names.join(', ')} } = ${dep};`;
      }
      if (/^\s*(import|export)\b/.test(line) || /\bimport\s*\(/.test(line)) {
        if ((m = EXPORT_DECL.exec(line))) { exported.push(m[1]); return line.slice('export '.length); }
        if ((m = EXPORT_LIST.exec(line))) { for (const n of m[1].split(',').map((s) => s.trim()).filter(Boolean)) { if (!/^\w+$/.test(n)) throw new Error(`${where}: unsupported export form`); exported.push(n); } return ''; }
        throw new Error(`${where}: unsupported import/export form: ${line.trim()}`);
      }
      return line.replace(/^\/\/# sourceMappingURL=.*$/, '');
    });
    const id = `__m${ids.size}`;
    ids.set(file, id);
    out.push(`const ${id} = (() => {\n${body.join('\n')}\nreturn { ${exported.join(', ')} };\n})();`);
    return id;
  };
  visit(resolve(entry), []);
  return `(() => {\n"use strict";\n${out.join('\n')}\n})();\n`;
}

const cspHash = (text) => `'sha256-${createHash('sha256').update(text, 'utf8').digest('base64')}'`;

export function buildPage() {
  const app = bundle(resolve(here, 'src/app.mjs'));
  const worker = bundle(resolve(here, 'src/worker.mjs'));
  const style = text(resolve(here, 'src/app.css'));
  for (const [name, code] of [['app', app], ['worker', worker]]) {
    if (/<\/script|<!--/i.test(code)) throw new Error(`${name} bundle contains </script or <!--, which would break inlining`);
  }
  const csp = [`default-src 'none'`, `script-src ${cspHash(app)}`, `style-src ${cspHash(style)}`, `worker-src blob:`, `img-src data:`,
    `connect-src 'none'`, `form-action 'none'`, `base-uri 'none'`, `object-src 'none'`].join('; ');
  const template = text(resolve(here, 'index.html'));
  const fill = { __CSP__: csp, __STYLE__: style, __WORKER__: worker, __APP__: app };
  for (const key of Object.keys(fill)) if (template.split(key).length !== 2) throw new Error(`index.html must contain ${key} exactly once`);
  return template.replace(/__CSP__|__STYLE__|__WORKER__|__APP__/g, (k) => fill[k]);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const html = buildPage();
  mkdirSync(resolve(here, 'dist'), { recursive: true });
  writeFileSync(resolve(here, 'dist/index.html'), html);
  process.stdout.write(`wrote dist/index.html (${(html.length / 1024).toFixed(0)} KB)\n`);
}
