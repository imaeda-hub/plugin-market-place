// 中心の処理：確認の待ち（設計書 4.14、6.1、10章「確認の待ち」）
import assert from 'node:assert/strict';
import test from 'node:test';
import { makeHarness, slotOf } from './harness.mjs';

const shell = { toolKind: 'shell', permissionKind: 'shell', command: 'rm -rf build && npm test', paths: ['/work/build'], urls: [], warning: '削除を含みます', sandboxBypass: false };

test('REQ-005 この実行のエージェントの許可の求めだけが「待ち」になり、何の確認かが状態に入る', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  const worker = await h.spawn('worker');
  await h.event({ type: 'wait.started', requestId: 'p-1', agentId: worker, kind: 'permission', detail: shell });
  const run = h.run();
  assert.deepEqual(run.waits, [{ requestId: 'p-1', slot: 'worker', kind: 'permission', detail: shell }]);
  assert.equal(slotOf(run, 'worker').status, 'waiting');
  assert.equal(slotOf(run, 'orchestrator').status, 'running');
  // コマンドの全文と注意が、そのまま入る
  assert.equal(run.waits[0].detail.command, 'rm -rf build && npm test');
  assert.equal(run.waits[0].detail.warning, '削除を含みます');
});

test('REQ-005 サンドボックスの外に出す求めは目立つ印が残り、記録だけにして中で動かし直す求めは、「外」の印を外す', async (t) => {
  const h = await makeHarness(t);
  const root = await h.begin();
  await h.event({ type: 'wait.started', requestId: 'b-1', agentId: root, kind: 'permission', detail: { ...shell, sandboxBypass: true } });
  await h.event({ type: 'wait.started', requestId: 'b-2', agentId: root, kind: 'permission', detail: { ...shell, sandboxBypass: true, sandboxPermissive: true } });
  const [outside, permissive] = h.run().waits;
  assert.equal(outside.detail.sandboxBypass, true);
  assert.equal(permissive.detail.sandboxBypass, false);
});

test('REQ-005 返事の待ち（質問）と、エージェントの番号がある利用の上限の待ちも「待ち」になる', async (t) => {
  const h = await makeHarness(t);
  const root = await h.begin();
  const verifier = await h.spawn('verifier');
  await h.event({ type: 'wait.started', requestId: 'q-1', agentId: verifier, kind: 'question', detail: { question: 'どちらにしますか' } });
  await h.event({ type: 'wait.started', requestId: 'l-1', agentId: root, kind: 'limit', detail: { maxAiCredits: 5 } });
  const run = h.run();
  assert.deepEqual(run.waits.map((w) => [w.requestId, w.slot, w.kind]), [['q-1', 'verifier', 'question'], ['l-1', 'orchestrator', 'limit']]);
  assert.equal(run.waits[0].detail.question, 'どちらにしますか');
});

test('REQ-005 チャットでのほかの作業と、エクステンション自身の権限の求めは、状態に入らない', async (t) => {
  const h = await makeHarness(t);
  const root = await h.begin();
  // この実行の木にないエージェント
  await h.event({ type: 'wait.started', requestId: 'o-1', agentId: 'chat-agent', kind: 'permission', detail: shell });
  // メインのエージェント自身の確認（エージェントの番号がない許可・質問）
  await h.event({ type: 'wait.started', requestId: 'o-2', kind: 'permission', detail: shell });
  await h.event({ type: 'wait.started', requestId: 'o-3', kind: 'question', detail: { question: '？' } });
  // エクステンション自身の権限の求め
  await h.event({ type: 'wait.started', requestId: 'e-1', agentId: root, kind: 'permission', detail: { permissionKind: 'extension-permission-access' } });
  await h.event({ type: 'wait.started', requestId: 'e-2', agentId: root, kind: 'permission', detail: { toolKind: 'extension-env-access' } });
  assert.deepEqual(h.run().waits, []);
  assert.equal(slotOf(h.run(), 'orchestrator').status, 'running');
});

test('REQ-005 ほかのフックがすでに答えを決めた許可の求め（resolvedByHook）は、待ちにならない', async (t) => {
  const h = await makeHarness(t);
  const root = await h.begin();
  await h.event({ type: 'wait.started', requestId: 'h-1', agentId: root, kind: 'permission', detail: shell, resolvedByHook: true });
  assert.deepEqual(h.run().waits, []);
});

