from fastapi import FastAPI, HTTPException, Query
from contextlib import asynccontextmanager
from .engine import MemoryEngine
# from .refiner import KnowledgeRefiner

# Global instances
engine = MemoryEngine()
# refiner = KnowledgeRefiner()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        engine.init_db()
    except Exception as e:
        print(f"⚠️ Memory Engine Init Warning: {e}")
    yield
    # Shutdown
    engine.close()

app = FastAPI(title="DACMI Memory Service", lifespan=lifespan)

@app.post("/store")
async def store_memory(data: dict):
    content = data.get("content")
    creator_id = data.get("creator_id", "system")
    privacy = data.get("privacy", "public")
    
    importance = data.get("importance")
    min_importance = data.get("min_importance", 0.2)
    
    # Optional triplets from brain
    triplets = data.get("triplets", [])
    # Handle legacy single-triplet fields if present
    if not triplets:
        sub = data.get("subject")
        rel = data.get("relation")
        obj = data.get("object")
        if sub and rel and obj:
            triplets = [(sub, rel, obj)]
    
    if not content:
        raise HTTPException(status_code=400, detail="Missing content")
    
    status = engine.store(
        content, 
        creator_id=creator_id, 
        privacy=privacy, 
        min_importance=min_importance,
        importance_override=importance,
        triplets_override=triplets
    )
    
    return {
        "status": status,
        "meta": {
            "creator_id": creator_id, 
            "privacy": privacy,
            "importance": importance,
            "triplets": triplets
        }
    }

# @app.post("/refine")
# async def refine_knowledge(user_id: str):
#     try:
#         summary_report = await refiner.summarize_clusters(user_id)
#         prune_report = await refiner.prune_weak_memories(user_id)
#         return {
#             "status": "Refinement Complete",
#             "summarization": summary_report,
#             "pruning": prune_report
#         }
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

@app.get("/query")
async def query_memory(
    q: str, 
    user_id: str | None = Query(None, description="ID of the user making the query"),
    top_k: int = 5
):
    results = engine.hybrid_search(q, user_id=user_id, top_k=top_k)
    return results

@app.get("/graph")
async def get_graph(
    concept: str,
    user_id: str | None = Query(None, description="ID of the user making the query")
):
    data = engine.get_related_graph(concept, user_id=user_id)
    return {"results": data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
