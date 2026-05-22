import os
from langchain_huggingface import HuggingFaceEmbeddings

def get_embeddings():
    model_name = os.getenv("HF_EMBED_MODEL", "intfloat/multilingual-e5-base")
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )
