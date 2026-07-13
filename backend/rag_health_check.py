# -*- coding: utf-8 -*-
"""
RAG Health Check Script — run with:
  cd backend && python rag_health_check.py

Tests:
  1. Module imports
  2. MongoDB connection & collections
  3. Embeddings model
  4. Retrieval with 3 test queries
  5. Chunking pipeline sanity
  6. chatbot_graph.py RAG wiring
"""

import sys
import os
import traceback

# Force UTF-8 output on Windows so special characters print fine
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

PASS = "  [PASS]"
FAIL = "  [FAIL]"
INFO = "  [INFO]"

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print("=" * 60)

# ── 1. Imports ───────────────────────────────────────────────────
section("1. Module Imports")

try:
    from config import MONGO_URI, MONGO_DB
    print(PASS, "config.py loaded. DB:", MONGO_DB)
except Exception as e:
    print(FAIL, "config.py:", e); sys.exit(1)

try:
    from database import knowledge_sources_collection, knowledge_chunks_collection
    print(PASS, "database.py imported")
except Exception as e:
    print(FAIL, "database.py:", e); sys.exit(1)

try:
    from rag.embeddings import embeddings_model
    print(PASS, "embeddings_model loaded:", embeddings_model.model_name)
except Exception as e:
    print(FAIL, "rag.embeddings:", e); sys.exit(1)

try:
    from rag.retriever import retrieve_company_context_details
    print(PASS, "rag.retriever imported")
except Exception as e:
    print(FAIL, "rag.retriever:", e); sys.exit(1)

try:
    from rag.source_manager import process_and_chunk_source
    print(PASS, "rag.source_manager imported")
except Exception as e:
    print(FAIL, "rag.source_manager:", e); sys.exit(1)

try:
    from rag.chunker import chunk_document
    from rag.records import RawRecord, serialize_records
    print(PASS, "rag.chunker + rag.records imported")
except Exception as e:
    print(FAIL, "rag.chunker/records:", e); sys.exit(1)

# ── 2. MongoDB Collections ───────────────────────────────────────
section("2. MongoDB Collections")

try:
    source_count = knowledge_sources_collection.count_documents({})
    active_count = knowledge_sources_collection.count_documents({"enabled": True})
    chunk_count  = knowledge_chunks_collection.count_documents({})
    print(PASS, f"knowledge_sources : {source_count} total, {active_count} active")
    print(PASS, f"knowledge_chunks  : {chunk_count} total")
    if source_count == 0:
        print(INFO, "WARNING: No knowledge sources. Upload docs via admin panel first.")
    if chunk_count == 0:
        print(INFO, "WARNING: No chunks found. Re-index sources via admin panel.")
except Exception as e:
    print(FAIL, "MongoDB query failed:", e)
    traceback.print_exc()

# Check and create performance indexes
try:
    indexes = list(knowledge_chunks_collection.list_indexes())
    index_keys = [list(i.get("key", {}).keys()) for i in indexes]
    print(INFO, "Existing chunk indexes:", index_keys)

    existing_fields = set(f for keys in index_keys for f in keys)
    if "source_id" not in existing_fields:
        print(INFO, "Creating index on source_id + status (performance fix)...")
        knowledge_chunks_collection.create_index(
            [("source_id", 1), ("status", 1)],
            background=True,
            name="source_id_status_idx"
        )
        print(PASS, "Index created: source_id + status")
    else:
        print(PASS, "source_id index already exists")
except Exception as e:
    print(FAIL, "Index operation failed:", e)

# ── 3. Embeddings Model ──────────────────────────────────────────
section("3. Embeddings Model")

try:
    vec = embeddings_model.embed_query("test query for embedding")
    print(PASS, f"embed_query returned vector of dim={len(vec)}")
    batch = embeddings_model.embed_documents(["hello world", "code and software"])
    print(PASS, f"embed_documents returned {len(batch)} vectors of dim={len(batch[0])}")
except Exception as e:
    print(FAIL, "Embedding error:", e)
    traceback.print_exc()

