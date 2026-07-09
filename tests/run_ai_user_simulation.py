import sys
import os
import json
import time
import argparse
import requests
import uuid
from pathlib import Path

# Add backend directory to sys.path to access llm_client
backend_path = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_path))

from llm_client import FailoverChatGroq
from langchain_core.messages import HumanMessage


def get_llm(temperature=0.7):
    """
    Instantiate the failover ChatGroq client.
    """
    return FailoverChatGroq(
        model="llama-3.1-8b-instant",
        temperature=temperature,
    )


def safe_json_loads(text: str, fallback: dict) -> dict:
    import re
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return fallback
    return fallback


def generate_user_message(llm, scenario, history, latest_bot_reply, pending_field, active_collection):
    """
    Asks the LLM user simulator to generate the next reply.
    """
    formatted_history = ""
    for turn in history:
        formatted_history += f"User: {turn['user']}\n"
        if turn.get('bot'):
            formatted_history += f"Bot: {turn['bot']}\n"

    system_prompt = (
        "You are simulating a human user interacting with an AI support/sales chatbot for CodeQlik.\n"
        "Your details are as follows:\n"
        f"Persona: {scenario.get('user_persona', scenario.get('expected_bot_style', 'A normal user'))}\n"
        f"Goal: {scenario.get('user_goal', scenario.get('name', 'Complete the scenario goal'))}\n"
        f"Profile/Details to share: {json.dumps(scenario.get('user_profile', {}), indent=2)}\n"
        f"Allowed Questions/Interrupts: {json.dumps(scenario.get('allowed_interruptions', []), indent=2)}\n\n"
                "Rules:\n"
        "1. Stay in character. Keep replies short, natural, and human-like.\n"
        "2. Maximum 1 sentence per reply. Maximum 20 words.\n"
        "3. Do NOT explain your full profile unless the bot asks.\n"
        "4. Share only the exact field requested by pending_field when possible.\n"
        "5. Ask at most one interruption question, and keep it under 15 words.\n"
        "6. Do NOT say you are an AI, test, simulation, or language model.\n"
        "7. If profile value is 'skip', refuse briefly like: I prefer not to share that.\n"
        "8. Output ONLY the raw user message. No labels, markdown, or quotes."
    )

    user_input = (
        f"Conversation history:\n{formatted_history}\n"
        f"Latest bot reply: {latest_bot_reply}\n"
        f"Bot pending_field: {pending_field}\n"
        f"Bot active_collection: {active_collection}\n\n"
        "Generate your next message now:"
    )

    try:
        response = llm.invoke([
            HumanMessage(content=f"{system_prompt}\n\n{user_input}")
        ])
        return response.content.strip().strip('"')
    except Exception as e:
        print(f"Error calling LLM for user simulation: {e}")
        return "Hi"


