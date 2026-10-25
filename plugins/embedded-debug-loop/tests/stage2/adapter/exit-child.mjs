// つなぎ口が、Copilot CLI の終了の合図（SIGTERM）で終わるかを確かめるための、子のプロセスの台本。
// shutdown.test.mjs が動かす。*.test.mjs ではないので、node --test の対象にはならない。
//
//   node exit-child.mjs <写した adapter.mjs の場所> <作業フォルダ>     （環境変数 COPILOT_HOME に記録の置き場所）
//
// 偽物の SDK でつなぎ口を動かし、画面を開いて、標準出力に次を出す（試験が読む）。
//   READY <画面の URL>     準備ができた
//   SHUTDOWN               中心の処理の終わる処理（core.shutdown）が呼ばれた
// Copilot CLI との通信がつながっている代わりに、タイマーでプロセスを生かしておく。
// 終わるのは、つなぎ口が終了の合図を受けて process.exit したときだけである。
import { pathToFileURL } from 'node:url';

import { createFakeSdk } from './fake-sdk.mjs';

const [adapterPath, work] = process.argv.slice(2);
const { startAdapter } = await import(pathToFileURL(adapterPath).href);
const fake = createFakeSdk({ cwd: work });
const handle = await startAdapter({ joinSession: fake.joinSession });

const closeCore = handle.core.shutdown.bind(handle.core);
handle.core.shutdown = async () => {
  process.stdout.write('SHUTDOWN\n');
  await closeCore();
};

const opened = await fake.callTool(`${handle.pluginName}_open`, { requestText: '週報を作る' });
setInterval(() => {}, 1000);
process.stdout.write(`READY ${opened.text.match(/http:\/\/\S+/)[0]}\n`);
