python -m venv venv

Windows:
venv\Scripts\activate
Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt

python -m uvicorn app:app --reload

## Stage 2 Memory API

Store a memory:

```bash
curl -X POST http://127.0.0.1:8000/store ^
	-H "Content-Type: application/json" ^
	-d "{\"content\":\"DACMI stores structured memory\",\"tags\":[\"memory\",\"stage2\"],\"source\":\"roadmap\"}"
```

Query by content or tag:

```bash
curl "http://127.0.0.1:8000/query?q=structured&tag=memory"
```