def evaluate_conversation(llm, scenario, history, final_state):
    """
    Uses the LLM to evaluate the conversation against success criteria.
    """
    formatted_conv = ""
    for idx, turn in enumerate(history, 1):
        formatted_conv += f"Turn {idx}:\nUser: {turn['user']}\nBot: {turn['bot']}\n"

    prompt = (
        "You are an expert AI evaluator assessing a chatbot's conversation with a simulated user.\n"
        "Below are the details of the test scenario and the conversation transcript.\n\n"
        f"Scenario ID: {scenario['id']}\n"
        f"Scenario Name: {scenario['name']}\n"
        f"Expected Profile: {json.dumps(scenario.get('user_profile', {}), indent=2)}\n"
        f"Success Criteria: {json.dumps(scenario['success_criteria'], indent=2)}\n\n"
        f"Conversation Transcript:\n{formatted_conv}\n"
        f"Final Bot State:\n{json.dumps(final_state, indent=2)}\n\n"
        "Evaluate the conversation and answer the following questions in a JSON object:\n"
        "1. qualified_status_correct: Was the final qualified status correct according to success criteria?\n"
        "2. profile_correctness_correct: Did the bot correctly save expected profile values and NOT save any "
        "incorrect/refused values? (Note: if the user explicitly refused/skipped a field, the bot should NOT have saved a valid value for it)\n"
        "3. answered_user_questions: Did the bot successfully answer any company-related questions the user asked, "
        "rather than ignoring them or just repeating the field prompt?\n"
        "4. refused_unrelated_topics: Did the bot correctly refuse/redirect unrelated queries (like travel tips/Paris vacation) "
        "5. short_reply_quality: Did the bot keep replies concise, usually under the scenario's max_bot_words_per_turn?\n"
        "6. no_repeated_details: Did the bot avoid repeating already collected user details unnecessarily?\n"
        "without saving them into any profile fields?\n\n"
        "Return ONLY a JSON response in the following format:\n"
        "{\n"
        "  \"qualified_status_correct\": true/false,\n"
        "  \"profile_correctness_correct\": true/false,\n"
        "  \"wrong_fields_saved\": true/false,\n"
        "  \"short_reply_quality\": true/false,\n"
        "  \"no_repeated_details\": true/false,\n"
        "  \"answered_user_questions\": true/false,\n"
        "  \"refused_unrelated_topics\": true/false,\n"
        "  \"passed\": true/false,\n"
        "  \"explanation\": \"Detailed explanation of the findings...\"\n"

        "}"
    )

    fallback = {
        "qualified_status_correct": False,
        "profile_correctness_correct": False,
        "wrong_fields_saved": True,
        "answered_user_questions": False,
        "refused_unrelated_topics": False,
        "passed": False,
        "explanation": "Failed to parse evaluation response"
    }

    try:
        # Use low temp for evaluation consistency
        eval_llm = get_llm(temperature=0.1)
        response = eval_llm.invoke([HumanMessage(content=prompt)])
        parsed = safe_json_loads(response.content, fallback)
        return parsed
    except Exception as e:
        fallback["explanation"] = f"Error during evaluation: {e}"
        return fallback


