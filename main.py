# ===== Imports =====
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from fastapi import FastAPI
from neo4j import GraphDatabase   # ✅ NEW

# ===== Lazy Model Loading =====
model = None

def get_model():
    global model
    if model is None:
        model = SentenceTransformer('all-MiniLM-L6-v2')
    return model


# ===== FAISS Setup =====
dimension = 384
index = faiss.IndexFlatL2(dimension)

memory_store = []


# ===== Neo4j Setup (Stage 4) =====
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "password"

driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))


# ===== Triplet Extraction =====
def extract_triplet(text):
    words = text.split()
    if len(words) >= 3:
        return words[0], words[1], words[2]
    return None, None, None


# ===== Graph Store =====
def create_relation(tx, subject, relation, obj):
    query = """
    MERGE (a:Concept {name: $subject})
    MERGE (b:Concept {name: $object})
    MERGE (a)-[:REL {type: $relation}]->(b)
    """
    tx.run(query, subject=subject, object=obj, relation=relation)


def add_to_graph(subject, relation, obj):
    with driver.session() as session:
        session.write_transaction(create_relation, subject, relation, obj)


# ===== Store Memory (FAISS + Graph) =====
def store_memory(memory):
    text = memory["content"]

    # ❗ prevent duplicate storage
    for m in memory_store:
        if m["content"] == text:
            return

    # ===== FAISS =====
    embedding = get_model().encode([text])[0]
    embedding = np.array([embedding]).astype('float32')

    index.add(embedding)
    memory_store.append(memory)

    # ===== GRAPH (NEW) =====
    subject, relation, obj = extract_triplet(text)

    if subject and relation and obj:
        add_to_graph(subject, relation, obj)


# ===== Search Memory (FAISS) =====
def search_memory(query, top_k=5):
    query_embedding = get_model().encode([query])[0]
    query_embedding = np.array([query_embedding]).astype('float32')

    distances, indices = index.search(query_embedding, top_k)

    results = []
    seen = set()

    for i, dist in zip(indices[0], distances[0]):
        if i < len(memory_store):
            content = memory_store[i]["content"]

            if content in seen:
                continue

            if dist < 1.0:
                results.append(memory_store[i])
                seen.add(content)

    return results


# ===== Graph Query =====
def get_related(tx, concept):
    query = """
    MATCH (a:Concept {name: $concept})-[r]->(b)
    RETURN b.name AS related, r.type AS relation
    """
    result = tx.run(query, concept=concept)
    return [record.data() for record in result]


# ===== FastAPI App =====
app = FastAPI()


# ===== API: Store =====
@app.post("/store")
def store(mem: dict):
    store_memory(mem)
    return {"message": "Memory stored successfully"}


# ===== API: Vector Query =====
@app.get("/query")
def query(q: str):
    results = search_memory(q)
    return {"results": results}


# ===== API: Graph Query (NEW) =====
@app.get("/graph")
def graph(concept: str):
    with driver.session() as session:
        data = session.read_transaction(get_related, concept)
    return {"results": data}