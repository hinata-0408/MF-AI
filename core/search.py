import os
import re
import requests
from googleapiclient.discovery import build
from typing import List, Optional, Dict, Set, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium_stealth import stealth

from .brand_cfg import BRAND_CONFIG
from .html_parser import extract_best_pdf_from_html, _extract_pdfs_with_requests
from .html_parser import _extract_pdfs_for_toshiba, _extract_pdfs_for_daikin


def create_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    if 'RENDER' in os.environ:
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=options)
    else:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)

    stealth(driver,
            languages=["ja-JP", "ja"],
            vendor="Google Inc.",
            platform="MacIntel",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True)

    return driver


GENERAL_KEYWORDS = {
    "positive": ["取扱説明書", "マニュアル", "ガイド", "download"],
    "negative": ["spec", "specification", "仕様", "寸法", "catalog", "info", "news", "ご案内"],
}


def _generate_aliases(product_name: str) -> List[str]:
    name = re.sub(r'[\s_　]+', ' ', product_name).strip().upper()
    aliases: Set[str] = {name}
    if " " in name:
        aliases.add(name.split(" ")[-1])

    for term in list(aliases):
        if '-' in term:
            aliases.add(term.replace('-', ''))

        if '-' not in term:
            match = re.match(r'^([A-Z0-9]+)(.*)', term)
            if match:
                prefix = match.group(1)
                rest = match.group(2)
                for i in range(1, len(prefix) + 1):
                    aliases.add(f"{prefix[:i]}-{prefix[i:]}{rest}")
    return list(dict.fromkeys(aliases))


def _check_url_exists(url: str) -> bool:
    try:
        response = requests.head(url, timeout=10, allow_redirects=True)
        if response.ok and 'application/pdf' in response.headers.get('Content-Type', '').lower():
            return True
    except requests.exceptions.RequestException:
        return False
    return False


def _search_google_cse(query: str, site_search: Optional[str] = None) -> List[Dict]:
    try:
        api_key, cse_cx = os.getenv("GOOGLE_CSE_KEY"), os.getenv("GOOGLE_CSE_CX")
        if not api_key or not cse_cx:
            return []
        service = build("customsearch", "v1", developerKey=api_key)
        params = {'q': query, 'cx': cse_cx, 'num': 5, 'filter': '1', 'safe': 'off'}
        if site_search:
            params['siteSearch'] = site_search
        res = service.cse().list(**params).execute()
        items = res.get('items', [])
        return [{'title': item.get('title', ''), 'link': item['link']} for item in items if 'link' in item]
    except Exception as e:
        print(f"Google CSE error: {e}")
        return []


def _build_web_queries(product_name: str, brand: str) -> List[str]:
    aliases = _generate_aliases(product_name)
    queries = []
    for p in aliases:
        quoted_p = f'"{p}"'
        queries.extend([f'"{brand}" {quoted_p} 取扱説明書'])
    return list(dict.fromkeys(queries))


