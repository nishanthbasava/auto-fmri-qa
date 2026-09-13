"""Minimal RAG over the QC knowledge base (autoqa/data/knowledge/*.md) using ChromaDB.

    autoqa rag build              # (re)index the knowledge docs
    autoqa rag query "multiband FD threshold"

Two uses, both advisory (retrieval never touches metrics or statuses):

  1. GROUNDING (before review): `context_for_scans()` builds a query from each
     scan's facts -- TR regime, scanner vendor, run length, which panels exist --
     and the top passages are placed in the prompt as "Reference notes" so the
     model judges figures against the cohort's actual protocol (e.g. respiratory
     pseudomotion on multiband runs is expected, not motion).
  2. CITATION (after review): when a scan is rated "concern"/"bad", `retrieve()`
     on the model's note attaches the passages that best explain the finding.

If chromadb is not installed or the index was never built, retrieval falls back
to an in-memory cosine search over the same hashed embedding -- the knowledge
base is ~20 chunks, so this is instant and needs no dependencies.

Chunks are the "## " sections of each markdown doc; each chunk carries its
source file, section heading, and the doc's "Source:" line as metadata, so every
retrieved passage is traceable to a real document.
"""
import argparse
import os
import re

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # .../autoqa
KNOW_DIR = os.environ.get("AFQ_KNOWLEDGE", os.path.join(PKG, "data", "knowledge"))
CHROMA_DIR = os.environ.get("AFQ_CHROMA", os.path.join(os.getcwd(), ".chroma"))
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


def _fallback_retrieve(query: str, k: int) -> list[dict]:
    """Dependency-free cosine search over the knowledge chunks (same embedding)."""
    ef = LexicalHashEmbedding()
    chunks = list(_chunks())
    if not chunks:
        return []
    qv = ef([query])[0]
    out = []
    for (cid, text, meta), dv in zip(chunks, ef([c[1] for c in chunks]), strict=True):
        sim = sum(a * b for a, b in zip(qv, dv, strict=True))
        out.append((1.0 - sim, cid, text, meta))
    out.sort(key=lambda t: t[0])
    return [{"source": m["source"], "file": m["file"], "section": m["section"],
             "snippet": t[:400], "text": t, "distance": round(d, 3)}
            for d, _, t, m in out[:k]]


def retrieve(query: str, k: int = 3) -> list[dict]:
    """Top-k passages for a query. Never raises -- RAG must never block the
    pipeline. Uses the chroma index when available, else the in-memory fallback."""
    try:
        col = _get_collection()
        res = col.query(query_texts=[query], n_results=k)
        out = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0],
                                   res["distances"][0], strict=True):
            out.append({"source": meta["source"], "file": meta["file"],
                        "section": meta["section"],
                        "snippet": doc[:400], "text": doc, "distance": round(dist, 3)})
        return out
    except Exception:
        try:
            return _fallback_retrieve(query, k)
        except Exception:
            return []


def scan_query(scan: dict) -> str:
    """Query text from a scan's facts (no free text from the model involved)."""
    m = scan.get("metrics") or {}
    tr = m.get("tr") or scan.get("tr") or 3.0
    parts = ["visual QC checklist carpet plot coregistration EPI contours T1w MNI registration"]
    if tr < 1.0:
        parts.append(f"multiband fast TR {tr:.3f} s respiratory pseudomotion FD oscillation")
    else:
        parts.append(f"single-band TR {tr:.1f} s FD spike threshold")
    if scan.get("vendor"):
        parts.append(f"{scan['vendor']} scanner DVARS")
    if m.get("n_volumes"):
        parts.append(f"{m['n_volumes']} volumes run length")
    figs = scan.get("rendered") or scan.get("figures") or {}
    parts.extend(k for k, v in figs.items() if v)
    return " ".join(parts)


def context_for_scans(scans: list[dict], k: int = 2, cap: int = 4) -> list[dict]:
    """Union of the top-k passages for each scan in a batch, deduplicated by
    chunk and capped, so the prompt carries the protocol facts these scans need."""
    seen, out = set(), []
    for s in scans:
        for p in retrieve(scan_query(s), k=k):
            key = (p["file"], p["section"])
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return out[:cap]


def format_context(passages: list[dict]) -> str:
    if not passages:
        return ""
    lines = ["Reference notes (from the cohort's protocol/QC documentation; use them to "
             "decide what is normal for THIS cohort):"]
    for i, p in enumerate(passages, 1):
        lines.append(f"\n[{i}] {p['file']} / {p['section']}\n{p.get('text', p['snippet']).strip()}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    q = sub.add_parser("query")
    q.add_argument("text")
    q.add_argument("-k", type=int, default=3)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        build()
    else:
        for r in retrieve(args.text, args.k):
            print(f"\n--- {r['file']} / {r['section']}  (d={r['distance']})")
            print(r["snippet"][:300])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
