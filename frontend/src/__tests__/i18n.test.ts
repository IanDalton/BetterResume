import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { availableLanguages, dictionaries } from '../i18n';

const SRC_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');

function collectSourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) {
      if (name === '__tests__' || name === 'node_modules') continue;
      collectSourceFiles(full, out);
    } else if (/\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) && name !== 'i18n.tsx') {
      out.push(full);
    }
  }
  return out;
}

const source = collectSourceFiles(SRC_DIR).map((f) => readFileSync(f, 'utf8')).join('\n');
// Keys built at runtime look like `type.${v}` or `site.${k}`: any dictionary key under
// such a prefix counts as used.
const dynamicPrefixes = Array.from(source.matchAll(/`([a-zA-Z0-9_.-]+)\.\$\{/g), (m) => `${m[1]}.`);

describe('i18n dictionaries', () => {
  const en = Object.keys(dictionaries.en);
  const es = Object.keys(dictionaries.es);

  it('have the same keys in English and Spanish', () => {
    expect(es.filter((k) => !dictionaries.en[k])).toEqual([]);
    expect(en.filter((k) => !dictionaries.es[k])).toEqual([]);
  });

  it('have no empty translations', () => {
    for (const lang of ['en', 'es'] as const) {
      for (const [k, v] of Object.entries(dictionaries[lang])) {
        expect(v.trim(), `${lang}:${k}`).not.toBe('');
      }
    }
  });

  it('contain no unused keys', () => {
    const referencedByRegistry = new Set(availableLanguages.map((l) => l.labelKey));
    const unused = en.filter((key) => {
      if (referencedByRegistry.has(key)) return false;
      if (source.includes(`'${key}'`) || source.includes(`"${key}"`)) return false;
      return !dynamicPrefixes.some((prefix) => key.startsWith(prefix));
    });
    expect(unused).toEqual([]);
  });

  it('references only keys that exist', () => {
    const referenced = new Set(Array.from(source.matchAll(/\bt\(\s*'([^']+)'\s*\)/g), (m) => m[1]));
    const missing = Array.from(referenced).filter((k) => !dictionaries.en[k]);
    expect(missing).toEqual([]);
  });

  it('uses voseo, sentence case and "currículum" in Spanish copy', () => {
    const tuteo = /\b(agrega|pega|sube|revisa|elige|ingresa|continúa|crea|considera|puedes|tienes|necesitas|haz|añade|mantén|celebra|apoya|ayúdanos)\b/i;
    const offenders = Object.entries(dictionaries.es)
      .filter(([, v]) => tuteo.test(v) || /\bCV\b/.test(v) || /Bienvenid[oa]/.test(v))
      .map(([k]) => k);
    expect(offenders).toEqual([]);
  });
});
