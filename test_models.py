import os
from dotenv import load_dotenv
load_dotenv()
from google import genai
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
for m in client.models.list():
    if m.supported_actions and "embedContent" in m.supported_actions:
        print(m.name)
