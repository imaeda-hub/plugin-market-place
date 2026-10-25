import {
  appendFileSync,
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  statSync,
  writeFileSync,
  writeSync,
} from 'node:fs';
import { join } from 'node:path';
import { parseJsonLines } from './util.mjs';

// 記録のファイル（6.5）。実行ごとのフォルダに、次を置く。
//   log.jsonl   イベント、記録、状態の変わり目を、届いた順に 1 行ずつ
//   result.json 終わったときの状態の全体（一時ファイルに書いて名前を変えて置く）。ない実行が、終わっていない実行
//   alive       生きている印（今の時刻）
//   issues/     案ごとの起票の印（4.11）
// 順番が確かで、試験で時計を進めるだけで済むように、同期の fs で書く。

export function createStore({ dataRoot, clock }) {
  const dirOf = (runId) => join(dataRoot, runId);
  const logPath = (runId) => join(dirOf(runId), 'log.jsonl');
  const resultPath = (runId) => join(dirOf(runId), 'result.json');
  const alivePath = (runId) => join(dirOf(runId), 'alive');
  const issuesDir = (runId) => join(dirOf(runId), 'issues');
  const markerPath = (runId, issueId) => join(issuesDir(runId), `${issueId}.json`);

  function writeAtomic(path, text) {
    const tmp = `${path}.tmp-${process.pid}-${Math.random().toString(36).slice(2, 8)}`;
    writeFileSync(tmp, text);
    renameSync(tmp, path);
  }

  return {
    dataRoot,
    dirOf,
    markerPath,
    issuesDir,

    ensureRoot() {
      mkdirSync(dataRoot, { recursive: true });
    },

    createRun(runId, header) {
      mkdirSync(issuesDir(runId), { recursive: true });
      appendFileSync(logPath(runId), `${JSON.stringify(header)}\n`);
      writeFileSync(alivePath(runId), String(clock.now()));
    },

    append(runId, entry) {
      appendFileSync(logPath(runId), `${JSON.stringify(entry)}\n`);
    },

    writeAlive(runId) {
      writeFileSync(alivePath(runId), String(clock.now()));
    },

    readAlive(runId) {
      try {
        const n = Number(readFileSync(alivePath(runId), 'utf8').trim());
        return Number.isFinite(n) ? n : null;
      } catch {
        return null;
      }
    },

    writeResult(runId, result) {
      writeAtomic(resultPath(runId), JSON.stringify(result));
    },

    readResult(runId) {
      try {
        return JSON.parse(readFileSync(resultPath(runId), 'utf8'));
      } catch {
        return null;
      }
    },

    hasResult(runId) {
      return existsSync(resultPath(runId));
    },

    readLog(runId) {
      try {
        return parseJsonLines(readFileSync(logPath(runId), 'utf8'));
      } catch {
        return [];
      }
    },

    // 実行の番号を古い順に返す
    listRuns() {
      try {
        return readdirSync(dataRoot)
          .filter((name) => {
            try {
              return statSync(logPath(name)).isFile();
            } catch {
              return false;
            }
          })
          .sort();
      } catch {
        return [];
      }
    },

    // 件数が上限を超えたら、終わった実行を古いものから消す。終わっていない実行は消さない。
    purge(keep) {
      const ids = this.listRuns();
      let count = ids.length;
      for (const id of ids) {
        if (count <= keep) break;
        if (!this.hasResult(id)) continue;
        try {
          rmSync(dirOf(id), { recursive: true, force: true });
          count -= 1;
        } catch {
          // 消せなければそのままにする
        }
      }
    },

    // ---- 起票の印（4.11） ----

    readMarker(runId, issueId) {
      try {
        return JSON.parse(readFileSync(markerPath(runId, issueId), 'utf8'));
      } catch {
        return null;
      }
    },

    // 印を「なければ作る」形で（排他的に）作る。作れたら true、すでにあれば false。
    createMarkerExclusive(runId, issueId, marker) {
      mkdirSync(issuesDir(runId), { recursive: true });
      let fd;
      try {
        fd = openSync(markerPath(runId, issueId), 'wx');
      } catch (e) {
        if (e.code === 'EEXIST') return false;
        throw e;
      }
      try {
        writeSync(fd, JSON.stringify(marker));
      } finally {
        closeSync(fd);
      }
      return true;
    },

    // 前の印の名前を変えて退ける。成功は 1 つのセッションだけ。成功したら true。
    retireMarker(runId, issueId, suffix) {
      try {
        renameSync(markerPath(runId, issueId), `${markerPath(runId, issueId)}.old-${suffix}`);
        return true;
      } catch (e) {
        if (e.code === 'ENOENT') return false;
        throw e;
      }
    },

    replaceMarker(runId, issueId, marker) {
      writeAtomic(markerPath(runId, issueId), JSON.stringify(marker));
    },
  };
}
