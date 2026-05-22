# 家電マニュアル AI 検索ツール

家電量販店でのアルバイト中に、膨大な取扱説明書を横断的に検索・質問できるツールが必要と感じて自作・実運用しました。

型番を入力するだけでメーカー公式サイトからマニュアル PDF を自動取得し、RAG（検索拡張生成）で自然言語の質問に回答します。



---

## 主な機能

- **マニュアル自動取得**: 型番を入力するとメーカー公式サイトから PDF を取得
- **RAG チャット**: 取得したマニュアルに対して日本語で質問・回答
- **ストリーミング応答**: Server-Sent Events によるリアルタイム表示
- **図表への回答**: 「配線図を見せて」等の質問では GPT-4o Vision で画像解析
- **逆質問モード**: 確度が低い場合は選択肢を提示して意図を絞り込む

---

## アーキテクチャ

```
[ユーザー]
    │ 型番 or PDF アップロード
    ▼
[マニュアル取得]
    ├─ Google Custom Search → メーカー公式 URL 特定
    └─ Selenium stealth → 動的サイトから PDF を抽出
    ▼
[インデックス構築]
    ├─ pdfplumber でテキスト抽出（フォントサイズで見出しを自動判定）
    ├─ OCR フォールバック（Google Cloud Vision API）
    └─ 親子チャンク構造で FAISS ベクトル DB に保存
    ▼
[クエリ処理]
    ├─ FAISS 類似検索（k=50）
    ├─ Cohere Rerank（multilingual-v3.0）で再ランキング
    ├─ 親チャンクを取得してコンテキスト拡張
    └─ GPT-4o-mini で日本語回答生成（JSON 構造化出力）
```

---

## 技術スタック

| カテゴリ | 技術 |
|---|---|
| バックエンド | Django 5.x |
| LLM | GPT-4o-mini / GPT-4o（図表） |
| Embeddings | text-embedding-3-small |
| Reranking | Cohere rerank-multilingual-v3.0 |
| ベクトル DB | FAISS |
| OCR | Google Cloud Vision API |

---

## 工夫した点

**1. 親子チャンク構造による精度向上**

ベクトル検索には細かい子チャンク（500文字）を使い、LLM へのコンテキストとしては見出し単位の親チャンクを渡す設計にしました。細かく分割するほど検索精度は上がりますが、文脈が失われる問題を解消しています。

**2. Cohere Rerank による再ランキング**

FAISS の近似最近傍探索は速いものの精度に限界があります。候補を 50 件取得した後、Cohere の多言語対応 Rerank モデルで意味的な関連度で再ランキングすることで回答精度を向上させました。

**3. 確度判定と逆質問モード**

Rerank スコアが一定以下の場合、無理に回答するのではなく、関連する候補をまとめて「どちらについて知りたいですか？」と選択肢を提示します。曖昧な質問でも的外れな回答を返さない設計です。

**4. メーカー別スコアリングによるマニュアル特定**

公式ドメイン、URL パターン（Golden Path）、型番のタイトル一致などを複合的にスコアリングして最良の候補を選びます。東芝・ダイキンなど動的サイトは Selenium の専用ルートを持ちます。

**5. フォントサイズで見出しを自動判定**

pdfplumber で各文字のフォントサイズを取得し、ページの中央値より 1.1 倍大きい行を見出しと判定します。マニュアルごとにレイアウトが異なるため、固定閾値ではなくページ内の相対値で判断しています。

---

## セットアップ

```bash
git clone <このリポジトリ>
cd new_MF_AI

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env に各種 API キーを設定

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### 必要な環境変数

`.env.example` を参照してください。最低限 `OPENAI_API_KEY` と `COHERE_API_KEY` が必要です。Web 検索機能を使う場合は `GOOGLE_CSE_KEY` / `GOOGLE_CSE_CX` も必要です。

---

## ディレクトリ構成

```
.
├── config/          # Django 設定
├── web/             # ビュー・テンプレート・URL
├── core/
│   ├── rag_chain.py     # RAG のエントリポイント
│   ├── answer.py        # Rerank + GPT 回答生成
│   ├── ingest.py        # PDF → FAISS インデックス構築
│   ├── search.py        # マニュアル URL 自動検索
│   ├── pdf_parse.py     # PDF テキスト抽出
│   ├── ocr.py           # Google Cloud Vision OCR
│   ├── vision.py        # 図表質問への Vision 対応
│   └── brand_cfg.py     # メーカー別 URL 設定
├── indices/         # FAISS インデックス（gitignore）
├── downloads/       # 取得 PDF（gitignore）
└── requirements.txt
```
