import os
import json
from pathlib import Path
from typing import Dict, Tuple
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS

from .ingest import build_and_save_index
from .answer import generative_answer, generative_answer_streaming
from . import vision

INDICES_DIR = Path("indices")
EMBEDDING_MODEL = "text-embedding-3-small"
VISION_KEYWORDS = ["図", "イラスト", "配線", "結線", "端子", "位置", "レイアウト", "配置", "向き", "形状"]

def index_pdf(pdf_path: str, index_name: str):
    build_and_save_index(index_name=index_name, pdf_path=pdf_path)

def load_retriever(index_name: str):
    index_path = INDICES_DIR / index_name
    if not index_path.exists():
        raise FileNotFoundError(f"Index '{index_name}' not found at {index_path}")
    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    db = FAISS.load_local(str(index_path), embeddings, allow_dangerous_deserialization=True)
    return db.as_retriever(search_type="similarity", search_kwargs={'k': 100})

def load_retriever_with_parents(index_name: str) -> Tuple:
    index_path = INDICES_DIR / index_name
    if not index_path.exists():
        raise FileNotFoundError(f"Index '{index_name}' not found at {index_path}")

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    db = FAISS.load_local(str(index_path), embeddings, allow_dangerous_deserialization=True)
    retriever = db.as_retriever(search_type="similarity", search_kwargs={'k': 50})

    parent_store: Dict[str, str] = {}
    parent_store_path = index_path / "parent_store.json"

    if parent_store_path.exists():
        try:
            with open(parent_store_path, "r", encoding="utf-8") as f:
                parent_store = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load parent_store.json: {e}")

    return retriever, parent_store

def answer_query(query: str, index_name: str, k: int = 6) -> str:
    retriever, parent_store = load_retriever_with_parents(index_name)

    text_based_json_str = generative_answer(
        query=query,
        retriever=retriever,
        parent_store=parent_store,
        k=k
    )

    text_based_data = json.loads(text_based_json_str)

    is_vision_query = any(keyword in query for keyword in VISION_KEYWORDS)
    confidence = text_based_data.get("confidence", 0.0)
    answer_text = text_based_data.get("answer", "")

    should_call_vision = False
    if is_vision_query:
        if confidence >= 0.9:
            should_call_vision = False
        elif confidence < 0.9 or "ご覧ください" in answer_text:
            should_call_vision = True

    if should_call_vision:
        if text_based_data.get("citations"):
            citation = text_based_data["citations"][0]
            target_page = citation.get("page")
            manual_id = citation.get("manual_id", f"{index_name}.pdf")
            pdf_path = f"downloads/{manual_id}"

            if target_page and os.path.exists(pdf_path):
                vision_data = vision.answer_with_vision(query, pdf_path, target_page)
                if vision_data:
                    return json.dumps(vision_data, ensure_ascii=False, indent=2)

    return text_based_json_str
