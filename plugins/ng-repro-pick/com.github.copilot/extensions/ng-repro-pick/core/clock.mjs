// 時計。試験では tests/stage2/fake-clock.mjs に差し替えて、時を進める。
// 形：{ now(), setTimeout(fn, ms), clearTimeout(h), setInterval(fn, ms), clearInterval(h) }

export const realClock = Object.freeze({
  now: () => Date.now(),
  setTimeout: (fn, ms) => {
    const h = setTimeout(fn, ms);
    h.unref?.(); // 時計の待ちだけでプロセスを生かさない
    return h;
  },
  clearTimeout: (h) => clearTimeout(h),
  setInterval: (fn, ms) => {
    const h = setInterval(fn, ms);
    h.unref?.();
    return h;
  },
  clearInterval: (h) => clearInterval(h),
});
