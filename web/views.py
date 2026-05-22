import os
import re
import json
import requests
from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, Http404
from django.conf import settings
from dotenv import load_dotenv
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from core.rag_chain import index_pdf, answer_query
from core.search import find_manual_pdf_url
from core.brand_cfg import BRAND_CONFIG
from django.http import StreamingHttpResponse

load_dotenv()

DOWNLOADS_DIR = os.path.join(settings.BASE_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


@login_required
def load_manual(request: HttpRequest):
    brands_for_template = []
    for brand_id, config in BRAND_CONFIG.items():
        brands_for_template.append({
            'id': brand_id,
            'display': config.get('display', brand_id.title()),
            'order': config.get('order', 999),
        })
    brands_for_template.sort(key=lambda x: x['order'])

    context = {
        "brands": brands_for_template,
        "error": None,
        "not_found": False,
        "brand_selected": "",
        "model_prefill": "",
    }

    if request.method == "POST":
        old_file_path = request.session.get('manual_file_path')
        if old_file_path:
            try:
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)
                del request.session['manual_file_path']
            except Exception as e:
                print(f"Failed to remove old PDF: {e}")

        context["brand_selected"] = request.POST.get("brand", "")
        context["model_prefill"] = request.POST.get("product_name", "")

        if "pdf_upload_submit" in request.POST and request.FILES.get("pdf"):
            pdf_file = request.FILES["pdf"]
            safe_filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', pdf_file.name)
            dest_path = os.path.join(DOWNLOADS_DIR, safe_filename)
            with open(dest_path, "wb") as out:
                for chunk in pdf_file.chunks():
                    out.write(chunk)
            index_name = re.sub(r'[^a-zA-Z0-9_-]', '_', os.path.splitext(safe_filename)[0])
            try:
                session_key = f'chat_history_{index_name}'
                if session_key in request.session:
                    del request.session[session_key]
                index_pdf(dest_path, index_name=index_name)
                request.session['manual_file_path'] = dest_path
                return redirect(f"/chat/?idx={index_name}")
            except Exception as e:
                context["error"] = f"PDFの解析中にエラーが発生しました: {e}"

        elif "web_search_submit" in request.POST:
            brand = request.POST.get("brand", "").strip().lower()
            product_name = request.POST.get("product_name", "").strip()
            if not brand or not product_name:
                context["error"] = "メーカーと製品名（型番）の両方を選択・入力してください。"
            else:
                pdf_url, driver = None, None
                try:
                    pdf_url, driver = find_manual_pdf_url(product_name, brand)

                    if not pdf_url:
                        context["not_found"] = True
                    else:
                        dest_path = os.path.join(DOWNLOADS_DIR, re.sub(r'[^a-zA-Z0-9_-]', '_', f"{brand}_{product_name}.pdf"))

                        response = None
                        if driver:
                            cookies = driver.get_cookies()
                            session = requests.Session()
                            for cookie in cookies:
                                session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                            headers = {'User-Agent': 'Mozilla/5.0'}
                            response = session.get(pdf_url, headers=headers, stream=True, timeout=60)
                        else:
                            response = requests.get(pdf_url, stream=True, timeout=60)

                        if response and response.status_code == 200 and 'application/pdf' in response.headers.get('Content-Type', ''):
                            with open(dest_path, "wb") as f:
                                f.write(response.content)

                            index_name = re.sub(r'[^a-zA-Z0-9_-]', '_', f"{brand}_{product_name}")
                            session_key = f'chat_history_{index_name}'
                            if session_key in request.session:
                                del request.session[session_key]
                            index_pdf(dest_path, index_name=index_name)
                            request.session['manual_file_path'] = dest_path
                            return redirect(f"/chat/?idx={index_name}")
                        else:
                            error_content = response.headers.get('Content-Type', '不明') if response else 'レスポンスなし'
                            raise Exception(f"コンテンツタイプがPDFではありません: {error_content}")

                except Exception as e:
                    context["error"] = f"処理中にエラーが発生しました: {e}"
                finally:
                    if driver:
                        driver.quit()

    return render(request, "load_manual.html", context)


@login_required
def chat(request: HttpRequest):
    index_name = request.GET.get("idx")
    if not index_name:
        return redirect('load_manual')

    product_name_display = ""
    if '_' in index_name:
        brand_id, model_part = index_name.split('_', 1)
        brand_config = BRAND_CONFIG.get(brand_id, {})
        display_name = brand_config.get('display', brand_id.title())
        product_name_display = f"{display_name} {model_part.upper()}"
    else:
        product_name_display = index_name.upper()

    session_key = f'chat_history_{index_name}'
    if request.method == "POST":
        question = request.POST.get("q", "").strip()
        if not question:
            return HttpResponse(status=204)
        chat_history = request.session.get(session_key, [])
        chat_history.append({"speaker": "user", "message": question})
        json_string_answer = answer_query(question, index_name=index_name)
        answer_data = json.loads(json_string_answer)
        if "confidence" in answer_data and isinstance(answer_data["confidence"], float):
            answer_data["confidence_percent"] = int(answer_data["confidence"] * 100)
        if "citations" in answer_data:
            page_numbers = [cite.get("page") for cite in answer_data["citations"]]
            unique_pages = sorted(list(set(p for p in page_numbers if p is not None)))
            answer_data["unique_pages_str"] = ", ".join(f"p.{p}" for p in unique_pages)
        chat_history.append({"speaker": "ai", "data": answer_data})
        request.session[session_key] = chat_history
        context = {"latest_ai_a": answer_data}
        return render(request, "partials/_chat_response.html", context)

    chat_history = request.session.get(session_key, [])

    manual_path = request.session.get('manual_file_path')
    pdf_url = None
    if manual_path:
        filename = os.path.basename(manual_path)
        pdf_url = reverse('view_pdf', kwargs={'filename': filename})

    context = {
        "idx": index_name,
        "product_name": product_name_display,
        "chat_history": chat_history,
        "pdf_url": pdf_url,
    }
    return render(request, "chat.html", context)


@login_required
def view_pdf(request: HttpRequest, filename: str):
    file_path = os.path.join(DOWNLOADS_DIR, filename)
    if os.path.exists(file_path):
        with open(file_path, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_path)}"'
            return response
    raise Http404("PDF not found")


@login_required
def chat_stream(request: HttpRequest):
    index_name = request.GET.get("idx")
    question = request.GET.get("q", "").strip()

    if not index_name or not question:
        return HttpResponse("Invalid request", status=400)

    def event_stream():
        try:
            from core.rag_chain import load_retriever_with_parents
            from core.answer import generative_answer_streaming

            retriever, parent_store = load_retriever_with_parents(index_name)

            for chunk in generative_answer_streaming(question, retriever, parent_store):
                yield f"data: {chunk}\n\n"

        except Exception as e:
            error_data = json.dumps({
                "type": "complete",
                "data": {
                    "answer": f"エラーが発生しました: {str(e)}",
                    "citations": [],
                    "confidence": 0.0,
                    "followups": []
                }
            }, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
