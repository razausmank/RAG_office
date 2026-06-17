"""
vector_service.py
-----------------
A simple service to interact with ChromaDB.
This file serves as your "Vector Tool". It handles:
1. Initializing a persistent ChromaDB client (saved in `./chroma_db` folder).
2. Creating a collection for Store FAQs.
3. Seeding the collection with sample shop policies.
4. Performing semantic (similarity) search queries.
"""

import os
from typing import Dict, List, Any
import chromadb
from chromadb.utils import embedding_functions

# Path where ChromaDB will store its data on disk
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "chroma_db")

# Initialize client. PersistentClient saves database files to the specified path on disk
# (analogous to SQLite saving database records to a file).
client = chromadb.PersistentClient(path=CHROMA_PATH)

# Use Chroma's default embedding function (runs locally, downloads the lightweight
# all-MiniLM-L6-v2 ONNX model on first use).
embedding_func = embedding_functions.DefaultEmbeddingFunction()

# Create or retrieve the FAQ collection
collection = client.get_or_create_collection(
    name="store_faq",
    embedding_function=embedding_func
)

# ---------------------------------------------------------------------------
# Seeding Sample FAQ Data
# ---------------------------------------------------------------------------
_FAQ_SEEDS = [
    {
        "id": "faq_shipping_time",
        "document": "Standard shipping takes 3-5 business days. Express shipping takes 1-2 business days. All orders are processed Monday through Friday.",
        "metadata": {"category": "shipping", "source": "shipping_policy.txt"}
    },
    {
        "id": "faq_shipping_cost",
        "document": "Standard shipping costs $4.99, but it is free for all orders over $50. Express shipping is a flat rate of $14.99 regardless of order value.",
        "metadata": {"category": "shipping", "source": "shipping_policy.txt"}
    },
    {
        "id": "faq_return_policy",
        "document": "We offer a 30-day return policy. Items must be returned in their original condition and packaging. Return shipping is completely free.",
        "metadata": {"category": "returns", "source": "return_policy.txt"}
    },
    {
        "id": "faq_refunds",
        "document": "Refunds are processed back to the original payment method within 5-7 business days after we receive and inspect the returned items.",
        "metadata": {"category": "returns", "source": "return_policy.txt"}
    },
    {
        "id": "faq_password_reset",
        "document": "To reset your password, click the 'Forgot Password' link on the login page, enter your email address, and follow the instructions sent to your inbox.",
        "metadata": {"category": "account", "source": "account_help.txt"}
    }
]

def seed_faqs() -> None:
    """Populate the vector database with store policies if it is empty."""
    # Check if we already have items in the collection
    existing_count = collection.count()
    if existing_count > 0:
        print(f"ChromaDB already contains {existing_count} documents. Skipping seed.")
        return

    print("Seeding ChromaDB with store FAQs...")
    
    ids = [item["id"] for item in _FAQ_SEEDS]
    documents = [item["document"] for item in _FAQ_SEEDS]
    metadatas = [item["metadata"] for item in _FAQ_SEEDS]

    # collection.add will automatically convert text documents into vectors (embeddings)
    # using the default ONNX model, and index them.
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )
    print("ChromaDB seeding completed successfully!")


# ---------------------------------------------------------------------------
# Semantic Search Query helper
# ---------------------------------------------------------------------------
def query_faq(user_query: str, n_results: int = 1) -> List[Dict[str, Any]]:
    """
    Search ChromaDB for documents semantically close to *user_query*.
    Returns a list of matching results with their details.
    """
    results = collection.query(
        query_texts=[user_query],
        n_results=n_results
    )

    formatted_results = []
    
    # ChromaDB queries return lists of lists because they support batch querying.
    # We index [0] to read results for our single query string.
    if results and "documents" in results and results["documents"]:
        docs = results["documents"][0]
        ids = results["ids"][0]
        metadatas = results["metadatas"][0]
        distances = results["distances"][0] if "distances" in results else [0.0] * len(docs)

        for i in range(len(docs)):
            formatted_results.append({
                "id": ids[i],
                "document": docs[i],
                "metadata": metadatas[i],
                "distance": distances[i]  # Distance score (lower distance = closer match)
            })

    return formatted_results


# ---------------------------------------------------------------------------
# Simple testing routine
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Seed the database
    seed_faqs()

    # 2. Test semantic search queries
    print("\n--- Testing Semantic Search ---")
    
    queries = [
        "How much do I have to spend to get free shipping?",
        "What happens if I want to return an item?",
        "I forgot my password, how do I recover it?"
    ]

    for q in queries:
        print(f"\nUser Query: '{q}'")
        matches = query_faq(q, n_results=1)
        if matches:
            match = matches[0]
            print(f"Best Match (ID: {match['id']}):")
            print(f" -> Text: \"{match['document']}\"")
            print(f" -> Distance Score: {match['distance']:.4f}")
        else:
            print("No matches found.")
