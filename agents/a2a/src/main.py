import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI()

# Agent Card — describes this agent to any A2A client
AGENT_CARD = {
    "name": "cert-agent",
    "version": "1.0.0",
    "description": "Certificate lab A2A agent",
    "url": os.getenv("AGENT_URL", "http://a2a-agent.kagent.svc.cluster.local:8000"),
    "capabilities": {
        "streaming": False,
        "pushNotifications": False
    },
    "skills": [
        {
            "id": "answer_question",
            "name": "Answer Question",
            "description": "Answers a plain-text question",
            "inputModes":  ["text/plain"],
            "outputModes": ["text/plain"]
        }
    ]
}

@app.get("/.well-known/agent.json")
async def agent_card():
    """A2A discovery endpoint — must be accessible at this exact path."""
    return JSONResponse(AGENT_CARD)

@app.post("/tasks")
async def create_task(body: dict):
    """Receive an A2A task and return an artifact."""
    parts = body.get("message", {}).get("parts", [])
    text  = parts[0].get("text", "") if parts else ""
    return {
        "id": "task-001",
        "status": {"state": "completed"},
        "artifacts": [
            {"parts": [{"type": "text", "text": f"Received: {text}"}]}
        ]
    }

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)