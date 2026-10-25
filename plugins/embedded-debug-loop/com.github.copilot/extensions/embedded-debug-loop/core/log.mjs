// 実行の記録の行を書く。メモリの写し（run.entries）と log.jsonl の両方に書く。
// ファイルに書けなくても、実行は止めない（メモリの写しで課題は洗い出せる）。

export function logEntry(ctx, run, entry) {
  run.entries.push(entry);
  try {
    ctx.store.append(run.id, entry);
  } catch (e) {
    ctx.recordingError = e;
  }
}
