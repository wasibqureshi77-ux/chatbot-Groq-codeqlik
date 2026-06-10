import random

class Embeddings:
    """Wrapper class for generating embeddings. Can easily be updated to HuggingFace or OpenAI."""
    def __init__(self, model_name: str = "text-embedding-ada-002"):
        self.model_name = model_name

    def embed_query(self, text: str) -> list[float]:
        # Stub: Return a mock vector of 1536 dimensions
        # Real implementation would call model API or local pipeline
        random.seed(hash(text))
        return [random.uniform(-1.0, 1.0) for _ in range(1536)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]
