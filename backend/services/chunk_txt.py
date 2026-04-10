import os
import json
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==============================
# CONFIG
# ==============================
DATA_PATH = "../data"

# ==============================
# 1. LOAD TXT FILES
# ==============================
print("\n🔍 STEP 1: Loading TXT files...\n")

all_docs = []

if not os.path.exists(DATA_PATH):
    print(f"❌ ERROR: Folder '{DATA_PATH}' does not exist")
    exit()

files = os.listdir(DATA_PATH)
print(f"📁 Found files: {files}")

txt_files = [f for f in files if f.endswith(".txt") and f.startswith("clean_")]

if not txt_files:
    print("❌ ERROR: No clean TXT files found")
    exit()

print(f"✅ TXT files detected: {txt_files}\n")

for file in txt_files:
    file_path = os.path.join(DATA_PATH, file)

    print(f"\n📄 Loading file: {file}")

    try:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()

        print(f"   ✅ Loaded {len(docs)} document(s)")

        for doc in docs:
            doc.metadata["source"] = file

        all_docs.extend(docs)

    except Exception as e:
        print(f"   ❌ ERROR loading {file}: {e}")

print(f"\n📊 Total loaded documents: {len(all_docs)}")

if not all_docs:
    print("❌ ERROR: No documents loaded. Stopping.")
    exit()

# ==============================
# 2. CHUNKING
# ==============================
print("\n✂️ STEP 2: Chunking...\n")

try:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,      # 🔥 slightly smaller for better quality
        chunk_overlap=80
    )

    split_docs = splitter.split_documents(all_docs)

    # Add metadata
    for i, doc in enumerate(split_docs):
        doc.metadata["seq_num"] = i
        doc.metadata["chunk_id"] = i

    print(f"✅ Chunking complete!")
    print(f"📊 Total chunks created: {len(split_docs)}\n")

    # Debug preview
    print("🔹 SAMPLE CHUNKS:\n")

    for i, doc in enumerate(split_docs[:5]):
        print(f"--- Chunk {i} ---")
        print("📄 Content Preview:\n", doc.page_content[:300])
        print("🏷️ Metadata:", doc.metadata)
        print("----------------------\n")

except Exception as e:
    print(f"❌ ERROR during chunking: {e}")
    exit()

# ==============================
# 3. SAVE CHUNKS (JSON)
# ==============================
print("\n💾 STEP 3: Saving chunks...\n")

OUTPUT_FILE = "../data/chunks_txt.json"

try:
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata
                }
                for doc in split_docs
            ],
            f,
            indent=2
        )

    print(f"✅ Chunks saved to {OUTPUT_FILE}")

except Exception as e:
    print(f"❌ ERROR saving chunks: {e}")

print("\n🎉 TXT CHUNKING COMPLETED SUCCESSFULLY!\n")