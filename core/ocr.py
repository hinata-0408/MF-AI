import os
import re
from typing import List
from google.cloud import vision, storage
from .schema import Chunk
from .utils import normalize_text

GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

def ocr_pdf_with_google(pdf_path: str) -> List[Chunk]:
    chunks: List[Chunk] = []

    if not GCS_BUCKET_NAME:
        print("ERROR: GCS_BUCKET_NAME is not set.")
        return []

    try:
        storage_client = storage.Client()
        client = vision.ImageAnnotatorClient()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)

        file_name = os.path.basename(pdf_path)
        if not file_name.lower().endswith('.pdf'):
            file_name = file_name + '.pdf'
        blob = bucket.blob(file_name)
        blob.upload_from_filename(pdf_path)
        gcs_source_uri = f"gs://{GCS_BUCKET_NAME}/{file_name}"

        mime_type = "application/pdf"
        gcs_source = vision.GcsSource(uri=gcs_source_uri)
        input_config = vision.InputConfig(gcs_source=gcs_source, mime_type=mime_type)

        gcs_destination_uri = f"gs://{GCS_BUCKET_NAME}/ocr_results/{file_name}-"
        gcs_destination = vision.GcsDestination(uri=gcs_destination_uri)
        output_config = vision.OutputConfig(gcs_destination=gcs_destination, batch_size=1)

        features = [vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)]
        request = vision.AsyncAnnotateFileRequest(
            features=features, input_config=input_config, output_config=output_config
        )

        print("Waiting for Google Cloud Vision OCR to complete...")
        operation = client.async_batch_annotate_files(requests=[request])
        operation.result(timeout=300)

        output_prefix = gcs_destination_uri.replace(f"gs://{GCS_BUCKET_NAME}/", "")
        full_text = ""
        blobs_to_delete = [blob]

        result_blobs = storage_client.list_blobs(GCS_BUCKET_NAME, prefix=output_prefix)
        for result_blob in result_blobs:
            if "output-" in result_blob.name and ".json" in result_blob.name:
                json_string = result_blob.download_as_string()
                response = vision.AnnotateFileResponse.from_json(json_string)
                for page_response in response.responses:
                    full_text += page_response.full_text_annotation.text + "\n\n"
                blobs_to_delete.append(result_blob)

        for b in blobs_to_delete:
            b.delete()

        paragraphs = re.split(r'\n\s*\n', full_text)
        for i, para in enumerate(paragraphs):
            para = para.strip().replace("\n", " ")
            if len(para) > 15:
                meta = {
                    "source": pdf_path, "page_start": 0, "page_end": 0,
                    "element_type": "paragraph_ocr", "lang": "ja",
                    "extractor": "ocr-google-vision"
                }
                chunks.append(Chunk(content=normalize_text(para), metadata=meta))

        print(f"OCR complete. {len(chunks)} chunks extracted.")
        return chunks

    except Exception as e:
        print(f"Google Cloud Vision OCR failed: {e}")
        return []
