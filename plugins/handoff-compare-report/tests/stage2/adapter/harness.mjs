// つなぎ口（adapter.mjs）の試験の道具。
// extension フォルダを、一時のプラグインの形（plugin.json、task.json、agents/ つき）に写し、
// 写した adapter.mjs を読み込んで、偽物の SDK（fake-sdk.mjs）で動かす。
// 写したものを動かすので、プラグインの根を求める処理が本番と同じになり、本体に試験のための引数は要らない。
import assert from 'node:assert/strict';
import { cpSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { createFakeSdk, sdkEvent } from './fake-sdk.mjs';

export { createFakeSdk, sdkEvent };

const here = dirname(fileURLToPath(import.meta.url));

// 試験では1つのプロセスで、つなぎ口を何度も起動する（本番は1プロセスに1つ）。終了の合図の受け口が増えても警告を出さない。
process.setMaxListeners(Math.max(process.getMaxListeners(), 200));

// 試験の対象（extensions/<名前>/）の場所。ひな形でも生成プラグインでも探せるようにする。
export function locateExtension() {
  const root = resolve(here, '..', '..', '..');
  const extensions = join(root, 'com.github.copilot', 'extensions');
  for (const name of readdirSync(extensions)) {
    const dir = join(extensions, name);
    try {
      if (readdirSync(dir).includes('adapter.mjs')) return { root, extensionDir: dir };
    } catch {
      // 次の候補へ
    }
  }
  throw new Error(`つなぎ口（${extensions}/<名前>/adapter.mjs）が見つかりません`);
}

export const located = locateExtension();

// 中心の処理の定数と記録のツールの定義（写す前のもの。つなぎ口が渡す文や定義と突き合わせる）
export const CONSTANTS = await import(pathToFileURL(join(located.extensionDir, 'core', 'constants.mjs')).href);
export const TOOLS = await import(pathToFileURL(join(located.extensionDir, 'core', 'tools.mjs')).href);

export const PLUGIN = 'weekly-report';

// 作業の定義の見本（BLUEPRINT 4.1）
export const TASK = {
  name: '週報の作成',
  maxIterationsDefault: 3,
  criteria: [
    { id: 'C-01', text: '先週の実績が3行以内にまとまっている' },
    { id: 'C-02', text: '来週の予定に担当者が書いてある' },
  ],
  workers: [{ agent: 'worker', label: '週報を書く係' }],
  settings: [{ key: 'week', label: '対象の週', type: 'text', default: '', required: true, help: '例：2026-W42', options: [] }],
  displays: [
    { key: 'draft', label: '下書き', type: 'text', when: 'running' },
    { key: 'report', label: '週報', type: 'file', when: 'both' },
  ],
};

export const SETTINGS = {
  models: { orchestrator: 'claude-opus-5-5', worker: 'gpt-6-luna', verifier: 'claude-opus-5-5' },
  maxIterations: 2,
  task: { week: '2026-W42' },
};

const AGENT_MODELS = {
  orchestrator: '[claude-opus-5-5]',
  worker: '[gpt-6-luna, claude-haiku-5-5]',
  verifier: '[claude-opus-5-5]',
};

// ---- 一時のフォルダ ------------------------------------------------------------------------------------

const temps = [];
const cleanups = [];

export function tempDir(prefix = 'adapter-test-') {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  temps.push(dir);
  return dir;
}

/** 試験のファイルの after で呼ぶ。動かしたつなぎ口を終わらせ、一時のフォルダを消す。 */
export async function cleanupAll() {
  while (cleanups.length > 0) {
    try {
      await cleanups.pop()();
    } catch {
      // 片づけの失敗は無視する
    }
  }
  for (const dir of temps.splice(0)) rmSync(dir, { recursive: true, force: true });
}

// ---- 一時のプラグイン ----------------------------------------------------------------------------------

/** extension フォルダを一時のプラグインに写す。agents は、モデルの既定を読む試験のために置く。 */
export function makePlugin({ name = PLUGIN, task = TASK, agents = true, manifest } = {}) {
  const root = tempDir('adapter-plugin-');
  const extensionDir = join(root, 'com.github.copilot', 'extensions', name);
  mkdirSync(dirname(extensionDir), { recursive: true });
  cpSync(located.extensionDir, extensionDir, { recursive: true });
  writeFileSync(join(extensionDir, 'task.json'), JSON.stringify(task));
  if (manifest !== null) writeFileSync(join(root, 'plugin.json'), JSON.stringify(manifest ?? { name, version: '0.0.1', description: '試験用のプラグイン' }));
  if (agents) {
    const agentsDir = join(root, 'com.github.copilot', 'agents');
    mkdirSync(agentsDir, { recursive: true });
    for (const [agent, models] of Object.entries(AGENT_MODELS)) {
      writeFileSync(join(agentsDir, `${agent}.agent.md`), `---\nname: ${agent}\ndescription: 試験用の ${agent}\nmodel: ${models}\n---\n試験用です。\n`);
    }
  }
  return { name, root, extensionDir, adapterPath: join(extensionDir, 'adapter.mjs'), extensionPath: join(extensionDir, 'extension.mjs') };
}

/** 写した adapter.mjs を読み込む（写した場所ごとに別のモジュールになる）。 */
export async function importAdapter(plugin) {
  return import(pathToFileURL(plugin.adapterPath).href);
}

/**
 * 一時のプラグインと偽物の SDK を用意する。launch() で startAdapter を動かし、finish(handle) で試験に渡す形にする。
 * 起動の途中で止めたいとき（セッションに加わった直後の動きを試すとき）は、launch() の返り値を待たずに使う。
 * options：name、task、agents、manifest、cwd（作業フォルダ）、sessionId、copilotHome、fake（作り直す前の偽物の SDK を使い回す）
 */
export async function prepareStart({ name = PLUGIN, task = TASK, agents = true, manifest, cwd, sessionId, copilotHome, fake: given } = {}) {
  const plugin = makePlugin({ name, task, agents, manifest });
  const home = copilotHome ?? tempDir('adapter-home-');
  const work = cwd ?? tempDir('adapter-work-');
  const fake = given ?? createFakeSdk({ cwd: work, ...(sessionId === undefined ? {} : { sessionId }) });
  const { startAdapter } = await importAdapter(plugin);
  const launch = () => {
    const saved = process.env.COPILOT_HOME;
    const restore = () => {
      if (saved === undefined) delete process.env.COPILOT_HOME;
      else process.env.COPILOT_HOME = saved;
    };
    process.env.COPILOT_HOME = home; // 起動が終わるまで、記録の置き場所を試験のフォルダにする
    const starting = startAdapter({ joinSession: fake.joinSession });
    starting.then(restore, restore);
    return starting;
  };
  const finish = (handle) => {
    cleanups.push(() => handle.shutdown());
    return { ...plugin, fake, handle, core: handle.core, port: handle.port, work, copilotHome: home };
  };
  return { plugin, fake, work, copilotHome: home, startAdapter, launch, finish };
}

/**
 * 一時のプラグインを作り、偽物の SDK で startAdapter を動かして、終わるまで待つ。
 * 返り値：plugin の項目、fake（偽物の SDK）、handle（startAdapter の返り値）、core、port、work（作業フォルダ）、copilotHome。
 * options.prepare(fake) で、起動の前に偽物の SDK を整えられる。
 */
export async function startPlugin(options = {}) {
  const prepared = await prepareStart(options);
  options.prepare?.(prepared.fake);
  return prepared.finish(await prepared.launch());
}

/**
 * セッションに加わった直後（joinSession が返った後、中心の処理ができる前）で止める。
 * 作業フォルダを聞く呼び出しを、release() が呼ばれるまで返さない。返り値：{ prepared, release }。
 */
export async function holdAfterJoin(options = {}) {
  const prepared = await prepareStart(options);
  let release;
  prepared.fake.behave('workspaces.getWorkspace', {
    gate: new Promise((resolve) => {
      release = resolve;
    }),
  });
  return { prepared, release };
}

/** 今の実行の記録（log.jsonl）を、行ごとに読む。 */
export function readRunLog(p) {
  const runId = p.core.getState().run?.id;
  assert.ok(runId, '実行がない');
  return readFileSync(join(p.copilotHome, 'plugin-data', p.name, 'runs', runId, 'log.jsonl'), 'utf8')
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line) => JSON.parse(line));
}

