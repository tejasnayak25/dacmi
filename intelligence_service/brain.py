import httpx
import os
import json
import re
try:
    import ollama
except ImportError:
    ollama = None

MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:8000")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3")

class IntelligenceBrain:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=MEMORY_SERVICE_URL, timeout=15.0)

    async def get_context(self, query, user_id=None):
        try:
            params = {"q": query}
            if user_id:
                params["user_id"] = user_id
            response = await self.client.get("/query", params=params)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"⚠️ Error fetching context: {e}")
        return {"direct": [], "related": []}

    async def evaluate_importance(self, content):
        if not ollama: return 0.5
        prompt = f"""
        Rate long-term importance (0.0 to 1.0).
        0.0 = Transient talk.
        0.5 = Useful fact/preference.
        1.0 = Critical secret/task.
        
        Text: "{content}"
        Score (return ONLY the number):"""
        try:
            response = ollama.generate(model=LLM_MODEL, prompt=prompt)
            return float(response['response'].strip())
        except: return 0.5

    async def evaluate_privacy(self, content):
        if not ollama: return "private"
        prompt = f"""
        Classify as "public" or "private".
        STRICT RULES:
        1. If it mentions "I", "me", "my", "mine", "my friend", "my professor", "my secret", it is PRIVATE.
        2. If it is a personal preference ("I like...", "I find..."), it is PRIVATE.
        3. If it is a general fact, news, or team info ("The hackathon is Friday", "Python is 3.12"), it is PUBLIC.
        Text: "{content}"
        Classification (return ONLY "public" or "private"):"""
        try:
            response = ollama.generate(model=LLM_MODEL, prompt=prompt)
            result = response['response'].strip().lower()
            if "private" in result: return "private"
            if "public" in result: return "public"
            return "private"
        except: return "private"

    async def extract_triplet(self, content):
        if not ollama: return None, None, None
        prompt = f"""
        Extract a single Subject-Relation-Object triplet from the following text to be stored in a knowledge graph.
        
        PERSPECTIVE:
        - "User" is the person speaking/asking.
        - "DACMI" is the AI system receiving the message.
        
        EXAMPLES:
        "I love the Tesla team" -> {{"subject": "User", "relation": "loves", "object": "Tesla team"}}
        "Do you know GTA?" -> {{"subject": "User", "relation": "asks about", "object": "GTA"}}
        "Your design is cool" -> {{"subject": "User", "relation": "likes", "object": "DACMI design"}}
        "European architecture is beautiful" -> {{"subject": "European architecture", "relation": "is", "object": "beautiful"}}
        
        STRICT RULES:
        1. Return ONLY a JSON object: {{"subject": "X", "relation": "Y", "object": "Z"}}.
        2. PRONOUN NORMALIZATION: Always convert 'I', 'me', 'my' to 'User'.
        3. QUESTION PERSPECTIVE: If the user asks "Do you [verb] [object]?", the subject is "User" and the relation is "asks about" or "queries DACMI about".
        4. If the sentence is a description, use "is" or "appears" as the relation.
        5. Keep the subject and object to 1-3 words maximum.
        
        Text: "{content}"
        JSON:"""
        try:
            response = ollama.generate(model=LLM_MODEL, prompt=prompt)
            match = re.search(r'\{.*\}', response['response'], re.DOTALL)
            if match:
                data = json.loads(match.group())
                return data.get("subject"), data.get("relation"), data.get("object")
        except: return None, None, None

    async def contextualize_for_storage(self, question, history):
        """Rewrites the current message into a standalone statement using conversation history."""
        if not ollama or not history:
            return question
        
        history_str = ""
        # Use the last 5 messages for context
        for msg in history[-5:]:
            role = "User" if msg["role"] == "user" else "DACMI"
            history_str += f"{role}: {msg['content']}\n"
            
        prompt = f"""
        Given the following conversation history and the new user message, rewrite the new message into a single standalone statement that is clear, concise, and contains all necessary context (names, entities, teams, etc.) from the history.
        
        Conversation History:
        {history_str}
        
        New User Message: {question}
        
        Standalone Statement (return ONLY the rewritten text):"""
        
        try:
            response = ollama.generate(model=LLM_MODEL, prompt=prompt)
            contextualized = response['response'].strip()
            if not contextualized or len(contextualized) < 3:
                return question
            return contextualized
        except Exception as e:
            print(f"⚠️ Contextualization Error: {e}")
            return question

    async def ask(self, question, user_id=None):
        """Legacy standalone ask method"""
        return await self.ask_with_history(question, [], user_id)

    async def ask_with_history(self, question, history, user_id=None):
        """Stateful chat with context from current session and long-term memory"""
        
        # 0. Contextualization
        # Resolve references like "it", "the team", etc. using history
        context_statement = await self.contextualize_for_storage(question, history)
        
        # 1. Long-term Retrieval (Moved up to check for redundancy)
        # Use contextualized statement for better retrieval matches
        context_data = await self.get_context(context_statement, user_id=user_id)
        raw_matches = [m["content"] for m in context_data.get("direct", [])]
        
        # Deduplicate context to prevent DACMI from repeating itself
        direct_matches = []
        for m in raw_matches:
            if not any(m.lower() in u.lower() or u.lower() in m.lower() for u in direct_matches):
                direct_matches.append(m)
                
        related_concepts = context_data.get("related", [])
        context_str = "\n".join([f"- {m}" for m in direct_matches])

        # 2. Proactive Memory Evaluation & Deduplication
        storage_status = None
        new_memory_stored = False
        sub, rel, obj = None, None, None
        
        # Heuristic check: is this statement already mostly present in the retrieved context?
        is_redundant = any(context_statement.lower() in m.lower() or m.lower() in context_statement.lower() for m in direct_matches)
        
        if not is_redundant:
            importance = await self.evaluate_importance(context_statement)
            if importance >= 0.4:
                privacy = await self.evaluate_privacy(context_statement)
                # Pre-extract triplet to inject into UI later
                sub, rel, obj = await self.extract_triplet(context_statement)
                success, engine_status = await self.store_important_memory(
                    context_statement, user_id=user_id, importance=importance, 
                    privacy=privacy, triplet=(sub, rel, obj)
                )
                if success:
                    if "duplicate" in str(engine_status):
                        storage_status = "Neural Link: Knowledge already present."
                    else:
                        storage_status = f"Neural Link updated ({privacy.capitalize()}, Score: {importance})"
                        new_memory_stored = True
        else:
            storage_status = "Neural Link: Knowledge already present."

        # 3. Short-term Session History Formatting
        history_str = ""
        for msg in history:
            role = "User" if msg["role"] == "user" else "DACMI"
            history_str += f"{role}: {msg['content']}\n"

        if ollama:
            prompt = f"""
            SYSTEM: You are DACMI (Decentralized Agentic Collective Memory Intelligence). 
            STRICT STYLE GUIDELINES:
            1. BE CONCISE BUT INSIGHTFUL. Every sentence must add value. Avoid one-word answers for complex or qualitative topics.
            2. NO FLUFF. Do not use generic assistant phrases like "I noticed you mentioned...", "I'm curious...", "Welcome!", or "Let's dive in...".
            3. NO INTRODUCTIONS. Start your answer directly with insights or facts.
            4. TONE: Direct, efficient, and sophisticated. You are a high-performance intelligence engine. Directness does not mean being abrupt or unhelpful.
            5. KNOWLEDGE INTEGRATION: Synthesize retrieved memories into a single, cohesive point. Do NOT repeat information if it appears multiple times in context. Do NOT announce your memories; just incorporate the facts naturally.
            6. QUALITATIVE TOPICS: For subjective or appreciative topics (like art, architecture, or culture), provide a brief but sophisticated observation rather than a simple binary confirmation.
            {context_str}
            
            Current Conversation History:
            {history_str}
            
            New User Message: {question}
            DACMI Answer:"""
            
            try:
                response = ollama.generate(model=LLM_MODEL, prompt=prompt)
                answer = response['response'].strip()
            except Exception as e:
                answer = f"⚠️ LLM Error: {e}"
        else:
            answer = f"Ollama not connected. Context: {len(direct_matches)} items."

        # 4. Instant UI Synchronization
        if new_memory_stored:
            # Prepend new memory to chips to ensure it appears first
            if context_statement not in direct_matches:
                direct_matches.insert(0, context_statement)
            
            # Update graph panel data
            if sub and rel and obj:
                concept_exists = False
                for entry in related_concepts:
                    if entry["original"].lower() == sub.lower():
                        entry["connections"].append({"related": obj, "relation": rel, "importance": importance})
                        concept_exists = True
                        break
                if not concept_exists:
                    related_concepts.insert(0, {
                        "original": sub,
                        "connections": [{"related": obj, "relation": rel, "importance": importance}]
                    })

        return {
            "answer": answer,
            "storage_log": storage_status,
            "context_used": direct_matches,
            "related_concepts": related_concepts
        }

    async def store_important_memory(self, content, user_id=None, importance=0.5, privacy="private", triplet=None):
        clean_content = re.sub(r'^(remember|save|store|keep in mind|don\'t forget)( that| to)?(,|:)?\s*', '', content, flags=re.IGNORECASE)
        clean_content = clean_content.strip().capitalize()
        if not clean_content: return False, "empty content"
        
        if triplet:
            sub, rel, obj = triplet
        else:
            sub, rel, obj = await self.extract_triplet(clean_content)
            
        payload = {
            "content": clean_content, "creator_id": user_id, "privacy": privacy,
            "importance": importance, "subject": sub, "relation": rel, "object": obj
        }
        try:
            response = await self.client.post("/store", json=payload)
            if response.status_code == 200:
                data = response.json()
                return True, data.get("status", "success")
            return True, "success"
        except Exception as e:
            print(f"⚠️ Error storing: {e}")
            return False, "error"
