import os
import sys

# Add project root to sys.path so we can import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.orchestrator import AgentOrchestrator

def safe_print(label, text):
    encoding = sys.stdout.encoding or 'utf-8'
    safe_text = text.encode(encoding, errors='replace').decode(encoding)
    print(f"{label}:\n{safe_text}")

def test_orchestrator_general_chat():
    orchestrator = AgentOrchestrator()
    state = {}
    
    # Test a simple general chat command
    print("Test 1: Running general chat...")
    res = orchestrator.run("Hello, who are you?", state)
    
    print("Steps Executed:")
    for step in res["steps"]:
        print(f" - {step}")
        
    safe_print("Result", res["result"])
    print(f"Final State: {res['state']}")
    assert len(res["steps"]) > 0
    assert res["result"] != ""

def test_orchestrator_search():
    orchestrator = AgentOrchestrator()
    state = {}
    
    print("\nTest 2: Running search action...")
    # This should trigger the search action
    res = orchestrator.run("search for Nandini_Srivastava_Resume", state)
    
    print("Steps Executed:")
    for step in res["steps"]:
        print(f" - {step}")
        
    safe_print("Result", res["result"])
    print(f"Final State: {res['state']}")
    assert any("search" in step.lower() for step in res["steps"])
    assert "Nandini_Srivastava_Resume" in res["result"]

def test_orchestrator_summarize():
    orchestrator = AgentOrchestrator()
    state = {}
    
    # 1. Search for file
    print("\nTest 3: Summarize file flow...")
    res = orchestrator.run("search for Nandini_Srivastava_Resume", state)
    state = res["state"]
    
    # 2. Summarize file
    res = orchestrator.run("summarize the file", state)
    
    print("Steps Executed:")
    for step in res["steps"]:
        print(f" - {step}")
        
    safe_print("Result", res["result"])
    print(f"Final State keys: {list(res['state'].keys())}")
    assert any("summarize" in step.lower() or "pipeline" in step.lower() for step in res["steps"])
    assert "text" in res["state"]

if __name__ == "__main__":
    test_orchestrator_general_chat()
    test_orchestrator_search()
    test_orchestrator_summarize()
    print("\nAll orchestrator tests passed successfully!")
