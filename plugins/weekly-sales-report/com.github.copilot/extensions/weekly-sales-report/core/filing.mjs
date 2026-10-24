import { LIMITS } from './constants.mjs';
import { checkCanFile, runCommand } from './github.mjs';
import { refreshPrevious } from './recovery.mjs';
import { newAttemptId, summarizeText } from './util.mjs';

// Issue の起票（4.11）。画面で案ごとに承認すると、gh で起票する。
// 順番待ちの列に入れるのは、印のファイルを作ることと、結果を印に書くことだけ。gh そのものは列の外で動かす。

// 印を作れなかった（印の名前を変えられなかった）のは、同じ記録を見ているほかの Copilot CLI が、先に起票を始めたとき
const OTHER_FILING_MESSAGE = 'ほかの Copilot CLI が、この案を起票しています。';

export async function refreshCanFile(ctx) {
  const result = await checkCanFile({ pluginRoot: ctx.pluginRoot, ghCommand: ctx.ghCommand, clock: ctx.clock });
  ctx.canFile = result;
  ctx.canFileChecked = true;
  ctx.bump();
  return result;
}

// 起票できるかの確かめを始める（すでに動いていれば、それを待つ）
export function startCanFileCheck(ctx) {
  ctx.canFilePromise ??= refreshCanFile(ctx)
    .catch(() => ctx.canFile)
    .finally(() => {
      ctx.canFilePromise = null;
    });
  return ctx.canFilePromise;
}

export async function ensureCanFile(ctx) {
  if (ctx.canFileChecked) return ctx.canFile;
  await startCanFileCheck(ctx);
  return ctx.canFile;
}

// 二重の起票を見分けるための、案ごとに一意の印。本文の終わりに入れる。
export function issueMarkerText(ctx, runId, issueId) {
  return `<!-- ${ctx.pluginName}-issue:${runId}/${issueId} -->`;
}

// 承認する案を探す。実行が終わった後の実行か、準備中に開ける前の実行。
function findTarget(ctx, issueId) {
  refreshPrevious(ctx);
  const run = ctx.run;
  if (run && run.status === 'finished') {
    const issue = run.issues.find((i) => i.id === issueId);
    return issue ? { runId: run.id, issue } : null;
  }
  if (!run && ctx.previous) {
    const issue = (ctx.previous.result.issues ?? []).find((i) => i.id === issueId);
    return issue ? { runId: ctx.previous.runId, issue } : null;
  }
  return null;
}

function effectiveState(ctx, marker) {
  if (marker.state === 'filing' && ctx.clock.now() - marker.startedAt > LIMITS.FILING_STALE_MS) return 'unknown';
  return marker.state;
}

// 印を「なければ作る」形で作る。作れたときだけ起票に進む。
function prepareMarker(ctx, runId, issueId) {
  const { store } = ctx;
  let previousState = 'none';
  const existing = store.readMarker(runId, issueId);
  if (existing) {
    const state = effectiveState(ctx, existing);
    if (state === 'filed') return { ok: false, error: 'この案は、すでに起票しました。' };
    if (state === 'filing') return { ok: false, error: 'この案は、いま起票しています。' };
    // 失敗か、起票したか分からない。前の印の名前を変えて退ける（成功するのは 1 つのセッションだけ）
    if (!store.retireMarker(runId, issueId, newAttemptId())) {
      return { ok: false, error: OTHER_FILING_MESSAGE };
    }
    previousState = state;
  }
  const attempt = newAttemptId();
  const marker = { runId, issueId, attempt, state: 'filing', startedAt: ctx.clock.now(), url: null, reason: null };
  if (!store.createMarkerExclusive(runId, issueId, marker)) {
    return { ok: false, error: OTHER_FILING_MESSAGE };
  }
  return { ok: true, attempt, previousState };
}

// 結果は、印がまだ自分の試みのものであるときだけ書く
function commitMarker(ctx, runId, issueId, attempt, outcome) {
  const marker = ctx.store.readMarker(runId, issueId);
  if (!marker || marker.attempt !== attempt) return false;
  ctx.store.replaceMarker(runId, issueId, {
    ...marker,
    state: outcome.state,
    url: outcome.url ?? null,
    reason: outcome.reason ?? null,
    updatedAt: ctx.clock.now(),
  });
  return true;
}

