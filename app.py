from flask import Flask, request, jsonify
import os
from letta_client import Letta
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import json 

# Load env variables
load_dotenv()

app = Flask(__name__)

# Initialize Letta client
client = Letta(token=os.getenv("LETTA_API_KEY"))
agent_id = None

firebase_creds = os.getenv('FIREBASE_CREDENTIALS')
if firebase_creds:
    # Production: credentials from environment variable
    cred_dict = json.loads(firebase_creds)
    cred = credentials.Certificate(cred_dict)
else:
    # Local development: credentials from file
    cred = credentials.Certificate("firebase-credentials.json")


# Initialize Firebase

firebase_admin.initialize_app(cred)
db = firestore.client()

# Your Flask server URL - UPDATE THIS with your ngrok URL
BACKEND_URL = "https://voicelog-backend.onrender.com"  # Change this to your ngrok URL


# ============================================
# FIREBASE HELPER FUNCTIONS
# ============================================

def _create_folder(folder_name: str, emoji: str = ""):
    """Create a folder in Firebase"""
    folder_id = folder_name.lower().replace(" ", "_")
    
    # Check if folder exists
    folder_ref = db.collection('folders').document(folder_id)
    if folder_ref.get().exists:
        return f"Folder '{folder_name}' already exists"
    
    # Create folder
    folder_ref.set({
        'id': folder_id,
        'name': folder_name,
        'emoji': emoji,
        'created_at': firestore.SERVER_TIMESTAMP
    })
    
    return f"Created folder {emoji} {folder_name}".strip()


def _create_task(task_name: str, folder_name: str, recurrence: str = "once", 
                time: str = None, duration: str = None):
    """Create a task in Firebase"""
    folder_id = folder_name.lower().replace(" ", "_")
    
    # Check if folder exists
    folder_ref = db.collection('folders').document(folder_id)
    if not folder_ref.get().exists:
        return f"Folder '{folder_name}' doesn't exist"
    
    # Create task
    task_ref = db.collection('tasks').document()
    task_ref.set({
        'name': task_name,
        'folder': folder_id,
        'completed': False,
        'recurrence': recurrence,
        'time': time,
        'duration': duration,
        'created_at': firestore.SERVER_TIMESTAMP
    })
    
    return f"Created task '{task_name}' in {folder_name}"


def _get_folder_contents(folder_name: str):
    """Get all tasks in a folder"""
    folder_id = folder_name.lower().replace(" ", "_")
    
    # Check if folder exists
    folder_ref = db.collection('folders').document(folder_id)
    folder = folder_ref.get()
    
    if not folder.exists:
        return f"Folder '{folder_name}' doesn't exist"
    
    folder_data = folder.to_dict()
    
    # Get tasks in this folder
    tasks = db.collection('tasks').where('folder', '==', folder_id).stream()
    task_list = []
    
    for task in tasks:
        task_data = task.to_dict()
        status = "✓" if task_data.get('completed', False) else "○"
        task_list.append(f"{status} {task_data['name']}")
    
    if not task_list:
        return f"{folder_data.get('emoji', '')} {folder_name} is empty"
    
    return f"{folder_data.get('emoji', '')} {folder_name}:\n" + "\n".join(task_list)


def _list_all_folders():
    """List all folders"""
    folders = db.collection('folders').stream()
    folder_list = []
    
    for folder in folders:
        folder_data = folder.to_dict()
        # Count tasks in this folder
        task_count = len(list(db.collection('tasks').where('folder', '==', folder.id).stream()))
        folder_list.append(f"{folder_data.get('emoji', '')} {folder_data['name']} ({task_count} tasks)")
    
    if not folder_list:
        return "You don't have any folders yet"
    
    return "Your folders:\n" + "\n".join(folder_list)


def _delete_task(task_name: str):
    """Delete a task"""
    tasks = db.collection('tasks').where('name', '==', task_name).stream()
    
    deleted = False
    for task in tasks:
        task.reference.delete()
        deleted = True
        break
    
    if deleted:
        return f"Deleted task '{task_name}'"
    return f"Task '{task_name}' not found"


