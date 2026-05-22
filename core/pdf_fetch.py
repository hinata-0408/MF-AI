import os
import re
import requests
from django.conf import settings

DOWNLOADS_DIR = os.path.join(settings.BASE_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def download_pdf(url: str, brand: str, product_name: str) -> str:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=60, allow_redirects=True)
        response.raise_for_status()

        content_type = response.headers.get('content-type', '').lower()
        if 'application/pdf' not in content_type:
            raise Exception(f"コンテンツタイプがPDFではありません: {content_type}")

        filename = f"{_sanitize_filename(brand)}_{_sanitize_filename(product_name)}.pdf"
        dest_path = os.path.join(DOWNLOADS_DIR, filename)

        with open(dest_path, "wb") as f:
            f.write(response.content)

        return dest_path

    except requests.exceptions.RequestException as e:
        raise Exception(f"ネットワークエラー: {e}")
    except Exception as e:
        raise Exception(f"ダウンロード失敗: {e}")
