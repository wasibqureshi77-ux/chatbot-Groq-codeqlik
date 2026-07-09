import math
from rag.embeddings import Embeddings, embeddings_model

class VectorStore:
    """In-memory vector store that computes similarity. Ready to be replaced by Pinecone, Chroma, or MongoDB Atlas Vector Search."""
    def __init__(self, embeddings_model_arg: Embeddings = None):
        self.embeddings = embeddings_model_arg or embeddings_model
        self.store = []  # List of dicts with {"text": text, "metadata": metadata, "vector": vector}

    def add_texts(self, texts: list[str], metadatas: list[dict] = None) -> None:
        vectors = self.embeddings.embed_documents(texts)
        for i, text in enumerate(texts):
            meta = metadatas[i] if metadatas and i < len(metadatas) else {}
            self.store.append({
                "text": text,
                "metadata": meta,
                "vector": vectors[i]
            })

    def _cosine_similarity(self, vec1: list[float], vec2: list[float]) -> float:
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude_1 = math.sqrt(sum(a * a for a in vec1))
        magnitude_2 = math.sqrt(sum(a * a for a in vec2))
        if magnitude_1 == 0 or magnitude_2 == 0:
            return 0.0
        return dot_product / (magnitude_1 * magnitude_2)

    def similarity_search(self, query: str, k: int = 3) -> list[dict]:
        if not self.store:
            return []
        query_vector = self.embeddings.embed_query(query)
        scored_docs = []
        
        for item in self.store:
            score = self._cosine_similarity(query_vector, item["vector"])
            scored_docs.append({
                "text": item["text"],
                "metadata": item["metadata"],
                "score": score
            })
            
        # Sort by similarity score descending
        scored_docs.sort(key=lambda x: x["score"], reverse=True)
        return scored_docs[:k]
