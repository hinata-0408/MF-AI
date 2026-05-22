import os
from typing import List
from langchain_community.vectorstores import FAISS
from .schema import Chunk
from .embeddings import get_embeddings
from .utils import ensure_dir

def build_faiss(chunks: List[Chunk], out_dir: str) -> str:
    ensure_dir(out_dir)
    texts = [c.content for c in chunks]
    metas = [c.metadata for c in chunks]
    emb = get_embeddings()
    db = FAISS.from_texts(texts, emb, metadatas=metas)
    db.save_local(out_dir)
    return out_dir

def load_faiss(dir_path: str):
    emb = get_embeddings()
    return FAISS.load_local(dir_path, emb, allow_dangerous_deserialization=True)
