import unittest
import os
import sys
from bson import ObjectId

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from database import chunks_collection, sources_collection
from rag.retriever import (
    retrieve_company_context_details,
    detect_query_topic,
    detect_query_service
)

class TestMetadataRAG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Backup and disable all currently enabled sources to isolate tests
        cls.enabled_sources = [str(s["_id"]) for s in sources_collection.find({"enabled": True})]
        if cls.enabled_sources:
            sources_collection.update_many(
                {"_id": {"$in": [ObjectId(sid) for sid in cls.enabled_sources]}},
                {"$set": {"enabled": False}}
            )

        # Create a dummy active source
        cls.source_doc = {
            "title": "Metadata RAG Test Source",
            "type": "manual",
            "category": "Company Information",
            "content": "Test content",
            "enabled": True
        }
        res = sources_collection.insert_one(cls.source_doc)
        cls.source_id = str(res.inserted_id)

        # Create dummy chunks
        cls.chunks = [
            {
                "source_id": cls.source_id,
                "title": "Metadata RAG Test Source",
                "category": "Company Information",
                "source_type": "manual",
                "chunk_index": 0,
                "chunk_text": "We offer custom python software development and fastapi web services.",
                "keywords": ["python", "software", "fastapi"],
                "summary": "python software",
                "metadata": {},
                "status": "active",
                "intent_scope": "client",
                "topic": "services",
                "service": "software",
                "priority": 1,
                "tags": []
            },
            {
                "source_id": cls.source_id,
                "title": "Metadata RAG Test Source",
                "category": "Company Information",
                "source_type": "manual",
                "chunk_index": 1,
                "chunk_text": "Our tech stack includes python javascript react node and langgraph technologies.",
                "keywords": ["tech", "languages", "react"],
                "summary": "languages",
                "metadata": {},
                "status": "active",
                "intent_scope": "all",
                "topic": "technologies",
                "service": "general",
                "priority": 1,
                "tags": []
            },
            {
                "source_id": cls.source_id,
                "title": "Metadata RAG Test Source",
                "category": "Company Information",
                "source_type": "manual",
                "chunk_index": 2,
                "chunk_text": "Contact us at info@codeqlik.com or visit our office address in Jaipur Rajasthan.",
                "keywords": ["contact", "office", "email"],
                "summary": "contact",
                "metadata": {},
                "status": "active",
                "intent_scope": "support",
                "topic": "contact",
                "service": "general",
                "priority": 1,
                "tags": []
            },
            {
                "source_id": cls.source_id,
                "title": "Metadata RAG Test Source",
                "category": "Company Information",
                "source_type": "manual",
                "chunk_index": 3,
                "chunk_text": "We build custom ecommerce shopify apps and online shopping carts.",
                "keywords": ["ecommerce", "shopify", "cart"],
                "summary": "ecommerce",
                "metadata": {},
                "status": "active",
                "intent_scope": "client",
                "topic": "services",
                "service": "ecommerce",
                "priority": 1,
                "tags": []
            }
        ]
        chunks_collection.insert_many(cls.chunks)

    @classmethod
    def tearDownClass(cls):
        # Clean up
        sources_collection.delete_one({"_id": ObjectId(cls.source_id)})
        chunks_collection.delete_many({"source_id": cls.source_id})

        # Restore enabled sources
        if cls.enabled_sources:
            sources_collection.update_many(
                {"_id": {"$in": [ObjectId(sid) for sid in cls.enabled_sources]}},
                {"$set": {"enabled": True}}
            )

    def setUp(self):
        if "USE_METADATA_RAG" in os.environ:
            del os.environ["USE_METADATA_RAG"]

    def test_query_detection_rules(self):
        # topic technologies
        topic, confident = detect_query_topic("what technologies do you use")
        self.assertEqual(topic, "technologies")
        self.assertTrue(confident)

        # topic services
        topic, confident = detect_query_topic("what services do you provide")
        self.assertEqual(topic, "services")
        self.assertTrue(confident)

        # topic contact
        topic, confident = detect_query_topic("how can I contact you, office address")
        self.assertEqual(topic, "contact")
        self.assertTrue(confident)

        # service ecommerce
        service, confident = detect_query_service("build an ecommerce app")
        self.assertEqual(service, "ecommerce")
        self.assertTrue(confident)

    def test_use_metadata_rag_disabled(self):
        import rag.retriever
        rag.retriever.USE_METADATA_RAG = False

        details = retrieve_company_context_details("contact address", intent="customer_support")
        self.assertIn("info@codeqlik.com", details["context_text"])

    def test_use_metadata_rag_enabled_filtering(self):
        import rag.retriever
        rag.retriever.USE_METADATA_RAG = True

        # For a technology question, it should filter to technologies topic
        details = retrieve_company_context_details("what technologies do you use", intent="general_chat")
        self.assertIn("tech stack", details["context_text"])
        self.assertNotIn("ecommerce", details["context_text"])
        self.assertNotIn("info@codeqlik.com", details["context_text"])

        # For an ecommerce query, it should filter to ecommerce service
        details = retrieve_company_context_details("build an ecommerce app", intent="client_lead")
        self.assertIn("ecommerce", details["context_text"])
        self.assertNotIn("tech stack", details["context_text"])
        self.assertNotIn("info@codeqlik.com", details["context_text"])

    def test_fallback_logic(self):
        import rag.retriever
        rag.retriever.USE_METADATA_RAG = True

        # Query that matches keywords but has no matching metadata filter (e.g. searching for 'python' with intent='hiring')
        # Since 'python' matches index 0 and 1, but intent_scope is hiring (which has no matches under levels 0, 1, 2)
        # it should progressively fall back and retrieve chunks using level 3 (old retrieval fallback)
        details = retrieve_company_context_details("python developer", intent="hiring_support")
        self.assertIn("python", details["context_text"])

if __name__ == "__main__":
    unittest.main()
