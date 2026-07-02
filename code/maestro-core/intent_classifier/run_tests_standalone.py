"""Standalone test runner for intent_classifier — no pytest required."""
import sys
import json
sys.path.insert(0, "/home/andjesse")

from nucleus.modules.intent_classifier import Intent, IntentResult, IntentClassifier

c = IntentClassifier()
results = []

def check(name, condition):
    results.append((name, condition))
    print(f"{'PASS' if condition else 'FAIL'}: {name}")

# Rule 1: ACK patterns
for ack in ["Acknowledged", "Got it", "Roger", "Standing by", "Copy that", "ack", "ACK", "Acknowledged, will proceed."]:
    r = c.classify(ack)
    check(f"Rule 1 ACK: {ack}", r.intent == Intent.ACK and r.should_reply == False and r.should_surface == False)

# Rule 1: long ACK no match
r = c.classify("Acknowledged " + ("x" * 80))
check("Rule 1 long ACK no match", r.intent != Intent.ACK)

# Rule 2: Subject + task
for content in ["Subject: Build the auth module", "Subject: implement login flow", "Subject: fix the null pointer bug", "Subject: deploy to staging", "Subject: review PR #42", "Subject: write unit tests for parser"]:
    r = c.classify(content)
    check(f"Rule 2 WORK: {content[:40]}", r.intent == Intent.WORK and r.should_reply == True and r.should_surface == True)

# Rule 2: Subject no task keyword
r = c.classify("Subject: Hello there")
check("Rule 2 Subject no task", r.intent != Intent.WORK)

# Rule 3: JSON status
r = c.classify(json.dumps({"status": "in_progress", "task": "build"}))
check("Rule 3 JSON status", r.intent == Intent.STATUS and r.should_reply == False)

# Rule 3: JSON no status
r = c.classify(json.dumps({"task": "build", "id": 1}))
check("Rule 3 JSON no status", r.intent != Intent.STATUS)

# Rule 3: invalid JSON
r = c.classify("{not valid json")
check("Rule 3 invalid JSON", r.intent != Intent.STATUS)

# Rule 4: health checks
for hc in ["health", "ping", "heartbeat", "alive", "status check", "healthcheck", "health-check"]:
    r = c.classify(hc)
    check(f"Rule 4 health: {hc}", r.intent == Intent.SYSTEM and r.should_reply == False)

# Rule 5: directive
r = c.classify("any content here", msg_type="directive")
check("Rule 5 directive", r.intent == Intent.WORK and r.should_reply == True and r.should_surface == True)

# Rule 6: system
r = c.classify("any content here", msg_type="system")
check("Rule 6 system", r.intent == Intent.SYSTEM and r.should_reply == False and r.should_surface == False)

# Priority: directive over ACK
r = c.classify("Acknowledged", msg_type="directive")
check("Priority: directive over ACK", r.intent == Intent.WORK and r.matched_rule == "rule_5: directive msg_type")

# Priority: system over WORK
r = c.classify("Subject: build the thing", msg_type="system")
check("Priority: system over WORK", r.intent == Intent.SYSTEM and r.matched_rule == "rule_6: system msg_type")

# Fallthrough
r = c.classify("random chatter that matches nothing")
check("Fallthrough UNKNOWN", r.intent == Intent.UNKNOWN and r.confidence == 0.5 and r.should_reply == False and r.should_surface == True)

# Custom rules
rid = c.add_rule(r"urgent", Intent.WORK, True, True)
check("Custom add rule", rid.startswith("custom_"))
r = c.classify("This is urgent, please respond")
check("Custom match", r.intent == Intent.WORK and r.matched_rule == rid)
check("Custom remove", c.remove_rule(rid) == True)
check("Custom remove nonexistent", c.remove_rule("custom_nonexistent") == False)

# Custom overrides default
c2 = IntentClassifier()
c2.add_rule(r"Acknowledged", Intent.WORK, True, True)
r = c2.classify("Acknowledged")
check("Custom overrides default", r.intent == Intent.WORK)

# Confidence values
check("Conf ACK 0.9", c.classify("Acknowledged").confidence == 0.9)
check("Conf WORK 0.85", c.classify("Subject: build it").confidence == 0.85)
check("Conf STATUS 0.95", c.classify(json.dumps({"status": "ok"})).confidence == 0.95)
check("Conf SYSTEM 0.95", c.classify("health").confidence == 0.95)
check("Conf directive 1.0", c.classify("x", msg_type="directive").confidence == 1.0)
check("Conf system 1.0", c.classify("x", msg_type="system").confidence == 1.0)
check("Conf unknown 0.5", c.classify("blah").confidence == 0.5)

passed = sum(1 for _, p in results if p)
total = len(results)
print(f"\n{passed}/{total} passed")
if passed == total:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
    sys.exit(1)