def _delete_folder(folder_name: str):
    """Delete a folder and all its tasks"""
    folder_id = folder_name.lower().replace(" ", "_")
    
    folder_ref = db.collection('folders').document(folder_id)
    if not folder_ref.get().exists:
        return f"Folder '{folder_name}' doesn't exist"
    
    # Delete all tasks in folder
    tasks = db.collection('tasks').where('folder', '==', folder_id).stream()
    for task in tasks:
        task.reference.delete()
    
    # Delete folder
    folder_ref.delete()
    
    return f"Deleted folder '{folder_name}'"


def _move_task(task_name: str, destination_folder: str):
    """Move a task to another folder"""
    dest_id = destination_folder.lower().replace(" ", "_")
    
    # Check destination folder exists
    if not db.collection('folders').document(dest_id).get().exists:
        return f"Folder '{destination_folder}' doesn't exist"
    
    # Find and move task
    tasks = db.collection('tasks').where('name', '==', task_name).stream()
    
    moved = False
    for task in tasks:
        task.reference.update({'folder': dest_id})
        moved = True
        break
    
    if moved:
        return f"Moved '{task_name}' to {destination_folder}"
    return f"Task '{task_name}' not found"


def _edit_folder_name(old_name: str, new_name: str, new_emoji: str = None):
    """Rename a folder"""
    old_id = old_name.lower().replace(" ", "_")
    new_id = new_name.lower().replace(" ", "_")
    
    old_ref = db.collection('folders').document(old_id)
    if not old_ref.get().exists:
        return f"Folder '{old_name}' doesn't exist"
    
    if new_id != old_id and db.collection('folders').document(new_id).get().exists:
        return f"A folder named '{new_name}' already exists"
    
    # Get old folder data
    old_data = old_ref.get().to_dict()
    
    # Create new folder
    new_data = {
        'id': new_id,
        'name': new_name,
        'emoji': new_emoji if new_emoji else old_data.get('emoji', ''),
        'created_at': old_data.get('created_at')
    }
    db.collection('folders').document(new_id).set(new_data)
    
    # Update all tasks
    tasks = db.collection('tasks').where('folder', '==', old_id).stream()
    for task in tasks:
        task.reference.update({'folder': new_id})
    
    # Delete old folder
    old_ref.delete()
    
    return f"Renamed folder to '{new_name}'"


def _edit_task(old_task_name: str, new_task_name: str = None, new_folder: str = None,
              new_recurrence: str = None, new_time: str = None, new_duration: str = None):
    """Edit task properties"""
    tasks = db.collection('tasks').where('name', '==', old_task_name).stream()
    
    updated = False
    for task in tasks:
        updates = {}
        
        if new_task_name:
            updates['name'] = new_task_name
        
        if new_folder:
            new_id = new_folder.lower().replace(" ", "_")
            if not db.collection('folders').document(new_id).get().exists:
                return f"Folder '{new_folder}' doesn't exist"
            updates['folder'] = new_id
        
        if new_recurrence:
            updates['recurrence'] = new_recurrence
        if new_time:
            updates['time'] = new_time
        if new_duration:
            updates['duration'] = new_duration
        
        if updates:
            task.reference.update(updates)
            updated = True
            final_name = new_task_name if new_task_name else old_task_name
            return f"Updated '{final_name}'"
    
    if not updated:
        return f"Task '{old_task_name}' not found"


# ============================================
# LETTA TOOL FUNCTIONS (MAKE HTTP CALLS)
# ============================================

def create_folder(folder_name: str, emoji: str = ""):
    """
    Create a new folder to organize tasks.
    
    Args:
        folder_name: Name of the folder to create
        emoji: Optional emoji icon for the folder
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/create_folder", json={
        "folder_name": folder_name,
        "emoji": emoji
    })
    return response.json()["result"]


def create_task(task_name: str, folder_name: str, recurrence: str = "once", 
                time: str = None, duration: str = None):
    """
    Create a new task in a specified folder.
    
    Args:
        task_name: Name of the task
        folder_name: Name of the folder to add the task to
        recurrence: How often the task repeats (once, daily, weekly, etc.)
        time: Optional scheduled time for the task
        duration: Optional duration for the task
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/create_task", json={
        "task_name": task_name,
        "folder_name": folder_name,
        "recurrence": recurrence,
        "time": time,
        "duration": duration
    })
    return response.json()["result"]


