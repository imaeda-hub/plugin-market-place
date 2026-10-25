// 順番待ちの列（6.1）。頼みとイベントを 1 つずつ、最後まで処理する。
// 1 つが失敗しても、次は動く。

export class SerialQueue {
  #tail = Promise.resolve();
  #pending = 0;

  enqueue(fn) {
    this.#pending += 1;
    const run = this.#tail.then(() => fn());
    this.#tail = run.then(
      () => {
        this.#pending -= 1;
      },
      () => {
        this.#pending -= 1;
      },
    );
    return run;
  }

  // 列が空になるまで待つ（画面の終了処理や試験で使う）
  async idle() {
    for (;;) {
      const tail = this.#tail;
      await tail;
      if (tail === this.#tail) return;
    }
  }

  get pending() {
    return this.#pending;
  }
}
