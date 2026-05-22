import os
import re
import json
from typing import List, Dict
from collections import Counter
from statistics import median
import cohere
from openai import OpenAI
from .schema import Chunk

try:
    COHERE_API_KEY = os.getenv("COHERE_API_KEY")
    if not COHERE_API_KEY:
        raise ValueError("COHERE_API_KEY not set")
    co = cohere.Client(COHERE_API_KEY)
except Exception as e:
    print(f"Cohere initialization failed: {e}")
    co = None

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "ユーザーへの最終的な回答文"},
        "citations": {
            "type": "array",
            "description": "回答の根拠となった出典情報のリスト",
            "items": {
                "type": "object",
                "properties": {
                    "manual_id": {"type": "string"}, "page": {"type": "integer"}, "chunk_id": {"type": "string"}
                },
                "required": ["manual_id", "page", "chunk_id"]
            }
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "followups": {
            "type": "array",
            "items": {"type": "string"},
            "description": "ユーザーが次に行うべき、具体的で分かりやすい質問の候補リスト（3つ以内）"
        }
    },
    "required": ["answer", "citations", "confidence"]
}

PAGE_PATTERN = re.compile(r"(?:p\.?\s*|ページ\.?\s*)(\d+)(?:\s*[-–~]\s*(\d+))?", flags=re.IGNORECASE)

def _compress(text: str, max_chars: int = 600) -> str:
    t = (text or "").strip()
    return t[:max_chars] + "…" if len(t) > max_chars else t

def _calc_confidence(scores: List[float]) -> float:
    if not scores: return 0.0
    return round(max(scores), 2)

def _section_scope_docs(docs, section_title: str):
    return [d for d in docs if d.metadata.get("section_title") == section_title]


