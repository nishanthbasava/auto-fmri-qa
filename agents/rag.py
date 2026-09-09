"""Minimal RAG over the QC knowledge base (docs/knowledge/*.md) using ChromaDB.

    python -m agents.rag build              # (re)index the knowledge docs
    python -m agents.rag query "multiband FD threshold"

Retrieval is deliberately rare and advisory: it runs only when the visual-review
agent rates a scan "concern" or "bad" (a handful of scans per cohort), attaching
the most relevant documentation passages as citations to the review note. It
never touches metrics or statuses.

Chunks are the "## " sections of each markdown doc; each chunk carries its
source file, section heading, and the doc's "Source:" line as metadata, so every
retrieved passage is traceable to a real document.
"""
import argparse
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOW_DIR = os.path.join(REPO, "docs", "knowledge")
CHROMA_DIR = os.environ.get("AFQ_CHROMA", os.path.join(REPO, ".chroma"))
COLLECTION = "afq_knowledge"

_collection = None  # lazy singleton

EMBED_DIM = 512


class LexicalHashEmbedding:
    """Self-contained hashed bag-of-words embedding (sublinear TF, L2-normed).

    Chosen over Chroma's default ONNX MiniLM deliberately: no model download at
    runtime, so indexing works on an offline / egress-restricted lab machine.
    For a ~20-chunk technical corpus queried with terms like "multiband",
    "ghosting", "saturated EPI", lexical overlap is what matters anyway. To
    upgrade to a neural embedder, replace this class and rebuild the index.
    """

    def name(self) -> str:  # chroma persists this with the collection
        return "afq-lexical-hash"

    def embed_query(self, input):  # chroma >=1.x calls these two explicitly
        return self(input)

    def embed_documents(self, input):
        return self(input)

    def __call__(self, input):  # noqa: A002 (chroma's required signature)
        import hashlib
        import math
        out = []
        for text in input:
            vec = [0.0] * EMBED_DIM
            for tok in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16)
                vec[h % EMBED_DIM] += 1.0
            vec = [math.log1p(v) for v in vec]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def _chunks():
    """Yield (id, text, metadata) for every '## ' section of every knowledge doc."""
    for name in sorted(os.listdir(KNOW_DIR)):
        if not name.endswith(".md"):
            continue
        body = open(os.path.join(KNOW_DIR, name)).read()
        title_m = re.search(r"^# (.+)$", body, re.M)
        src_m = re.search(r"^Source: (.+)$", body, re.M)
        doc_title = title_m.group(1).strip() if title_m else name
        source = src_m.group(1).strip() if src_m else name
        parts = re.split(r"^## ", body, flags=re.M)[1:]  # drop preamble
        for part in parts:
            heading, _, text = part.partition("\n")
            heading = heading.strip()
            text = text.strip()
            if not text:
                continue
            cid = f"{name}::{heading}"
            yield cid, f"{doc_title} — {heading}\n\n{text}", {
                "file": name, "section": heading, "source": source}


def _get_collection(create: bool = False):
    global _collection
    if _collection is not None and not create:
        return _collection
    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    ef = LexicalHashEmbedding()
    if create:
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass
        _collection = client.create_collection(COLLECTION, embedding_function=ef)
    else:
        _collection = client.get_collection(COLLECTION, embedding_function=ef)
    return _collection


def build() -> int:
    col = _get_collection(create=True)
    ids, docs, metas = [], [], []
    for cid, text, meta in _chunks():
        ids.append(cid)
        docs.append(text)
        metas.append(meta)
    col.add(ids=ids, documents=docs, metadatas=metas)
    print(f"indexed {len(ids)} chunks from {KNOW_DIR} -> {CHROMA_DIR}")
    return len(ids)


def retrieve(query: str, k: int = 3) -> list[dict]:
    """Top-k passages for a query. Returns [] on any failure -- RAG must never
    block the pipeline (missing index, missing chromadb, offline embedder)."""
    try:
        col = _get_collection()
        res = col.query(query_texts=[query], n_results=k)
        out = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                                   res["distances"][0]):
            out.append({"source": meta["source"], "file": meta["file"],
                        "section": meta["section"],
                        "snippet": doc[:400], "distance": round(dist, 3)})
        return out
    except Exception:
        return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    q = sub.add_parser("query")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=3)
    args = ap.parse_args()
    if args.cmd == "build":
        build()
    else:
        for r in retrieve(args.text, args.k):
            print(f"\n--- {r['file']} / {r['section']}  (d={r['distance']})")
            print(r["snippet"][:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
