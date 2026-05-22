from pathlib import Path
from typing import Dict, List
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from .schema import Chunk
from .pdf_parse import parse_pdf_to_chunks
from .ocr import ocr_pdf_with_google
import json

INDICES_DIR = Path("indices")
INDICES_DIR.mkdir(exist_ok=True)

def build_and_save_index(index_name: str, pdf_path: str):
    print("Parsing PDF...")
    parent_chunks: List[Chunk] = parse_pdf_to_chunks(pdf_path)

    if not parent_chunks:
        print("Text extraction failed. Switching to OCR...")
        parent_chunks = ocr_pdf_with_google(pdf_path)

    total_chars = sum(len(c.content) for c in parent_chunks)
    if not parent_chunks or total_chars < 500:
        raise ValueError("テキストの抽出に失敗しました。PDFファイルを確認してください。")

    parent_store: Dict[str, str] = {}
    child_documents = []

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "、", " "]
    )

    for parent_idx, parent_chunk in enumerate(parent_chunks):
        parent_id = f"parent_{parent_idx}"
        parent_store[parent_id] = parent_chunk.content

        if len(parent_chunk.content) <= 600:
            child_meta = {**parent_chunk.metadata, "parent_id": parent_id, "chunk_type": "single"}
            child_documents.append(Document(page_content=parent_chunk.content, metadata=child_meta))
        else:
            sub_docs = text_splitter.create_documents([parent_chunk.content], metadatas=[parent_chunk.metadata])
            for sub_idx, sub_doc in enumerate(sub_docs):
                sub_doc.metadata["parent_id"] = parent_id
                sub_doc.metadata["chunk_type"] = "split"
                sub_doc.metadata["sub_index"] = sub_idx
                child_documents.append(sub_doc)

    print(f"Created {len(child_documents)} child chunks from {len(parent_chunks)} parents.")

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    db = FAISS.from_documents(child_documents, embeddings)

    save_dir = INDICES_DIR / index_name
    save_dir.mkdir(parents=True, exist_ok=True)
    db.save_local(str(save_dir))

    parent_store_path = save_dir / "parent_store.json"
    with open(parent_store_path, "w", encoding="utf-8") as f:
        json.dump(parent_store, f, ensure_ascii=False, indent=2)

    print(f"Index saved to: {save_dir}")
    return db