const URL_PATTERN = /https?:\/\/\S+/;

// 前に「起票したか分からない」になった案は、起票の前に、本文にその案の印がある Issue を探す
async function searchExisting(ctx, repo, marker) {
  const r = await runCommand({
    command: ctx.ghCommand,
    args: ['issue', 'list', '--repo', repo, '--state', 'all', '--limit', String(LIMITS.GH_LIST_LIMIT), '--json', 'title,url,body'],
    timeoutMs: LIMITS.GH_TIMEOUT_MS,
    clock: ctx.clock,
  });
  const failed = (reason) => ({ status: 'failed', reason });
  if (r.spawnError) return failed('gh を起動できなかったため、起票したかを確かめられません。');
  if (r.timedOut) return failed('起票したかを探す処理が時間の上限を超えたため、起票したかを確かめられません。');
  if (r.code !== 0) return failed(`起票したかを探す処理が失敗したため、起票したかを確かめられません。（${summarizeText(r.stderr, 200)}）`);
  let list;
  try {
    list = JSON.parse(r.stdout);
  } catch {
    return failed('起票したかを探す処理の結果が読めなかったため、起票したかを確かめられません。');
  }
  if (!Array.isArray(list)) return failed('起票したかを探す処理の結果が読めなかったため、起票したかを確かめられません。');
  const hit = list.find((i) => typeof i?.body === 'string' && i.body.includes(marker));
  return hit ? { status: 'found', url: hit.url ?? null } : { status: 'none' };
}

async function createIssue(ctx, repo, issue, marker) {
  const r = await runCommand({
    command: ctx.ghCommand,
    args: ['issue', 'create', '--repo', repo, '--title', issue.title, '--body-file', '-'],
    input: `${issue.body}\n\n${marker}\n`,
    timeoutMs: LIMITS.GH_TIMEOUT_MS,
    clock: ctx.clock,
  });
  if (r.spawnError) return { state: 'failed', reason: 'gh を起動できませんでした。gh が入っているか確かめてください。' };
  if (r.timedOut) {
    return {
      state: 'unknown',
      reason: `gh が時間の上限（${LIMITS.GH_TIMEOUT_MS / 1000} 秒）を超えたため止めました。送信は済んでいるかもしれないので、起票できたかは分かりません。`,
    };
  }
  if (r.code !== 0) {
    const detail = summarizeText(r.stderr || r.stdout, 300);
    return { state: 'failed', reason: `gh が失敗しました。${detail ? `（${detail}）` : ''}ログインが切れていないか確かめてください。` };
  }
  const url = (r.stdout.match(URL_PATTERN) ?? [null])[0];
  if (!url) return { state: 'unknown', reason: 'gh は成功を返しましたが、できた Issue の URL が読めませんでした。起票できたかは分かりません。' };
  return { state: 'filed', url };
}

// 案を承認して起票する。起票できなかったときは、平易な日本語の Error を投げる。
export async function fileIssue(ctx, issueId) {
  const target = findTarget(ctx, issueId);
  if (!target) throw new Error('その課題の案が見つかりません。');
  const can = await ensureCanFile(ctx);
  if (!can.ok) throw new Error(`今は Issue を起票できません。${can.reason ?? ''}`.trim());
  const { runId, issue } = target;

  const prep = await ctx.queue.enqueue(() => prepareMarker(ctx, runId, issue.id));
  ctx.bump();
  if (!prep.ok) throw new Error(prep.error);

  const marker = issueMarkerText(ctx, runId, issue.id);
  let outcome = null;
  if (prep.previousState === 'unknown') {
    const found = await searchExisting(ctx, can.repo, marker);
    if (found.status === 'found') outcome = { state: 'filed', url: found.url };
    else if (found.status === 'failed') outcome = { state: 'unknown', reason: found.reason };
  }
  outcome ??= await createIssue(ctx, can.repo, issue, marker);

  await ctx.queue.enqueue(() => commitMarker(ctx, runId, issue.id, prep.attempt, outcome));
  ctx.bump();
  if (outcome.state !== 'filed') throw new Error(outcome.reason);
  return { state: 'filed', url: outcome.url };
}
