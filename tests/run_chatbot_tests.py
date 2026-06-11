from pyparsing import warnings
import json
import re
import time
import uuid
import argparse
import requests
from datetime import datetime
from pathlib import Path


def normalize(text):
    return (text or "").lower().strip()

def normalize_value(text):
    text = normalize(text)
    text = text.replace("months", "month")
    text = text.replace("weeks", "week")
    text = text.replace("days", "day")
    text = text.replace("years", "year")
    return text


def contains_any(text, keywords):
    text = normalize(text)
    return any(normalize(k) in text for k in keywords)


def contains_none(text, keywords):
    text = normalize(text)
    return all(normalize(k) not in text for k in keywords)


def get_nested(data, key, default=None):
    return data.get(key, default)


def check_profile_contains(actual_profile, expected_profile):
    errors = []
    actual_profile = actual_profile or {}
    for k, expected_val in expected_profile.items():
        actual_val = actual_profile.get(k)
        if actual_val is None:
            errors.append(f"profile missing key '{k}', expected '{expected_val}'")
            continue
        if normalize_value(str(expected_val)) not in normalize_value(str(actual_val)):
            errors.append(f"profile.{k} expected contains '{expected_val}', got '{actual_val}'")
    return errors


def check_profile_should_not_contain_values(actual_profile, forbidden_map):
    errors = []
    actual_profile = actual_profile or {}
    for k, forbidden_val in forbidden_map.items():
        actual_val = actual_profile.get(k)
        if actual_val is not None and normalize(str(forbidden_val)) in normalize(str(actual_val)):
            errors.append(f"profile.{k} should not contain '{forbidden_val}', got '{actual_val}'")
    return errors


def sentence_count(text):
    parts = re.split(r"[.!?]+", text or "")
    return len([p for p in parts if p.strip()])


def check_turn(actual, expected):
    errors = []
    reply = actual.get("reply", "")
    profile = actual.get("profile") or {}

    # State checks
    for field in ["intent", "primary_intent", "active_collection", "pending_field", "qualified"]:
        if field in expected:
            if actual.get(field) != expected[field]:
                errors.append(f"{field} expected {expected[field]!r}, got {actual.get(field)!r}")

    # Profile checks
    if "profile_contains" in expected:
        errors += check_profile_contains(profile, expected["profile_contains"])

    if "profile_should_not_contain_keys_with_value" in expected:
        errors += check_profile_should_not_contain_values(
            profile,
            expected["profile_should_not_contain_keys_with_value"]
        )

    if "profile_should_equal" in expected:
        if profile != expected["profile_should_equal"]:
            errors.append(f"profile expected exactly {expected['profile_should_equal']}, got {profile}")

    # Reply keyword checks
    if "reply_should_contain_any" in expected:
        if not contains_any(reply, expected["reply_should_contain_any"]):
            errors.append(
                f"reply should contain any of {expected['reply_should_contain_any']}, got: {reply[:200]}"
            )

    if "reply_should_not_contain_any" in expected:
        if not contains_none(reply, expected["reply_should_not_contain_any"]):
            errors.append(
                f"reply should NOT contain any of {expected['reply_should_not_contain_any']}, got: {reply[:200]}"
            )

    if "max_sentences" in expected:
        if sentence_count(reply) > expected["max_sentences"]:
            errors.append(f"reply has more than {expected['max_sentences']} sentences: {sentence_count(reply)}")

    # Generic behavior checks using simple heuristics
    if expected.get("should_not_only_ask_field"):
        field_words = ["name", "email", "phone", "company", "budget", "timeline"]
        is_short_field_ask = len(reply.split()) <= 15 and contains_any(reply, field_words)
        if is_short_field_ask:
            errors.append("reply looks like only a field request, but should answer latest question first")

    if "should_not_ask" in expected:
        for field in expected["should_not_ask"]:
            if normalize(field) in normalize(reply):
                errors.append(f"reply should not ask/repeat field '{field}', got: {reply[:200]}")

    if expected.get("should_decline_unrelated") or expected.get("should_not_answer_unrelated"):
        decline_keywords = [
            "codeqlik", "company", "services", "support", "projects", "hiring",
            "company-related", "related to our company", "can only help"
        ]
        if not contains_any(reply, decline_keywords):
            errors.append("expected unrelated refusal/redirection, but reply does not look like a refusal")

    if expected.get("should_refuse_sensitive"):
        refusal_keywords = ["can't", "cannot", "unable", "not able", "can only help", "company-related", "not provide"]
        if not contains_any(reply, refusal_keywords):
            errors.append("expected sensitive refusal, but reply does not look like refusal")

    return errors


