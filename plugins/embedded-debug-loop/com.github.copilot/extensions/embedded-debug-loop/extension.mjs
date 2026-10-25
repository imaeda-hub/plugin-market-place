// 生成プラグインのエクステンションの入口（設計書 3.2、7章）。どの生成プラグインでも中身が同じ。
// Copilot SDK の joinSession を、つなぎ口（adapter.mjs）に渡すだけにする。中身はすべて adapter.mjs にある。
// `@github/copilot-sdk` は Copilot CLI が同梱のものに向けるので、npm では入れない（R2 の 3.9）。

import { joinSession } from '@github/copilot-sdk/extension';

import { startAdapter } from './adapter.mjs';

await startAdapter({ joinSession });