def generative_answer(
    query: str,
    retriever,
    parent_store: Dict[str, str] = None,
    k: int = 6
) -> str:
    pool_size = 100
    initial_candidates = retriever.invoke(query, k=pool_size)
    if not initial_candidates:
        return json.dumps({"answer": "マニュアルに該当する記載は見つかりませんでした。", "citations": [], "confidence": 0.0, "followups": []}, ensure_ascii=False, indent=2)

    docs_to_rerank = [doc.page_content for doc in initial_candidates]
    try:
        if not co: raise Exception("Cohere client not initialized.")
        rerank_response = co.rerank(model='rerank-multilingual-v3.0', query=query, documents=docs_to_rerank, top_n=25)
    except Exception as e:
        return json.dumps({"answer": f"Cohere Rerank APIエラー: {e}", "citations": [], "confidence": 0.0, "followups": ["APIキーを再確認してください。"]}, ensure_ascii=False, indent=2)

    reranked = []
    reranked_scores = []
    for hit in rerank_response.results:
        reranked.append((initial_candidates[hit.index], hit.relevance_score))
        reranked_scores.append(hit.relevance_score)

    if not reranked:
        return json.dumps({"answer": "関連情報が見つかりませんでした。", "citations": [], "confidence": 0.0, "followups": []}, ensure_ascii=False, indent=2)

    conf0 = _calc_confidence(reranked_scores)

    # 確度が低い場合は選択肢を提示して意図を絞り込む
    if conf0 < 0.6:
        top_n_candidates = []
        seen_content = set()
        for doc, score in reranked:
            content = doc.page_content.strip()
            if len(content) > 30 and content not in seen_content:
                seen_content.add(content)
                top_n_candidates.append(doc)
            if len(top_n_candidates) >= 3:
                break

        if not top_n_candidates:
            return json.dumps({
                "answer": "関連する可能性のある情報が見つかりましたが、質問の意図を特定できませんでした。もう少し具体的に質問していただけますか？",
                "citations": [], "confidence": conf0, "followups": []
            }, ensure_ascii=False, indent=2)

        context_parts = []
        for i, doc in enumerate(top_n_candidates):
            context_parts.append(f"参考情報{i+1} (P.{doc.metadata.get('page_start')}):\n{_compress(doc.page_content)}")
        context = "\n---\n".join(context_parts)

        clarification_prompt = (
            "あなたはユーザーの曖昧な質問の意図を特定する、優秀なアシスタントです。\n"
            f"ユーザーは「{query}」と質問しましたが、意図が曖昧です。\n"
            "こちらで関連しそうな以下の参考情報を見つけました。\n\n"
            f"### 参考情報\n{context}\n\n"
            "### あなたのタスク\n"
            "1. 上記の参考情報が、それぞれ「何について」書かれているかを簡潔に特定してください。\n"
            "2. それらのトピックを元に、ユーザーが本当に知りたいことを明確にするための、自然な**質問文**を作成してください。\n"
            "3. ユーザーが選択しやすいように、それぞれのトピックを**箇条書きの選択肢**として提示してください。\n"
            "4. 回答は、必ず以下のJSON形式で出力してください。\n\n"
            "```json\n"
            "{\n"
            '  "question": "（ここにユーザーへの自然な質問文を生成）",\n'
            '  "choices": [\n'
            '    { "page": （参考情報1のページ番号）, "summary": "（参考情報1の要約/選択肢）" },\n'
            '    { "page": （参考情報2のページ番号）, "summary": "（参考情報2の要約/選択肢）" },\n'
            '    { "page": （参考情報3のページ番号）, "summary": "（参考情報3の要約/選択肢）" }\n'
            '  ]\n'
            "}\n"
            "```"
        )

        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": clarification_prompt}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            clarification_data = json.loads(response.choices[0].message.content)

            summary_answer = clarification_data.get("question", "関連する可能性のある、以下の項目が見つかりました。") + "\n\n"
            generated_followups = []

            for i, choice in enumerate(clarification_data.get("choices", [])):
                page = choice.get("page")
                summary = choice.get("summary")
                if page and summary:
                    summary_answer += f"**{i+1}. {summary}** (P.{page})\n"
                    generated_followups.append(f"「{summary}」について詳しく教えて")

            return json.dumps({
                "answer": summary_answer.strip(),
                "citations": [],
                "confidence": conf0,
                "followups": generated_followups
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"Clarification generation failed: {e}")
            return json.dumps({
                "answer": "関連情報が見つかりましたが、絞り込みに失敗しました。お手数ですが、より具体的なキーワードで再度ご質問ください。",
                "citations": [], "confidence": conf0, "followups": []
            }, ensure_ascii=False, indent=2)

    final_tuples = reranked
    top_5_sections = [doc.metadata.get("section_title") for doc, score in reranked[:5]]
    section_counts = Counter(s for s in top_5_sections if s and s != "概要")

    target_section = None
    if section_counts:
        most_common_section, count = section_counts.most_common(1)[0]
        if count >= 2:
            target_section = most_common_section

    if target_section:
        scoped_docs = _section_scope_docs(initial_candidates, target_section)
        if scoped_docs:
            scoped_docs_content = [doc.page_content for doc in scoped_docs]
            scoped_rerank_response = co.rerank(model='rerank-multilingual-v3.0', query=query, documents=scoped_docs_content, top_n=10)
            scoped_reranked = []
            for hit in scoped_rerank_response.results:
                scoped_reranked.append((scoped_docs[hit.index], hit.relevance_score))
            if scoped_reranked:
                final_tuples = scoped_reranked

    topn = min(8, len(final_tuples))
    chosen_docs, chosen_scores, context_parts = [], [], []
    seen_parent_ids = set()

    for i in range(topn):
        doc, score = final_tuples[i]
        page_num = int(doc.metadata.get("page_start") or doc.metadata.get("page", 0))
        parent_id = doc.metadata.get("parent_id")

        if parent_store and parent_id:
            if parent_id in seen_parent_ids:
                continue
            seen_parent_ids.add(parent_id)
            parent_content = parent_store.get(parent_id)

            if parent_content:
                chunk_id = f"p{page_num}_{parent_id}"
                doc.metadata["chunk_id"] = chunk_id
                context_parts.append(
                    f"参考情報{len(context_parts)+1} (p.{page_num}, id:{chunk_id}, section:'{doc.metadata.get('section_title', 'N/A')}'):\n"
                    f"{_compress(parent_content, max_chars=1200)}\n"
                )
                chosen_docs.append(doc)
                chosen_scores.append(score)
            else:
                chunk_id = f"p{page_num}_{i}"
                doc.metadata["chunk_id"] = chunk_id
                context_parts.append(
                    f"参考情報{len(context_parts)+1} (p.{page_num}, id:{chunk_id}, section:'{doc.metadata.get('section_title', 'N/A')}'):\n"
                    f"{_compress(doc.page_content)}\n"
                )
                chosen_docs.append(doc)
                chosen_scores.append(score)
        else:
            chunk_id = f"p{page_num}_{i}"
            if chunk_id in {d.metadata.get("chunk_id") for d in chosen_docs}:
                continue
            doc.metadata["chunk_id"] = chunk_id
            context_parts.append(
                f"参考情報{len(context_parts)+1} (p.{page_num}, id:{chunk_id}, section:'{doc.metadata.get('section_title', 'N/A')}'):\n"
                f"{_compress(doc.page_content)}\n"
            )
            chosen_docs.append(doc)
            chosen_scores.append(score)

    context = "\n".join(context_parts)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    SYSTEM_PROMPT = (
        "あなたはユーザーを助ける、家電の取扱説明書に非常に詳しい専門家アシスタントです。\n"
        "あなたの仕事は、提供された参考情報だけを元に、ユーザーの質問に対する答えを統合し、要約して提示することです。\n\n"
        "### 厳守すべきルール\n"
        "1. **情報の統合**: 参考情報が断片的な場合、それらを組み合わせて一つの完全な回答を作成してください。\n"
        "2. **手順の再構築**: ユーザーが「方法」や「やり方」について尋ねている場合、必ず**改行を用いた番号付きリスト**で再構築してください。\n"
        "3. **事実厳守**: 参考情報に書かれていない憶測や一般的な知識で回答を補完してはいけません。\n"
        "4. **回答の原則**: まず、参考情報から質問に対する直接的で確信のある答えを探してください。\n"
        "   - **もし答えが見つかれば**、絶対に「XXページをご覧ください」とは答えず、その内容を直接要約・説明してください。（案内係からの脱却）\n"
        "   - **もし確信のある答えが見つからない場合**は、無理に答えず、『関連する情報が複数見つかりました。』といった短い応答を生成してください。そして、ユーザーが答えにたどり着くのを助ける、具体的で分かりやすいフォローアップの質問（followups）を3つ提案してください。（低信頼度時の逆質問）\n"
        "5. **JSON形式の徹底**: 出力は必ず指定されたJSONスキーマに従ってください。"
    )

    USER_PROMPT = (
        f"JSONスキーマ: {json.dumps(ANSWER_SCHEMA, ensure_ascii=False)}\n\n"
        f"参考情報:\n{context}\n\n"
        f"質問: {query}\n\n"
        "上記のルールとJSONスキーマに厳密に従って、日本語で回答のJSONを生成してください。"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": USER_PROMPT}],
            response_format={"type": "json_object"}, temperature=0.0, max_tokens=1024,
        )
        data = json.loads(response.choices[0].message.content)

        if "confidence" not in data or not isinstance(data.get("confidence"), (int, float)):
            data["confidence"] = _calc_confidence(chosen_scores)
        if data["confidence"] < 0.55 and not data.get("followups"):
            data["answer"] = "関連する可能性のある箇所は見つかりましたが、確度が十分ではありません。"
            data["followups"] = ["型番や接続機器、症状の詳細を教えてください。"]
        if not data.get("citations"):
            data["citations"] = [{"manual_id": d.metadata.get("source", "unknown").split("/")[-1], "page": int(d.metadata.get("page_start") or d.metadata.get("page", 0)), "chunk_id": d.metadata.get("chunk_id", "unknown")} for d in chosen_docs[:1]]

        return json.dumps(data, ensure_ascii=False, indent=2)

    except Exception as e:
        return json.dumps({"answer": f"GPT APIエラー: {str(e)}", "citations": [], "confidence": 0.0, "followups": ["時間をおいて再度お試しください。"]}, ensure_ascii=False, indent=2)


def generative_answer_streaming(
    query: str,
    retriever,
    parent_store: Dict[str, str] = None,
    k: int = 6
):
    pool_size = 50
    initial_candidates = retriever.invoke(query, k=pool_size)

    if not initial_candidates:
        yield json.dumps({
            "type": "complete",
            "data": {"answer": "マニュアルに該当する記載は見つかりませんでした。", "citations": [], "confidence": 0.0, "followups": []}
        }, ensure_ascii=False)
        return

    yield json.dumps({"type": "progress", "message": "検索結果を精査中..."}, ensure_ascii=False)

    docs_to_rerank = [doc.page_content for doc in initial_candidates]
    try:
        if not co:
            raise Exception("Cohere client not initialized.")
        rerank_response = co.rerank(
            model='rerank-multilingual-v3.0',
            query=query,
            documents=docs_to_rerank,
            top_n=25
        )
    except Exception as e:
        yield json.dumps({
            "type": "complete",
            "data": {"answer": f"Cohere Rerank APIエラー: {e}", "citations": [], "confidence": 0.0, "followups": ["APIキーを再確認してください。"]}
        }, ensure_ascii=False)
        return

    reranked = []
    reranked_scores = []
    for hit in rerank_response.results:
        reranked.append((initial_candidates[hit.index], hit.relevance_score))
        reranked_scores.append(hit.relevance_score)

    if not reranked:
        yield json.dumps({
            "type": "complete",
            "data": {"answer": "関連情報が見つかりませんでした。", "citations": [], "confidence": 0.0, "followups": []}
        }, ensure_ascii=False)
        return

    yield json.dumps({"type": "progress", "message": "回答を生成中..."}, ensure_ascii=False)

    conf0 = _calc_confidence(reranked_scores)

    if conf0 < 0.6:
        top_n_candidates = []
        seen_content = set()
        for doc, score in reranked:
            content = doc.page_content.strip()
            if len(content) > 30 and content not in seen_content:
                seen_content.add(content)
                top_n_candidates.append(doc)
            if len(top_n_candidates) >= 3:
                break

        if not top_n_candidates:
            yield json.dumps({
                "type": "complete",
                "data": {
                    "answer": "関連する可能性のある情報が見つかりましたが、質問の意図を特定できませんでした。もう少し具体的に質問していただけますか？",
                    "citations": [], "confidence": conf0, "followups": []
                }
            }, ensure_ascii=False)
            return

        context_parts = []
        for i, doc in enumerate(top_n_candidates):
            context_parts.append(f"参考情報{i+1} (P.{doc.metadata.get('page_start')}):\n{_compress(doc.page_content)}")
        context = "\n---\n".join(context_parts)

        clarification_prompt = (
            "あなたはユーザーの曖昧な質問の意図を特定する、優秀なアシスタントです。\n"
            f"ユーザーは「{query}」と質問しましたが、意図が曖昧です。\n"
            "こちらで関連しそうな以下の参考情報を見つけました。\n\n"
            f"### 参考情報\n{context}\n\n"
            "### あなたのタスク\n"
            "1. 上記の参考情報が、それぞれ「何について」書かれているかを簡潔に特定してください。\n"
            "2. それらのトピックを元に、ユーザーが本当に知りたいことを明確にするための、自然な**質問文**を作成してください。\n"
            "3. ユーザーが選択しやすいように、それぞれのトピックを**箇条書きの選択肢**として提示してください。\n"
            "4. 回答は、必ず以下のJSON形式で出力してください。\n\n"
            "```json\n"
            "{\n"
            '  "question": "（ここにユーザーへの自然な質問文を生成）",\n'
            '  "choices": [\n'
            '    { "page": （参考情報1のページ番号）, "summary": "（参考情報1の要約/選択肢）" },\n'
            '    { "page": （参考情報2のページ番号）, "summary": "（参考情報2の要約/選択肢）" },\n'
            '    { "page": （参考情報3のページ番号）, "summary": "（参考情報3の要約/選択肢）" }\n'
            '  ]\n'
            "}\n"
            "```"
        )

        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": clarification_prompt}],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            clarification_data = json.loads(response.choices[0].message.content)

            summary_answer = clarification_data.get("question", "関連する可能性のある、以下の項目が見つかりました。") + "\n\n"
            generated_followups = []

            for i, choice in enumerate(clarification_data.get("choices", [])):
                page = choice.get("page")
                summary = choice.get("summary")
                if page and summary:
                    summary_answer += f"**{i+1}. {summary}** (P.{page})\n"
                    generated_followups.append(f"「{summary}」について詳しく教えて")

            yield json.dumps({
                "type": "complete",
                "data": {
                    "answer": summary_answer.strip(),
                    "citations": [], "confidence": conf0,
                    "followups": generated_followups
                }
            }, ensure_ascii=False)
            return

        except Exception as e:
            print(f"Clarification generation failed: {e}")
            yield json.dumps({
                "type": "complete",
                "data": {
                    "answer": "関連情報が見つかりましたが、絞り込みに失敗しました。お手数ですが、より具体的なキーワードで再度ご質問ください。",
                    "citations": [], "confidence": conf0, "followups": []
                }
            }, ensure_ascii=False)
            return

    final_tuples = reranked
    top_5_sections = [doc.metadata.get("section_title") for doc, score in reranked[:5]]
    section_counts = Counter(s for s in top_5_sections if s and s != "概要")

    target_section = None
    if section_counts:
        most_common_section, count = section_counts.most_common(1)[0]
        if count >= 2:
            target_section = most_common_section

    if target_section:
        scoped_docs = _section_scope_docs(initial_candidates, target_section)
        if scoped_docs:
            scoped_docs_content = [doc.page_content for doc in scoped_docs]
            scoped_rerank_response = co.rerank(
                model='rerank-multilingual-v3.0',
                query=query,
                documents=scoped_docs_content,
                top_n=10
            )
            scoped_reranked = []
            for hit in scoped_rerank_response.results:
                scoped_reranked.append((scoped_docs[hit.index], hit.relevance_score))
            if scoped_reranked:
                final_tuples = scoped_reranked

    topn = min(8, len(final_tuples))
    chosen_docs, chosen_scores, context_parts = [], [], []
    seen_parent_ids = set()

    for i in range(topn):
        doc, score = final_tuples[i]
        page_num = int(doc.metadata.get("page_start") or doc.metadata.get("page", 0))
        parent_id = doc.metadata.get("parent_id")

        if parent_store and parent_id:
            if parent_id in seen_parent_ids:
                continue
            seen_parent_ids.add(parent_id)
            parent_content = parent_store.get(parent_id)

            if parent_content:
                chunk_id = f"p{page_num}_{parent_id}"
                doc.metadata["chunk_id"] = chunk_id
                context_parts.append(
                    f"参考情報{len(context_parts)+1} (p.{page_num}, id:{chunk_id}, section:'{doc.metadata.get('section_title', 'N/A')}'):\n"
                    f"{_compress(parent_content, max_chars=800)}\n"
                )
                chosen_docs.append(doc)
                chosen_scores.append(score)
            else:
                chunk_id = f"p{page_num}_{i}"
                doc.metadata["chunk_id"] = chunk_id
                context_parts.append(
                    f"参考情報{len(context_parts)+1} (p.{page_num}, id:{chunk_id}, section:'{doc.metadata.get('section_title', 'N/A')}'):\n"
                    f"{_compress(doc.page_content)}\n"
                )
                chosen_docs.append(doc)
                chosen_scores.append(score)
        else:
            chunk_id = f"p{page_num}_{i}"
            if chunk_id in {d.metadata.get("chunk_id") for d in chosen_docs}:
                continue
            doc.metadata["chunk_id"] = chunk_id
            context_parts.append(
                f"参考情報{len(context_parts)+1} (p.{page_num}, id:{chunk_id}, section:'{doc.metadata.get('section_title', 'N/A')}'):\n"
                f"{_compress(doc.page_content)}\n"
            )
            chosen_docs.append(doc)
            chosen_scores.append(score)

    context = "\n".join(context_parts)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    SYSTEM_PROMPT = (
        "あなたはユーザーを助ける、家電の取扱説明書に非常に詳しい専門家アシスタントです。\n"
        "あなたの仕事は、提供された参考情報だけを元に、ユーザーの質問に対する答えを統合し、要約して提示することです。\n\n"
        "### 厳守すべきルール\n"
        "1. **情報の統合**: 参考情報が断片的な場合、それらを組み合わせて一つの完全な回答を作成してください。\n"
        "2. **手順の再構築**: ユーザーが「方法」や「やり方」について尋ねている場合、必ず**改行を用いた番号付きリスト**で再構築してください。\n"
        "3. **事実厳守**: 参考情報に書かれていない憶測や一般的な知識で回答を補完してはいけません。\n"
        "4. **回答の原則**: まず、参考情報から質問に対する直接的で確信のある答えを探してください。\n"
        "   - **もし答えが見つかれば**、絶対に「XXページをご覧ください」とは答えず、その内容を直接要約・説明してください。（案内係からの脱却）\n"
        "   - **もし確信のある答えが見つからない場合**は、無理に答えず、『関連する情報が複数見つかりました。』といった短い応答を生成してください。そして、ユーザーが答えにたどり着くのを助ける、具体的で分かりやすいフォローアップの質問（followups）を3つ提案してください。（低信頼度時の逆質問）\n"
        "5. **JSON形式の徹底**: 出力は必ず指定されたJSONスキーマに従ってください。"
    )

    USER_PROMPT = (
        f"JSONスキーマ: {json.dumps(ANSWER_SCHEMA, ensure_ascii=False)}\n\n"
        f"参考情報:\n{context}\n\n"
        f"質問: {query}\n\n"
        "上記のルールとJSONスキーマに厳密に従って、日本語で回答のJSONを生成してください。"
    )

    try:
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=600,
            stream=True
        )

        json_buffer = ""
        for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                json_buffer += content
                yield json.dumps({"type": "chunk", "content": content}, ensure_ascii=False)

        data = json.loads(json_buffer)

        if "confidence" not in data or not isinstance(data.get("confidence"), (int, float)):
            data["confidence"] = _calc_confidence(chosen_scores)

        if data["confidence"] < 0.55 and not data.get("followups"):
            data["answer"] = "関連する可能性のある箇所は見つかりましたが、確度が十分ではありません。"
            data["followups"] = ["型番や接続機器、症状の詳細を教えてください。"]

        if not data.get("citations"):
            data["citations"] = [
                {
                    "manual_id": d.metadata.get("source", "unknown").split("/")[-1],
                    "page": int(d.metadata.get("page_start") or d.metadata.get("page", 0)),
                    "chunk_id": d.metadata.get("chunk_id", "unknown")
                }
                for d in chosen_docs[:1]
            ]

        yield json.dumps({"type": "complete", "data": data}, ensure_ascii=False)

    except Exception as e:
        yield json.dumps({
            "type": "complete",
            "data": {
                "answer": f"GPT APIエラー: {str(e)}",
                "citations": [], "confidence": 0.0,
                "followups": ["時間をおいて再度お試しください。"]
            }
        }, ensure_ascii=False)
