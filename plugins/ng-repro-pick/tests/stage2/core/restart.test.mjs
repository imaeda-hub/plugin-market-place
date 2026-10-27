// 中心の処理：起動し直したとき（設計書 4.13、6.5、10章「起動し直したとき」）
import assert from 'node:assert/strict';
import { appendFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import test from 'node:test';
import { createCore, LIMITS, makeHarness, PLUGIN, recovery, TASK } from './harness.mjs';

const resultOf = (h, runId) => JSON.parse(readFileSync(join(h.dataRoot, runId, 'result.json'), 'utf8'));
const runIds = (h) => readdirSync(h.dataRoot).sort();

// 実行を始めてから、エクステンションのプロセスだけが終わった状態にする（エージェントは偽物の窓口の中に残る）
async function crashedRun(t, options = {}) {
  const h1 = await makeHarness(t, { sessionId: 's1', ...options });
  await h1.begin();
  await h1.tool('plan', h1.planArgs(1), h1.root);
  const worker = await h1.spawn('worker');
  await h1.core.shutdown();
  return { h1, worker, runId: h1.run().id };
}

const restart = (t, h1, options = {}) => makeHarness(t, { reuse: h1, port: h1.port, sessionId: 's1', ...options });

test('REQ-008 起動したときの分かれ目：自分のセッションは取り消して終わらせ、ほかのセッションは生きている印で見分ける', () => {
  const base = { now: 100_000, sessionId: 's1' };
  const classify = recovery.classifyUnfinishedRun;
  assert.equal(classify({ ...base, begin: { sessionId: 's1' }, aliveAt: base.now }), 'cancel_and_end');
  assert.equal(classify({ ...base, begin: { sessionId: 's2' }, aliveAt: base.now - LIMITS.ALIVE_STALE_MS - 1 }), 'cut_off');
  assert.equal(classify({ ...base, begin: { sessionId: 's2' }, aliveAt: base.now - 1000 }), 'check_later');
  assert.equal(classify({ ...base, begin: { sessionId: 's2' }, aliveAt: null }), 'cut_off');
  assert.equal(classify({ ...base, begin: null, aliveAt: null }), 'cut_off');
});

test('REQ-008 同じセッションのまま起動し直すと、前の実行の動いているエージェントが取り消され、「途中で終わった（エクステンションが再起動した）」になる', async (t) => {
  const { h1, worker, runId } = await crashedRun(t);
  assert.equal(h1.port.task(h1.root).status, 'running', '前のプロセスが終わっても、エージェントは動き続けている');
  const h2 = await restart(t, h1);
  // 起動した時点で、拒む一覧に入っている
  assert.equal(h2.core.preToolUse({ agentId: h1.root, toolName: 'edit' }).deny, true);
  assert.equal(h2.core.preToolUse({ agentId: worker, toolName: 'edit' }).deny, true);
  await h2.settle();
  assert.ok(h1.port.argsOf('cancelAgent').includes(h1.root));
  assert.equal(h1.port.task(h1.root).status, 'cancelled');
  assert.equal(h1.port.task(worker).status, 'cancelled');
  const result = resultOf(h2, runId);
  assert.equal(result.status, 'finished');
  assert.deepEqual([result.endReason.kind, result.endReason.detail, result.endReason.unstoppable], ['aborted', 'extension_restarted', false]);
  assert.ok(result.issues.some((i) => i.title.includes('エクステンションが再起動した')), '課題に入る');
  // 次に画面を開くと、そのことが示される
  const { notices } = await h2.core.open({ requestText: 'もう一度' });
  assert.ok(notices.some((n) => n.includes('途中で終わっていました')));
  const { previous, run } = h2.state();
  assert.equal(run, null);
  assert.equal(previous.runId, runId);
  assert.equal(previous.endReason.detail, 'extension_restarted');
});

test('REQ-008 起動し直したとき、一覧に動いているエージェントが見つからなければ、「途中で終わった（途中で切れた）」になる', async (t) => {
  const { h1, runId } = await crashedRun(t);
  const h2 = await makeHarness(t, { reuse: h1, sessionId: 's1' }); // /clear の後のように、一覧は空
  await h2.settle();
  assert.equal(h2.port.callsOf('cancelAgent').length, 0);
  const result = resultOf(h2, runId);
  assert.deepEqual([result.endReason.kind, result.endReason.detail], ['aborted', 'cut_off']);
  assert.equal(h2.core.preToolUse({ agentId: h1.root, toolName: 'edit' }).deny, true, '拒む一覧には入れる');
});

test('REQ-008 起動し直したとき、一覧が取れなければ、「途中で切れた」にして、拒む一覧には入れる', async (t) => {
  const { h1, runId } = await crashedRun(t);
  h1.port.behave('listTasks', { error: new Error('つながりません') });
  const h2 = await restart(t, h1);
  await h2.settle();
  assert.equal(resultOf(h2, runId).endReason.detail, 'cut_off');
  assert.equal(h2.core.preToolUse({ agentId: h1.root, toolName: 'edit' }).deny, true);
});

test('REQ-009 起動し直したとき、取り消せなかったエージェントは、止めきれなかったエージェントとして記録される', async (t) => {
  const { h1, worker, runId } = await crashedRun(t);
  h1.port.stubborn.add(worker);
  const h2 = await restart(t, h1);
  await h2.settle();
  assert.equal(existsSync(join(h2.dataRoot, runId, 'result.json')), false, '確かめている間は終わらない');
  await h2.clock.advance(LIMITS.STOP_DEADLINE_MS);
  const result = resultOf(h2, runId);
  assert.equal(result.endReason.detail, 'extension_restarted');
  assert.equal(result.endReason.unstoppable, true);
  assert.deepEqual(result.unstopped.map((u) => u.agentId), [worker]);
  assert.ok(result.issues.some((i) => i.title.includes('止めても止まらない')));
});

test('REQ-009 起動し直したときの取り消しの呼び出しにも待ち時間の上限があり、8 秒で打ち切られる', async (t) => {
  const { h1, runId } = await crashedRun(t);
  h1.port.behave('cancelAgent', { hang: true });
  const h2 = await restart(t, h1);
  await h2.settle();
  await h2.clock.advance(LIMITS.STOP_DEADLINE_MS - 1);
  assert.equal(existsSync(join(h2.dataRoot, runId, 'result.json')), false);
  await h2.clock.advance(1);
  const result = resultOf(h2, runId);
  assert.equal(result.endReason.unstoppable, true);
  assert.ok(result.unstopped.length >= 1);
});

test('REQ-008 起動し直している間に画面を開いて開始しても、起動し直しの後始末が先に終わる（列で待つ）', async (t) => {
  const { h1, runId } = await crashedRun(t);
  h1.port.behave('listTasks', { delay: 2000, times: 1 });
  const h2 = await restart(t, h1);
  await h2.core.open({ requestText: '次の依頼' });
  const p = h2.core.start(h2.settings());
  await h2.settle();
  assert.equal(h2.port.callsOf('startAgent').length, 1, '後始末が終わるまで、新しい統括は起動しない（前の実行の分の 1 回だけ）');
  await h2.clock.advance(2000);
  await p;
  assert.equal(h2.port.callsOf('startAgent').length, 2);
  assert.equal(resultOf(h2, runId).endReason.detail, 'extension_restarted');
  assert.equal(h2.run().status, 'running');
});

test('REQ-008 ほかのセッションの実行は、生きている印が古いものだけが「途中で切れた」になる。そのエージェントには触れない', async (t) => {
  // 古い印：すぐ切れたことになる
  const { h1, runId } = await crashedRun(t);
  await h1.clock.advance(LIMITS.ALIVE_STALE_MS + 1000);
  const stale = await makeHarness(t, { reuse: h1, sessionId: 's2' });
  await stale.settle();
  assert.deepEqual(
    [resultOf(stale, runId).endReason.kind, resultOf(stale, runId).endReason.detail],
    ['aborted', 'cut_off'],
  );
  assert.equal(stale.port.callsOf('cancelAgent').length, 0);
  assert.equal(stale.port.callsOf('listTasks').length, 0, 'ほかのセッションのエージェントは探さない');
  // ほかのセッションの実行の木は、拒む一覧に入れない
  assert.equal(stale.core.preToolUse({ agentId: h1.root, toolName: 'edit' }).deny, false);
});

test('REQ-008 ほかのセッションの実行で、起動したときに生きている印が新しければ、決めた時間が過ぎてからもう一度確かめる', async (t) => {
  // 動いているセッション：印が書き換わり続けるので、切れたことにならない
  const live = await makeHarness(t, { sessionId: 's1' });
  await live.begin();
  const other = await makeHarness(t, { reuse: live, sessionId: 's2' });
  await other.clock.advance(LIMITS.ALIVE_STALE_MS + 2000);
  assert.equal(existsSync(join(other.dataRoot, live.run().id, 'result.json')), false);

  // 落ちたセッション：印が止まっているので、決めた時間の後に切れたことになる
  const crashed = await makeHarness(t, { sessionId: 's3' });
  await crashed.begin();
  await crashed.core.shutdown();
  const runId = crashed.run().id;
  await crashed.clock.advance(5000); // 印はまだ新しい
  const checker = await makeHarness(t, { reuse: crashed, sessionId: 's4' });
  await checker.settle();
  assert.equal(existsSync(join(checker.dataRoot, runId, 'result.json')), false, '起動した時点では印が新しい');
  await checker.clock.advance(LIMITS.ALIVE_STALE_MS + 1000);
  assert.equal(resultOf(checker, runId).endReason.detail, 'cut_off');
});

test('REQ-009 拒む一覧は、自分のセッションの記録だけから作り直される', async (t) => {
  const h1 = await makeHarness(t, { sessionId: 's1', idPrefix: 'a-' });
  await h1.begin();
  const w1 = await h1.spawn('worker', { id: 'a-worker' });
  await h1.core.stop();
  await h1.clock.advance(100);
  assert.equal(h1.run().status, 'finished');

  const h2 = await makeHarness(t, { reuse: h1, sessionId: 's2', idPrefix: 'b-' });
  await h2.begin();
  const w2 = await h2.spawn('worker', { id: 'b-worker' });
  await h2.core.stop();
  await h2.clock.advance(100);
  assert.equal(h2.run().status, 'finished');

  // セッション s1 として起動し直す
  const again = await makeHarness(t, { reuse: h1, sessionId: 's1', idPrefix: 'c-' });
  for (const id of [h1.root, w1]) assert.equal(again.core.preToolUse({ agentId: id, toolName: 'x' }).deny, true, id);
  for (const id of [h2.root, w2]) assert.equal(again.core.preToolUse({ agentId: id, toolName: 'x' }).deny, false, `${id}（ほかのセッション）`);
});

test('REQ-008 書きかけの最後の行がある記録も読める', async (t) => {
  const { h1, worker, runId } = await crashedRun(t);
  appendFileSync(join(h1.dataRoot, runId, 'log.jsonl'), '{"t":"event","at":12345,"e":{"type":"agent.sta');
  h1.port.tasks.length = 0; // 一覧は空：途中で切れた
  const h2 = await restart(t, h1);
  await h2.settle();
  const result = resultOf(h2, runId);
  assert.equal(result.endReason.detail, 'cut_off');
  assert.equal(result.iterations.length, 1, '書きかけの行より前の記録は読めている');
  assert.equal(h2.core.preToolUse({ agentId: worker, toolName: 'x' }).deny, true);
});

test('REQ-008 同じセッションの最後の実行を、準備中の「前の結果」に出す。なければ同じ作業フォルダの最後の実行', async (t) => {
  const a = await makeHarness(t, { sessionId: 's1', idPrefix: 'a-' });
  await a.begin();
  await a.core.stop();
  await a.clock.advance(100);
  const idA = a.run().id;
  await a.clock.advance(2000);
  const b = await makeHarness(t, { reuse: a, sessionId: 's2', idPrefix: 'b-' });
  await b.begin();
  await b.core.stop();
  await b.clock.advance(100);
  const idB = b.run().id;
  assert.notEqual(idA, idB);

  const sameSession = await makeHarness(t, { reuse: a, sessionId: 's1' });
  await sameSession.core.open({ requestText: 'x' });
  assert.equal(sameSession.state().previous.runId, idA, '新しい実行が別のセッションにあっても、同じセッションを選ぶ');

  const sameCwd = await makeHarness(t, { reuse: a, sessionId: 's3' });
  await sameCwd.core.open({ requestText: 'x' });
  assert.equal(sameCwd.state().previous.runId, idB, '同じセッションの実行がなければ、同じ作業フォルダの最後の実行');

  const otherCwd = await makeHarness(t, { reuse: a, sessionId: 's4' });
  // 作業フォルダの違う実行は出さない
  const dir = join(otherCwd.dataRoot, idB);
  const result = JSON.parse(readFileSync(join(dir, 'result.json'), 'utf8'));
  for (const id of [idA, idB]) {
    const r = JSON.parse(readFileSync(join(otherCwd.dataRoot, id, 'result.json'), 'utf8'));
    writeFileSync(join(otherCwd.dataRoot, id, 'result.json'), JSON.stringify({ ...r, cwd: '/somewhere/else' }));
  }
  assert.ok(result);
  await otherCwd.core.open({ requestText: 'x' });
  assert.equal(otherCwd.state().previous, null);
});

test('REQ-008 古い記録は 20 件を超えたら古いものから消し、終わっていない実行は消さない', async (t) => {
  const h = await makeHarness(t, { sessionId: 's1' });
  mkdirSync(h.dataRoot, { recursive: true });
  const make = (name, finished, at = h.clock.now()) => {
    mkdirSync(join(h.dataRoot, name), { recursive: true });
    writeFileSync(join(h.dataRoot, name, 'log.jsonl'), `${JSON.stringify({ t: 'begin', at, runId: name, sessionId: 'old', cwd: 'x' })}\n`);
    writeFileSync(join(h.dataRoot, name, 'alive'), String(at));
    if (finished) writeFileSync(join(h.dataRoot, name, 'result.json'), JSON.stringify({ status: 'finished', sessionId: 'old', cwd: 'x', endReason: { kind: 'user_stopped' } }));
  };
  make('20250101-000000-zzzzzz', false); // いちばん古い。ほかのセッションで生きている（印が新しい）
  for (let i = 0; i < 22; i += 1) make(`20260101-0000${String(i).padStart(2, '0')}-aaaaaa`, true);
  const again = await makeHarness(t, { reuse: h, sessionId: 's1' });
  const ids = runIds(again);
  assert.equal(ids.length, 20);
  assert.ok(ids.includes('20250101-000000-zzzzzz'), '終わっていない実行は消さない');
  assert.ok(!ids.includes('20260101-000000-aaaaaa'), '終わった実行の古いものが消える');
  assert.ok(ids.includes('20260101-000021-aaaaaa'));
});

test('REQ-008 記録の置き場所が使えなくても、起動は失敗せず、例外を投げない', async (t) => {
  const h = await makeHarness(t, { sessionId: 's1' });
  writeFileSync(join(h.base, 'blocked'), 'これはファイル');
  assert.doesNotThrow(() =>
    createCore({ port: h.port, pluginRoot: h.pluginRoot, pluginName: PLUGIN, dataRoot: join(h.base, 'blocked', 'runs'), sessionId: 'x', cwd: h.cwd, clock: h.clock, task: TASK }),
  );
});

// ---- 知らせの範囲：画面の「前の結果」に出る実行（同じセッション、なければ同じ作業フォルダ）だけ ----

const NOTICE = '前の実行が途中で終わっていました。画面で結果を見られます。';

test('REQ-008 ほかの作業フォルダの実行が途中で切れても、「前の実行が途中で終わっていました」の知らせは出ない。前の結果にも出ない', async (t) => {
  const { h1, runId } = await crashedRun(t);
  await h1.clock.advance(LIMITS.ALIVE_STALE_MS + 1000); // 印が古くなった（ほかのセッションの実行として切れる）
  const other = await makeHarness(t, { reuse: h1, sessionId: 's2', cwd: join(h1.base, 'other-work') });
  await other.settle();
  assert.equal(resultOf(other, runId).endReason.detail, 'cut_off', '記録の上では切れたことになる');
  const { notices } = await other.core.open({ requestText: 'x' });
  assert.ok(!notices.includes(NOTICE), notices.join(' / '));
  assert.equal(other.state().previous, null, 'ほかの作業フォルダの実行は、前の結果に出ない');
});

test('REQ-008 同じ作業フォルダのほかのセッションの実行が途中で切れたときは、知らせが出て、前の結果にも出る', async (t) => {
  const { h1, runId } = await crashedRun(t);
  await h1.clock.advance(LIMITS.ALIVE_STALE_MS + 1000);
  const same = await makeHarness(t, { reuse: h1, sessionId: 's2' });
  await same.settle();
  const { notices } = await same.core.open({ requestText: 'x' });
  assert.ok(notices.includes(NOTICE));
  assert.equal(same.state().previous.runId, runId);
  // 知らせは 1 回だけ
  assert.ok(!(await same.core.open({ requestText: 'x' })).notices.includes(NOTICE));
});

test('REQ-008 同じセッションの実行は、作業フォルダが違っても、知らせが出る（前の結果は同じセッションの実行を選ぶ）', async (t) => {
  const { h1, runId } = await crashedRun(t);
  h1.port.tasks.length = 0;
  const same = await makeHarness(t, { reuse: h1, port: h1.port, sessionId: 's1', cwd: join(h1.base, 'moved-work') });
  await same.settle();
  assert.equal(resultOf(same, runId).endReason.detail, 'cut_off');
  const { notices } = await same.core.open({ requestText: 'x' });
  assert.ok(notices.includes(NOTICE));
  assert.equal(same.state().previous.runId, runId);
});

test('REQ-008 決めた時間の後の確かめで切れた、ほかの作業フォルダの実行も、知らせは出ない', async (t) => {
  const crashed = await makeHarness(t, { sessionId: 's3' });
  await crashed.begin();
  await crashed.core.shutdown();
  await crashed.clock.advance(5000); // 印はまだ新しい
  const checker = await makeHarness(t, { reuse: crashed, sessionId: 's4', cwd: join(crashed.base, 'other-work') });
  await checker.clock.advance(LIMITS.ALIVE_STALE_MS + 1000);
  assert.ok(existsSync(join(checker.dataRoot, crashed.run().id, 'result.json')));
  assert.ok(!(await checker.core.open({ requestText: 'x' })).notices.includes(NOTICE));
});
