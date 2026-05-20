"""Smoke-test for frozen ExecutionCapsTracker and CapsEnforcer."""
import sys, time
sys.path.insert(0, "/media/sf_Projects/Maestro/runtime")

# Pull in the relevant module sections — run_agent.py has too many deps to import directly,
# so we build the classes from the source we just patched.
source = open("/media/sf_Projects/Maestro/runtime/run_agent.py").read()

# Find ExecutionCapsTracker class text
start_tracker = source.find("class ExecutionCapsTracker:")
start_breach  = source.find("class ExecutionCapBreach(Exception):")
start_caps    = source.find("class CapsEnforcer:")
end_caps      = source.find("\nclass AIAgent:")

exec(source[start_tracker:start_breach])   # ExecutionCapsTracker
exec(source[start_breach:start_caps])       # ExecutionCapBreach
exec(source[start_caps:end_caps])           # CapsEnforcer

# --- Test frozen ExecutionCapsTracker ---
caps = ExecutionCapsTracker(
    max_iterations=10,
    max_wall_clock_s=60,
    max_tokens=1000,
    max_cost_cents=50,
)

assert caps.max_iterations == 10
assert caps.wall_clock_start is None

caps.mark_start()
assert caps.wall_clock_start is not None

try:
    caps.max_iterations = 99
    raise AssertionError("should have raised AttributeError")
except AttributeError:
    pass

try:
    caps.wall_clock_start = time.monotonic()
    raise AssertionError("should have raised AttributeError")
except AttributeError:
    pass

# --- Test CapsEnforcer wrapper ---
raw = ExecutionCapsTracker(max_iterations=5)
enf = CapsEnforcer(raw)
assert enf.max_iterations == 5
enf.mark_start()
assert raw.wall_clock_start is not None
assert enf.check(3) is None

try:
    enf._caps = None
    raise AssertionError("should have raised AttributeError")
except AttributeError:
    pass

print("ALL FROZEN CAP TESTS PASSED")
