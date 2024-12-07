from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Set, Optional
import asyncio
import uvicorn
import requests
import uuid
from datetime import datetime
import json
import base64

import os
import httpx

from enum import Enum
import random
from typing import Dict, List, Optional, Set
import asyncio
from dotenv import load_dotenv
load_dotenv()

# Update your constants to use environment variables
GETIMG_API_KEY = os.getenv("GETIMG_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
DEFAULT_SIZE = 1024
GETIMG_API_BASE = "https://api.getimg.ai/v1"
TEXT_TO_IMAGE_URL = f"{GETIMG_API_BASE}/flux-schnell/text-to-image"
GETIMG_API_KEY = "key-43UOsOppfzIPRWQ3uMaXDo2TFXuSDbj6H6ttFPdaIOWGKV6XW4GnZ9uLG9DTgWUtFNecW6uiHzEMQlzhKQ0hJQ43HKGJWiP7"




from pymongo import MongoClient
from datetime import datetime
from typing import Optional, Dict, List
from bson import ObjectId

# MongoDB connection
MONGO_URI = "mongodb+srv://simongage0:Slug3.14159@cluster1.yc2fw.mongodb.net/?retryWrites=true&w=majority&appName=Cluster1"

client = MongoClient(MONGO_URI)
db = client.image_generation_db

# Collections
users_collection = db.users
nodes_collection = db.nodes

@app.get("/workspaces/{username}")
async def get_user_workspaces(username: str):
    """Get all workspaces for a user"""
    try:
        user = await DatabaseManager.get_user(username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        workspaces = []
        for workspace_id, workspace in workspace_manager.workspaces.items():
            if username in workspace['members']:
                workspaces.append({
                    "id": workspace_id,
                    "name": workspace['name'],
                    "creator": workspace['creator'],
                    "member_count": len(workspace['members']),
                    "created_at": workspace.get('created_at', datetime.now().isoformat()),
                    "is_creator": workspace['creator'] == username
                })
        
        return {"workspaces": workspaces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/workspaces")
async def create_new_workspace(username: str, name: str):
    """Create a new workspace"""
    try:
        workspace_id = str(uuid.uuid4())
        workspace_manager.create_workspace(workspace_id, username, name)
        
        return {
            "workspace_id": workspace_id,
            "name": name,
            "creator": username
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/workspaces/{workspace_id}")
async def delete_workspace(workspace_id: str, username: str):
    """Delete a workspace (only creator can delete)"""
    workspace = workspace_manager.workspaces.get(workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    
    if workspace['creator'] != username:
        raise HTTPException(status_code=403, detail="Only the creator can delete a workspace")
    
    workspace_manager.delete_workspace(workspace_id)
    return {"status": "success"}
class DatabaseManager:
    @staticmethod
    async def create_user(username: str) -> Dict:
        """Create a new user if username doesn't exist"""
        if users_collection.find_one({"username": username}):
            raise ValueError("Username already exists")
        
        user = {
            "username": username,
            "created_at": datetime.utcnow(),
            "last_active": datetime.utcnow()
        }
        result = users_collection.insert_one(user)
        user["_id"] = result.inserted_id
        return user

    @staticmethod
    async def get_user(username: str) -> Optional[Dict]:
        """Get user by username"""
        return users_collection.find_one({"username": username})

    @staticmethod
    async def update_user_activity(username: str):
        """Update user's last active timestamp"""
        users_collection.update_one(
            {"username": username},
            {"$set": {"last_active": datetime.utcnow()}}
        )

    @staticmethod
    async def create_node(
        workspace_id: str,
        node_id: str,
        text: str,
        image: str,
        username: str,
        parent_id: Optional[str] = None,
        full_prompt: Optional[str] = None
    ) -> Dict:
        """Create a new node in the tree"""
        node = {
            "node_id": node_id,
            "workspace_id": workspace_id,
            "text": text,
            "image": image,
            "created_by": username,
            "created_at": datetime.utcnow(),
            "parent_id": parent_id,
            "full_prompt": full_prompt or text
        }
        result = nodes_collection.insert_one(node)
        node["_id"] = result.inserted_id
        return node

    @staticmethod
    async def update_node(
        node_id: str,
        text: str,
        image: str,
        username: str
    ) -> Optional[Dict]:
        """Update an existing node"""
        result = nodes_collection.update_one(
            {"node_id": node_id},
            {
                "$set": {
                    "text": text,
                    "image": image,
                    "updated_by": username,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        if result.modified_count:
            return nodes_collection.find_one({"node_id": node_id})
        return None

    @staticmethod
    async def get_workspace_nodes(workspace_id: str) -> List[Dict]:
        """Get all nodes for a workspace"""
        return list(nodes_collection.find({"workspace_id": workspace_id}))

    @staticmethod
    async def get_node_chain(node_id: str) -> List[Dict]:
        """Get the chain of nodes from root to target"""
        chain = []
        current_node = nodes_collection.find_one({"node_id": node_id})
        
        while current_node:
            chain.insert(0, current_node)
            if not current_node.get("parent_id"):
                break
            current_node = nodes_collection.find_one({"node_id": current_node["parent_id"]})
        
        return chain

# Initialize indexes
users_collection.create_index("username", unique=True)
nodes_collection.create_index("node_id", unique=True)
nodes_collection.create_index("workspace_id")
nodes_collection.create_index("parent_id")
class WorkspaceManager:
    def __init__(self):
        self.workspaces = {}  # workspace_id -> workspace info
        self.user_workspaces = {}  # user_id -> set of workspace_ids
        self.workspace_connections = {}  # workspace_id -> set of websockets
        
        # Create default workspace on initialization
        self.create_workspace("default", "system", "Default Workspace")

    def create_workspace(self, workspace_id: str, creator_id: str, name: str = "Default Workspace"):
        """Create a new workspace"""
        self.workspaces[workspace_id] = {
            'name': name,
            'creator': creator_id,
            'members': {creator_id},
            'chat_history': [],
            'prompt_trees': {}
        }
        self.workspace_connections[workspace_id] = set()
        self.add_user_to_workspace(creator_id, workspace_id)

    def add_user_to_workspace(self, user_id: str, workspace_id: str):
        """Add a user to a workspace"""
        if workspace_id not in self.workspaces:
            raise ValueError("Workspace does not exist")
        
        self.workspaces[workspace_id]['members'].add(user_id)
        if user_id not in self.user_workspaces:
            self.user_workspaces[user_id] = set()
        self.user_workspaces[user_id].add(workspace_id)

    async def connect_to_workspace(self, websocket: WebSocket, workspace_id: str):
        """Connect a websocket to a workspace"""
        if workspace_id not in self.workspaces:
            print(f"Creating new workspace: {workspace_id}")  # Debug log
            self.create_workspace(workspace_id, "system", f"Workspace {workspace_id}")
        
        self.workspace_connections[workspace_id].add(websocket)
        
        # Send workspace history
        workspace = self.workspaces[workspace_id]
        for message in workspace['chat_history']:
            try:
                await websocket.send_json(message)
            except Exception:
                break

    def disconnect_from_workspace(self, websocket: WebSocket, workspace_id: str):
        """Disconnect a websocket from a workspace"""
        if workspace_id in self.workspace_connections:
            self.workspace_connections[workspace_id].discard(websocket)

    def delete_workspace(self, workspace_id: str):
        """Delete a workspace and clean up connections"""
        if workspace_id in self.workspaces:
            # Remove workspace from user mappings
            workspace = self.workspaces[workspace_id]
            for user_id in workspace['members']:
                if user_id in self.user_workspaces:
                    self.user_workspaces[user_id].discard(workspace_id)
                    if not self.user_workspaces[user_id]:
                        del self.user_workspaces[user_id]
            
            # Close all connections
            for connection in list(self.workspace_connections.get(workspace_id, set())):
                self.disconnect_from_workspace(connection, workspace_id)
            
            # Remove workspace data
            del self.workspaces[workspace_id]
            if workspace_id in self.workspace_connections:
                del self.workspace_connections[workspace_id]

    async def broadcast_to_workspace(self, workspace_id: str, message: dict):
        """Broadcast a message to all connections in a workspace"""
        if workspace_id not in self.workspaces:
            return
        
        # Add message to workspace history
        self.workspaces[workspace_id]['chat_history'].append(message)
        
        # Update prompt tree if applicable
        self.update_workspace_prompt_tree(workspace_id, message)
        
        # Broadcast to all connections
        disconnected = set()
        for connection in self.workspace_connections[workspace_id]:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        
        # Clean up disconnected websockets
        for connection in disconnected:
            self.disconnect_from_workspace(connection, workspace_id)

    def update_workspace_prompt_tree(self, workspace_id: str, message: dict):
        """Update the prompt tree for a workspace"""
        workspace = self.workspaces[workspace_id]
        prompt_trees = workspace['prompt_trees']
        
        if message.get('type') == 'update':
            self._update_node_and_children(workspace_id, message['id'], message['text'])
        elif not message.get('parentId'):
            prompt_trees[message['id']] = {
                'prompt': message['text'],
                'children': {},
                'cumulative_prompt': message['text']
            }
        else:
            parent_id = message['parentId']
            for tree in prompt_trees.values():
                if self._add_to_tree(tree, parent_id, message):
                    break

    def _update_node_and_children(self, workspace_id: str, node_id: str, new_prompt: str):
        """Update a node and recalculate all descendants in a workspace"""
        node = self._find_node_in_workspace(workspace_id, node_id)
        if not node:
            raise ValueError(f"Node {node_id} not found in workspace")

        node['prompt'] = new_prompt
        cumulative_prompt = self.get_workspace_cumulative_prompt(workspace_id, node_id)
        node['cumulative_prompt'] = cumulative_prompt
        self._recalculate_children_prompts(node)

    def _find_node_in_workspace(self, workspace_id: str, node_id: str) -> Optional[Dict]:
        """Find a node in a workspace's prompt trees"""
        workspace = self.workspaces[workspace_id]
        prompt_trees = workspace['prompt_trees']
        
        if node_id in prompt_trees:
            return prompt_trees[node_id]
        
        for root_node in prompt_trees.values():
            found_node = self._find_node_recursive(root_node, node_id)
            if found_node:
                return found_node
        return None

    def _find_node_recursive(self, current_node: Dict, target_id: str) -> Optional[Dict]:
        """Recursively search for a node in the tree"""
        for child_id, child_node in current_node.get('children', {}).items():
            if child_id == target_id:
                return child_node
            found_in_child = self._find_node_recursive(child_node, target_id)
            if found_in_child:
                return found_in_child
        return None

    def get_workspace_cumulative_prompt(self, workspace_id: str, node_id: str) -> str:
        """Get the full cumulative prompt for a node in a workspace"""
        node_chain = self.get_workspace_node_chain(workspace_id, node_id)
        if node_chain:
            return ", ".join(node['prompt'] for node in node_chain)
        raise ValueError(f"Node {node_id} not found in workspace")

    def get_workspace_node_chain(self, workspace_id: str, node_id: str) -> List[Dict]:
        """Get the chain of nodes from root to target in a workspace"""
        workspace = self.workspaces[workspace_id]
        prompt_trees = workspace['prompt_trees']
        
        if node_id in prompt_trees:
            return [{'id': node_id, 'prompt': prompt_trees[node_id]['prompt']}]
        
        for root_id, tree in prompt_trees.items():
            chain = []
            if self._find_node_chain(tree, node_id, chain):
                chain.insert(0, {'id': root_id, 'prompt': tree['prompt']})
                return chain
        return []

    def _find_node_chain(self, node: dict, target_id: str, chain: List[Dict]) -> bool:
        """Recursively build the chain of nodes to target"""
        if not node.get('children'):
            return False
        
        for child_id, child in node['children'].items():
            if child_id == target_id:
                chain.append({'id': child_id, 'prompt': child['prompt']})
                return True
            
            if self._find_node_chain(child, target_id, chain):
                chain.insert(-1, {'id': child_id, 'prompt': child['prompt']})
                return True
        return False

    def _add_to_tree(self, tree: dict, parent_id: str, message: dict) -> bool:
        """Add a new node under the specified parent"""
        parent_node = self._find_node_recursive(tree, parent_id)
        if not parent_node:
            return False

        cumulative_prompt = f"{parent_node['cumulative_prompt']}, {message['text']}"
        
        if 'children' not in parent_node:
            parent_node['children'] = {}
            
        parent_node['children'][message['id']] = {
            'prompt': message['text'],
            'children': {},
            'cumulative_prompt': cumulative_prompt
        }
        return True

    def _recalculate_children_prompts(self, node: dict):
        """Update cumulative prompts for all descendants"""
        if not node.get('children'):
            return
            
        parent_prompt = node['cumulative_prompt']
        for child in node['children'].values():
            child['cumulative_prompt'] = f"{parent_prompt}, {child['prompt']}"
            self._recalculate_children_prompts(child)
# Create workspace manager instance
workspace_manager = WorkspaceManager()
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.chat_history: List[Dict] = []
        self.prompt_trees: Dict[str, Dict] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        self.chat_history.append(message)
        self.update_prompt_tree(message)
        disconnected = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.add(connection)
        for connection in disconnected:
            self.disconnect(connection)

    def find_node_in_tree(self, node_id: str) -> Optional[Dict]:
        """Find a node in any tree by its ID"""
        # Check root nodes first
        if node_id in self.prompt_trees:
            return self.prompt_trees[node_id]
        
        # Search in all trees
        for root_node in self.prompt_trees.values():
            found_node = self._find_node_recursive(root_node, node_id)
            if found_node:
                return found_node
        return None

    def _find_node_recursive(self, current_node: Dict, target_id: str) -> Optional[Dict]:
        """Recursively search for a node in the tree"""
        for child_id, child_node in current_node.get('children', {}).items():
            if child_id == target_id:
                return child_node
            found_in_child = self._find_node_recursive(child_node, target_id)
            if found_in_child:
                return found_in_child
        return None

    def get_node_chain(self, node_id: str) -> List[Dict]:
        """Get the chain of nodes from root to target"""
        # For root nodes
        if node_id in self.prompt_trees:
            return [{'id': node_id, 'prompt': self.prompt_trees[node_id]['prompt']}]
        
        # For child nodes
        for root_id, tree in self.prompt_trees.items():
            chain = []
            if self._find_node_chain(tree, node_id, chain):
                chain.insert(0, {'id': root_id, 'prompt': tree['prompt']})
                return chain
        return []

    def _find_node_chain(self, node: dict, target_id: str, chain: List[Dict]) -> bool:
        """Recursively build the chain of nodes to target"""
        if not node.get('children'):
            return False

        for child_id, child in node['children'].items():
            if child_id == target_id:
                chain.append({'id': child_id, 'prompt': child['prompt']})
                return True
            
            if self._find_node_chain(child, target_id, chain):
                chain.insert(-1, {'id': child_id, 'prompt': child['prompt']})
                return True
        return False

    def get_cumulative_prompt(self, node_id: str) -> str:
        """Get the full cumulative prompt for a node"""
        try:
            node_chain = self.get_node_chain(node_id)
            if node_chain:
                return ", ".join(node['prompt'] for node in node_chain)
            raise ValueError(f"Node {node_id} not found in any prompt tree")
        except Exception as e:
            print(f"Error getting cumulative prompt for node {node_id}: {str(e)}")
            raise

    def update_prompt_tree(self, message: dict):
        """Update the prompt tree with a new message"""
        try:
            if message.get('type') == 'update':
                # For reloaded nodes
                self.update_node_and_children(message['id'], message['text'])
            elif not message.get('parentId'):
                # For new root nodes
                self.prompt_trees[message['id']] = {
                    'prompt': message['text'],
                    'children': {},
                    'cumulative_prompt': message['text']
                }
            else:
                # For new child nodes
                parent_id = message['parentId']
                for tree in self.prompt_trees.values():
                    if self.add_to_tree(tree, parent_id, message):
                        break
        except Exception as e:
            print(f"Error updating prompt tree: {str(e)}")
            raise

    def update_node_and_children(self, node_id: str, new_prompt: str):
        """Update a node and recalculate all descendants"""
        node = self.find_node_in_tree(node_id)
        if not node:
            raise ValueError(f"Node {node_id} not found in any prompt tree")

        node['prompt'] = new_prompt
        # Update cumulative prompts for this node and all descendants
        cumulative_prompt = self.get_cumulative_prompt(node_id)
        node['cumulative_prompt'] = cumulative_prompt
        self.recalculate_children_prompts(node)

    def add_to_tree(self, tree: dict, parent_id: str, message: dict) -> bool:
        """Add a new node under the specified parent"""
        parent_node = self.find_node_in_tree(parent_id)
        if not parent_node:
            return False

        # Create cumulative prompt from parent chain
        cumulative_prompt = f"{parent_node['cumulative_prompt']}, {message['text']}"
        
        # Add new node
        if 'children' not in parent_node:
            parent_node['children'] = {}
            
        parent_node['children'][message['id']] = {
            'prompt': message['text'],
            'children': {},
            'cumulative_prompt': cumulative_prompt
        }
        return True

    def recalculate_children_prompts(self, node: dict):
        """Update cumulative prompts for all descendants"""
        if not node.get('children'):
            return
            
        parent_prompt = node['cumulative_prompt']
        for child in node['children'].values():
            child['cumulative_prompt'] = f"{parent_prompt}, {child['prompt']}"
            self.recalculate_children_prompts(child)


async def generate_image_async(prompt: str) -> str:
    """Generate an image using FLUX.1 [schnell] model"""
    if len(prompt) > 2048:
        raise ValueError("Prompt length exceeds 2048 characters")

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {GETIMG_API_KEY}"
    }
    
    payload = {
        "prompt": prompt,
        "width": DEFAULT_SIZE,
        "height": DEFAULT_SIZE,
        "steps": 4,
        "seed": 42,
        "output_format": "jpeg",
        "response_format": "b64"
    }
    
    try:
        response = await asyncio.to_thread(
            lambda: requests.post(TEXT_TO_IMAGE_URL, headers=headers, json=payload)
        )
        
        if response.status_code == 200:
            result = response.json()
            if "image" in result:
                return result["image"]
            else:
                raise ValueError(f"No image in response: {response.text}")
        else:
            raise ValueError(f"Image generation failed (Status {response.status_code}): {response.text}")
    except Exception as e:
        print(f"Error generating image: {str(e)}")
        raise

manager = ConnectionManager()

# Add these new REST endpoints at the top level of your FastAPI app
@app.post("/workspace")
async def create_workspace(creator_id: str, name: str = "Default Workspace"):
    """Create a new workspace and return its ID"""
    workspace_id = str(uuid.uuid4())
    workspace_manager.create_workspace(workspace_id, creator_id, name)
    return {"workspace_id": workspace_id}

@app.post("/workspace/{workspace_id}/join")
async def join_workspace(workspace_id: str, user_id: str):
    """Join an existing workspace"""
    try:
        workspace_manager.add_user_to_workspace(user_id, workspace_id)
        return {"status": "success"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.websocket("/ws/{workspace_id}")
async def websocket_endpoint(websocket: WebSocket, workspace_id: str):
    try:
        # 1. Accept the connection first
        await websocket.accept()

        # 2. Get username from query parameters
        username = websocket.query_params.get("username")
        if not username:
            await websocket.close(code=4000, reason="Username is required")
            return

        # 3. Create a default workspace if it doesn't exist
        if workspace_id not in workspace_manager.workspaces:
            workspace_manager.create_workspace(
                workspace_id=workspace_id,
                creator_id=username,
                name=f"Workspace {workspace_id}"
            )

        # 4. Create or verify user
        try:
            user = await DatabaseManager.get_user(username)
            if not user:
                user = await DatabaseManager.create_user(username)
        except ValueError as e:
            await websocket.close(code=4001, reason=str(e))
            return

        # 5. Add user to workspace if not already a member
        if username not in workspace_manager.workspaces[workspace_id]['members']:
            workspace_manager.add_user_to_workspace(username, workspace_id)

        # Add connection to workspace
        workspace_manager.workspace_connections[workspace_id].add(websocket)





        # Load existing nodes for the workspace
        existing_nodes = await DatabaseManager.get_workspace_nodes(workspace_id)
        for node in existing_nodes:
            try:
                await websocket.send_json({
                    "id": node["node_id"],
                    "text": node["text"],
                    "image": node["image"],
                    "parentId": node.get("parent_id"),
                    "userId": node["created_by"],
                    "username": node["created_by"],
                    "timestamp": node["created_at"].isoformat(),
                    "type": "new"
                })
            except Exception:
                break

        while True:
            try:
                data = await websocket.receive_json()
                
                if not isinstance(data, dict) or "text" not in data:
                    raise ValueError("Missing required field: text")

                # Update user activity
                await DatabaseManager.update_user_activity(username)
                
                if data.get("isReload"):
                    # Get the full cumulative prompt chain from the workspace
                    cumulative_prompt = workspace_manager.get_workspace_cumulative_prompt(
                        workspace_id, data.get("nodeId")
                    )
                    if not cumulative_prompt:
                        raise ValueError("Could not find node in workspace prompt tree")
                        
                    
                    generation_prompt = prompt_to_use

                    # Generate image
                    image_base64 = await generate_image_async(generation_prompt)

                    # Update node in database
                    node = await DatabaseManager.update_node(
                        data.get("nodeId"),
                        prompt_to_use,
                        image_base64,
                        username
                    )
                    
                    message = {
                        "id": data.get("nodeId"),
                        "text": prompt_to_use,
                        "original_text": cumulative_prompt,
                        "image": image_base64,
                        "userId": username,
                        "username": username,
                        "timestamp": datetime.now().isoformat(),
                        "isReload": True,
                        "type": "update"
                    }
                else:
                    prompt_to_use = data["text"]
                    generation_prompt = data.get("fullPrompt", prompt_to_use)
                    
                    # Generate image
                    image_base64 = await generate_image_async(generation_prompt)

                    # Create new node in database
                    node_id = str(uuid.uuid4())
                    node = await DatabaseManager.create_node(
                        workspace_id,
                        node_id,
                        prompt_to_use,
                        image_base64,
                        username,
                        data.get("parentId"),
                        generation_prompt
                    )
                    
                    message = {
                        "id": node_id,
                        "text": prompt_to_use,
                        "original_text": data["text"],
                        "fullPrompt": generation_prompt,
                        "image": image_base64,
                        "parentId": data.get("parentId"),
                        "userId": username,
                        "username": username,
                        "timestamp": datetime.now().isoformat(),
                        "type": "new"
                    }
                
                await workspace_manager.broadcast_to_workspace(workspace_id, message)
                
            except WebSocketDisconnect:
                break
            except Exception as e:
                try:
                    error_message = {
                        "id": str(uuid.uuid4()),
                        "error": str(e),
                        "userId": username,
                        "username": username,
                        "timestamp": datetime.now().isoformat()
                    }
                    await websocket.send_json(error_message)
                except:
                    break
                    
    except WebSocketDisconnect:
        workspace_manager.disconnect_from_workspace(websocket, workspace_id)
    except Exception as e:
        print(f"Unexpected error in websocket connection: {str(e)}")
        workspace_manager.disconnect_from_workspace(websocket, workspace_id)
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))  # Default to 8080 for Cloud Run
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)