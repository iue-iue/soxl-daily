# SOXL 定例判定 — GitHub Actions でコードAを回す（プランB）

## 何をするか
平日 22:08 JST（米国冬時間は 23:08 JST）に `codeA_gha.py`（コードA v7.5 と判定ロジック同一）を実行し、
`out/today_check.csv` と判定カード `out/latest_card.txt`（＋日付つきコピー）をこのリポジトリにコミットします。
Cowork のスケジュールタスクは、このリポジトリを「コンテキスト → GitHub」で読み、分析だけを行います。

## 初回セットアップ（10分）
1. GitHub で **private リポジトリ**を作る（例: `soxl-daily`）。
2. この4ファイルをそのまま入れる: `codeA_gha.py` / `requirements.txt` / `.github/workflows/soxl_daily.yml` / `README.md`。
3. リポジトリの Settings → Actions → General → 「Workflow permissions」を **Read and write** にする。
4. Actions タブ → 「SOXL daily judgment (code A)」→ **Run workflow** で1回手動実行（手動実行は時間帯ガードを無視します）。
   数分後に `out/` に `today_check.csv` と `latest_card.txt` ができていれば成功。
5. Cowork のプロジェクト →「コンテキスト」→ **GitHub** → このリポジトリを接続。
6. スケジュールタスクのプロンプトの【1. 取得】を「リポジトリの out/latest_card.txt と out/today_check.csv を読む」に差し替える（Cowork設定テンプレートのB'節）。

## 運用の注意
- GitHub Actions の cron は混雑時に数分〜十数分遅れることがある。ET 09:25 を過ぎた回は `codeA_gha.py` が出力せずに終了するので、
  Cowork 側は **カードの取得時刻が今日の日付か**を必ず確認する（古いカードで判定しない）。
- 米国休場日はコードAが「基準セッションが古い」と出す。読み飛ばす。
- コードAを改訂したら `codeA_gha.py` も同じ差分を入れる（正は `05_Colabコード集` のコードA。ここは複製）。
- `BASE_SIZE` は `codeA_gha.py` の先頭。撤退トリガー（−8.70%）に当たったら 10 に戻す。
