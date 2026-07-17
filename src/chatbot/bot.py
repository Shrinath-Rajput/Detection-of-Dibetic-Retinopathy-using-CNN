import os
import requests
from dotenv import load_dotenv
import json
import time
from datetime import datetime, timedelta
from functools import wraps

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Try to use google-generativeai SDK if available
GENAI_AVAILABLE = False
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
    try:
        if GEMINI_API_KEY:
            genai.configure(api_key=GEMINI_API_KEY)
    except Exception as config_error:
        print(f"[GENAI CONFIG ERROR] {config_error}")
        GENAI_AVAILABLE = False
except ImportError:
    GENAI_AVAILABLE = False

# Fallback REST API endpoint
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Rate limiting configuration
REQUEST_DELAY = 1  # Minimum seconds between requests
RETRY_ATTEMPTS = 3  # Number of retries for failed requests
RETRY_DELAY = 2  # Initial delay in seconds for retry backoff

# Store last request time for rate limiting
last_request_time = 0

SYSTEM_PROMPT = """
You are a helpful AI assistant for CareSense, a healthcare information platform. 
Answer any question the user asks about health, medical conditions, symptoms, nutrition, fitness, or general wellness.
Be informative, accurate, and concise. Provide practical advice when appropriate.
Always recommend consulting a healthcare professional for serious medical concerns.
"""

def rate_limit_check():
    """Enforce minimum delay between API requests to avoid rate limiting"""
    global last_request_time
    
    current_time = time.time()
    time_since_last = current_time - last_request_time
    
    if time_since_last < REQUEST_DELAY:
        wait_time = REQUEST_DELAY - time_since_last
        print(f"[RATE LIMIT] Waiting {wait_time:.2f}s before next request...")
        time.sleep(wait_time)
    
    last_request_time = time.time()

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


def chatbot_response(user_message):
    """
    Send user message to Gemini API or use fallback for responses.
    """

    if not user_message or len(user_message.strip()) < 2:
        return "Please enter a valid question."

    print(f"\n[CHATBOT] Processing message: '{user_message[:50]}...'")

    # Try using the genai SDK first
    if GENAI_AVAILABLE:
        try:
            print("[CHATBOT] Using google-generativeai SDK")
            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(user_message, stream=False, safety_settings={})
            reply = response.text if hasattr(response, 'text') else str(response)
            print(f"[CHATBOT] Response received: {len(reply)} characters")
            return reply
        except Exception as e:
            print(f"[CHATBOT SDK ERROR] {type(e).__name__}: {e}")
            print("[CHATBOT] Falling back to REST API...")

    # Fallback to REST API
    try:
        print("[CHATBOT] Using REST API")
        
        if not GEMINI_API_KEY:
            print("[CHATBOT ERROR] API key not configured")
            return get_fallback_response(user_message)

        payload = {
            "contents": [{
                "parts": [{"text": user_message}]
            }]
        }

        response = requests.post(
            f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=10
        )

        print(f"[CHATBOT API] Status: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            if ("candidates" in data and len(data["candidates"]) > 0 and
                "content" in data["candidates"][0] and
                "parts" in data["candidates"][0]["content"] and
                len(data["candidates"][0]["content"]["parts"]) > 0):
                reply = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"[CHATBOT] Success: {len(reply)} characters")
                return reply
            else:
                return get_fallback_response(user_message)

        else:
            # API failed, use fallback
            print(f"[CHATBOT] API error {response.status_code}, using fallback")
            return get_fallback_response(user_message)

    except Exception as e:
        print(f"[CHATBOT ERROR] {type(e).__name__}: {e}")
        return get_fallback_response(user_message)