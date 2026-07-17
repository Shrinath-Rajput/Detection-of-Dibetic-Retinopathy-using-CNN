import os
import requests
from dotenv import load_dotenv
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Try to use the supported Gemini SDK if available
GENAI_AVAILABLE = False
try:
    from google import genai as google_genai
    GENAI_AVAILABLE = True
    try:
        if GEMINI_API_KEY:
            google_genai_client = google_genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        GENAI_AVAILABLE = False
except ImportError:
    GENAI_AVAILABLE = False
    google_genai_client = None

# Fallback REST API endpoint
DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
]

GEMINI_MODELS = [
    model.strip()
    for model in os.getenv("GEMINI_MODELS", ",".join(DEFAULT_GEMINI_MODELS)).split(",")
    if model.strip()
]
GEMINI_MODEL = GEMINI_MODELS[0] if GEMINI_MODELS else DEFAULT_GEMINI_MODELS[0]
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Rate limiting configuration
REQUEST_DELAY = 2  # Minimum seconds between requests
RETRY_ATTEMPTS = 3  # Number of retries for failed requests
RETRY_DELAY = 3  # Initial delay in seconds for retry backoff

# Store last request time for rate limiting
last_request_time = 0
quota_reset_time = None  # Track when quota resets

SYSTEM_PROMPT = """
You are a helpful AI assistant for CareSense, a healthcare information platform. 
Answer any question the user asks about health, medical conditions, symptoms, nutrition, fitness, or general wellness.
Be informative, accurate, and concise. Provide practical advice when appropriate.
Always recommend consulting a healthcare professional for serious medical concerns.
"""


def build_gemini_request(user_message, api_key=None, model_name=None):
    """Build a Gemini request using Google AI Studio API key authentication."""
    key = api_key or GEMINI_API_KEY
    payload = {
        "contents": [{"parts": [{"text": user_message}]}],
        "generationConfig": {
            "temperature": 0.9,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 400,
        },
    }

    headers = {
        "Content-Type": "application/json",
    }
    model = model_name or GEMINI_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    if key:
        headers["x-goog-api-key"] = key
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}key={key}"

    return {"url": url, "headers": headers, "payload": payload}


def rate_limit_check():
    """Enforce minimum delay between API requests to avoid rate limiting"""
    global last_request_time, quota_reset_time
    
    # If quota is exhausted, check if reset time has passed
    if quota_reset_time is not None:
        if time.time() < quota_reset_time:
            return False
        else:
            quota_reset_time = None
    
    # Standard rate limiting between requests
    current_time = time.time()
    time_since_last = current_time - last_request_time
    
    if time_since_last < REQUEST_DELAY:
        wait_time = REQUEST_DELAY - time_since_last
        time.sleep(wait_time)
    
    last_request_time = time.time()
    return True


def validate_api_key():
    """Validate API key format and existence"""
    if not GEMINI_API_KEY:
        return False, "API key not set in .env file"
    
    if len(GEMINI_API_KEY) < 20:
        return False, f"API key too short (length: {len(GEMINI_API_KEY)})"
    
    # Accept keys starting with AI, AQ, or other valid prefixes
    if not (GEMINI_API_KEY.startswith("AI") or GEMINI_API_KEY.startswith("AQ")):
        return False, f"API key has invalid format (should start with 'AI' or 'AQ')"
    
    return True, "API key format valid"

REPORT_SECTION_KEYS = [
    "Clinical Interpretation",
    "Disease Summary",
    "Possible Medical Concerns",
    "Treatment Guidance",
    "Lifestyle Recommendations",
    "Follow-up Advice",
    "Medical Disclaimer",
]


def build_report_prompt(prediction, request_id=None):
    """Create a fresh, highly specific Gemini prompt for a retina medical report."""
    diagnosis = (prediction or "unknown diagnosis").strip()
    nonce = request_id or str(uuid.uuid4())[:8]
    return f"""You are generating a brand-new retina medical report for request ID {nonce}. 
The imaging assessment indicates: {diagnosis}. 
Write as an experienced ophthalmologist and produce a clinically sound, natural-sounding report that is different from any previous report. 
Important instructions: create a genuinely fresh report every time, never reuse earlier wording, and vary sentence structure and explanation style even when the diagnosis is the same. 
Do not use templates, sentence pools, or canned wording. Do not include placeholder text. 
Return valid JSON with exactly these keys and no extra text: Clinical Interpretation, Disease Summary, Possible Medical Concerns, Treatment Guidance, Lifestyle Recommendations, Follow-up Advice, Medical Disclaimer. 
Each value must be a concise paragraph or one short list. Keep the total response under 220 words and ensure every section is professionally written and unique."""


