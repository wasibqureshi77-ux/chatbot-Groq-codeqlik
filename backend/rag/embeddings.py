from sentence_transformers import SentenceTransformer

class Embeddings:
    """Wrapper class for generating embeddings using sentence-transformers and all-MiniLM-L6-v2."""
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)

    def embed_query(self, text: str) -> list[float]:
        # Generate embedding vector for a single query text
        embedding = self.model.encode(text)
        return embedding.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Generate embedding vectors for a list of document chunks
        embeddings = self.model.encode(texts)
        return embeddings.tolist()

# Global singleton instance loaded once on startup
embeddings_model = Embeddings()
