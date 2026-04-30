from neo4j import GraphDatabase

# 🔑 Connection details
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "password123"

# ✅ Create driver (THIS WAS MISSING)
driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))


def create_memory(content, timestamp, tags):
    with driver.session() as session:
        session.run("""
            MERGE (u:User {name: "Tharun"})
            CREATE (m:Memory {
                content: $content,
                timestamp: $timestamp
            })
            MERGE (u)-[:HAS]->(m)

            WITH m
            UNWIND $tags AS tag
            MERGE (t:Tag {name: tag})
            MERGE (m)-[:TAGGED]->(t)
        """, content=content, timestamp=timestamp, tags=tags)