// ---- 待ち方 --------------------------------------------------------------------------------------------

export const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** promise を ms ミリ秒まで待つ。間に合わなければ value を返す。使わなかったタイマーは片づける（プロセスが終わるのを遅らせない）。 */
export function withTimeout(promise, ms, value = 'time-out') {
  let timer;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve(value), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

/** condition が真になるまで待つ。なったらすぐ返る。timeout ミリ秒たってもならなければ失敗する。 */
export async function until(condition, { timeout = 3000, step = 5 } = {}) {
  const limit = Date.now() + timeout;
  while (Date.now() < limit) {
    if (await condition()) return;
    await delay(step);
  }
  throw new Error('待っていた条件が、時間内に満たされませんでした');
}

// ---- 実行の場面 ----------------------------------------------------------------------------------------

/** 画面を開くツールを呼び、開始して、統括の開始のイベントを流す。統括の番号を返す。 */
export async function beginRun(p, { settings = SETTINGS } = {}) {
  const opened = await p.fake.callTool(`${p.name}_open`, { requestText: '週報を作る' });
  assert.equal(opened.ok, true, opened.error);
  p.url = opened.text.match(/http:\/\/\S+/)[0];
  await p.core.start(settings);
  const root = p.fake.tasks.find((t) => t.agentType === `${p.name}:orchestrator`);
  assert.ok(root, '統括が起動されていない');
  // 統括は tasks.startAgent で起動する。agentDisplayName には、起動のときに渡した名前が入る
  p.fake.emit(
    sdkEvent.subagentStarted(root.id, {
      agentType: `${p.name}:orchestrator`,
      agentDisplayName: root.displayName,
      agentDescription: '統括エージェントの定義の説明',
      executionMode: 'background',
      model: settings.models.orchestrator,
    }),
  );
  await p.core.whenIdle();
  return root.id;
}

/** 画面のサーバーに、合言葉つきで問い合わせる（beginRun の後に使える）。 */
export async function fetchApi(p, path, init) {
  const url = new URL(p.url);
  return fetch(`${url.origin}${path}${path.includes('?') ? '&' : '?'}k=${url.searchParams.get('k')}`, init);
}

/**
 * 統括の下のエージェントを、一覧に載せて、開始のイベントを流す。
 * 実機（Copilot CLI 1.0.102）と同じ順に、統括の task の呼び出し（description つき）の開始 → サブエージェントの開始を流す。
 * サブエージェントの開始の agentDisplayName は、実機では呼び出しの説明ではなく短い名前（worker など）。
 */
export async function startChild(p, { agentId, parentAgentId, agent, executionMode = 'sync', model = 'm', description = `${agent} の作業` }) {
  const agentType = `${p.name}:${agent}`;
  const toolCallId = `tc-task-${agentId}`;
  p.fake.spawn({ agentId, parentAgentId, agentType, executionMode });
  p.fake.emit(sdkEvent.toolStart(parentAgentId, toolCallId, 'task', { description, agent_type: agentType, prompt: '頼む内容', mode: executionMode }));
  p.fake.emit(
    sdkEvent.subagentStarted(agentId, {
      agentType,
      agentName: agentType,
      agentDisplayName: agent,
      agentDescription: `${agent} の定義の説明`,
      toolCallId,
      executionMode,
      parentId: parentAgentId,
      model,
    }),
  );
  await p.core.whenIdle();
}

export async function settle(p) {
  await p.core.whenIdle();
}
