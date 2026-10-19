# Palworld 日本語配合計算機

日本語で使えるPalworldの配合計算機です。リリース `1.1.0` は `v1.0.5.102999`（SteamサーバーBuild `25247047`）のゲームデータと配合関数を照合しています。

**公開URL:** <https://kitworks-iino.github.io/palworld-hub/>

- 公開済みパル: 288形態
- 配合計算の親候補: 287形態、41,328組
- 基準表: 41,616組、性別条件を含め41,617行
- 現行ビルドのネイティブ配合関数との直接照合: 166,464呼び出し、差分0

親2体からの計算、子からの逆引き、親1体からの候補一覧、配合ツリー、属性・作業適性での図鑑検索に対応します。ひらがな・半角カナでも検索でき、選択したパルや検索条件を共有リンクから復元できます。スマートフォンとキーボードで操作でき、広告・アクセス解析・Cookieは使用しません。

## データの扱い

元の `v1.0.1.100619`／Build `24181105` の確定表と検証記録はそのまま保存しています。現行ゲームから抽出した配合入力と全結果の一致を別途照合し、`data/current-compatibility.json` に対応版・証拠のSHA-256・実用上の制約を記録しています。旧データのBuild IDや証拠を最新版の値で上書きしていません。

グランジーラは配合牧場に配置できないというゲーム内報告に基づき、実用の親候補と配合経路から除外しています。花付きナエモチは通常形態と区別して表示します。現行版で変更されたドンツムの英名は `Snock Terra` を表示します。

ネイティブ照合は、抽出したデータ行を検証用に注入し、実ゲームの配合関数に渡す方法です。基礎となる子の形態IDを検証しており、無改変サーバーによるPAK内DataTableの直接読込、全組み合わせのゲーム内孵化、個体値・パッシブ・アルファ化などの個体状態処理は検証対象に含めていません。

## 検証

```bash
python tools/build_verified_dataset.py
python tools/audit_breeding_sources.py
python tools/verify_current_compatibility.py
python -m unittest -v tests.test_verified_dataset tests.test_pal_icons tests.test_current_game_evidence tests.test_current_native_runtime
npm ci
npx playwright install chromium
npm test
```

データの由来、照合範囲、未実施のゲーム内検証は、サイトおよび `evidence/README.md`、`audit/` の機械可読レポートに記録しています。

## ビルドと公開

`npm run build` はブラウザーに必要なファイルとローカル画像だけを `dist/` へまとめ、参照先の欠落を検査します。ブラウザーテストもこの出力を使います。

GitHub Pagesは `main` への変更後にデータ再生成・証拠照合・ブラウザーテストを実行し、すべて成功した場合だけ `dist/` を公開します。毎週のBuild監視とページ上の公開Build確認で新しいゲーム版を検出した場合は、未確認の更新を対応済みとして表示しません。
