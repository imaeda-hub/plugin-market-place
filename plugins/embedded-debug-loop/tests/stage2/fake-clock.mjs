// 試験用の時計。中心の処理（core）の clock に差し替えて、時を進める。
// 形は core/clock.mjs と同じ：{ now, setTimeout, clearTimeout, setInterval, clearInterval }。
// 足した部品：advance(ms)（時を進めて、期限の来た待ちを順に動かす）、flush()（待っている Promise を片づける）。

export function createFakeClock(start = Date.UTC(2026, 9, 22, 3, 0, 0)) {
  let now = start;
  let seq = 0;
  const timers = new Map(); // 番号 → { at, fn, interval }

  const clock = {
    now: () => now,
    setTimeout(fn, ms) {
      seq += 1;
      timers.set(seq, { at: now + Math.max(0, ms), fn, interval: null });
      return seq;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    setInterval(fn, ms) {
      seq += 1;
      timers.set(seq, { at: now + ms, fn, interval: ms });
      return seq;
    },
    clearInterval(id) {
      timers.delete(id);
    },

    // 待っている Promise をすべて片づける（記録のファイルは同期で書くので、これで足りる）
    async flush() {
      for (let i = 0; i < 4; i += 1) await new Promise((resolve) => setImmediate(resolve));
    },

    // 時を ms 進める。途中で期限の来た待ちは、期限の順に動かし、そのたびに Promise を片づける。
    async advance(ms) {
      const target = now + ms;
      await clock.flush();
      for (;;) {
        let nextId = null;
        let nextAt = Infinity;
        for (const [id, t] of timers) {
          if (t.at <= target && t.at < nextAt) {
            nextAt = t.at;
            nextId = id;
          }
        }
        if (nextId === null) break;
        const t = timers.get(nextId);
        now = Math.max(now, t.at);
        if (t.interval !== null) t.at += t.interval;
        else timers.delete(nextId);
        t.fn();
        await clock.flush();
      }
      now = target;
      await clock.flush();
    },

    get pendingTimers() {
      return timers.size;
    },
  };
  return clock;
}
