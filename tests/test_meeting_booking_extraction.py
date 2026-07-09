import importlib
import sys
import types
from pathlib import Path


def load_chatbot_graph_with_stubs():
    backend_dir = Path(__file__).resolve().parents[1] / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    stubbed_modules = [
        "database",
        "rag",
        "rag.retriever",
        "llm_client",
        "langsmith",
        "chatbot_graph",
    ]
    original_modules = {name: sys.modules.get(name) for name in stubbed_modules}

    database_stub = types.ModuleType("database")
    database_stub.save_chat_to_mongo = lambda *args, **kwargs: None
    database_stub.save_collection_data = lambda *args, **kwargs: None
    database_stub.get_booked_meeting_slots = lambda *args, **kwargs: set()
    database_stub.get_chatbot_settings = lambda: {
        "company_name": "CodeQlik",
        "company_description": "Software services",
        "fallback_message": "Fallback",
    }
    sys.modules["database"] = database_stub

    rag_pkg = types.ModuleType("rag")
    rag_pkg.__path__ = []
    retriever_stub = types.ModuleType("rag.retriever")
    retriever_stub.retrieve_company_context_details = lambda *args, **kwargs: {
        "context_text": "",
        "confidence": 0.0,
        "sources": [],
    }
    sys.modules["rag"] = rag_pkg
    sys.modules["rag.retriever"] = retriever_stub

    class DummyContextVar:
        def set(self, value):
            return value

    class DummyLLM:
        def __init__(self, *args, **kwargs):
            pass

        def bind(self, *args, **kwargs):
            return self

        def invoke(self, *args, **kwargs):
            return types.SimpleNamespace(content="{}")

    llm_stub = types.ModuleType("llm_client")
    llm_stub.FailoverChatGroq = DummyLLM
    llm_stub.thread_id_var = DummyContextVar()
    llm_stub.node_name_var = DummyContextVar()
    sys.modules["llm_client"] = llm_stub

    langsmith_stub = types.ModuleType("langsmith")
    langsmith_stub.traceable = lambda fn=None, **kwargs: fn if fn else (lambda inner: inner)
    sys.modules["langsmith"] = langsmith_stub

    sys.modules.pop("chatbot_graph", None)
    module = importlib.import_module("chatbot_graph")

    def restore_modules():
        sys.modules.pop("chatbot_graph", None)
        for name, original in original_modules.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original

    return module, restore_modules


def test_meeting_booking_trigger_does_not_become_name():
    cg, restore_modules = load_chatbot_graph_with_stubs()
    try:
        for message in ["book a meeting", "book a meeting tomorrow"]:
            data = cg.extract_collection_data(
                {"messages": [cg.HumanMessage(content=message)], "profile": {}},
                "meeting_booking",
            )

            assert "name" not in data["profile"]
            assert data["pending_field"] == "name"
            assert data["qualified"] is False
            assert data["is_field_answer"] is False
    finally:
        restore_modules()


def test_meeting_booking_collects_one_field_per_turn_without_repeating():
    cg, restore_modules = load_chatbot_graph_with_stubs()
    try:
        profile = {}

        turns = [
            ("Anurag", "email"),
            ("anurag@example.com", "phone"),
            ("9876543210", "company"),
            ("Acme Inc", "work_details"),
            ("CRM automation project", "meeting_mode"),
            ("Google Meet", "date"),
            ("tomorrow", "time_slot"),
            ("2", None),
        ]

        for message, next_pending in turns:
            data = cg.extract_collection_data(
                {"messages": [cg.HumanMessage(content=message)], "profile": profile},
                "meeting_booking",
            )
            profile = data["profile"]
            assert data["pending_field"] == next_pending

        assert profile["name"] == "Anurag"
        assert profile["email"] == "anurag@example.com"
        assert profile["phone"] == "9876543210"
        assert profile["company"] == "Acme Inc"
        assert profile["work_details"] == "CRM automation project"
        assert profile["meeting_mode"] == "google_meet"
        assert profile["date"] == "tomorrow"
        assert profile["time_slot"] == "02:00 PM"
        assert data["qualified"] is True
    finally:
        restore_modules()


def test_meeting_booking_extracts_labeled_all_in_one_message():
    cg, restore_modules = load_chatbot_graph_with_stubs()
    try:
        message = (
            "name: Priya, email: priya@example.com, phone: 9876543210, "
            "company: RetailX, topic: ecommerce website, mode: phone call, "
            "date: 12 July, slot: 3"
        )

        data = cg.extract_collection_data(
            {"messages": [cg.HumanMessage(content=message)], "profile": {}},
            "meeting_booking",
        )
        profile = data["profile"]

        assert profile["name"] == "Priya"
        assert profile["email"] == "priya@example.com"
        assert profile["phone"] == "9876543210"
        assert profile["company"] == "RetailX"
        assert profile["work_details"] == "ecommerce website"
        assert profile["meeting_mode"] == "phone_call"
        assert profile["date"] == "12 July"
        assert profile["time_slot"] == "04:00 PM"
        assert data["qualified"] is True
    finally:
        restore_modules()
