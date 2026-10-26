// 中心の処理：記録と課題（設計書 4.10、10章「課題」）
import assert from 'node:assert/strict';
import test from 'node:test';
import { LIMITS, makeHarness, PLUGIN } from './harness.mjs';

const titles = (run) => run.issues.map((i) => i.title);

async function finishNormally(h) {
  await h.tool('finish', { summary: 'まとめ' }, h.root);
  await h.rootIdle();
  await h.clock.advance(100);
  return h.run();
}

test('REQ-013 わざと失敗させたイベントの流れで、その失敗が課題に出る（ツールの失敗、エージェントの失敗）', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  const worker = await h.spawn('worker');
  for (const id of ['tc-1', 'tc-2']) {
    await h.event({ type: 'tool.started', agentId: worker, toolCallId: id, toolName: 'bash' });
    await h.event({ type: 'tool.completed', agentId: worker, toolCallId: id, toolName: 'bash', success: false, error: 'コマンドが見つかりません' });
  }
  h.port.setStatus(worker, 'failed');
  await h.event({ type: 'agent.failed', agentId: worker, error: '作業の途中で失敗しました' });
  const verifier = await h.spawn('verifier');
  await h.tool('verdict', h.verdictArgs(1), verifier);
  await h.complete(verifier);
  const run = await finishNormally(h);
  assert.equal(run.status, 'finished');

  const toolIssue = run.issues.find((i) => i.title === 'ツール「bash」が失敗しました（作業エージェント）');
  assert.ok(toolIssue, titles(run).join(' / '));
  assert.match(toolIssue.body, /2 回失敗しました/);
  assert.match(toolIssue.body, /コマンドが見つかりません/);
  assert.match(toolIssue.body, new RegExp(run.id));
  const agentIssue = run.issues.find((i) => i.title === '作業エージェントが失敗しました');
  assert.ok(agentIssue);
  assert.match(agentIssue.body, /作業の途中で失敗しました/);
  assert.ok(run.issues.every((i) => i.source === 'mechanical'));
});

test('REQ-013 記録のツールの断りは、ふつうの動きなので、ツールの失敗の課題にしない', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.event({ type: 'tool.started', agentId: h.root, toolCallId: 'r1', toolName: `${PLUGIN}_plan` });
  await h.event({ type: 'tool.completed', agentId: h.root, toolCallId: 'r1', toolName: `${PLUGIN}_plan`, success: false, error: '評価基準が足りません' });
  await h.rootIdle();
  assert.ok(!h.run().issues.some((i) => i.title.includes('ツール「')), titles(h.run()).join(' / '));
});

test('REQ-013 課題の案は、番号つきで、題と本文が平易な日本語になっている（英語の役割名を使わない）', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  const worker = await h.spawn('worker', { model: 'other-model' });
  await h.event({ type: 'tool.completed', agentId: worker, toolCallId: 'x', toolName: 'edit', success: false, error: '失敗' });
  await h.rootIdle();
  const run = h.run();
  assert.ok(run.issues.length >= 2);
  assert.deepEqual(run.issues.map((i) => i.id), run.issues.map((_, i) => `M${i + 1}`));
  for (const issue of run.issues) {
    assert.doesNotMatch(`${issue.title}${issue.body}`, /orchestrator|worker|verifier|undefined|null/);
    assert.ok(issue.title.length > 0 && issue.body.length > 0);
  }
});

test('REQ-007 選んだモデルと実際に動いたモデルが違うと、課題に入る。Auto のときはそのことも添える', async (t) => {
  const h = await makeHarness(t);
  h.port.currentModel = { model: 'claude-opus-5-5', isAuto: true };
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  const worker = await h.spawn('worker', { model: 'claude-opus-5-5' }); // 選んだのは gpt-6-luna
  await h.complete(worker);
  const verifier = await h.spawn('verifier', { model: 'claude-opus-5-5' }); // 選んだものと同じ
  await h.tool('verdict', h.verdictArgs(1), verifier);
  const run = await finishNormally(h);
  const issue = run.issues.find((i) => i.title.includes('選んだモデルと実際のモデルが違いました'));
  assert.ok(issue);
  assert.match(issue.title, /作業エージェント/);
  assert.match(issue.body, /選んだモデル：gpt-6-luna/);
  assert.match(issue.body, /実際に動いたモデル：claude-opus-5-5/);
  assert.match(issue.body, /Auto/);
  assert.equal(run.issues.filter((i) => i.title.includes('選んだモデルと実際のモデル')).length, 1, '一致した検証エージェントは入らない');
});

test('REQ-013 決めた時間（5 分）イベントがないエージェントは、詰まりとして課題に入る。確認の待ちの間は入らない', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  const stuck = await h.spawn('worker');
  await h.clock.advance(LIMITS.STALL_MS + 60_000);
  await h.complete(stuck);
  await h.rootIdle();
  const run = h.run();
  const issue = run.issues.find((i) => i.title.includes('作業エージェントが 6 分以上動きませんでした'));
  assert.ok(issue, titles(run).join(' / '));

  // 確認の待ち（ユーザーの答えを待つ時間）は詰まりにしない
  const g = await makeHarness(t);
  await g.begin();
  await g.tool('plan', g.planArgs(1), g.root);
  const waiting = await g.spawn('worker');
  await g.event({ type: 'wait.started', requestId: 'p-1', agentId: waiting, kind: 'permission', detail: { toolKind: 'shell', command: 'ls' } });
  await g.clock.advance(LIMITS.STALL_MS * 3);
  await g.event({ type: 'wait.ended', requestId: 'p-1', kind: 'permission' });
  await g.complete(waiting);
  await g.rootIdle();
  assert.ok(!g.run().issues.some((i) => i.title.includes('動きませんでした')), titles(g.run()).join(' / '));
});