# ── 4. RAG Retrieval Tests ───────────────────────────────────────
section("4. RAG Retrieval Pipeline")

TEST_QUERIES = [
    ("General services", "what services does codeqlik provide"),
    ("Pricing query",    "how much does a website cost"),
    ("Contact info",     "what is your office address or phone number"),
]

for label, query in TEST_QUERIES:
    try:
        result = retrieve_company_context_details(query)
        conf   = round(float(result.get("confidence", 0)), 4)
        ans    = result.get("answerable", False)
        reason = result.get("reason", "unknown")
        srcs   = result.get("sources", [])
        ctx_snippet = (result.get("context_text") or "")[:100].replace("\n", " ")
        status = PASS if conf >= 0.30 else (INFO if conf >= 0.10 else FAIL)
        print(f"\n{status} [{label}]")
        print(f"         confidence={conf}, answerable={ans}, reason={reason}")
        print(f"         sources={srcs}")
        print(f"         context preview: {ctx_snippet}...")
    except Exception as e:
        print(FAIL, f"[{label}] retrieval error:", e)
        traceback.print_exc()

# ── 5. Chunking Sanity ───────────────────────────────────────────
section("5. Chunking Pipeline Sanity")

try:
    sample_record = RawRecord(
        title="CodeQlik Services Overview",
        text=(
            "CodeQlik is a software development company specializing in web apps, "
            "mobile apps, ERP, CRM, AI chatbots, and e-commerce solutions. "
            "We offer competitive pricing and dedicated support. "
            "Contact: info@codeqlik.com | +91-8949687368"
        ),
        source_type="manual",
    )
    chunks = chunk_document(
        "manual",
        serialize_records([sample_record]),
        base_metadata={
            "source_name": "Test Source",
            "title": "Test Source",
            "category": "Company Information",
        },
    )
    print(PASS, f"chunk_document produced {len(chunks)} chunks")
    if chunks:
        c = chunks[0]
        print(INFO, f"  First chunk keys     : {list(c.keys())}")
        print(INFO, f"  Has embedding field  : {'embedding' in c}")
        has_text = "retrieval_text" in c or "chunk_text" in c
        print(INFO, f"  Has retrieval_text   : {has_text}")
        print(INFO, f"  Title                : {c.get('title', '')[:60]}")
except Exception as e:
    print(FAIL, "Chunking error:", e)
    traceback.print_exc()

# ── 6. chatbot_graph.py RAG Wiring ──────────────────────────────
section("6. chatbot_graph.py RAG Wiring")

try:
    import ast, pathlib
    src = pathlib.Path(__file__).parent / "chatbot_graph.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    rag_imports = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("rag")
    ]
    print(PASS, f"chatbot_graph.py has {len(rag_imports)} RAG import(s):")
    for imp in rag_imports:
        names = [alias.name for alias in imp.names]
        print(INFO, f"  from {imp.module} import {', '.join(names)}")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    rag_calls = set()
    for call in calls:
        if isinstance(call.func, ast.Name) and "retrieve" in call.func.id:
            rag_calls.add(call.func.id)
        elif isinstance(call.func, ast.Attribute) and "retrieve" in call.func.attr:
            rag_calls.add(call.func.attr)
    print(PASS, f"RAG retrieve calls found: {rag_calls}")
except Exception as e:
    print(FAIL, "chatbot_graph.py analysis error:", e)

# ── Summary ──────────────────────────────────────────────────────
section("Health Check Complete")
print("""
Key thresholds:
  confidence >= 0.30  -> Good retrieval
  answerable = True   -> Context usable by LLM
  active_count > 0    -> Knowledge sources enabled
  chunk_count  > 0    -> Documents indexed

If confidence is low:
  - Upload more content via Admin > Knowledge Sources
  - Click RE-INDEX after editing a source
  - Check RAG_DEBUG=true in .env for verbose logs
  - Adjust RAG_MIN_HYBRID_SCORE env var (default 0.30)
""")
