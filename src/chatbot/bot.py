# src/chatbot/bot.py

import re

def chatbot_response(message: str) -> str:
    if not message:
        return "Please ask something 🙂"

    msg = message.lower().strip()

    # ---------------- BASIC TALKS ----------------
    greetings = ["hi", "hello", "hey", "hii", "hiii"]
    if msg in greetings:
        return "Hello 👋 I'm your AI Healthcare Assistant. Ask me anything."

    if "who are you" in msg:
        return (
            "I am CareSense AI Assistant 🤖. "
            "I help with health-related questions as well as general questions."
        )

    if "what are you doing" in msg:
        return "I'm here to answer your questions and help you 😊"

    # ---------------- HEALTH QUESTIONS ----------------
    if "pcod" in msg:
        return (
            "PCOD (Polycystic Ovary Disease) is a hormonal disorder in women. "
            "Common symptoms include irregular periods, weight gain, acne, "
            "hair growth, and difficulty in pregnancy."
        )

    if "diabetes" in msg:
        return (
            "Diabetes is a condition where blood sugar levels become high. "
            "It can be managed with diet, exercise, and proper medication."
        )

    if "migraine" in msg:
        return (
            "Migraine is a neurological condition causing intense headaches, "
            "often with nausea, light sensitivity, and sound sensitivity."
        )

    if "heart rate" in msg:
        return (
            "A normal resting heart rate for adults is usually between 60 and 100 BPM."
        )

    if "spo2" in msg or "oxygen" in msg:
        return (
            "Normal SpO₂ (oxygen level) is between 95% and 100%."
        )

    # ---------------- GENERAL KNOWLEDGE ----------------
    if "virat kohli" in msg:
        return (
            "Virat Kohli is a famous Indian cricketer and former captain of the "
            "Indian national team. He is known for his aggressive batting style."
        )

    if "india" in msg:
        return "India is a country in South Asia, known for its rich culture and history."

    if "python" in msg:
        return (
            "Python is a popular programming language used for web development, "
            "AI, machine learning, and data science."
        )

    if "ai" in msg or "artificial intelligence" in msg:
        return (
            "Artificial Intelligence (AI) is a field of computer science where "
            "machines simulate human intelligence."
        )

    # ---------------- FALLBACK (SMART ANSWER) ----------------
    return (
        f"I understood your question: '{message}'. "
        "Currently, I can answer health and general knowledge questions. "
        "Please ask something related 😊"
    )
