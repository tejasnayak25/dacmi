import os
import json
from fastapi import FastAPI, Depends, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .brain import IntelligenceBrain
from jose import jwt, jwk
from dotenv import load_dotenv

# Load environment variables at the absolute start
load_dotenv()

app = FastAPI(title="DACMI Intelligence Service")
brain = IntelligenceBrain()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- AUTHENTICATION LOGIC (Restored & Reliable) ---
RAW_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()

def get_verification_key():
    try:
        # Clean the secret (strip all quote variants)
        clean_secret = RAW_JWT_SECRET.replace("'", "").replace('"', "").strip()
        
        # DEBUG: Print status (Censored)
        print(f"📡 Neural Security Init: Secret Length = {len(clean_secret)}")
        
        if clean_secret.startswith('{') and clean_secret.endswith('}'):
            print("💎 Detected JSON JWK format. Constructing key...")
            jwk_dict = json.loads(clean_secret)
            return jwk.construct(jwk_dict)
        
        print("📝 Detected Plain String format.")
        return clean_secret
    except Exception as e:
        print(f"⚠️ JWT Key Construction Error: {e}")
        return RAW_JWT_SECRET

VERIFICATION_KEY = get_verification_key()
ALLOWED_ALGORITHMS = ["HS256", "ES256"]

async def get_current_user(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing auth header")
    
    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, VERIFICATION_KEY, algorithms=ALLOWED_ALGORITHMS, audience="authenticated")
        return payload["sub"]
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")

# --- WEBSOCKET CHAT ---

@app.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    user_id = None
    history = []
    
    try:
        # 1. Initial Auth Handshake
        auth_msg = await websocket.receive_text()
        try:
            auth_data = json.loads(auth_msg)
            token = auth_data.get("token")
        except:
            token = auth_msg.strip()

        if not token or token in ["undefined", "null", ""]:
            print("❌ Neural Link: Received invalid token.")
            await websocket.send_json({"type": "auth_status", "status": "failed", "error": "Token missing"})
            await websocket.close()
            return

        try:
            # Universal verification
            payload = jwt.decode(token, VERIFICATION_KEY, algorithms=ALLOWED_ALGORITHMS, audience="authenticated")
            user_id = payload["sub"]
            await websocket.send_json({"type": "auth_status", "status": "success"})
            print(f"✅ Neural Link Verified: {user_id}")
        except Exception as e:
            print(f"❌ Neural Link Auth Failed: {e}")
            await websocket.send_json({"type": "auth_status", "status": "failed", "error": str(e)})
            await websocket.close()
            return

        # 2. Chat Loop
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            query = message_data.get("text")
            
            if not query:
                continue

            result = await brain.ask_with_history(query, history, user_id=user_id)
            
            history.append({"role": "user", "content": query})
            history.append({"role": "assistant", "content": result["answer"]})
            if len(history) > 10:
                history = history[-10:]
            
            await websocket.send_json({
                "type": "message",
                "answer": result["answer"],
                "storage_log": result["storage_log"],
                "context_used": result["context_used"],
                "related_concepts": result["related_concepts"]
            })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"⚠️ Neural Link Error: {e}")
        try:
            await websocket.close()
        except:
            pass

# Serve static files
app.mount("/static", StaticFiles(directory="intelligence_service/static"), name="static")

@app.get("/")
async def read_index():
    from fastapi.responses import FileResponse
    return FileResponse("intelligence_service/static/index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, ws_ping_interval=20, ws_ping_timeout=20)
