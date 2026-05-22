import re
from typing import List, Dict, Any
from statistics import median
import pdfplumber
from .utils import normalize_text
from .schema import Chunk


def parse_pdf_to_chunks(pdf_path: str) -> List[Chunk]:
    chunks: List[Chunk] = []

    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                if page.chars:
                    main_font_size = median([char['size'] for char in page.chars])
                else:
                    continue
            except Exception:
                main_font_size = 10.0

            lines = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=True, extra_attrs=['size'])
            sorted_lines = sorted(lines, key=lambda word: word['top'])

            text_lines = []
            if sorted_lines:
                current_top = sorted_lines[0]['top']
                current_line = []
                for word in sorted_lines:
                    if abs(word['top'] - current_top) > 5:
                        text_lines.append(_process_line(current_line))
                        current_top = word['top']
                        current_line = [word]
                    else:
                        current_line.append(word)
                text_lines.append(_process_line(current_line))

            current_heading = f"P.{i}の冒頭"
            current_paragraph = ""

            for j, line in enumerate(text_lines):
                if not line or not line['text'].strip():
                    continue

                try:
                    next_line = text_lines[j+1]
                    vertical_gap = next_line['top'] - line['bottom']
                except IndexError:
                    vertical_gap = line['height'] * 2

                is_heading = False
                if line['size'] > main_font_size * 1.1:
                    is_heading = True
                elif vertical_gap > line['height'] * 1.5 and len(line['text']) < 50:
                    is_heading = True

                if is_heading:
                    if current_paragraph.strip():
                        meta = _create_meta(pdf_path, i, "paragraph", current_heading)
                        chunks.append(Chunk(content=normalize_text(current_paragraph), metadata=meta))
                    current_heading = line['text']
                    current_paragraph = ""
                else:
                    current_paragraph += line['text'] + "\n"

            if current_paragraph.strip():
                meta = _create_meta(pdf_path, i, "paragraph", current_heading)
                chunks.append(Chunk(content=normalize_text(current_paragraph), metadata=meta))

    return chunks


def _process_line(words: List[Dict]) -> Dict[str, Any]:
    if not words:
        return None

    line_text = " ".join(w['text'] for w in words)
    avg_size = sum(w['size'] for w in words) / len(words)
    top = min(w['top'] for w in words)
    bottom = max(w['bottom'] for w in words)
    height = bottom - top

    return {'text': line_text, 'size': avg_size, 'top': top, 'bottom': bottom, 'height': height}


def _create_meta(pdf_path: str, page_num: int, element_type: str, section_title: str) -> Dict[str, Any]:
    return {
        "source": pdf_path,
        "page_start": page_num,
        "page_end": page_num,
        "section_title": normalize_text(section_title),
        "element_type": element_type,
        "lang": "ja",
        "extractor": "heuristic-heading-parser-v1"
    }
