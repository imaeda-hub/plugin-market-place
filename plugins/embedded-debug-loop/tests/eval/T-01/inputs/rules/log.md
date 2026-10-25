# ログ追加のルール

- ログは printf を直接使わず、src/dbg_log.h の DBG_LOG(fmt, ...) を使う。
- 追加したログには、どこで出したかが分かる言葉を入れる（例：DBG_LOG("sensor_average: i=%d sum=%d", i, sum)）。
