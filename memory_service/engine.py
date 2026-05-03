import os
import faiss
import numpy as np
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()

# ===== Configuration =====
STORAGE_DIR = "storage"
FAISS_INDEX_PATH = os.path.join(STORAGE_DIR, "faiss.index")
MEMORIES_JSON_PATH = os.path.join(STORAGE_DIR, "memories.json")

if not os.path.exists(STORAGE_DIR):
    os.makedirs(STORAGE_DIR)

# ===== Lazy Model Loading =====
_model = None

def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model


class MemoryEngine:
    def __init__(self):
        # FAISS Setup
        self.dimension = 384
        
        # Load existing data if available
        if os.path.exists(FAISS_INDEX_PATH):
            self.index = faiss.read_index(FAISS_INDEX_PATH)
            print("📂 Loaded existing FAISS index")
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            print("✨ Created new FAISS index")

        if os.path.exists(MEMORIES_JSON_PATH):
            with open(MEMORIES_JSON_PATH, "r") as f:
                self.memory_store = json.load(f)
            self.memory_seen = {m["content"] for m in self.memory_store}
            print(f"📂 Loaded {len(self.memory_store)} memories from disk")
        else:
            self.memory_store = []
            self.memory_seen = set()

        # Neo4j Setup
        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USERNAME", "neo4j")
        self.pwd = os.getenv("NEO4J_PASSWORD", "password123")
        self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.pwd))

    def _persist(self):
        """Save the vector index and memory store to disk."""
        faiss.write_index(self.index, FAISS_INDEX_PATH)
        with open(MEMORIES_JSON_PATH, "w") as f:
            json.dump(self.memory_store, f)

    def init_db(self):
        with self.driver.session() as session:
            # 1. Constraints
            session.run("CREATE CONSTRAINT concept_name IF NOT EXISTS FOR (c:Concept) REQUIRE c.name IS UNIQUE")
            session.run("CREATE CONSTRAINT user_name IF NOT EXISTS FOR (u:User) REQUIRE u.name IS UNIQUE")
            session.run("CREATE CONSTRAINT tag_name IF NOT EXISTS FOR (t:Tag) REQUIRE t.name IS UNIQUE")
            
            # 2. Migration
            session.run("MATCH (c:Concept) WHERE c.privacy IS NULL SET c.privacy = 'public', c.creator_id = 'system'")
            session.run("MATCH ()-[r:REL]->() WHERE r.privacy IS NULL SET r.privacy = 'public', r.creator_id = 'system', r.importance = 0.5")
            
        print(f"✅ Neo4j initialized and migrated on {self.uri}")

    def close(self):
        self._persist()
        self.driver.close()

    def _extract_triplet(self, text):
        # Improved fallback: skip common leading stop words
        stop_words = {"the", "a", "an", "this", "that", "those", "these"}
        pronoun_map = {"i": "User", "me": "User", "my": "User", "you": "DACMI", "your": "DACMI"}
        
        raw_words = text.lower().strip().split()
        if not raw_words: return None, None, None
        
        # Question Detection
        question_starters = {"do", "did", "does", "have", "has", "can", "could", "will", "would", "what", "how", "why", "where", "when"}
        is_question = raw_words[0] in question_starters or text.endswith('?')
        
        words = [w for w in text.split() if w.lower() not in stop_words]
        
        def normalize(word):
            return pronoun_map.get(word.lower(), word.capitalize())

        if is_question:
            # If the user asks a question, they are the subject
            meaningful_words = [w for w in words if w.lower() not in question_starters and w.lower() not in {"you", "your"}]
            obj = " ".join(meaningful_words[:2]).capitalize() if meaningful_words else "Query"
            return "User", "asks about", obj

        if len(words) >= 3:
            return normalize(words[0]), words[1], normalize(words[2])
        elif len(words) == 2:
            return normalize(words[0]), "is", normalize(words[1])
        return None, None, None

    def _calculate_importance(self, content):
        words = content.split()
        score = min(1.0, len(words) / 20.0)
        return round(score, 2)

    def store(self, content, creator_id="system", privacy="public", min_importance=0.2, 
              importance_override=None, triplet_override=None):
        """Store memory with optional pre-extracted metadata."""
        if content in self.memory_seen:
            return "duplicate"

        importance = importance_override if importance_override is not None else self._calculate_importance(content)
        
        if importance < min_importance:
            return "discarded (low importance)"

        embedding = get_model().encode([content])[0]
        embedding = np.array([embedding]).astype('float32')
        
        # --- Semantic Deduplication ---
        if self.index.ntotal > 0:
            distances, indices = self.index.search(embedding, 1)
            # Threshold 0.28 (~0.86 cosine similarity) for high-confidence duplicates
            if distances[0][0] < 0.28:
                return "duplicate (semantic)"
        
        self.index.add(embedding)
        
        self.memory_store.append({
            "content": content,
            "creator_id": creator_id,
            "privacy": privacy,
            "importance": importance
        })
        self.memory_seen.add(content)
        self._persist()

        # Graph Store (Neo4j) - Synchronized with Vector Store
        if triplet_override:
            sub, rel, obj = triplet_override
        else:
            sub, rel, obj = self._extract_triplet(content)
            
        if sub and rel and obj:
            print(f"🔗 Graph Link: Syncing [{sub}] -({rel})-> [{obj}]")
            with self.driver.session() as session:
                session.execute_write(self._create_relation_tx, sub, rel, obj, creator_id, privacy, importance)
        else:
            print(f"⚠️ Graph Link: Sync skipped (Reason: Incomplete triplet extracted for '{content[:30]}...')")
        
        return "success"

    def _create_relation_tx(self, tx, subject, relation, obj, creator_id, privacy, importance):
        query = """
        MERGE (a:Concept {name: $subject})
        ON CREATE SET a.creator_id = $creator_id, a.privacy = $privacy
        MERGE (b:Concept {name: $object})
        ON CREATE SET b.creator_id = $creator_id, b.privacy = $privacy
        MERGE (a)-[r:REL {type: $relation}]->(b)
        ON CREATE SET r.creator_id = $creator_id, r.privacy = $privacy, r.importance = $importance
        """
        tx.run(query, subject=subject, object=obj, relation=relation, 
               creator_id=creator_id, privacy=privacy, importance=importance)

    def search_vector(self, query_text, user_id=None, top_k=5):
        query_embedding = get_model().encode([query_text])[0]
        query_embedding = np.array([query_embedding]).astype('float32')
        distances, indices = self.index.search(query_embedding, top_k * 2)

        results = []
        seen = set()
        for i, dist in zip(indices[0], distances[0]):
            if 0 <= i < len(self.memory_store):
                mem = self.memory_store[i]
                is_accessible = (mem.get("privacy", "public") == "public") or (user_id and mem.get("creator_id") == user_id)
                
                # ✅ Relaxed threshold from 1.0 to 1.3 for better recall
                if is_accessible and mem["content"] not in seen and dist < 1.3:
                    results.append(mem)
                    seen.add(mem["content"])
                    if len(results) >= top_k:
                        break
        return results

    def get_related_graph(self, concept, user_id=None):
        query = """
        MATCH (a:Concept {name: $concept})-[r]->(b)
        WHERE coalesce(r.privacy, 'public') = 'public' OR r.creator_id = $user_id
        RETURN b.name AS related, r.type AS relation, coalesce(r.importance, 0.5) AS importance
        """
        with self.driver.session() as session:
            result = session.execute_read(lambda tx: tx.run(query, concept=concept, user_id=user_id).data())
        return result

    def hybrid_search(self, query_text, user_id=None, top_k=5):
        direct = self.search_vector(query_text, user_id=user_id, top_k=top_k)
        extensions = []
        seen_concepts = set()
        for res in direct:
            sub, _, obj = self._extract_triplet(res["content"])
            for concept in [sub, obj]:
                if concept and concept not in seen_concepts:
                    related = self.get_related_graph(concept, user_id=user_id)
                    if related:
                        extensions.append({"original": concept, "connections": related})
                    seen_concepts.add(concept)
        return {"direct": direct, "related": extensions}
