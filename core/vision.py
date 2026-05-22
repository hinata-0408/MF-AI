import os
import base64
import json
import traceback
from openai import OpenAI, APIStatusError
import pdfplumber


def _encode_image_to_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode('utf-8')


def answer_with_vision(query: str, pdf_path: str, page_num: int) -> dict:
    temp_image_path = "temp_page_image.png"

    try:
        with pdfplumber.open(pdf_path) as pdf:
            if not (1 <= page_num <= len(pdf.pages)):
                return None
            page = pdf.pages[page_num - 1]
            img = page.to_image(resolution=200)
            img.save(temp_image_path, format="PNG")

        base64_image = _encode_image_to_base64(temp_image_path)

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        client = OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"このページ画像を見て、次の質問に答えてください：{query}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }],
            max_tokens=500,
        )

        final_answer = response.choices[0].message.content
        return {
            "answer": final_answer,
            "citations": [{"manual_id": pdf_path.split("/")[-1], "page": page_num, "chunk_id": "vision_analysis"}],
            "confidence": 0.95,
            "followups": ["他に図で確認したいことはありますか？"]
        }

    except APIStatusError as e:
        print(f"OpenAI API error: {e.status_code} - {e.response.text}")
        return None
    except Exception:
        traceback.print_exc()
        return None
    finally:
        if os.path.exists(temp_image_path):
            os.remove(temp_image_path)
