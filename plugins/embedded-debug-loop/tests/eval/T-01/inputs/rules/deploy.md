# デプロイのルール

1. ビルドした src/sensor.out を inputs/device/bin/ にコピーする（フォルダがなければ作る）。
2. ログは inputs/device/bin/sensor.out を実行して取る。その標準出力を、実機のシェルコンソールのログとみなす。
