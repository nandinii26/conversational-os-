import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from config import get_genai_model

# Load env variables from root directory
load_dotenv(Path(__file__).parent.parent / ".env")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    _client = genai.Client(api_key=api_key)
    return _client

# Allow overriding the model via env var for compatibility
MODEL_NAME = get_genai_model()

def summarize(text: str) -> str:
    """Generate a structured, detailed summary of the provided text using the LLM."""
    prompt = f"""You are an expert document analyst. Read the following document and produce a comprehensive, well-structured summary.

Your summary MUST include:
1. **Overview** – A 2-3 sentence high-level description of what the document is about.
2. **Key Points** – A bullet-point list of the most important facts, arguments, or findings (at least 5 bullets).
3. **Important Details** – Any notable data, statistics, dates, names, or specifics mentioned.
4. **Conclusion / Takeaway** – A 1-2 sentence closing insight or main message.

Format your response using Markdown headings and bullet points.

DOCUMENT:
---
{text}
---

Provide the summary now:"""

    response = _get_client().models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    return (response.text or "").strip()





"""from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI


load_dotenv(Path(__file__).parent.parent / ".env")

client = OpenAI()

response = client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[
        {
            "role": "user",
            "content": "Summarize this meeting note"
        }
    ]
)

print(response.choices[0].message.content)"""
