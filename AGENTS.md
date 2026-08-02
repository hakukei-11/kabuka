# AGENTS.md

## プロジェクト概要

このリポジトリは、yfinanceで株価を取得し、GitHub Actionsで日次CSVを生成し、Streamlitで可視化する株価分析プロジェクトです。

主な構成は以下です。

- `app.py`: Streamlit画面
- `export_data.py`: 日次CSVの生成とLINE通知
- `update_checker.py`: 終値更新の監視とLINE通知
- `analysis_engine.py`: 銘柄分析・判定・スコア計算の共通処理
- `indicators.py`: RSI・MACDの計算
- `scoring.py`: 反発確度スコアの計算
- `tickers.py`: 対象銘柄一覧
- `data/`: GitHub Actionsが生成する日次CSV

## コード変更のルール

- コード修正を提案する場合は、変更対象ファイルごとに全ソースコードを表示する。
- 差分だけを表示しない。
- Python、Markdown、YAMLなど、`#` によるコメントまたは見出しを記述できるソース・設定・文書ファイルの先頭には、必ず `# ファイル名` を記載する。
- 例:
  - Python: `# app.py`
  - Markdown: `# README.md`
  - YAML: `# daily_export.yml`
- JSON、CSVなどコメントを記述できないファイルには、ファイル形式を壊すため `# ファイル名` を追加しない。
- 既存の処理を削除・変更する前に、影響範囲を確認する。
- 関係のないファイルや既存ユーザー変更は変更しない。
- 日本語を含むファイルはUTF-8で保存する。

## 分析ロジックのルール

- RSI、MACD、25MA、20日高値・安値、判定文、反発確度スコアは `analysis_engine.py` を唯一の定義元とする。
- `app.py`、`export_data.py`、`update_checker.py` に分析ロジックを重複実装しない。
- RSIとMACDの計算関数は `indicators.py` に置く。
- スコアの計算関数は `scoring.py` に置く。
- yfinanceの価格調整設定は、CSV生成・画面表示・更新確認で統一する。
- 現在は `auto_adjust=True` を使用する。
- 画面、CSV、LINE通知で同じ取引日・指標・判定・スコアになることを維持する。

## CSVデータのルール

日次CSVには最低限、以下の列を保存する。

- `分析実行日時`
- `取引日`
- `銘柄コード`
- `銘柄名`
- `終値`
- `前日比`
- `前日比率(%)`
- `RSI`
- `MACD`
- `Signal`
- `25MA`
- `20日高値`
- `20日安値`
- `判定`
- `反発確度スコア`

Azureでの時系列分析では、`取引日` と `銘柄コード` の組み合わせを基本キーとして扱う。

## セキュリティのルール

- APIキー、LINEトークン、Azure接続文字列、証券会社の認証情報をコードやCSVへ保存しない。
- 秘密情報はGitHub Secrets、Azure Key Vault、またはローカルの環境変数で管理する。
- `.env`、`.streamlit/secrets.toml`、秘密鍵はGitHubへコミットしない。

## 売買に関するルール

- このプロジェクトは分析・可視化・バックテストを目的とする。
- 証券会社APIへの実注文機能は、明示的な依頼があるまで実装しない。
- 底値予測やスコアは投資助言ではなく、検証対象の分析指標として扱う。
- 機能追加時は、実装前に過去データでバックテスト可能な形を優先する。

## 確認手順

分析ロジックを変更した場合は、以下を確認する。

1. GitHub Actionsの `Daily Export` を手動実行する。
2. 新しいCSVに必要な列が出力されることを確認する。
3. `Stock Close Update Checker` を手動実行する。
4. `update_status.json` に取引日と確認時刻が記録されることを確認する。
5. Streamlit画面とCSVで、取引日・RSI・MACD・Signal・判定・スコアが一致することを確認する。