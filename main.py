# ===== Imports =====
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from fastapi import FastAPI

# ===== Lazy Model Loading =====
model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer('all-MiniLM-L6-v2')  
        # WHY: lightweight, fast, no API cost
    return model


# ===== FAISS Setup =====
dimension = 384  # must match embedding size
index = faiss.IndexFlatL2(dimension)  
# WHY: simple + accurate for small projects

memory_store = []  # stores actual text data


# ===== Store Memory =====
def store_memory(memory):
    text = memory["content"]

    # ❗ Prevent duplicate storage
    for m in memory_store:
        if m["content"] == text:
            return  # skip if already exists

    embedding = get_model().encode([text])[0]
    embedding = np.array([embedding]).astype('float32')

    index.add(embedding)  
    memory_store.append(memory)


# ===== Search Memory =====
def search_memory(query, top_k=5):
    query_embedding = get_model().encode([query])[0]
    query_embedding = np.array([query_embedding]).astype('float32')

    distances, indices = index.search(query_embedding, top_k)

    results = []
    seen = set()  # ❗ remove duplicate results

    for i in indices[0]:
        if i < len(memory_store):
            content = memory_store[i]["content"]

            if content not in seen:
                results.append(memory_store[i])
                seen.add(content)

    return results


# ===== FastAPI App =====
app = FastAPI()


@app.post("/store")
def store(mem: dict):
    store_memory(mem)
    return {"message": "Memory stored successfully"}


@app.get("/query")
def query(q: str):
    results = search_memory(q)
    return {"results": results}


# ===== How it works =====
# Store → text → embedding → FAISS index + memory_store
# Query → embedding → FAISS search → filter duplicates → return result