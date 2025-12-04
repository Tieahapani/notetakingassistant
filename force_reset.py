#!/usr/bin/env python3
"""Force delete old agent and create a fresh one"""

import os
from letta_client import Letta
from dotenv import load_dotenv

load_dotenv()

client = Letta(token=os.getenv("LETTA_API_KEY"))

# Delete old agent ID file
if os.path.exists(".voicelog_agent_id"):
    with open(".voicelog_agent_id", "r") as f:
        old_agent_id = f.read().strip()
    
    print(f"🗑️  Deleting old agent: {old_agent_id}")
    
    try:
        client.agents.delete(agent_id=old_agent_id)
        print("✅ Deleted old agent from Letta")
    except Exception as e:
        print(f"⚠️  Could not delete agent (may not exist): {e}")
    
    os.remove(".voicelog_agent_id")
    print("✅ Removed local agent ID file")
else:
    print("ℹ️  No existing agent found")

print("\n✅ Ready to create fresh agent!")
print("Now run: python3 app.py")