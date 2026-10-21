from google import genai
import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

client = genai.Client(api_key=GOOGLE_API_KEY)

EMBED_MODEL = "gemini-embedding-2"

def get_embeddings(texts):
    try:
        response = client.models.embed_content(
            model=EMBED_MODEL,
            contents=texts
        )
        return [e.values for e in response.embeddings]  # 🔥 FIX

    except Exception as e:
        print(f"❌ Embedding xato: {e}")
        return None


batch_chunks = [
    "Bu birinchi matn.",
    "Bu ikkinchi matn.",
    "Bu uchinchi matn."
]

embeddings = get_embeddings(batch_chunks)

print("✅ OK:", len(embeddings))
print("Vector length:", len(embeddings[0]))