test('REQ-013 終わった時点で動いたままのエージェントの沈黙も、詰まりとして課題に入る', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  await h.spawn('worker');
  await h.clock.advance(LIMITS.STALL_MS * 2);
  await h.core.stop();
  await h.clock.advance(100);
  assert.ok(h.run().issues.some((i) => i.title.includes('動きませんでした')));
});

test('REQ-013 同じツールを同じ引数で続けて呼んだ跡は、繰り返しとして課題に入る', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  const worker = await h.spawn('worker');
  const call = (id, args) => h.event({ type: 'tool.started', agentId: worker, toolCallId: id, toolName: 'view', arguments: args });
  await call('a', { path: 'x.md' });
  await call('b', { path: 'x.md' });
  await call('c', { path: 'y.md' }); // 違う引数で途切れる
  await call('d', { path: 'x.md' });
  await call('e', { path: 'x.md' });
  await h.rootIdle();
  assert.ok(!h.run().issues.some((i) => i.title.includes('繰り返しました')), '2 回ずつなら課題にしない');

  const g = await makeHarness(t);
  await g.begin();
  const w = await g.spawn('worker');
  for (const id of ['a', 'b', 'c', 'd']) await g.event({ type: 'tool.started', agentId: w, toolCallId: id, toolName: 'view', arguments: { b: 1, a: 2 } });
  await g.event({ type: 'tool.started', agentId: w, toolCallId: 'e', toolName: 'view', arguments: { a: 2, b: 1 } });
  await g.rootIdle();
  const issue = g.run().issues.find((i) => i.title.includes('同じ「view」を同じ内容で繰り返しました'));
  assert.ok(issue);
  assert.match(issue.body, /5 回続けて/, '引数のキーの順が違っても同じ呼び出しとして数える');
});

test('REQ-013 計画 → 作業 → 検証 → 合否の記録がそろわない試行は、課題に入る', async (t) => {
  const h = await makeHarness(t);
  await h.begin({ maxIterations: 2 });
  await h.tool('plan', h.planArgs(1), h.root); // 作業も検証も合否の記録もないまま、次の計画へ
  await h.iterate(2);
  const run = await finishNormally(h);
  const issue = run.issues.find((i) => i.title.startsWith('試行 1 で'));
  assert.ok(issue, titles(run).join(' / '));
  assert.match(issue.title, /作業の開始・検証の開始・合否の記録がそろいませんでした/);
  assert.ok(!run.issues.some((i) => i.title.startsWith('試行 2 で')));
});

test('REQ-013 ユーザーが止めた実行では、止めたときの試行がそろっていなくても、それだけでは課題にならない', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  await h.core.stop();
  await h.clock.advance(100);
  assert.deepEqual(h.run().issues, []);
});

test('REQ-013 最後まで繰り返した実行では、統括が振り返って足した Issue の案が、機械的な課題の後に並ぶ', async (t) => {
  const h = await makeHarness(t);
  await h.toSummarizing();
  const review = await h.tool('review', {}, h.root);
  assert.match(review, /機械的に洗い出した課題：/);
  assert.match(review, /試行 1：評価基準 2 件中 2 件が合格。/);
  assert.match(review, new RegExp(`${PLUGIN}_issue`));
  await h.tool('issue', { title: '統括の案 1', body: '本文 1' }, h.root);
  await h.tool('issue', { title: '統括の案 2', body: '本文 2' }, h.root);
  const run = await finishNormally(h);
  assert.deepEqual(run.issues.filter((i) => i.source === 'orchestrator').map((i) => [i.id, i.title, i.body]), [
    ['O1', '統括の案 1', '本文 1'],
    ['O2', '統括の案 2', '本文 2'],
  ]);
  // 足した案は実行中から画面に見える
  const mechanicalFirst = run.issues.findIndex((i) => i.source === 'orchestrator') >= run.issues.filter((i) => i.source === 'mechanical').length;
  assert.ok(mechanicalFirst);
});

test('REQ-013 何も見つからなければ、課題の一覧は空で、review は「見つかった課題はありません」と返す', async (t) => {
  const h = await makeHarness(t);
  await h.toSummarizing();
  assert.match(await h.tool('review', {}, h.root), /見つかった課題はありません/);
  const run = await finishNormally(h);
  // まとめを記録して終わったので、まとめのない終わりも入らない
  assert.deepEqual(run.issues.filter((i) => i.source === 'mechanical'), []);
});

test('REQ-013 review は、繰り返しの途中に見える課題を返し、終わったときだけ分かる課題（まとめのない終わり）は含めない', async (t) => {
  const h = await makeHarness(t);
  await h.toSummarizing();
  const text = await h.tool('review', {}, h.root);
  assert.doesNotMatch(text, /まとめを記録しないまま/);
});

test('REQ-012 途中で終わった実行では、統括が足せないので、機械的に分かる課題だけが示される', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  await h.tool('plan', h.planArgs(1), h.root);
  assert.match(await expectRefusalMessage(h.tool('issue', { title: '題', body: '本文' }, h.root)), /まだ繰り返しの途中/);
  await h.rootIdle();
  const run = h.run();
  assert.ok(run.issues.length >= 1);
  assert.ok(run.issues.every((i) => i.source === 'mechanical'));
});

async function expectRefusalMessage(promise) {
  try {
    await promise;
  } catch (e) {
    return e.message;
  }
  throw new Error('断られなかった');
}
