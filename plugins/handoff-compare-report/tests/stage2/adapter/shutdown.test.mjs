// 2段目 部品の試験（つなぎ口）：終わるとき。
// Copilot CLI を終えると、エクステンション（画面のサーバーを含む）も終わり、プロセスが残らない（REQ-029、設計書 4.2）。
// Copilot CLI は終了のときに SIGTERM を送り、5秒後に SIGKILL する（R2 の 3.9）。
// つなぎ口は SIGTERM（と SIGINT）を受けると、中心の処理の終わる処理（core.shutdown。画面のサーバーを閉じる）を呼んでから、プロセスを終える。
// 設計書：generated-plugin-structure.md 4.2、10章。
// 実行：node --test "tests/stage2/adapter/*.test.mjs"
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { after, describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';

import { PLUGIN, cleanupAll, makePlugin, startPlugin, tempDir, until, withTimeout } from './harness.mjs';

after(cleanupAll);

const CHILD = join(dirname(fileURLToPath(import.meta.url)), 'exit-child.mjs');

describe('終わるとき（REQ-029）', () => {
  test('REQ-029 shutdown は、画面のサーバーを閉じ、イベントの受け取りをやめ、終了の合図の受け口を外す。何度呼んでも、終わる処理は1回', async () => {
    const before = { term: process.listenerCount('SIGTERM'), int: process.listenerCount('SIGINT') };
    const p = await startPlugin();
    assert.equal(process.listenerCount('SIGTERM'), before.term + 1);
    assert.equal(process.listenerCount('SIGINT'), before.int + 1);
    assert.equal(p.fake.handlerCount(), 1);
    const opened = await p.fake.callTool(`${PLUGIN}_open`, { requestText: '週報を作る' });
    const url = opened.text.match(/http:\/\/\S+/)[0];
    assert.equal((await fetch(url)).status, 200);

    let closed = 0;
    const closeCore = p.core.shutdown.bind(p.core);
    p.core.shutdown = async () => {
      closed += 1;
      return closeCore();
    };
    await Promise.all([p.handle.shutdown(), p.handle.shutdown()]);
    await p.handle.shutdown();
    assert.equal(closed, 1);
    await assert.rejects(fetch(url), '画面のサーバーが閉じている');
    assert.equal(process.listenerCount('SIGTERM'), before.term);
    assert.equal(process.listenerCount('SIGINT'), before.int);
    assert.equal(p.fake.handlerCount(), 0);
  });

  test('REQ-029 イベントの受け取りをやめられなくても（セッションが切れている）、中心の処理の終わる処理は呼ぶ', async () => {
    const p = await startPlugin({
      prepare: (fake) => {
        const subscribe = fake.session.on;
        fake.session.on = (...args) => {
          subscribe(...args);
          return () => {
            throw new Error('セッションが切れている');
          };
        };
      },
    });
    let closed = 0;
    const closeCore = p.core.shutdown.bind(p.core);
    p.core.shutdown = async () => {
      closed += 1;
      return closeCore();
    };
    await p.handle.shutdown();
    assert.equal(closed, 1);
  });

  test('REQ-029 終わる処理が失敗しても、shutdown は例外を投げず、標準エラーに残す', async () => {
    const p = await startPlugin();
    p.core.shutdown = async () => {
      throw new Error('閉じられない');
    };
    const lines = [];
    const original = console.error;
    console.error = (...args) => lines.push(args.map(String).join(' '));
    try {
      await p.handle.shutdown();
    } finally {
      console.error = original;
    }
    assert.equal(lines.length, 1);
    assert.match(lines[0], /つなぎ口.*終わる処理/);
  });

  // Windows の Node.js は、子のプロセスに SIGTERM・SIGINT を届けられない（kill は強制終了になる）ので、合図を送る試験は飛ばす。
  // Windows でも残る確かめ（プロセスが終わると画面のサーバーが残らない）は、下の「強制終了」の試験が受け持つ。
  const SIGNAL_SKIP = process.platform === 'win32' ? 'Windows の Node.js は、子のプロセスに終了の合図（SIGTERM・SIGINT）を届けられないため、飛ばす' : false;
  for (const signal of ['SIGTERM', 'SIGINT']) {
    test(`REQ-029 Copilot CLI の終了の合図（${signal}）を受けると、中心の処理の終わる処理を呼んでから、プロセスが終わる。画面のサーバーも残らない`, { skip: SIGNAL_SKIP }, async () => {
      const plugin = makePlugin();
      const child = spawn(process.execPath, [CHILD, plugin.adapterPath, tempDir('adapter-work-')], {
        env: { ...process.env, COPILOT_HOME: tempDir('adapter-home-') },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let out = '';
      let err = '';
      child.stdout.on('data', (chunk) => {
        out += chunk;
      });
      child.stderr.on('data', (chunk) => {
        err += chunk;
      });
      const exited = new Promise((resolve) => child.on('exit', (code, sig) => resolve({ code, signal: sig })));
      try {
        await until(() => /READY http/.test(out) || child.exitCode !== null, { timeout: 15000 });
        const url = out.match(/READY (http:\/\/\S+)/)?.[1];
        assert.ok(url, `子のプロセスの出力：${out} ${err}`);
        assert.equal((await fetch(url)).status, 200, '終わる前は、画面が開ける');
        child.kill(signal);
        const result = await withTimeout(exited, 8000);
        assert.notEqual(result, 'time-out', `${signal} を受けても終わらなかった`);
        assert.deepEqual(result, { code: 0, signal: null });
        assert.ok(out.includes('SHUTDOWN'), `中心の処理の終わる処理が呼ばれていない：${out}`);
        assert.ok(out.indexOf('SHUTDOWN') > out.indexOf('READY'));
        await assert.rejects(fetch(url), '画面のサーバーが残っていない');
      } finally {
        if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
      }
    });
  }

  test('REQ-029 エクステンションのプロセスが強制終了されても（異常終了と同じ）、画面のサーバーが残らない', async () => {
    const plugin = makePlugin();
    const child = spawn(process.execPath, [CHILD, plugin.adapterPath, tempDir('adapter-work-')], {
      env: { ...process.env, COPILOT_HOME: tempDir('adapter-home-') },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '';
    let err = '';
    child.stdout.on('data', (chunk) => {
      out += chunk;
    });
    child.stderr.on('data', (chunk) => {
      err += chunk;
    });
    const exited = new Promise((resolve) => child.on('exit', () => resolve('exited')));
    try {
      await until(() => /READY http/.test(out) || child.exitCode !== null, { timeout: 15000 });
      const url = out.match(/READY (http:\/\/\S+)/)?.[1];
      assert.ok(url, `子のプロセスの出力：${out} ${err}`);
      assert.equal((await fetch(url)).status, 200, '終わる前は、画面が開ける');
      child.kill('SIGKILL'); // Windows でも強制終了として効く
      assert.equal(await withTimeout(exited, 8000), 'exited', 'プロセスが終わらなかった');
      await assert.rejects(fetch(url), '画面のサーバーが残っていない');
    } finally {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    }
  });
});
