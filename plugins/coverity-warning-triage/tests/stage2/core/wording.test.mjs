// 中心の処理：画面とツールの返り値に出る文の言葉（REQ-025）
// 画面を開く人には、「セッション」のような説明のない言葉を見せない。「このチャット」「ほかの Copilot CLI」のように言う。
// コメントと内部の名前（変数やファイルの記録の中身）は対象にしない。文字列の中の「セッション」だけを見つける。
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { locateCore } from './harness.mjs';

// 行コメント（// …）と複数行コメント（/* … */）を除く。URL の // は、前が : なので除かない。
function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((line) => line.replace(/(^|[^:])\/\/.*$/, '$1'))
    .join('\n');
}

test('REQ-025 中心の処理の、画面やツールの返り値に出る文に、説明のない「セッション」がない', () => {
  const { coreDir } = locateCore();
  const checked = [];
  for (const name of readdirSync(coreDir).filter((f) => f.endsWith('.mjs'))) {
    const code = stripComments(readFileSync(join(coreDir, name), 'utf8'));
    checked.push(name);
    code.split('\n').forEach((line, i) => {
      // sessionId など英字の内部の名前は、日本語の「セッション」ではないので対象外
      assert.ok(!line.includes('セッション'), `${name}:${i + 1} に「セッション」がある：${line.trim()}`);
    });
  }
  assert.ok(checked.includes('constants.mjs') && checked.includes('filing.mjs') && checked.includes('github.mjs'));
});

test('REQ-025 コメントを除く見分け方が働く（試験自身の確かめ）', () => {
  const sample = ["const a = 'ok'; // セッション", '/* セッション', '  セッション */', "const url = 'https://example.com/セッション';"].join('\n');
  const stripped = stripComments(sample);
  assert.equal(stripped.split('セッション').length - 1, 1, '文字列の中の 1 つだけが残る');
});
