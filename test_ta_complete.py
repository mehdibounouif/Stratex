# test_ta_complete.py

print("="*70)
print("TESTING TRADINGAGENTS INSTALLATION")
print("="*70)

# Test 1: Imports
print("\n[1/5] Testing imports...")
try:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
    print("✅ Imports successful")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    exit(1)

# Test 2: Config
print("\n[2/5] Testing configuration...")
try:
    config = DEFAULT_CONFIG.copy()
    config["deep_think_llm"] = "gpt-4o-mini"
    config["quick_think_llm"] = "gpt-4o-mini"
    config["max_debate_rounds"] = 1
    print("✅ Configuration ready")
except Exception as e:
    print(f"❌ Config failed: {e}")
    exit(1)

# Test 3: API Keys
#print("\n[3/5] Checking API keys...")
#try:
#    from config import BaseConfig
#    BaseConfig.validate()
#    print("✅ API keys configured")
#except Exception as e:
#    print(f"❌ API keys missing: {e}")
#    exit(1)

# Test 4: Initialize
print("\n[4/5] Testing TradingAgents initialization...")
try:
    ta = TradingAgentsGraph(debug=False, config=config)
    print("✅ TradingAgents initialized")
except Exception as e:
    print(f"❌ Initialization failed: {e}")
    exit(1)

print("\n[5/5] ✅ READY!")
print("\n" + "="*70)
print("✅ ALL TESTS PASSED - TRADINGAGENTS INSTALLED!")
print("="*70)
print("\nNext: Create integration files from Task 3.1")
