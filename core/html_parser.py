import requests
import re
import time
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from typing import Optional

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException


def _score_link_in_html(link_tag, product_name: str) -> int:
    score = 0
    link_text = link_tag.get_text(strip=True).lower()
    href = link_tag.get('href', '').lower()
    if any(k in link_text for k in ["取扱説明書", "マニュアル", "manual"]):
        score += 100
    product_alnum = re.sub(r'[^a-zA-Z0-9]', '', product_name).lower()
    text_alnum = re.sub(r'[^a-zA-Z0-9]', '', href + link_text)
    if product_alnum and product_alnum in text_alnum:
        score += 50
    return score

def _extract_pdfs_with_requests(html_url: str, product_name: str) -> Optional[str]:
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(html_url, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        all_links = soup.find_all('a', href=re.compile(r'\.pdf', re.IGNORECASE))
        if not all_links: return None
        candidates = [{'score': _score_link_in_html(link, product_name), 'link': link} for link in all_links]
        best_candidate = max(candidates, key=lambda x: x['score'])
        if best_candidate['score'] < 0: return None
        return urljoin(html_url, best_candidate['link']['href'])
    except Exception:
        return None

def _extract_pdfs_with_selenium_general(html_url: str, product_name: str, driver: webdriver.Chrome) -> Optional[str]:
    try:
        driver.get(html_url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.PARTIAL_LINK_TEXT, 'PDF')))
        time.sleep(2)

        soup = BeautifulSoup(driver.page_source, 'lxml')
        all_links = soup.find_all('a', href=re.compile(r'\.pdf', re.IGNORECASE))
        if not all_links: return None

        candidates = [{'score': _score_link_in_html(link, product_name), 'link': link} for link in all_links]
        best_candidate = max(candidates, key=lambda x: x['score'])
        return urljoin(html_url, best_candidate['link']['href'])
    except Exception as e:
        print(f"汎用Seleniumモードでエラー: {e}")
        return None

def _extract_pdfs_for_toshiba(driver: webdriver.Chrome, product_name: str) -> Optional[str]:
    base_url = "https://www.toshiba-living.jp/search.php"
    wait = WebDriverWait(driver, 20)

    try:
        driver.get(base_url)
        search_box = wait.until(EC.presence_of_element_located((By.NAME, "query")))
        search_box.send_keys(product_name)
        search_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[text()='検索']")))
        search_button.click()

        first_manual_button_xpath = "//table[@class='tblSearch']/tbody/tr[1]//a[contains(text(), '説明書')]"
        manual_button = wait.until(EC.element_to_be_clickable((By.XPATH, first_manual_button_xpath)))
        manual_button.click()

        # 同意画面のチェックボックスをクリックしてフォーム送信
        wait.until(EC.number_of_windows_to_be(2))
        driver.switch_to.window(driver.window_handles[-1])
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "check")))
        checkbox.click()
        agree_button = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@value='同意して次へ']")))
        agree_button.submit()

        wait.until(EC.visibility_of_element_located((By.XPATH, "//h1[contains(., '取扱説明書ダウンロード')]")))
        download_link_element = wait.until(EC.presence_of_element_located((By.XPATH, "//a[@download]")))
        pdf_url = download_link_element.get_attribute('href')

        if not pdf_url.startswith('http'):
            pdf_url = urljoin(driver.current_url, pdf_url)
        return pdf_url

    except Exception as e:
        print(f"東芝専用ルートでエラー: {e}")
        driver.save_screenshot("error_screenshot.png")
        return None

def _extract_pdfs_for_daikin(driver: webdriver.Chrome, product_name: str) -> Optional[str]:
    base_url = "https://www.free.dtnet.daikin.co.jp/DT-NET/torisetu/search"
    wait = WebDriverWait(driver, 20)

    # 末尾に"-W"が付くパターンも試す
    search_candidates = list(dict.fromkeys([f"{product_name}-W", product_name]))

    for i, model_name in enumerate(search_candidates):
        try:
            driver.get(base_url)
            search_box = wait.until(EC.presence_of_element_located((By.ID, "searchForm")))
            search_box.clear()
            search_box.send_keys(model_name)
            search_button = wait.until(EC.element_to_be_clickable((By.ID, "searchBtn")))
            search_button.click()

            pdf_button_xpath = "//span[contains(text(), '取扱説明書')]/ancestor::div[@class='dt-tbl__row dt-tbl__row--control']//a[contains(@class, 'pdfDlBtn')]"
            pdf_button = wait.until(EC.element_to_be_clickable((By.XPATH, pdf_button_xpath)))
            pdf_button.click()

            # 同意モーダルを突破してPDFタブのURLを取得
            consent_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@id='consentBtn']")))
            consent_button.click()

            wait.until(EC.number_of_windows_to_be(2))
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(1)
            return driver.current_url

        except TimeoutException:
            continue

    print("ダイキン専用ルート: 全候補でPDFが見つかりませんでした。")
    driver.save_screenshot("daikin_error_screenshot.png")
    return None

def extract_best_pdf_from_html(html_url: str, product_name: str, brand: str, driver: webdriver.Chrome) -> Optional[str]:
    if brand.lower() == 'toshiba':
        return _extract_pdfs_for_toshiba(driver, product_name)
    else:
        return _extract_pdfs_with_selenium_general(html_url, product_name, driver)
