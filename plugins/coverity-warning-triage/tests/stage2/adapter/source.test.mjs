// 2段目 部品の試験（つなぎ口）：書き方の検査。
// つなぎ口は Copilot CLI がないと動かせない部分（入口の extension.mjs）を、できるだけ薄くする（設計書 3.2）。
// また、エクステンションの標準出力は Copilot CLI との通信（JSON-RPC）に使われるので、何も書いてはいけない（R2 の 3.9）。
// 設計書：generated-plugin-structure.md 3.2、4.1、7章。
// 実行：node --test "tests/stage2/adapter/*.test.mjs"
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { describe, test } from 'node:test';

import { located } from './harness.mjs';

const dir = located.extensionDir;
const withoutComments = (source) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
const read = (file) => readFileSync(join(dir, file), 'utf8');

// エクステンションの .mjs（画面の部品 ui/static は、ブラウザーで動くので除く）
const modules = readdirSync(dir, { recursive: true })
  .map((file) => String(file).split('\\').join('/'))
  .filter((file) => file.endsWith('.mjs') && !file.startsWith('ui/static/'))
  .sort();

describe('エクステンションの書き方（REQ-005、REQ-029）', () => {
  test('REQ-005 エクステンションの .mjs が見つかる（adapter.mjs、extension.mjs、core/、ui/）', () => {
    for (const expected of ['adapter.mjs', 'extension.mjs', 'core/index.mjs', 'ui/app.mjs', 'ui/server.mjs']) {
      assert.ok(modules.includes(expected), `${expected} がない`);
    }
  });

  test('REQ-005 標準出力に書かない：console.log・console.info・console.debug・process.stdout を使わない（調べるための出力は console.error に出す）', () => {
    for (const file of modules) {
      const source = withoutComments(read(file));
      assert.doesNotMatch(source, /console\s*\.\s*(log|info|debug)\s*\(/, `${file} が標準出力に書いている`);
      assert.doesNotMatch(source, /process\s*\.\s*stdout/, `${file} が標準出力に書いている`);
    }
  });

  test('REQ-005 入口の extension.mjs は薄い：joinSession を読み込み、つなぎ口に渡すだけ', () => {
    const code = withoutComments(read('extension.mjs')).replace(/\s+/g, ' ').trim();
    assert.equal(
      code,
      "import { joinSession } from '@github/copilot-sdk/extension'; import { startAdapter } from './adapter.mjs'; await startAdapter({ joinSession });",
    );
  });

  test('REQ-005 Copilot SDK を読み込むのは extension.mjs だけ（ほかは、joinSession を引数で受けて、偽物でも動かせる）', () => {
    for (const file of modules.filter((f) => f !== 'extension.mjs')) {
      assert.doesNotMatch(withoutComments(read(file)), /@github\/copilot-sdk/, `${file} が Copilot SDK を読み込んでいる`);
    }
  });

  test('REQ-005 外部の npm パッケージを使わない：読み込むのは Node.js の標準の部品と相対の場所だけ（Copilot SDK は extension.mjs だけ）', () => {
    for (const file of modules) {
      const source = withoutComments(read(file));
      const specifiers = [...source.matchAll(/^\s*import\s[^;]*?from\s+['"]([^'"]+)['"]/gm)].map((m) => m[1]);
      specifiers.push(...[...source.matchAll(/\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g)].map((m) => m[1]));
      for (const specifier of specifiers) {
        const allowed = specifier.startsWith('node:') || specifier.startsWith('.') || (file === 'extension.mjs' && specifier === '@github/copilot-sdk/extension');
        assert.ok(allowed, `${file} が ${specifier} を読み込んでいる`);
      }
    }
  });

  test('REQ-005 process.execPath を使わない（エクステンションでは Node.js ではなく copilot の実行ファイルを指す。R2 の 3.9）', () => {
    for (const file of modules) assert.doesNotMatch(withoutComments(read(file)), /process\s*\.\s*execPath/, `${file} が process.execPath を使っている`);
  });

  test('REQ-005 機微な環境変数を求めない（断られるとエクステンションごと読み込まれない。設計書 4.11）', () => {
    for (const file of modules) assert.doesNotMatch(withoutComments(read(file)), /requestedEnvironmentVariables/, `${file} が環境変数を求めている`);
  });

  test('REQ-029 プロセスを終わらせる process.exit は、つなぎ口の終了の合図の受け口にだけある', () => {
    const using = modules.filter((file) => /process\s*\.\s*exit\s*\(/.test(withoutComments(read(file))));
    assert.deepEqual(using, ['adapter.mjs']);
  });
});
