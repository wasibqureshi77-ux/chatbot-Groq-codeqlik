import os
from dotenv import load_dotenv

load_dotenv()

API_KEY_1 = os.getenv("API_KEY_1")
API_KEY_2 = os.getenv("API_KEY_2")
API_KEY = API_KEY_1 or os.getenv("API_KEY")    
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "company_chatbot")

if not API_KEY_1 and not API_KEY:
    raise ValueError("API_KEY_1 or API_KEY is missing in .env file")

# LangSmith Tracing Configuration
LANGCHAIN_API_KEY = os.getenv("LANGCHAIN_API_KEY") or os.getenv("langsmith_api_key")
if LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGCHAIN_API_KEY"] = LANGCHAIN_API_KEY  
    if not os.getenv("LANGCHAIN_PROJECT"):
        os.environ["LANGCHAIN_PROJECT"] = "company_chatbot"
    print(f"[LangSmith] Tracing enabled. Project: {os.environ['LANGCHAIN_PROJECT']}")