def extract_report_sections(text):
    """Parse Gemini JSON or headings into structured report sections."""
    if not text:
        return None

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            sections = {}
            for key in REPORT_SECTION_KEYS:
                value = parsed.get(key)
                if isinstance(value, str) and value.strip():
                    sections[key] = value.strip()
            if sections:
                return sections
    except Exception:
        pass

    sections = {}
    for key in REPORT_SECTION_KEYS:
        pattern = re.compile(rf"{re.escape(key)}\s*[:\-]\s*(.+)", re.I | re.S)
        match = pattern.search(cleaned)
        if match:
            sections[key] = match.group(1).strip()
    return sections or None


def generate_dynamic_medical_report(prediction, request_id=None, strict=True, api_key=None):
    """Generate a fresh, Gemini-produced medical report for the retina prediction."""
    prompt = build_report_prompt(prediction=prediction, request_id=request_id)
    try:
        reply = chatbot_response(prompt, strict=strict, api_key=api_key)
    except Exception as exc:
        if strict:
            raise RuntimeError("AI report generation is temporarily unavailable. Please try again later.") from exc
        return None

    if not reply:
        if strict:
            raise RuntimeError("AI report generation is temporarily unavailable. Please try again later.")
        return None

    sections = extract_report_sections(reply)
    if sections and len(sections) >= 5:
        return sections

    if strict:
        raise RuntimeError("AI report generation is temporarily unavailable. Please try again later.")
    return None


def get_fallback_response(user_message):
    """Generate intelligent responses for common health questions"""
    message = user_message.lower().strip()
    
    # Common health questions and answers
    responses = {
        "diabetes": "Diabetes is a chronic condition where the body struggles to regulate blood sugar levels. Type 1 occurs when the pancreas doesn't produce insulin, while Type 2 is when the body can't use insulin effectively. Symptoms include increased thirst, frequent urination, and fatigue. Management involves lifestyle changes, medications, and regular monitoring. Consult a healthcare professional for proper diagnosis and treatment.",
        
        "what is": "I can help explain many health topics. Common questions I can answer include: diabetes, hypertension, PCOD, migraines, symptoms, nutrition, fitness, and preventive care. What would you like to know?",
        
        "heart rate": "A normal resting heart rate is typically 60-100 BPM for adults. Factors like age, fitness level, stress, and caffeine intake affect it. Regular exercise, stress reduction, and adequate sleep can help maintain a healthy heart rate. If you experience persistent abnormal heart rates, consult a doctor.",
        
        "blood pressure": "Normal blood pressure is below 120/80 mmHg. High blood pressure (hypertension) is a major risk factor for heart disease and stroke. Manage it through regular exercise, reduced salt intake, stress management, and medications if needed. Monitor regularly and consult your doctor.",
        
        "exercise": "Regular physical activity (150 minutes of moderate exercise per week) improves cardiovascular health, weight management, and mental well-being. Include a mix of cardio, strength training, and flexibility exercises. Start gradually and consult a doctor before major exercise changes.",
        
        "diet": "A healthy diet includes fruits, vegetables, whole grains, lean proteins, and healthy fats. Limit processed foods, sugar, and salt. Maintain proper hydration and portion sizes. Personalized nutrition advice from a dietitian can help achieve your health goals.",
        
        "stress": "Chronic stress affects physical and mental health. Manage it through exercise, meditation, adequate sleep, social connections, and hobbies. If stress becomes overwhelming, consider professional counseling. Practice relaxation techniques daily.",
        
        "sleep": "Adults need 7-9 hours of quality sleep nightly. Poor sleep increases disease risk. Improve sleep by maintaining a regular schedule, avoiding screens before bed, creating a dark room, and exercising regularly. Consult a doctor if you have persistent sleep issues.",
        
        "weight": "Healthy weight depends on age, height, and body composition. Regular exercise combined with a balanced diet helps maintain weight. BMI is a general guideline, but muscle weight affects it. Consult a healthcare provider for personalized advice.",
        
        "migraine": "Migraines are severe headaches often accompanied by nausea, light sensitivity, or aura. Triggers include stress, hormonal changes, certain foods, and lack of sleep. Management involves identifying triggers, lifestyle changes, and medications. Consult a neurologist for severe cases.",
        
        "cholesterol": "High cholesterol increases heart disease risk. Reduce it through a healthy diet, exercise, and weight management. Medications may be needed. Regular monitoring helps track levels. Consult your doctor about your cholesterol targets.",
        
        "hypertension": "High blood pressure (above 130/80) can lead to serious complications. Manage it through salt reduction, regular exercise, stress management, weight loss, and medications if needed. Regular monitoring is essential.",
        
        "pcod": "PCOD (Polycystic Ovary Disorder) affects many women and causes irregular periods, infertility, and metabolic issues. Management includes lifestyle changes, medications, and regular monitoring. Consult a gynecologist for diagnosis and treatment.",
        
        "default": "I'm your AI healthcare assistant. I can answer questions about common health conditions, symptoms, nutrition, fitness, preventive care, and our diagnostic services. Ask me anything to learn more!"
    }
    
    # Try to find a relevant response
    for keyword, response_text in responses.items():
        if keyword in message:
            return response_text
    
    # If message contains multiple keywords, try to match
    if any(word in message for word in ["symptom", "signs", "disease"]):
        return "Please describe the symptoms or condition you're asking about, and I'll provide relevant health information."
    
    if any(word in message for word in ["help", "how", "what"]):
        return responses["default"]
    
    # Default response
    return responses["default"]


