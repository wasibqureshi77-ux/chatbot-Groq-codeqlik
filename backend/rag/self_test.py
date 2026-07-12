"""Run with: python -m rag.self_test

This test does not connect to MongoDB or load an embedding model. It validates the
all-format loader/chunker contract that previously caused JSON/CSV/XLSX corruption.
"""
from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from rag.chunker import chunk_document
from rag.loader import load_any_file


def _chunks(path: Path):
    document = load_any_file(str(path))
    assert not document.metadata.get("load_error"), document.metadata.get("load_error")
    return chunk_document(document.metadata["source_type"], document.content, {"source_name": path.name})


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)

        json_path = root / "kb.json"
        json_path.write_text(
            json.dumps({
                "metadata": {"company": "Example"},
                "entries": [
                    {
                        "id": "service-1",
                        "title": "Website Development",
                        "content": "The company builds responsive websites.",
                        "sample_questions": ["Do you build websites?"],
                        "keywords": ["website"],
                    },
                    {
                        "id": "count-policy",
                        "title": "Project count",
                        "content": "The verified total project count is unavailable.",
                        "answer_mode": "verified_information_unavailable",
                        "verification_status": "conflicting_source_claims",
                    },
                ],
            }),
            encoding="utf-8",
        )
        json_chunks = _chunks(json_path)
        assert len(json_chunks) == 2
        assert all("entries[" not in chunk["content"] for chunk in json_chunks)
        assert json_chunks[1]["answer_mode"] == "verified_information_unavailable"

        csv_path = root / "records.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["id", "name", "service", "password"])
            writer.writerow([1, "Anurag", "Website Development", "do-not-index"])
            writer.writerow([2, "Ravi", "Mobile App", "do-not-index"])
        csv_chunks = _chunks(csv_path)
        assert len(csv_chunks) == 2
        assert all("password" not in chunk["content"].lower() for chunk in csv_chunks)
        assert "Website Development" in csv_chunks[0]["content"]

        markdown_path = root / "company.md"
        markdown_path.write_text(
            "# Services\n## Website Development\nWe build responsive websites.\n"
            "## Mobile Apps\nWe build Android and iOS applications.",
            encoding="utf-8",
        )
        markdown_chunks = _chunks(markdown_path)
        assert len(markdown_chunks) == 2
        assert markdown_chunks[0]["title"] == "Services > Website Development"

        text_path = root / "company.txt"
        text_path.write_text(
            "Services\n\nWe build websites and mobile applications.\n\n"
            "Pricing\n\nPricing depends on project scope.",
            encoding="utf-8",
        )
        text_chunks = _chunks(text_path)
        assert len(text_chunks) == 2

    print("RAG all-format ingestion self-test: PASS")


if __name__ == "__main__":
    main()
