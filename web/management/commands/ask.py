# web/management/commands/ask.py
from django.core.management.base import BaseCommand, CommandError
from dotenv import load_dotenv
from core.rag_chain import answer_query
import json
import textwrap

def _render_cli_answer(raw: str) -> str:
    """
    generative_answer の戻り値（JSON文字列 or 旧プレーン文字列）を
    人間向けの整形テキストに変換する。JSONでなければそのまま返す。
    """
    try:
        data = json.loads(raw)
    except Exception:
        return raw  # 後方互換：プレーンなら素のまま

    answer = (data.get("answer") or "").strip()
    citations = data.get("citations") or []
    confidence = data.get("confidence")
    followups = data.get("followups") or []

    lines = []
    lines.append("— 回答 —")
    lines.append(textwrap.dedent(answer).strip())

    if citations:
        lines.append("\n— 出典 —")
        for c in citations:
            mid = c.get("manual_id", "unknown")
            page = c.get("page", "?")
            cid = c.get("chunk_id", None)
            # chunk_id はデバッグ用途。不要なら下の行の括弧を外してOK
            if cid:
                lines.append(f"- {mid} p.{page}（{cid}）")
            else:
                lines.append(f"- {mid} p.{page}")

    if isinstance(confidence, (int, float)):
        pct = int(round(float(confidence) * 100))
        lines.append(f"\n— 信頼度 —\n{pct}%")

    if followups:
        lines.append("\n— 追加で教えてほしいこと —")
        for f in followups:
            lines.append(f"- {f}")

    return "\n".join(lines)


class Command(BaseCommand):
    help = '指定されたインデックスに対して質問し、AIからの回答を表示します。'

    def add_arguments(self, parser):
        parser.add_argument('query', type=str, help='AIへの質問内容')
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='使用するインデックスの名前'
        )
        parser.add_argument(
            '--k',
            type=int,
            default=6,
            help='検索するチャンクの数'
        )
        # 必要なら raw JSON で見たいとき用：
        parser.add_argument(
            '--json',
            action='store_true',
            help='生成結果をJSONのまま出力する'
        )

    def handle(self, *args, **options):
        load_dotenv()
        query = options['query']
        index_name = options['name']
        k = options['k']
        as_json = options['json']

        self.stdout.write(self.style.SUCCESS(f"質問: '{query}'"))
        self.stdout.write(self.style.SUCCESS(f"インデックス '{index_name}' を使用して回答を生成します..."))

        try:
            # rag_chain経由で回答生成処理を呼び出す
            answer = answer_query(query=query, index_name=index_name, k=k)

            self.stdout.write(self.style.SUCCESS("\n--- 回答 ---"))
            if as_json:
                # そのままJSON出力（機械可読/デバッグ用）
                self.stdout.write(answer)
            else:
                # 人間向け整形
                pretty = _render_cli_answer(answer)
                self.stdout.write(pretty)
            self.stdout.write(self.style.SUCCESS("------------"))

        except FileNotFoundError as e:
            raise CommandError(f"エラー: {e}")
        except Exception as e:
            raise CommandError(f"回答生成中にエラーが発生しました: {e}")
