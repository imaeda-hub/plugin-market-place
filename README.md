# plugin-market-place

[plugin-creator](https://github.com/imaeda-hub/plugin-creator) で作った GitHub Copilot CLI のプラグインを集めたマーケットプレイスです。

## 入れ方

マーケットプレイスを登録してから、使いたいプラグインを入れます。

```shell
copilot plugin marketplace add imaeda-hub/plugin-market-place
copilot plugin install <プラグインの名前>@plugin-market-place
```

- 入っているプラグインの一覧は、`copilot plugin marketplace browse plugin-market-place` でも見られます。
- プラグインを使う前に要る準備（試験的機能を有効にする、など）は、それぞれのプラグインの README に書いてあります。

## プラグインの一覧

| 名前 | できること | 版 |
| --- | --- | --- |
| [weekly-sales-report](plugins/weekly-sales-report/) | 毎週の売上データ（sales.csv）から、部長に出す週報 weekly_report.md を作る | 0.1.0 |

weekly-sales-report は、plugin-creator の試験で作った見本です。AI が演じたユーザー（営業チームのリーダー）と plugin-creator が会話して作りました。中に出てくる人の名前や売上の数字は、架空のものです。

## プラグインを足すとき

1. プラグインのフォルダを `plugins/<プラグインの名前>/` に置きます。
2. `.github/plugin/marketplace.json` の `plugins` に、名前・説明・版と、`"source": "./plugins/<プラグインの名前>"` を足します。
3. 上の一覧に1行足します。
