# web/management/commands/create_index.py
from django.core.management.base import BaseCommand, CommandError
from pathlib import Path
from core.rag_chain import index_pdf # 修正後のrag_chainからインポート

class Command(BaseCommand):
    help = '指定されたPDFファイルからFAISSインデックスを作成します。'

    def add_arguments(self, parser):
        parser.add_argument('pdf_path', type=str, help='インデックスを作成するPDFファイルのパス')
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='作成するインデックスの名前'
        )

    def handle(self, *args, **options):
        pdf_path = Path(options['pdf_path'])
        index_name = options['name']

        if not pdf_path.exists() or not pdf_path.is_file():
            raise CommandError(f"エラー: 指定されたPDFファイルが見つかりません: {pdf_path}")

        self.stdout.write(self.style.SUCCESS(f"'{pdf_path}' のインデックス作成を開始します..."))
        self.stdout.write(self.style.SUCCESS(f"インデックス名: '{index_name}'"))

        try:
            # rag_chain経由でインデックス作成処理を呼び出す
            index_pdf(pdf_path=str(pdf_path), index_name=index_name)
            self.stdout.write(self.style.SUCCESS(f"\nインデックスの作成が完了しました！"))
            self.stdout.write(self.style.SUCCESS(f"保存先: indices/{index_name}"))

        except Exception as e:
            raise CommandError(f"インデックス作成中にエラーが発生しました: {e}")