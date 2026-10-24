import { LIMITS, UNSTOPPED_HOW_TO } from './constants.mjs';
import {
  analyzeEntries,
  buildMechanicalSummary,
  iterationsFromEntries,
  numberIssues,
  phaseFromEntries,
} from './analysis.mjs';
import { viewEndReason, viewIssues } from './run.mjs';
import { callWithTimeout, sleep } from './util.mjs';

// エクステンションが起動したとき（セッションの始めと読み込み直し）の、記録のファイルの読み直し（4.13、6.5）。
//   - 終わっていない実行を終わらせる（下の classifyUnfinishedRun の分かれ目）
//   - 拒む一覧を、自分のセッションの実行の木から作り直す
//   - 古い記録を件数で消す
//   - 準備中の画面に出す、前の実行を探す

// ---- 終わっていない実行の扱いの分かれ目（ここ 1 か所） ----------------------------------------
// 起動したときに見つけた「終わっていない実行」を、どうするかを決める。扱いを変えるときは、この関数だけを変える。
// 返り値：
//   'cancel_and_end'  自分のセッションの実行。動いているエージェントを探して取り消し、「途中で終わった（エクステンションが再起動した）」にする。
//                     動いているエージェントが見つからなければ、「途中で終わった（途中で切れた）」にする
//   'cut_off'         すぐ「途中で切れた」として終わらせる（ほかのセッションの実行で、生きている印が古いもの）
//   'check_later'     ほかのセッションの実行で、生きている印が新しい。決めた時間が過ぎてから、もう一度確かめる
// 自分のセッションの実行を取り消すのは、/clear をしなくても、エクステンションだけが同じセッションのまま
// 起動し直されることがあり（extensions_reload、/extensions mode の切り替え）、そのときエージェントは動き続けるため。
export function classifyUnfinishedRun({ begin, aliveAt, now, sessionId }) {
  if (begin && begin.sessionId === sessionId) return 'cancel_and_end';
  if (aliveAt === null || aliveAt === undefined || now - aliveAt > LIMITS.ALIVE_STALE_MS) return 'cut_off';
  return 'check_later';
}
// ----------------------------------------------------------------------------------------------

function lastTimestamp(entries, fallback) {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    if (Number.isFinite(entries[i].at)) return entries[i].at;
  }
  return fallback;
}

function treeIdsOf(entries) {
  const ids = [];
  for (const entry of entries) {
    if (entry.t === 'tree' && Array.isArray(entry.agentIds)) for (const id of entry.agentIds) if (!ids.includes(id)) ids.push(id);
  }
  return ids;
}

// 起動したときに見つけた実行を、記録の上で終了にする（result.json を置く）。
// detail は cut_off か extension_restarted。unstopped は、取り消せなかったエージェント。
export function finishRecoveredRun(ctx, runId, entries, begin, { detail, unstopped = [] }) {
  const now = ctx.clock.now();
  const userCriteria = begin?.criteria ?? [];
  const iterations = iterationsFromEntries(entries, userCriteria);
  const endReason = { kind: 'aborted', detail, unstoppable: unstopped.length > 0 };
  const drafts = analyzeEntries(entries, {
    pluginName: ctx.pluginName,
    runId,
    endReason,
    endAt: lastTimestamp(entries, now),
    unstopped,
    isAuto: begin?.isAuto ?? false,
    models: begin?.settings?.models ?? {},
  });
  const summary = buildMechanicalSummary({ iterations, phase: phaseFromEntries(entries, ctx.pluginName) });
  const result = {
    runId,
    id: runId,
    sessionId: begin?.sessionId ?? null,
    cwd: begin?.cwd ?? null,
    startedAt: begin?.at ?? null,
    finishedAt: now,
    status: 'finished',
    endReason,
    settings: begin?.settings ?? null,
    isAuto: begin?.isAuto ?? false,
    phase: null,
    iteration: iterations.length > 0 ? iterations[iterations.length - 1].n : 0,
    maxIterations: begin?.settings?.maxIterations ?? null,
    agents: [],
    iterations,
    displays: {},
    summary,
    issues: numberIssues(drafts, 'M', 'mechanical'),
    unstopped,
    waits: [],
    recovered: true,
  };
  try {
    ctx.store.append(runId, { t: 'status', at: now, status: 'finished', endReason });
  } catch {
    // 記録に書けなくても、終了の印は置く
  }
  ctx.store.writeResult(runId, result);
  // 「前の実行が途中で終わっていました」と知らせるのは、画面の「前の結果」に出る範囲（同じセッション、なければ同じ作業フォルダ）の実行だけ
  if (begin && (begin.sessionId === ctx.sessionId || begin.cwd === ctx.cwd)) ctx.endedAtStartup.push(runId);
  ctx.previousDirty = true;
}