def move_task(task_name: str, destination_folder: str):
    """
    Move a task from one folder to another.
    
    Args:
        task_name: Name of the task to move
        destination_folder: Name of the destination folder
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/move_task", json={
        "task_name": task_name,
        "destination_folder": destination_folder
    })
    return response.json()["result"]


def delete_task(task_name: str):
    """
    Delete a task permanently.
    
    Args:
        task_name: Name of the task to delete
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/delete_task", json={
        "task_name": task_name
    })
    return response.json()["result"]


def delete_folder(folder_name: str):
    """
    Delete a folder and all tasks inside it.
    
    Args:
        folder_name: Name of the folder to delete
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/delete_folder", json={
        "folder_name": folder_name
    })
    return response.json()["result"]


def edit_folder_name(old_name: str, new_name: str, new_emoji: str = None):
    """
    Rename a folder and optionally change its emoji.
    
    Args:
        old_name: Current name of the folder
        new_name: New name for the folder
        new_emoji: Optional new emoji for the folder
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/edit_folder_name", json={
        "old_name": old_name,
        "new_name": new_name,
        "new_emoji": new_emoji
    })
    return response.json()["result"]


def edit_task(old_task_name: str, new_task_name: str = None, new_folder: str = None,
              new_recurrence: str = None, new_time: str = None, new_duration: str = None):
    """
    Edit a task's properties.
    
    Args:
        old_task_name: Current name of the task
        new_task_name: Optional new name for the task
        new_folder: Optional new folder to move the task to
        new_recurrence: Optional new recurrence pattern
        new_time: Optional new scheduled time
        new_duration: Optional new duration
    
    Returns:
        Success or error message
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/edit_task", json={
        "old_task_name": old_task_name,
        "new_task_name": new_task_name,
        "new_folder": new_folder,
        "new_recurrence": new_recurrence,
        "new_time": new_time,
        "new_duration": new_duration
    })
    return response.json()["result"]


def get_folder_contents(folder_name: str):
    """
    Get all tasks in a specific folder.
    
    Args:
        folder_name: Name of the folder to view
    
    Returns:
        Formatted list of tasks in the folder
    """
    import requests
    response = requests.post(f"{BACKEND_URL}/api/get_folder_contents", json={
        "folder_name": folder_name
    })
    return response.json()["result"]


def list_all_folders():
    """
    List all folders and their task counts.
    
    Returns:
        Formatted list of all folders
    """
    import requests
    response = requests.get(f"{BACKEND_URL}/api/list_all_folders")
    return response.json()["result"]


# ============================================
# API ENDPOINTS FOR LETTA TOOLS TO CALL
# ============================================

@app.route("/api/create_folder", methods=["POST"])
def api_create_folder():
    data = request.get_json()
    result = _create_folder(data["folder_name"], data.get("emoji", ""))
    return jsonify({"result": result})


@app.route("/api/create_task", methods=["POST"])
def api_create_task():
    data = request.get_json()
    result = _create_task(
        data["task_name"],
        data["folder_name"],
        data.get("recurrence", "once"),
        data.get("time"),
        data.get("duration")
    )
    return jsonify({"result": result})


@app.route("/api/move_task", methods=["POST"])
def api_move_task():
    data = request.get_json()
    result = _move_task(data["task_name"], data["destination_folder"])
    return jsonify({"result": result})


@app.route("/api/delete_task", methods=["POST"])
def api_delete_task():
    data = request.get_json()
    result = _delete_task(data["task_name"])
    return jsonify({"result": result})


@app.route("/api/delete_folder", methods=["POST"])
def api_delete_folder():
    data = request.get_json()
    result = _delete_folder(data["folder_name"])
    return jsonify({"result": result})


@app.route("/api/edit_folder_name", methods=["POST"])
def api_edit_folder_name():
    data = request.get_json()
    result = _edit_folder_name(data["old_name"], data["new_name"], data.get("new_emoji"))
    return jsonify({"result": result})


@app.route("/api/edit_task", methods=["POST"])
def api_edit_task():
    data = request.get_json()
    result = _edit_task(
        data["old_task_name"],
        data.get("new_task_name"),
        data.get("new_folder"),
        data.get("new_recurrence"),
        data.get("new_time"),
        data.get("new_duration")
    )
    return jsonify({"result": result})


@app.route("/api/get_folder_contents", methods=["POST"])
def api_get_folder_contents():
    data = request.get_json()
    result = _get_folder_contents(data["folder_name"])
    return jsonify({"result": result})


@app.route("/api/list_all_folders", methods=["GET"])
def api_list_all_folders():
    result = _list_all_folders()
    return jsonify({"result": result})


# ============================================
# REGISTER TOOLS WITH LETTA
# ============================================

def register_tools():
    tools = []
    functions = [
        create_folder, create_task, move_task, delete_task,
        delete_folder, edit_folder_name, edit_task,
        get_folder_contents, list_all_folders
    ]

    print("Registering tools with Letta...")

    for func in functions:
        try:
            t = client.tools.upsert_from_function(func=func)
            tools.append(t.id)
            print(f"✅ Registered tool: {t.name} ({t.id})")
        except Exception as e:
            print(f"❌ Error registering tool {func.__name__}: {e}")

    return tools


# ============================================
# AGENT HANDLING
# ============================================

def get_or_create_agent():
    global agent_id

    tool_ids = register_tools()

    if os.path.exists(".voicelog_agent_id"):
        with open(".voicelog_agent_id") as f:
            agent_id = f.read().strip()
            print(f"Using existing agent: {agent_id}")

        for tid in tool_ids:
            try:
                client.agents.tools.attach(agent_id=agent_id, tool_id=tid)
            except:
                pass

        return agent_id

    agent = client.agents.create(
        model="openai/gpt-4o-mini",
        memory_blocks=[
            {
                "label": "persona",
                "value": """You are VoiceLog AI, a helpful task management assistant. 
