# Getting Started with DACMI

## 🚀 Setup

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

## 🏗️ Running the Services

DACMI is built with a modular architecture. You need to run both the Memory Service and the Intelligence Service.

### 1. Memory Service (Storage & Retrieval)
Runs on port 8000.
```bash
python -m memory_service.main
```

### 2. Intelligence Service (LLM & Brain)
Runs on port 8001.
```bash
python -m intelligence_service.main
```

---

## 🧠 Using the API

### Store a memory:
```bash
curl -X POST http://127.0.0.1:8000/store ^
    -H "Content-Type: application/json" ^
    -d "{\"content\":\"Python is a programming language\"}"
```

### Hybrid Query (Vector + Graph):
```bash
curl "http://127.0.0.1:8000/query?q=Python"
```

### Ask a Question (via Intelligence Service):
```bash
curl "http://127.0.0.1:8001/ask?q=What+is+Python?"
```