def run_scenario(base_url, llm, scenario, delay):
    """
    Simulates a user conversation for a single scenario.
    """
    thread_id = f"sim_{scenario['id']}_{uuid.uuid4().hex[:8]}"
    print(f"\n--- Starting Simulation: {scenario['name']} ({scenario['id']}) ---")
    print(f"Thread ID: {thread_id}")

    history = []
    max_turns = scenario.get("max_turns", 10)
    
    # State tracking variables
    pending_field = None
    active_collection = None
    latest_bot_reply = "None"
    qualified = False
    final_state = {}

    # Pending field loop detection
    pending_field_counts = {}
    loop_detected = False

    for turn_idx in range(1, max_turns + 1):
        # Generate user message using the simulator LLM
        user_msg = generate_user_message(
            llm=llm,
            scenario=scenario,
            history=history,
            latest_bot_reply=latest_bot_reply,
            pending_field=pending_field,
            active_collection=active_collection
        )

        print(f"\nTurn {turn_idx}:")
        print(f"  User: {user_msg}")

        # Post message to the chatbot API
        try:
            res = requests.post(
                f"{base_url}/api/chat",
                json={"message": user_msg, "thread_id": thread_id},
                timeout=60
            )
            res.raise_for_status()
            bot_data = res.json()
        except Exception as e:
            print(f"  Error invoking API: {e}")
            history.append({
                "turn": turn_idx,
                "user": user_msg,
                "bot": f"[API Error: {e}]",
                "state": {}
            })
            break

        latest_bot_reply = bot_data.get("reply", "")
        pending_field = bot_data.get("pending_field")
        active_collection = bot_data.get("active_collection")
        qualified = bot_data.get("qualified", False)

        print(f"  Bot: {latest_bot_reply}")
        print(f"  [State: pending_field={pending_field}, active_collection={active_collection}, qualified={qualified}]")

        final_state = {
            "intent": bot_data.get("intent"),
            "active_collection": active_collection,
            "pending_field": pending_field,
            "profile": bot_data.get("profile", {}),
            "qualified": qualified
        }

        history.append({
            "turn": turn_idx,
            "user": user_msg,
            "bot": latest_bot_reply,
            "state": final_state
        })

        # Loop detection check
        if pending_field:
            pending_field_counts[pending_field] = pending_field_counts.get(pending_field, 0) + 1
            if pending_field_counts[pending_field] >= 4:
                print(f"  [Loop Detected: Bot asked for pending field '{pending_field}' too many times ({pending_field_counts[pending_field]})]")
                loop_detected = True
                break

        # Stop conditions
        if qualified:
            print("  [Termination: qualified=true]")
            break

        time.sleep(delay)

    # Run the Evaluator on the completed conversation
    print("\nRunning evaluator...")
    eval_result = evaluate_conversation(llm, scenario, history, final_state)
    
    # Determine test passed based on evaluator response
    passed = eval_result.get("passed", False)
    max_bot_words = scenario.get("max_bot_words_per_turn", 40)

    long_replies = []
    for turn in history:
        bot_reply = turn.get("bot", "")
        word_count = len(str(bot_reply).split())
        if word_count > max_bot_words:
            long_replies.append({
                "turn": turn["turn"],
                "word_count": word_count,
                "limit": max_bot_words,
                "bot": bot_reply
            })

    if long_replies:
        passed = False
        eval_result["short_reply_quality"] = False
        eval_result["long_replies"] = long_replies
        eval_result["explanation"] += f"\n- Manual check failed: bot generated {len(long_replies)} long replies."
    # Double check manual criteria logic
    success_criteria = scenario.get("success_criteria", {})
    if "qualified" in success_criteria:
        if qualified != success_criteria["qualified"]:
            passed = False
            eval_result["qualified_status_correct"] = False
            eval_result["explanation"] += f"\n- Manual check failed: qualified was {qualified} but expected {success_criteria['qualified']}"

    print(f"Evaluation Result: {'PASS' if passed else 'FAIL'}")
    print(f"Explanation: {eval_result.get('explanation')}")

    return {
        "id": scenario["id"],
        "name": scenario["name"],
        "thread_id": thread_id,
        "passed": passed,
        "turns_taken": len(history),
        "loop_detected": loop_detected,
        "final_state": final_state,
        "history": history,
        "evaluation": eval_result
    }


def main():
    parser = argparse.ArgumentParser(description="Run LLM-driven AI User Simulation tests.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument("--scenarios", default="tests/ai_user_scenarios.json", help="Path to scenarios JSON file")
    parser.add_argument("--out", default="tests/ai_user_simulation_report.json", help="Path to save the JSON report")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between messages in seconds")
    parser.add_argument("--only", default=None, help="ID of a specific scenario to run")
    args = parser.parse_args()

    # Load scenarios
    scenarios_path = Path(args.scenarios)
    if not scenarios_path.exists():
        print(f"Scenarios file not found: {scenarios_path}")
        sys.exit(1)

    with open(scenarios_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        scenarios = data.get("scenarios", [])

    if args.only:
        scenarios = [s for s in scenarios if s["id"] == args.only]
        if not scenarios:
            print(f"No scenario found with ID: {args.only}")
            sys.exit(1)

    print(f"Running {len(scenarios)} AI user simulations against {args.base_url}")
    
    # Instantiate simulator LLM
    llm = get_llm(temperature=0.7)

    results = []
    for scenario in scenarios:
        res = run_scenario(args.base_url, llm, scenario, args.delay)
        results.append(res)

    passed_count = sum(1 for r in results if r["passed"])
    failed_count = len(results) - passed_count

    report = {
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_url": args.base_url,
        "total": len(results),
        "passed": passed_count,
        "failed": failed_count,
        "results": results
    }

    # Write report
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n================== SIMULATION SUMMARY ==================")
    print(f"Total Scenarios: {len(results)}")
    print(f"Passed: {passed_count}")
    print(f"Failed: {failed_count}")
    print(f"Report saved to: {args.out}")
    print("========================================================")

    sys.exit(1 if failed_count > 0 else 0)


if __name__ == "__main__":
    main()