test('REQ-005 エージェントの番号のない利用の上限の待ちは、実行中なら、この実行全体の待ちとして状態に入る', async (t) => {
  const h = await makeHarness(t);
  // 実行がないとき（準備中）は入らない
  await h.event({ type: 'wait.started', requestId: 'l-0', kind: 'limit', detail: {} });
  assert.equal(h.run(), null);
  await h.begin();
  await h.event({ type: 'wait.started', requestId: 'l-1', kind: 'limit', detail: { maxAiCredits: 10, usedAiCredits: 10 } });
  const run = h.run();
  assert.deepEqual(run.waits.map((w) => [w.requestId, w.slot, w.kind]), [['l-1', null, 'limit']]);
  assert.ok(run.agents.every((a) => a.status !== 'waiting'), '特定のエージェントは待ちにならない');
  await h.event({ type: 'wait.ended', requestId: 'l-1', kind: 'limit', action: 'add' });
  assert.deepEqual(h.run().waits, []);
});

test('REQ-005 待ちの終わりで、同じ requestId の待ちが消えて、エージェントが実行中に戻る', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  const worker = await h.spawn('worker');
  await h.event({ type: 'wait.started', requestId: 'p-1', agentId: worker, kind: 'permission', detail: shell });
  await h.event({ type: 'wait.started', requestId: 'p-2', agentId: worker, kind: 'permission', detail: shell });
  await h.event({ type: 'wait.ended', requestId: 'p-1', kind: 'permission' });
  assert.equal(h.run().waits.length, 1);
  assert.equal(slotOf(h.run(), 'worker').status, 'waiting', '別の待ちが残っている間は待ち');
  await h.event({ type: 'wait.ended', requestId: 'p-2', kind: 'permission' });
  assert.deepEqual(h.run().waits, []);
  assert.equal(slotOf(h.run(), 'worker').status, 'running');
  // 知らない requestId の終わりは、何も変えない
  await h.event({ type: 'wait.ended', requestId: 'zzz', kind: 'permission' });
  assert.equal(slotOf(h.run(), 'worker').status, 'running');
});

test('REQ-008 待っているエージェントが終わったら、その待ちも消える', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  const worker = await h.spawn('worker');
  await h.event({ type: 'wait.started', requestId: 'p-1', agentId: worker, kind: 'permission', detail: shell });
  await h.complete(worker);
  assert.deepEqual(h.run().waits, []);
  assert.equal(slotOf(h.run(), 'worker').status, 'completed');
});

test('REQ-005 作業の下で動くエージェント（枠のないエージェント）の待ちは、いちばん近い上の枠の待ちとして示される', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  const worker = await h.spawn('worker');
  const helper = `helper-1`;
  h.port.spawn({ agentId: helper, parentAgentId: worker, agentType: 'general-purpose' });
  await h.event({ type: 'agent.started', agentId: helper, parentAgentId: worker, agentType: 'general-purpose', executionMode: 'sync' });
  await h.event({ type: 'wait.started', requestId: 'p-9', agentId: helper, kind: 'permission', detail: shell });
  assert.equal(h.run().waits[0].slot, 'worker');
  assert.equal(slotOf(h.run(), 'worker').status, 'waiting');
  await h.event({ type: 'wait.ended', requestId: 'p-9', kind: 'permission' });
  assert.equal(slotOf(h.run(), 'worker').status, 'running');
});

test('REQ-005 許可の求めの受け口は、いつも no-result を返し、中で失敗しても例外を投げない', async (t) => {
  const h = await makeHarness(t);
  await h.begin();
  const boom = new Proxy({}, { get() { throw new Error('読めない'); } });
  for (const req of [{ requestId: 'r', kind: 'shell' }, null, undefined, 'x', boom]) {
    let result;
    assert.doesNotThrow(() => {
      result = h.core.onPermissionRequest(req);
    });
    assert.deepEqual(result, { kind: 'no-result' });
  }
  await h.settle();
  // 受け口は列に入れるだけで、待ちを作らない（待ちは permission.requested のイベントで作る）
  assert.deepEqual(h.run().waits, []);
});

test('REQ-005 画面は確認に答えない：中心の処理は、確認に答える窓口を持たない', async (t) => {
  const h = await makeHarness(t);
  for (const name of ['answerPermission', 'approve', 'respond', 'answer', 'handlePermission']) {
    assert.equal(name in h.core, false, name);
  }
  // 窓口（port）にも、確認に答える呼び出しがない
  assert.deepEqual(Object.keys(h.port).filter((k) => /answer|approve|permission/i.test(k)), []);
});
