from chatbot_graph import chatbot, HumanMessage
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

config = {"configurable": {"thread_id": "test_thread_unrelated_102"}}

def run_turn(text):
    print(f"\n=== INPUT: {text} ===")
    state = chatbot.invoke({"messages": [HumanMessage(content=text)]}, config=config)
    
    debug_state = {
        "intent": state.get("intent"),
        "primary_intent": state.get("primary_intent"),
        "active_collection": state.get("active_collection"),
        "pending_field": state.get("pending_field"),
        "profile": state.get("profile"),
        "missing_fields": state.get("missing_fields"),
        "reply": state["messages"][-1].content
    }
    print(json.dumps(debug_state, indent=2)) 

run_turn("i want to build a website")
run_turn("Anurag")
run_turn("how to make pasta at home?")
run_turn("my phone number is 9876543210")
run_turn("what is the weather today?")