You help users organize their tasks into folders and manage them efficiently.
You can create folders, add tasks, move tasks between folders, edit tasks and folders, 
and help users stay organized. Always be friendly and concise in your responses."""
            }
        ],
        tool_ids=tool_ids
    )

    agent_id = agent.id
    with open(".voicelog_agent_id", "w") as f:
        f.write(agent_id)

    print(f"Created new agent: {agent_id}")
    return agent_id


# ============================================
# FLASK ROUTES
# ============================================

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "agent_id": agent_id})


@app.route("/process_command", methods=["POST"])
def process():
    data = request.get_json()
    text = data.get("text", "").strip()

    if not text:
        return jsonify({"error": "empty text"}), 400

    agent_id_local = agent_id or get_or_create_agent()

    print(f"📨 Received command: {text}")

    try:
        response = client.agents.messages.create(
            agent_id=agent_id_local,
            messages=[{"role": "user", "content": text}]
        )

        final = ""
        for m in response.messages:
            if hasattr(m, "content") and m.content:
                final += m.content + " "

        final = final.strip()
        print(f"✅ Response: {final}")

        return jsonify({"response": final})

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/folders")
def get_folders():
    folders = db.collection('folders').stream()
    folder_list = []
    
    for folder in folders:
        folder_data = folder.to_dict()
        folder_list.append({
            'id': folder.id,
            'name': folder_data['name'],
            'emoji': folder_data.get('emoji', '')
        })
    
    return jsonify({"folders": folder_list, "success": True})


@app.route("/folders/<fid>/tasks")
def get_tasks(fid):
    tasks = db.collection('tasks').where('folder', '==', fid).stream()
    task_list = []
    
    for task in tasks:
        task_data = task.to_dict()
        task_list.append({
            'id': task.id,
            'name': task_data['name'],
            'completed': task_data.get('completed', False),
            'recurrence': task_data.get('recurrence', 'once'),
            'time': task_data.get('time'),
            'duration': task_data.get('duration'),
            'folder': task_data['folder']
        })
    
    return jsonify({"tasks": task_list, "success": True})


@app.route("/tasks")
def all_tasks():
    tasks = db.collection('tasks').stream()
    task_list = []
    
    for task in tasks:
        task_data = task.to_dict()
        task_list.append({
            'id': task.id,
            'name': task_data['name'],
            'completed': task_data.get('completed', False),
            'folder': task_data['folder']
        })
    
    return jsonify({"tasks": task_list, "success": True})


# ============================================
# START SERVER
# ============================================

if __name__ == "__main__":
    get_or_create_agent()
    print("VoiceLog backend running on port 5002...")
    app.run(host="0.0.0.0", port=5002, debug=True)