def run_test_case(base_url, test, delay=4):
    thread_id = f"test_{test['id']}_{uuid.uuid4().hex[:8]}"
    messages = test["messages"]
    expectations = {e["turn"]: e for e in test.get("expected_each_turn", [])}

    turn_results = []
    test_errors = []

    for idx, msg in enumerate(messages, start=1):
        try:
            res = requests.post(
                f"{base_url}/api/chat",
                json={"message": msg, "thread_id": thread_id},
                timeout=60
            )
            res.raise_for_status()
            actual = res.json()
        except Exception as e:
            actual = {"reply": "", "error": str(e)}
            test_errors.append(f"Turn {idx}: API error: {e}")
            turn_results.append({
                "turn": idx,
                "message": msg,
                "actual": actual,
                "errors": [str(e)]
            })
            continue

        expected = expectations.get(idx, {})
        errors = check_turn(actual, expected) if expected else []

        turn_results.append({
            "turn": idx,
            "message": msg,
            "expected": expected,
            "actual": {
                "reply": actual.get("reply"),
                "intent": actual.get("intent"),
                "primary_intent": actual.get("primary_intent"),
                "active_collection": actual.get("active_collection"),
                "pending_field": actual.get("pending_field"),
                "profile": actual.get("profile"),
                "missing_fields": actual.get("missing_fields"),
                "qualified": actual.get("qualified"),
                "rag_confidence": actual.get("rag_confidence")
            },
            "errors": errors
        })

        for err in errors:
            test_errors.append(f"Turn {idx}: {err}")

        time.sleep(delay)

    return {
        "id": test["id"],
        "name": test["name"],
        "category": test.get("category"),
        "thread_id": thread_id,
        "passed": len(test_errors) == 0,
        "error_count": len(test_errors),
        "errors": test_errors,
        "turn_results": turn_results
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument("--tests", default="codeqlik_multiturn_stabilization_tests.json", help="Path to tests JSON")
    parser.add_argument("--out", default="test_report.json", help="Output report path")
    parser.add_argument("--delay", type=float, default=10, help="Delay between messages")
    parser.add_argument("--only", default=None, help="Run single test ID")
    args = parser.parse_args()

    with open(args.tests, "r", encoding="utf-8") as f:
        suite = json.load(f)

    tests = suite.get("tests", [])

    if args.only:
        tests = [t for t in tests if t["id"] == args.only]

    results = []

    print(f"Running {len(tests)} conversation tests against {args.base_url}")

    for test in tests:
        print(f"Running {test['id']}: {test['name']}")
        result = run_test_case(args.base_url, test, delay=args.delay)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"  {status} ({result['error_count']} errors)")

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed

    report = {
        "suite_name": suite.get("suite_name"),
        "run_at": datetime.utcnow().isoformat() + "Z",
        "base_url": args.base_url,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "pass_rate": round((passed / len(results)) * 100, 2) if results else 0,
        "results": results
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\nSUMMARY")
    print(f"Total: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print(f"Pass rate: {report['pass_rate']}%")
    print(f"Report saved to: {args.out}")

    if failed:
        print("\nFAILED TESTS")
        for r in results:
            if not r["passed"]:
                print(f"- {r['id']} {r['name']}: {r['error_count']} errors")
                for e in r["errors"][:3]:
                    print(f"  - {e}")

    # Exit non-zero if any test fails, useful for CI/CD
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
