import { randomBytes } from 'node:crypto';

// Copilot CLI の呼び出しに待ち時間の上限を付ける（6.1）。
// 返り値：{ status: 'ok', value } | { status: 'error', error } | { status: 'timeout' } | { status: 'stopped' }
// stopSignal は、止めるが届いたときに解決する Promise（開始中の止める。4.3）。
export function callWithTimeout(clock, fn, ms, stopSignal = null) {
  return new Promise((resolve) => {
    if (!(ms > 0)) {
      resolve({ status: 'timeout' });
      return;
    }
    let done = false;
    let timer = null;
    const finish = (result) => {
      if (done) return;
      done = true;
      if (timer !== null) clock.clearTimeout(timer);
      resolve(result);
    };
    timer = clock.setTimeout(() => finish({ status: 'timeout' }), ms);
    if (stopSignal) stopSignal.then(() => finish({ status: 'stopped' }));
    let p;
    try {
      p = Promise.resolve(fn());
    } catch (error) {
      finish({ status: 'error', error });
      return;
    }
    p.then(
      (value) => finish({ status: 'ok', value }),
      (error) => finish({ status: 'error', error }),
    );
  });
}

export function sleep(clock, ms) {
  return new Promise((resolve) => {
    clock.setTimeout(resolve, Math.max(0, ms));
  });
}

export function errorMessage(e) {
  if (e == null) return '';
  if (typeof e === 'string') return e;
  return String(e.message ?? e);
}

export function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

// 改行や連続した空白を 1 つにして、長ければ切る
export function summarizeText(text, maxChars) {
  const flat = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (flat.length <= maxChars) return flat;
  return `${flat.slice(0, maxChars)}…`;
}

// JSON Lines を読む。書きかけの行など、読めない行は飛ばす（6.5）
export function parseJsonLines(text) {
  const out = [];
  for (const line of String(text ?? '').split('\n')) {
    const s = line.trim();
    if (!s) continue;
    try {
      out.push(JSON.parse(s));
    } catch {
      // 書きかけの最後の行など
    }
  }
  return out;
}

// 実行の番号。フォルダの名前にもなる（6.5）。古い順に並ぶ。
export function newRunId(nowMs) {
  const d = new Date(nowMs);
  const p = (n, w = 2) => String(n).padStart(w, '0');
  const stamp = `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}-${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}`;
  return `${stamp}-${randomBytes(3).toString('hex')}`;
}

export function newAttemptId() {
  return randomBytes(6).toString('hex');
}

// 引数の同じ呼び出しを見分けるための、キーの順に依らない文字列
export function stableStringify(v) {
  if (v === null || typeof v !== 'object') return JSON.stringify(v) ?? 'undefined';
  if (Array.isArray(v)) return `[${v.map(stableStringify).join(',')}]`;
  return `{${Object.keys(v)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${stableStringify(v[k])}`)
    .join(',')}}`;
}

export function clone(v) {
  return v === undefined ? undefined : JSON.parse(JSON.stringify(v));
}
