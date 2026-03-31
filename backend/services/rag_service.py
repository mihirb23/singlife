# rag_service.py — vector store for SOP document retrieval
# uses chromadb with sentence-transformers embeddings (all local, no api cost).
# instead of stuffing ALL docs into the prompt, we only retrieve the
# relevant chunks for each query. saves tokens and scales better.

import logging
from pathlib import Path
from typing import List

import chromadb
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

KB_DIR = Path(__file__).parent.parent.parent / 'knowledge_base'
CHROMA_DIR = Path(__file__).parent.parent.parent / 'chroma_db'

# chunk size in characters — roughly 500 tokens per chunk
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """split text into overlapping chunks. we overlap a bit so that
    if a rule spans two chunks, it still gets captured in at least one"""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


class VectorStore:
    """manages the chromadb vector store for our knowledge base docs.
    on init, it chunks all the txt files and indexes them.
    on query, it returns the top-k most relevant chunks"""

    def __init__(self):
        self.client = None
        self.collection = None
        self._init_store()

    def _init_store(self):
        """set up chromadb with sentence-transformers embeddings"""
        try:
            # use persistent storage so we don't re-embed every restart
            self.client = chromadb.PersistentClient(path=str(CHROMA_DIR))

            # sentence-transformers runs locally — no API key needed
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

            self.collection = self.client.get_or_create_collection(
                name="singlife_kb",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"}
            )

            logger.info(f"Vector store ready — {self.collection.count()} chunks indexed")
        except Exception as e:
            logger.error(f"Failed to init vector store: {e}")
            self.collection = None

    def index_documents(self):
        """read all txt files from knowledge_base/, chunk them, and add to chromadb.
        clears existing data first so we always have a fresh index"""
        if not self.collection:
            logger.error("Collection not available — can't index")
            return

        # wipe existing data
        existing = self.collection.count()
        if existing > 0:
            all_ids = self.collection.get()["ids"]
            if all_ids:
                self.collection.delete(ids=all_ids)
            logger.info(f"Cleared {existing} old chunks")

        KB_DIR.mkdir(exist_ok=True)
        files = sorted(KB_DIR.glob('*.txt'))
        if not files:
            logger.warning("No documents to index")
            return

        all_chunks = []
        all_ids = []
        all_metadata = []

        for f in files:
            try:
                text = f.read_text(encoding='utf-8').strip()
                chunks = chunk_text(text)
                for i, chunk in enumerate(chunks):
                    chunk_id = f"{f.stem}_chunk_{i}"
                    all_chunks.append(chunk)
                    all_ids.append(chunk_id)
                    all_metadata.append({
                        "source": f.name,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                    })
                logger.info(f"Chunked {f.name}: {len(chunks)} chunks")
            except Exception as e:
                logger.error(f"Failed to process {f.name}: {e}")

        if all_chunks:
            # chromadb has a batch limit, add in batches of 100
            batch_size = 100
            for i in range(0, len(all_chunks), batch_size):
                self.collection.add(
                    documents=all_chunks[i:i+batch_size],
                    ids=all_ids[i:i+batch_size],
                    metadatas=all_metadata[i:i+batch_size],
                )
            logger.info(f"Indexed {len(all_chunks)} chunks from {len(files)} documents")

    def query(self, question: str, top_k: int = 8) -> List[dict]:
        """find the most relevant chunks for a given question.
        returns list of {text, source, score}"""
        if not self.collection or self.collection.count() == 0:
            return []

        try:
            results = self.collection.query(
                query_texts=[question],
                n_results=min(top_k, self.collection.count()),
            )

            chunks = []
            for i, doc in enumerate(results["documents"][0]):
                chunks.append({
                    "text": doc,
                    "source": results["metadatas"][0][i]["source"],
                    "score": results["distances"][0][i] if results["distances"] else None,
                })
            return chunks
        except Exception as e:
            logger.error(f"Vector store query failed: {e}")
            return []

    def is_available(self) -> bool:
        return self.collection is not None and self.collection.count() > 0
