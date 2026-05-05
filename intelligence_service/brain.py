import asyncio
import httpx
import os
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List
try:
    import ollama
except ImportError:
    ollama = None

try:
    from google import genai
except ImportError:
    genai = None

MEMORY_SERVICE_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:8000")
DEFAULT_LLM_MODEL = os.getenv("LLM_MODEL", "llama3")
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-preview")


@dataclass
class WorkflowResponse:
    answer: str = ""
    importance: float = 0.5
    privacy: str = "private"
    contextualized_statement: str = ""
    triplets: List[Dict[str, str]] = field(default_factory=list)

class IntelligenceBrain:
    def __init__(self):
        self.llm_model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
        self.gemini_model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.llm_provider = os.getenv("LLM_PROVIDER", os.getenv("INTELLIGENCE_LLM_PROVIDER", "ollama")).strip().lower()
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

        self.client = httpx.AsyncClient(base_url=MEMORY_SERVICE_URL, timeout=15.0)
        self.provider, self.provider_reason = self._select_provider()
        self.gemini_client = None

        if self.provider == "gemini" and genai and self.gemini_api_key:
            self.gemini_client = genai.Client(api_key=self.gemini_api_key)

        print(f"🧠 Intelligence provider: {self.provider} (requested={self.llm_provider}, reason={self.provider_reason})")

    def _select_provider(self):
        if self.llm_provider in {"gemini", "google", "gemini-api"}:
            if genai and self.gemini_api_key:
                return "gemini", "gemini requested and SDK/key available"
            if not genai and not self.gemini_api_key:
                return "ollama" if ollama else "none", "gemini requested but google-genai and GEMINI_API_KEY are missing"
            if not genai:
                return "ollama" if ollama else "none", "gemini requested but google-genai is not installed"
            return "ollama" if ollama else "none", "gemini requested but GEMINI_API_KEY is missing"

        if self.llm_provider in {"ollama", "local"}:
            if ollama:
                return "ollama", "ollama requested and installed"
            if genai and self.gemini_api_key:
                return "gemini", "ollama requested but Gemini SDK/key are available and Ollama is unavailable"
            return "none", "ollama requested but neither Ollama nor Gemini is available"

        if ollama:
            return "ollama", "no explicit provider set; defaulting to available Ollama"
        if genai and self.gemini_api_key:
            return "gemini", "no explicit provider set; defaulting to available Gemini"
        return "none", "no provider available"

    def _strip_code_fences(self, text):
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def _safe_json_loads(self, raw_text):
        cleaned = self._strip_code_fences(raw_text)
        return json.loads(cleaned)

    def _normalize_triplets(self, triplets):
        normalized = []
        if not isinstance(triplets, list):
            return normalized

        for item in triplets:
            if not isinstance(item, dict):
                continue

            subject = str(item.get("subject", "")).strip()
            relation = str(item.get("relation", "")).strip()
            obj = str(item.get("object", "")).strip()

            if subject and relation and obj:
                normalized.append({"subject": subject, "relation": relation, "object": obj})

        return normalized

    def _coerce_float(self, value, default=0.5):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _build_history_block(self, history):
        history_str = ""
        for msg in history:
            role = "User" if msg["role"] == "user" else "DACMI"
            history_str += f"{role}: {msg['content']}\n"
        return history_str.strip()

    def _build_context_block(self, direct_matches):
        if not direct_matches:
            return "None"
        return "\n".join([f"- {match}" for match in direct_matches])

    async def _generate_gemini_workflow(self, question, history, context_str):
        if not self.gemini_client:
            raise RuntimeError("Gemini client is not configured")

        prompt = f"""
SYSTEM: You are DACMI, a concise intelligence engine.

Return ONLY a single JSON object with these keys:
- answer: string
- importance: number between 0.0 and 1.0
- privacy: one of ["public", "private"]
- contextualized_statement: a standalone memory-ready statement rewritten from the user message
- triplets: a JSON list of objects with keys subject, relation, object

Rules:
1. Use the retrieved context and conversation history to answer directly.
2. Make the answer concise but useful.
3. Mark importance higher when the message contains a durable fact, preference, goal, identity detail, or actionable task.
4. Mark privacy as private if the content is personal, subjective, or user-specific.
5. triplets must contain only atomic facts suitable for storage.
6. Do not wrap the JSON in markdown fences.

Retrieved Context:
{context_str}

Conversation History:
{history}

New User Message:
{question}

JSON:
""".strip()

        response = await asyncio.to_thread(
            self.gemini_client.models.generate_content,
            model=self.gemini_model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )

        raw_text = getattr(response, "text", "") or ""
        if not raw_text:
            raw_text = str(response)

        parsed = self._safe_json_loads(raw_text)

        return WorkflowResponse(
            answer=str(parsed.get("answer", "")).strip(),
            importance=self._coerce_float(parsed.get("importance"), 0.5),
            privacy=str(parsed.get("privacy", "private")).strip().lower(),
            contextualized_statement=str(parsed.get("contextualized_statement", "")).strip(),
            triplets=self._normalize_triplets(parsed.get("triplets", [])),
        )

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
            response = ollama.generate(model=self.llm_model, prompt=prompt)
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
            response = ollama.generate(model=self.llm_model, prompt=prompt)
            result = response['response'].strip().lower()
            if "private" in result: return "private"
            if "public" in result: return "public"
            return "private"
        except: return "private"

    async def extract_triplets(self, content):
        if not ollama: return []
        prompt = f"""
        Extract ALL distinct Subject-Relation-Object triplets from the following text to be stored in a knowledge graph.
        
        PERSPECTIVE:
        - "User" is the person speaking/asking.
        - "DACMI" is the AI system receiving the message.
        
        EXAMPLES:
        "Swasthik is a human, he is my friend" -> [
            {{"subject": "Swasthik", "relation": "is", "object": "human"}},
            {{"subject": "Swasthik", "relation": "is friend of", "object": "User"}}
        ]
        "I love the Tesla team and know about GTA" -> [
            {{"subject": "User", "relation": "loves", "object": "Tesla team"}},
            {{"subject": "User", "relation": "knows about", "object": "GTA"}}
        ]
        "Do you know Manga?" -> [{{"subject": "User", "relation": "asks about", "object": "Manga"}}]
        
        STRICT RULES:
        1. Return ONLY a JSON list: [{{"subject": "X", "relation": "Y", "object": "Z"}}, ...].
        2. Extract EVERY atomic fact separately.
        3. PRONOUN NORMALIZATION: Always convert 'I', 'me', 'my' to 'User'.
        4. Use precise, descriptive relations (e.g., "is friend of", "works at", "is named").
        5. Keep the subject and object to 1-3 words maximum.
        
        Text: "{content}"
        JSON:"""
        try:
            response = ollama.generate(model=self.llm_model, prompt=prompt)
            match = re.search(r'\[.*\]', response['response'], re.DOTALL)
            if match:
                return json.loads(match.group())
            return []
        except: return []

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
            response = ollama.generate(model=self.llm_model, prompt=prompt)
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
        history_str = self._build_history_block(history)

        # 1. Long-term Retrieval
        # Use the raw question for search, then let the LLM refine the rest.
        context_data = await self.get_context(question, user_id=user_id)
        raw_matches = [m["content"] for m in context_data.get("direct", [])]
        
        # Deduplicate context to prevent DACMI from repeating itself
        direct_matches = []
        for m in raw_matches:
            if not any(m.lower() in u.lower() or u.lower() in m.lower() for u in direct_matches):
                direct_matches.append(m)
                
        related_concepts = context_data.get("related", [])
        context_str = self._build_context_block(direct_matches)

        # 2. LLM response generation
        storage_status = None
        new_memory_stored = False
        new_triplets = []
        importance = 0.5
        privacy = "private"
        context_statement = question
        answer = ""

        if self.provider == "gemini":
            try:
                structured_response = await self._generate_gemini_workflow(question, history_str, context_str)
                answer = structured_response.answer or "I could not generate a response."
                importance = structured_response.importance
                privacy = structured_response.privacy
                context_statement = structured_response.contextualized_statement or question
                new_triplets = structured_response.triplets
            except Exception as e:
                answer = f"⚠️ Gemini Error: {e}"
        elif ollama:
            # 0. Contextualization
            # Resolve references like "it", "the team", etc. using history
            context_statement = await self.contextualize_for_storage(question, history)

            # 2a. Proactive Memory Evaluation & Deduplication
            importance = await self.evaluate_importance(context_statement)
            if importance >= 0.4:
                privacy = await self.evaluate_privacy(context_statement)
                # Extract multiple facts for high-fidelity graph sync
                new_triplets = await self.extract_triplets(context_statement)

            # 2b. Response generation
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
                response = ollama.generate(model=self.llm_model, prompt=prompt)
                answer = response['response'].strip()
            except Exception as e:
                answer = f"⚠️ LLM Error: {e}"
        else:
            answer = f"No LLM provider connected. Context: {len(direct_matches)} items."
        
        # Heuristic check: is this statement already mostly present in the retrieved context?
        is_redundant = any(context_statement.lower() in m.lower() or m.lower() in context_statement.lower() for m in direct_matches)
        
        if not is_redundant:
            if importance >= 0.4:
                success, engine_status = await self.store_important_memory(
                    context_statement, user_id=user_id, importance=importance, 
                    privacy=privacy, triplets=new_triplets
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
                response = ollama.generate(model=self.llm_model, prompt=prompt)
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
            
            # Update graph panel data with all extracted facts
            for triplet in new_triplets:
                sub = triplet.get("subject")
                rel = triplet.get("relation")
                obj = triplet.get("object")
                
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

    async def store_important_memory(self, content, user_id=None, importance=0.5, privacy="private", triplets=None):
        clean_content = re.sub(r'^(remember|save|store|keep in mind|don\'t forget)( that| to)?(,|:)?\s*', '', content, flags=re.IGNORECASE)
        clean_content = clean_content.strip().capitalize()
        if not clean_content: return False, "empty content"
        
        if triplets:
            final_triplets = triplets
        else:
            final_triplets = await self.extract_triplets(clean_content)
            
        payload = {
            "content": clean_content, "creator_id": user_id, "privacy": privacy,
            "importance": importance, "triplets": final_triplets
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