def chatbot_response(user_message, strict=False, api_key=None):
    """
    Send user message to Gemini API or use intelligent offline fallback.
    Silently handles all API failures without exposing errors to user.
    """
    global quota_reset_time

    if not user_message or len(user_message.strip()) < 2:
        return "Please enter a valid question."

    if not rate_limit_check():
        if strict:
            raise RuntimeError("AI report generation is temporarily unavailable. Please try again later.")
        return get_fallback_response(user_message)

    if not (api_key or GEMINI_API_KEY):
        if strict:
            raise RuntimeError("AI report generation is temporarily unavailable. Please try again later.")
        return get_fallback_response(user_message)

    for model_name in GEMINI_MODELS:
        if GENAI_AVAILABLE and google_genai_client is not None:
            try:
                response = google_genai_client.models.generate_content(
                    model=model_name,
                    contents=user_message,
                )
                reply = response.text if hasattr(response, 'text') else str(response)
                print(f"[CHATBOT] Gemini Response Generated via {model_name}")
                return reply
            except Exception as exc:
                print(f"[CHATBOT] Gemini SDK model failed: {model_name}: {exc}")
                continue

        for attempt in range(RETRY_ATTEMPTS):
            try:
                request = build_gemini_request(user_message, api_key=api_key, model_name=model_name)
                response = requests.post(
                    request["url"],
                    headers=request["headers"],
                    json=request["payload"],
                    timeout=20,
                )

                if response.status_code == 200:
                    data = response.json()
                    if ("candidates" in data and len(data["candidates"]) > 0 and
                        "content" in data["candidates"][0] and
                        "parts" in data["candidates"][0]["content"] and
                        len(data["candidates"][0]["content"]["parts"]) > 0):
                        reply = data["candidates"][0]["content"]["parts"][0]["text"]
                        print(f"[CHATBOT] Gemini Response Generated via {model_name}")
                        return reply

                if response.status_code in {404, 429, 500, 502, 503, 504}:
                    print(f"[CHATBOT] Gemini REST model failed: {model_name} ({response.status_code})")
                    if attempt < RETRY_ATTEMPTS - 1:
                        time.sleep(RETRY_DELAY * (attempt + 1))
                        continue
                    break
                break
            except requests.RequestException as exc:
                print(f"[CHATBOT] Gemini REST request failed for {model_name}: {exc}")
                if attempt < RETRY_ATTEMPTS - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                break
            except Exception as exc:
                print(f"[CHATBOT] Gemini request error for {model_name}: {exc}")
                break

    quota_reset_time = time.time() + 60
    if strict:
        raise RuntimeError("AI report generation is temporarily unavailable. Please try again later.")

    print("[CHATBOT] Using Offline Medical Knowledge")
    return get_fallback_response(user_message)