def _score_candidate(candidate: Dict, product_name: str, brand: str, debug: bool = False) -> int:
    score, log = 0, []
    url, title = candidate.get('link', '').lower(), candidate.get('title', '').lower()
    brand_config = BRAND_CONFIG.get(brand.lower(), {})
    brand_domains = brand_config.get("domains", [])
    is_official = any(domain in url for domain in brand_domains)
    if is_official:
        score += 50
        log.append("+50 (公式サイト)")
    if is_official:
        if any(key in url for key in brand_config.get("golden_paths", [])):
            score += 150
            log.append("+150 (Golden Path)")
        if any(key in os.path.basename(url) for key in brand_config.get("filename_hints", [])):
            score += 100
            log.append("+100 (ファイル名ヒント)")
        if any(key in (url + title) for key in brand_config.get("positive_keywords", [])):
            score += 30
            log.append("+30 (メーカー固有OKワード)")

    aliases_alnum = [re.sub(r'[^a-zA-Z0-9]', '', a).lower() for a in _generate_aliases(product_name)]
    title_alnum = re.sub(r'[^a-zA-Z0-9]', '', title).lower()
    url_alnum = re.sub(r'[^a-zA-Z0-9]', '', url).lower()

    if any(alias in title_alnum for alias in aliases_alnum):
        score += 80
        log.append("+80 (タイトルに型番)")
    if any(alias in url_alnum for alias in aliases_alnum):
        score += 20
        log.append("+20 (URLに型番)")
    if any(key in (url + title) for key in GENERAL_KEYWORDS["positive"]):
        score += 20
        log.append("+20 (汎用OKワード)")
    if "/ja/" in url or "_jp" in url:
        score += 25
        log.append("+25 (日本語ボーナス)")
    if any(key in (url + title) for key in GENERAL_KEYWORDS["negative"]):
        score -= 50
        log.append("-50 (NGワード)")

    if debug:
        print(f"  URL: {candidate.get('link')}\n  TITLE: {candidate.get('title')}\n  SCORE: {score} | {' | '.join(log) or 'N/A'}\n" + "-" * 20)
    return score


def find_manual_pdf_url(product_name: str, brand: str) -> Tuple[Optional[str], Optional[webdriver.Chrome]]:
    driver = None
    if brand.lower() in ['toshiba', 'daikin']:
        try:
            driver = create_driver()

            if brand.lower() == 'toshiba':
                pdf_url = _extract_pdfs_for_toshiba(driver, product_name)
            elif brand.lower() == 'daikin':
                pdf_url = _extract_pdfs_for_daikin(driver, product_name)

            if pdf_url:
                return pdf_url, driver
            else:
                print(f"{brand.capitalize()} dedicated route found nothing. Falling back to web search.")
                if driver:
                    driver.quit()

        except Exception as e:
            if driver:
                driver.quit()
            print(f"{brand.capitalize()} dedicated route error: {e}")

    brand_config = BRAND_CONFIG.get(brand.lower(), {})
    brand_domains = brand_config.get("domains", [])
    queries = _build_web_queries(product_name, brand)
    all_candidates, seen_urls = [], set()
    for domain in (brand_domains + [None]):
        for query in queries:
            results = _search_google_cse(query, site_search=domain)
            for res in results:
                if res['link'] not in seen_urls:
                    all_candidates.append(res)
                    seen_urls.add(res['link'])

    if not all_candidates:
        return None, None

    scored_candidates = [{'score': _score_candidate(c, product_name, brand, debug=True), **c} for c in all_candidates]
    official_candidates = [c for c in scored_candidates if any(domain in c['link'] for domain in brand_domains)]
    unofficial_candidates = [c for c in scored_candidates if not any(domain in c['link'] for domain in brand_domains)]

    best_candidate = None
    if official_candidates:
        best_official = max(official_candidates, key=lambda x: x['score'])
        if best_official['score'] >= 100:
            best_candidate = best_official
    if not best_candidate and unofficial_candidates:
        best_unofficial = max(unofficial_candidates, key=lambda x: x['score'])
        if best_unofficial['score'] >= 120:
            best_candidate = best_unofficial

    if not best_candidate:
        return None, None

    print(f"Best candidate: {best_candidate['link']} (score: {best_candidate['score']})")
    best_url = best_candidate['link']

    if best_url.lower().endswith('.pdf'):
        return best_url, None

    pdf_url = _extract_pdfs_with_requests(best_url, product_name)
    if pdf_url:
        return pdf_url, None

    driver = None
    try:
        driver = create_driver()
        pdf_url = extract_best_pdf_from_html(best_url, product_name, brand, driver)

        if not pdf_url:
            driver.quit()
            return None, None

        return pdf_url, driver
    except Exception as e:
        if driver:
            driver.quit()
        print(f"Selenium fallback error: {e}")
        return None, None
