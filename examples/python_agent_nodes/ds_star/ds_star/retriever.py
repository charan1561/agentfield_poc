from typing import List, Tuple
import math
from .azure_client import AzureLLM


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def retrieve_top_k(
    llm: AzureLLM,
    query: str,
    descriptions: List[str],
    k: int = 100,
) -> List[int]:
    """
    Compute Azure embeddings for query and each description, then select top-k by cosine similarity.
    Returns indices into descriptions.
    """
    if len(descriptions) <= k:
        return list(range(len(descriptions)))

    # Embed
    q_emb = llm.embed([query])[0]
    d_embs = llm.embed(descriptions)

    # Score and sort
    scores: List[Tuple[int, float]] = []
    for i, emb in enumerate(d_embs):
        scores.append((i, _cosine(q_emb, emb)))

    scores.sort(key=lambda x: x[1], reverse=True)
    top = [i for i, _ in scores[:k]]
    return top
