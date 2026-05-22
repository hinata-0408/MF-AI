import json
import types
import pytest

from core.answer import generative_answer

class DummyDoc:
    def __init__(self, text, meta):
        self.page_content = text
        self.metadata = meta

class DummyRetriever:
    def __init__(self, docs):
        self.docs = docs
    def invoke(self, query, k=10):
        return self.docs[:k]

@pytest.fixture
def docs_ok():
    # p.8 相当の良質チャンク3本 + ノイズ
    return [
        DummyDoc("紙パック交換手順: ふたを開ける。… 指で押して…", {"page": 8, "manual_id": "1", "chunk_id":"cid:12498"}),
        DummyDoc("紙パックをケースにセット…", {"page": 8, "manual_id": "1", "chunk_id":"cid:12499"}),
        DummyDoc("交換後はケースを戻す…", {"page": 8, "manual_id": "1", "chunk_id":"cid:12500"}),
        DummyDoc("（ノイズ）", {"page": 2, "manual_id": "1", "chunk_id":"noise"}),
    ]

def test_json_shape_monkeypatched(monkeypatch, docs_ok):
    # CrossEncoder.predict を固定値でモック（安定化）
    import core.answer as ans

    def fake_get_reranker():
        class R:
            def predict(self, pairs):
                # 質の高い最初の3件を高得点、他は低め
                return [0.95, 0.93, 0.91] + [0.2]*(len(pairs)-3)
        return R()
    monkeypatch.setattr(ans, "_get_reranker", fake_get_reranker)

    # OpenAI 応答も固定（Structured JSONを直接返す）
    class FakeChoice: 
        def __init__(self, content): self.message = types.SimpleNamespace(content=content)
    class FakeResp:  
        def __init__(self, content): self.choices = [FakeChoice(content)]
    class FakeClient:
        def __init__(self, *a, **kw): pass
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    payload = {
                        "answer": "1. ふたを開ける…",
                        "citations": [
                            {"manual_id":"1","page":8,"chunk_id":"cid:12498"},
                            {"manual_id":"1","page":8,"chunk_id":"cid:12499"},
                        ],
                        "confidence": 0.88,
                        "followups": []
                    }
                    return FakeResp(json.dumps(payload, ensure_ascii=False))
    monkeypatch.setattr(ans, "OpenAI", FakeClient)

    out = generative_answer("紙パック交換", DummyRetriever(docs_ok), k=3)
    data = json.loads(out)

    # 1) JSON構造
    assert set(["answer","citations","confidence"]).issubset(data.keys())
    assert isinstance(data["answer"], str)
    assert isinstance(data["citations"], list)
    assert isinstance(data["confidence"], (int, float))
    assert 0.0 <= data["confidence"] <= 1.0

    # 2) 出典妥当性
    for c in data["citations"]:
        assert c["page"] == 8
        assert c["manual_id"] == "1"
        assert c["chunk_id"].startswith("cid:")

def test_empty_index(monkeypatch):
    # 空ヒット時のフォールバック確認
    import core.answer as ans
    # reranker/LLMは呼ばれない設計なのでモック不要
    out = generative_answer("紙パック交換", retriever=type("R",(object,),{"invoke":lambda self,q,k: []})(), k=3)
    data = json.loads(out)
    assert data["citations"] == []
    assert data["confidence"] == 0.0
    assert "見つかりません" in data["answer"]
    assert len(data.get("followups",[])) >= 1
