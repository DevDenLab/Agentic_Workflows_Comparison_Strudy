"""Local, free text search: TF-IDF cosine similarity over a fixed corpus.

The project brief called for embeddings (bge-small/MiniLM + FAISS). This uses scikit-learn's
TF-IDF instead — a deliberate substitution: no multi-GB model download, no torch dependency,
milliseconds on a laptop CPU, and it is still genuinely local, free, and "semantic enough" for a
corpus this small (a few dozen documents). Swapping in real embeddings later means replacing this
module only — `SearchIndex` and `SearchHit` are the whole contract the tools depend on.
"""

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass(frozen=True, slots=True)
class SearchHit:
    doc_id: str
    text: str
    score: float
    metadata: dict[str, str]


class SearchIndex:
    """Built once from a fixed corpus at start-up; `search` never mutates it."""

    def __init__(self, documents: list[tuple[str, str, dict[str, str]]]) -> None:
        """`documents`: (doc_id, text, metadata) triples. An empty corpus is allowed; search then
        always returns nothing."""
        self._ids = [doc_id for doc_id, _, _ in documents]
        self._texts = [text for _, text, _ in documents]
        self._metadata = [metadata for _, _, metadata in documents]
        self._vectorizer = TfidfVectorizer(stop_words="english") if documents else None
        self._matrix = self._vectorizer.fit_transform(self._texts) if self._vectorizer else None

    def search(self, query: str, k: int = 3, *, min_score: float = 0.05) -> list[SearchHit]:
        if self._vectorizer is None or self._matrix is None:
            return []
        query_vector = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vector, self._matrix)[0]
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [
            SearchHit(self._ids[i], self._texts[i], float(scores[i]), self._metadata[i])
            for i in ranked[:k]
            if scores[i] >= min_score
        ]