// 拒む一覧を作り直す。元にするのは、自分のセッションの実行の log.jsonl にある、木に入れたエージェントの番号。
// ほかのセッションの実行は使わない（4.4、6.5）。
export function rebuildDenyList(ctx) {
  for (const runId of ctx.store.listRuns()) {
    const entries = ctx.store.readLog(runId);
    const begin = entries.find((e) => e.t === 'begin');
    if (!begin || begin.sessionId !== ctx.sessionId) continue;
    for (const id of treeIdsOf(entries)) ctx.deny.add(id);
  }
}

function examine(ctx, runId) {
  const entries = ctx.store.readLog(runId);
  const begin = entries.find((e) => e.t === 'begin') ?? null;
  const action = classifyUnfinishedRun({
    begin,
    aliveAt: ctx.store.readAlive(runId),
    now: ctx.clock.now(),
    sessionId: ctx.sessionId,
  });
  return { entries, begin, action };
}

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

// 自分のセッションの終わっていない実行（エクステンションが再起動した）。
// 木のエージェント（log.jsonl に書いた番号）を探し、動いているものを取り消して、「途中で終わった」にする。
async function endRestartedRun(ctx, runId, entries, begin) {
  const { clock, port } = ctx;
  const ids = new Set(treeIdsOf(entries));
  const deadline = clock.now() + LIMITS.STOP_DEADLINE_MS;
  const left = () => deadline - clock.now();
  const call = (fn) => callWithTimeout(clock, fn, Math.min(LIMITS.CALL_TIMEOUT_MS, left()));
  let tasks = [];
  const refresh = async () => {
    const r = await call(() => port.listTasks());
    if (r.status !== 'ok' || !Array.isArray(r.value)) return false;
    tasks = r.value
      .filter((t) => t && (!t.type || t.type === 'agent') && (t.agentId ?? t.id) != null)
      .map((t) => ({ agentId: t.agentId ?? t.id, status: t.status, parentAgentId: t.parentAgentId ?? null }));
    for (const t of tasks) {
      if (t.parentAgentId && ids.has(t.parentAgentId) && !ids.has(t.agentId)) {
        ids.add(t.agentId);
        ctx.deny.add(t.agentId);
      }
    }
    return true;
  };
  const activeNow = () => tasks.filter((t) => ids.has(t.agentId) && !TERMINAL.has(t.status)).map((t) => t.agentId);

  const listed = await refresh();
  let active = listed ? activeNow() : [];
  if (active.length === 0) {
    // 動いているエージェントが見つからない（/clear の後など）。今までどおり、途中で切れたことにする
    finishRecoveredRun(ctx, runId, entries, begin, { detail: 'cut_off' });
    return;
  }
  // 親が動いていないものから順に取り消す
  const parentOf = new Map(tasks.map((t) => [t.agentId, t.parentAgentId]));
  const ordered = [...active].sort((a, b) => Number(active.includes(parentOf.get(a))) - Number(active.includes(parentOf.get(b))));
  for (const id of ordered) {
    const c = await call(() => port.cancelAgent(id));
    try {
      ctx.store.append(runId, { t: 'note', at: clock.now(), kind: 'restart_cancel', agentId: id, status: c.status });
    } catch {
      // 記録に書けなくても続ける
    }
  }
  let unstopped = [];
  let knownActive = ordered;
  for (;;) {
    const ok = await refresh();
    if (ok) {
      knownActive = activeNow();
      if (knownActive.length === 0) break;
    }
    if (left() <= 0) {
      unstopped = knownActive.map((agentId) => ({ agentId, role: 'worker', howTo: UNSTOPPED_HOW_TO }));
      break;
    }
    await sleep(clock, Math.min(LIMITS.STOP_POLL_MS, Math.max(left(), 0)));
  }
  finishRecoveredRun(ctx, runId, entries, begin, { detail: 'extension_restarted', unstopped });
}

