# test_search_accuracy.py (プロジェクトのルートディレクトリに保存)

import os
import sys
import time
import django
from dotenv import load_dotenv

# -------------------------------------------------
# Djangoプロジェクト設定のロード
# -------------------------------------------------
sys.path.append(os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
# -------------------------------------------------

# 作成した search.py のメイン関数をインポート
from core.search import find_manual_pdf_url

# ▼▼▼ ここに精度をテストしたい製品を追加・編集してください ▼▼▼
TEST_CASES = [





("toshiba", "AW-12DP3"),   




]
# ▲▲▲ ここまで ▲▲▲


def run_tests():
    """
    TEST_CASES を順番に実行し、見つかったPDFのURLを出力する
    """
    print(">>> PDF検索の精度テストを開始します...")

    for brand, product_name in TEST_CASES:
        print("-" * 60)
        print(f"🔎 テスト対象: {brand} - {product_name}")

        try:
            # メインの検索関数を実行
            found_url = find_manual_pdf_url(product_name, brand)

            if found_url:
                print(f"  ✅ 発見したURL: {found_url}")
            else:
                print("  ❌ PDFは見つかりませんでした。")

        except Exception as e:
            print(f"  💥 テスト中にエラーが発生しました: {e}")

        # APIのレートリミットを避けるため、テストごとに待機
        print("\n...API制限を避けるため5秒待機...")
        time.sleep(5)

    print("-" * 60)
    print(">>> 全てのテストが完了しました。")


if __name__ == '__main__':
    # .envファイルからAPIキーをロード
    load_dotenv()

    # GOOGLE_CSE_KEY が設定されているか確認
    if not os.getenv("GOOGLE_CSE_KEY"):
        print("エラー: .envファイルに GOOGLE_CSE_KEY が設定されていません。")
    else:
        run_tests()
