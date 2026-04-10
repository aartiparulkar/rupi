import os
import json
import numpy as np
import traceback
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface.embeddings import HuggingFaceEmbeddings
from dotenv import load_dotenv
load_dotenv()

def main():
    try:
        print("🔹 Starting Vector Store Build Process...")

        # -------- Step 1: Check Chunk File --------
        if not os.path.exists("../data/chunks_txt.json"):
            raise FileNotFoundError("chunks_txt.json not found.")

        print("✅ chunks_txt.json found.")

        # -------- Step 2: Load Chunks --------
        with open("../data/chunks_txt.json", "r", encoding="utf-8") as f:
            chunks = json.load(f)

        print(f"✅ Loaded {len(chunks)} chunks.")

        if len(chunks) == 0:
            raise ValueError("No chunks found inside JSON file.")

        # -------- Step 3: Convert to LangChain Documents --------
        documents = []
        for chunk in chunks:
            documents.append(
                Document(
                    page_content=chunk["content"],
                    metadata=chunk["metadata"]
                )
            )

        print("✅ Converted chunks to LangChain Document objects.")

        # -------- Step 4: Load Embedding Model --------
        print("🔹 Loading SentenceTransformer model...")
        embedding_model = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-mpnet-base-v2"
        )
        print("✅ Embedding model loaded.")

        # -------- Step 5: Create Chroma Vector Store --------
        persist_directory = "../chroma_storage_txt"

        print("🔹 Creating Chroma vector store...")
        vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=embedding_model,
            persist_directory=persist_directory
        )

        # vectorstore.persist()
        print("✅ Vector store created and persisted.")

        # ==============================
        # 4. TEST RETRIEVAL
        # ==============================
        print("\n🔍 STEP 4: Testing retrieval...\n")

        retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

        query = "how to save money"

        results = retriever.invoke(query)

        for i, doc in enumerate(results):
            print(f"\n--- Result {i} ---")
            print("Content Preview:", doc.page_content[:200])
            print("Metadata:", doc.metadata)

        # ==============================
        # 5. SIMILARITY METRICS (DEBUG)
        # ==============================
        print("\n📊 STEP 5: Testing similarity metrics...\n")

        def cosine_similarity(vec1, vec2):
            vec1 = np.array(vec1)
            vec2 = np.array(vec2)
            return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

        def euclidean_distance(vec1, vec2):
            return np.linalg.norm(np.array(vec1) - np.array(vec2))

        def dot_product(vec1, vec2):
            return np.dot(np.array(vec1), np.array(vec2))

        # Test on first document
        if documents:
            query_vec = embedding_model.embed_query(query)
            doc_vec = embedding_model.embed_query(documents[0].page_content)

            print("Cosine Similarity:", cosine_similarity(query_vec, doc_vec))
            print("Euclidean Distance:", euclidean_distance(query_vec, doc_vec))
            print("Dot Product:", dot_product(query_vec, doc_vec))

        # ==============================
        # 6. SAVE DEBUG LOG
        # ==============================
        print("\n💾 STEP 6: Saving debug log...\n")

        with open("vector_store_build_log.txt", "w", encoding="utf-8") as f:
            f.write(f"Total Documents: {len(documents)}\n")
            f.write("Sample Metadata:\n")

            for doc in documents[:5]:
                f.write(str(doc.metadata) + "\n")

        print("📁 Debug log saved as vector_store_build_log_txt.txt")

        print("\n🎉 Vector Store Build Completed Successfully!\n")

    except Exception as e:
        print("\n❌ ERROR OCCURRED:")
        print("Message:", str(e))
        print("\n🔍 FULL TRACEBACK:")
        traceback.print_exc()

if __name__ == "__main__":
    main()