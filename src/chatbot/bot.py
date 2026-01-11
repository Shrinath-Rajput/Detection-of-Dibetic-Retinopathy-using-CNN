import wikipedia
import requests

# -------------------------
# Helper: greeting check
# -------------------------
def is_greeting(text):
    greetings = [
        "hi", "hello", "hey", "good morning",
        "good afternoon", "good evening"
    ]
    return text.lower().strip() in greetings


# -------------------------
# Main chatbot function
# -------------------------
def chatbot_response(user_message: str) -> str:
    if not user_message or len(user_message.strip()) < 2:
        return "Please ask a clear question 🙂"

    query = user_message.strip()

    # 1️⃣ HANDLE GREETINGS (IMPORTANT FIX)
    if is_greeting(query):
        return "Hello 👋 I'm your AI Assistant. You can ask me any question."

    # 2️⃣ VERY SHORT / VAGUE QUESTIONS
    if len(query.split()) <= 1:
        return "Please ask a complete question so I can help you better 🙂"

    # 3️⃣ TRY WIKIPEDIA (ONLY FOR REAL QUESTIONS)
    try:
        wikipedia.set_lang("en")
        summary = wikipedia.summary(query, sentences=2)
        return summary
    except wikipedia.exceptions.DisambiguationError:
        return (
            "Your question is a bit broad.\n"
            "👉 Please be more specific.\n"
            "Example: 'Virat Kohli cricketer' or 'Python programming language'"
        )
    except wikipedia.exceptions.PageError:
        pass
    except Exception:
        pass

    # 4️⃣ TRY DUCKDUCKGO (FACTUAL BACKUP)
    try:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1
        }
        res = requests.get(url, params=params, timeout=5)
        data = res.json()

        if data.get("AbstractText"):
            return data["AbstractText"]

        if data.get("Answer"):
            return data["Answer"]

        if data.get("Definition"):
            return data["Definition"]

    except Exception:
        pass

    # 5️⃣ CLEAN FINAL FALLBACK (NO FALTU)
    return (
        "I couldn't find a reliable answer for this question.\n\n"
        "👉 Please try rephrasing it or ask with more details."
    )
