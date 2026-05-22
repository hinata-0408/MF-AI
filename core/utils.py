import re
import unicodedata

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("　", " ")
    text = re.sub(r"[\s\n]+", " ", text).strip()
    return text
