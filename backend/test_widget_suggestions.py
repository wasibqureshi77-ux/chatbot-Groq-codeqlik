import sys
import os

# Adjust path to import backend modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from widget_suggestions import WidgetSuggestionRequest, generate_widget_suggestions

def run_tests():
    print("=== Running Widget Suggestions Tests ===")

    # Test Case 1: Service answer -> project/service suggestions
    print("Test 1: Service answer -> project/service suggestions...")
    req1 = WidgetSuggestionRequest(
        latest_bot_message="We offer a wide range of services including software development, web apps, mobile apps, CRM systems.",
        latest_user_message="what services do you provide?",
        recent_messages=[
            {"role": "user", "content": "what services do you provide?"},
            {"role": "assistant", "content": "We offer a wide range of services including software development, web apps, mobile apps, CRM systems."}
        ]
    )
    suggs1 = generate_widget_suggestions(req1)
    print("Result 1:", suggs1)
    assert isinstance(suggs1, list)
    assert len(suggs1) <= 4

    # Test Case 2: Project type question -> project categories
    print("Test 2: Project type question -> project categories...")
    req2 = WidgetSuggestionRequest(
        latest_bot_message="What kind of project are you planning — website, app, CRM, SaaS, or something custom?",
        latest_user_message="I want to discuss a project",
        recent_messages=[
            {"role": "user", "content": "I want to discuss a project"},
            {"role": "assistant", "content": "What kind of project are you planning — website, app, CRM, SaaS, or something custom?"}
        ]
    )
    suggs2 = generate_widget_suggestions(req2)
    print("Result 2:", suggs2)
    assert any(term in "".join(suggs2).lower() for term in ["web", "app", "crm", "saas", "custom"])

    # Test Case 3: Requirements question -> feature suggestions
    print("Test 3: Requirements question -> feature suggestions...")
    req3 = WidgetSuggestionRequest(
        latest_bot_message="What should this system mainly help you do? Tell me about the features.",
        latest_user_message="website",
        recent_messages=[
            {"role": "user", "content": "website"},
            {"role": "assistant", "content": "What should this system mainly help you do? Tell me about the features."}
        ]
    )
    suggs3 = generate_widget_suggestions(req3)
    print("Result 3:", suggs3)

    # Test Case 4: Budget question -> budget ranges
    print("Test 4: Budget question -> budget ranges...")
    req4 = WidgetSuggestionRequest(
        latest_bot_message="Do you have a rough budget range in mind?",
        latest_user_message="Yes",
        recent_messages=[
            {"role": "user", "content": "Yes"},
            {"role": "assistant", "content": "Do you have a rough budget range in mind?"}
        ]
    )
    suggs4 = generate_widget_suggestions(req4)
    print("Result 4:", suggs4)

    # Test Case 5: Timeline question -> timeline options
    print("Test 5: Timeline question -> timeline options...")
    req5 = WidgetSuggestionRequest(
        latest_bot_message="When would you like to start or have this ready?",
        latest_user_message="1 lakh",
        recent_messages=[
            {"role": "user", "content": "1 lakh"},
            {"role": "assistant", "content": "When would you like to start or have this ready?"}
        ]
    )
    suggs5 = generate_widget_suggestions(req5)
    print("Result 5:", suggs5)

    # Test Case 6: Name question -> []
    print("Test 6: Name question -> []...")
    req6 = WidgetSuggestionRequest(
        latest_bot_message="Before we go ahead — what name should I use for you?",
        latest_user_message="I want to discuss a project",
        recent_messages=[
            {"role": "user", "content": "I want to discuss a project"},
            {"role": "assistant", "content": "Before we go ahead — what name should I use for you?"}
        ]
    )
    suggs6 = generate_widget_suggestions(req6)
    print("Result 6:", suggs6)
    assert suggs6 == []

    # Test Case 7: Email/phone/contact question -> []
    print("Test 7: Email/phone/contact question -> []...")
    req7 = WidgetSuggestionRequest(
        latest_bot_message="To help the team follow up — what’s the best email or phone number for you?",
        latest_user_message="Anurag",
        recent_messages=[
            {"role": "user", "content": "Anurag"},
            {"role": "assistant", "content": "To help the team follow up — what’s the best email or phone number for you?"}
        ]
    )
    suggs7 = generate_widget_suggestions(req7)
    print("Result 7:", suggs7)
    assert suggs7 == []

    # Test Case 8: Mixed message (services list + name request) -> should return suggestions
    print("Test 8: Mixed message (services list + name request) -> should return suggestions...")
    req8 = WidgetSuggestionRequest(
        latest_bot_message="We offer a wide range of services, including:\n1. software development\n2. AI automation\n3. web apps\n\nBefore we go ahead — what name should I use for you?",
        latest_user_message="What services do you provide?",
        recent_messages=[
            {"role": "user", "content": "What services do you provide?"},
            {"role": "assistant", "content": "We offer a wide range of services, including:\n1. software development\n2. AI automation\n3. web apps\n\nBefore we go ahead — what name should I use for you?"}
        ]
    )
    suggs8 = generate_widget_suggestions(req8)
    print("Result 8:", suggs8)
    assert len(suggs8) > 0
    assert any("software" in s.lower() or "ai" in s.lower() or "web" in s.lower() for s in suggs8)

    # Test Case 13: Hinglish conversation returns Hinglish or natural mixed suggestions
    print("Test 13: Hinglish conversation returns Hinglish/mixed suggestions...")
    req13 = WidgetSuggestionRequest(
        latest_bot_message="Aap kis tarah ka project plan kar rahe hain — website, mobile app, ya CRM?",
        latest_user_message="mujhse ek software banwana hai",
        recent_messages=[
            {"role": "user", "content": "mujhse ek software banwana hai"},
            {"role": "assistant", "content": "Aap kis tarah ka project plan kar rahe hain — website, mobile app, ya CRM?"}
        ]
    )
    suggs13 = generate_widget_suggestions(req13)
    print("Result 13:", suggs13)

    print("=== All Tests Completed Successfully ===")

if __name__ == "__main__":
    run_tests()