export function recoverOnStartup(ctx) {
  try {
    ctx.store.ensureRoot();
  } catch {
    return; // 記録の置き場所が使えないときは、読み直すものがない
  }
  const later = [];
  const own = [];
  for (const runId of ctx.store.listRuns()) {
    if (ctx.store.hasResult(runId)) continue;
    try {
      const { entries, begin, action } = examine(ctx, runId);
      if (action === 'cut_off') {
        finishRecoveredRun(ctx, runId, entries, begin, { detail: 'cut_off' });
      } else if (action === 'cancel_and_end') {
        for (const id of treeIdsOf(entries)) ctx.deny.add(id); // 取り消しを待たずに、すぐ拒む
        own.push({ runId, entries, begin });
      } else if (action === 'check_later') {
        later.push(runId);
      }
    } catch {
      // 読めない実行は、そのままにする
    }
  }
  try {
    rebuildDenyList(ctx);
    ctx.store.purge(LIMITS.KEEP_RUNS);
  } catch {
    // 拒む一覧と掃除の失敗で、起動は止めない
  }
  if (own.length > 0) {
    // Copilot CLI を待つので、順番待ちの列の中でやる。画面は待たない
    ctx.recoveryPromise = ctx.queue
      .enqueue(async () => {
        for (const { runId, entries, begin } of own) {
          try {
            await endRestartedRun(ctx, runId, entries, begin);
          } catch {
            finishRecoveredRun(ctx, runId, entries, begin, { detail: 'cut_off' });
          }
        }
        ctx.bump();
      })
      .catch(() => {});
  }
  if (later.length > 0) {
    ctx.recheckTimer = ctx.clock.setTimeout(() => {
      ctx.recheckTimer = null;
      for (const runId of later) {
        if (ctx.store.hasResult(runId)) continue;
        try {
          const { entries, begin, action } = examine(ctx, runId);
          if (action === 'cut_off') finishRecoveredRun(ctx, runId, entries, begin, { detail: 'cut_off' });
        } catch {
          // 読めない実行は、そのままにする
        }
      }
      ctx.bump();
    }, LIMITS.ALIVE_STALE_MS + 1000);
  }
}

// 準備中の画面に出す、前の実行（4.2）。同じセッションの最後の実行。なければ、同じ作業フォルダの最後の実行。
// 返り値：{ runId, result } か null。画面に出す形は viewPrevious() で作る（起票の状態を、見るたびに印から読むため）。
export function loadPrevious(ctx) {
  let sameCwd = null;
  for (const runId of ctx.store.listRuns().reverse()) {
    const result = ctx.store.readResult(runId);
    if (!result || result.startFailed) continue;
    if (result.sessionId === ctx.sessionId) return { runId, result };
    if (!sameCwd && result.cwd === ctx.cwd) sameCwd = { runId, result };
  }
  return sameCwd;
}

// 前の実行を読み直す必要があれば読み直す（準備中のときだけ）
export function refreshPrevious(ctx) {
  if (ctx.previousDirty && !ctx.run) {
    ctx.previous = loadPrevious(ctx);
    ctx.previousDirty = false;
  }
}

export function viewPrevious(ctx, previous) {
  if (!previous) return null;
  const { runId, result } = previous;
  return {
    runId,
    endReason: viewEndReason(result.endReason),
    summary: result.summary ?? null,
    issues: viewIssues(ctx, runId, result.issues ?? []),
    finishedAt: result.finishedAt ?? null,
    unstopped: result.unstopped ?? [],
    canFile: JSON.parse(JSON.stringify(ctx.canFile)),
  };
}
