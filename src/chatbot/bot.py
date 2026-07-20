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
            "maxOutputTokens": 2000,  # Increased from 400 to allow full medical reports
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
    return f"""You are an expert ophthalmologist writing a detailed medical assessment report for retinal imaging. Request ID: {nonce}.

Based on the imaging assessment showing "{diagnosis}", create a comprehensive and professionally written report.

CRITICAL: You MUST return valid JSON with EXACTLY these 7 keys (and no other keys):
1. Clinical Interpretation
2. Disease Summary
3. Possible Medical Concerns
4. Treatment Guidance
5. Lifestyle Recommendations
6. Follow-up Advice
7. Medical Disclaimer

Rules:
- Write each section as a clear, professional paragraph (2-3 sentences)
- Never use placeholder text or generic messages
- Each response must be UNIQUE and different from previous reports for the same diagnosis
- Never repeat the same wording or phrasing
- Include specific clinical details relevant to "{diagnosis}"
- Make the report clinically accurate and actionable

Return ONLY valid JSON, no markdown, no code blocks, no explanations. Start with {{ and end with }}.

Example format:
{{
  "Clinical Interpretation": "Your detailed clinical text here...",
  "Disease Summary": "Your summary text here...",
  "Possible Medical Concerns": "Your concerns text here...",
  "Treatment Guidance": "Your guidance text here...",
  "Lifestyle Recommendations": "Your recommendations here...",
  "Follow-up Advice": "Your follow-up text here...",
  "Medical Disclaimer": "Standard medical disclaimer..."
}}"""


def extract_report_sections(text):
    """
    Parse Gemini response (JSON, Markdown, or plain text) into structured report sections.
    CRITICAL: Extract actual values, never return raw JSON strings into PDF.
    Handles: valid JSON, JSON in code blocks, Markdown headings, bullet lists.
    """
    if not text:
        return None

    cleaned = text.strip()
    if not cleaned:
        return None
    
    # Try 1: Direct JSON parsing - MUST WORK for well-formed JSON
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            sections = {}
            for key in REPORT_SECTION_KEYS:
                value = parsed.get(key)
                # Ensure we extract the actual string value, not a nested object
                if isinstance(value, str) and value.strip() and len(value.strip()) > 5:
                    sections[key] = value.strip()
            if len(sections) >= 6:
                for key in REPORT_SECTION_KEYS:
                    if key not in sections:
                        sections[key] = "Based on the analysis, please consult with your healthcare provider."
                return sections
    except (json.JSONDecodeError, ValueError):
        pass
    except Exception as e:
        pass
    
    # Try 2: JSON wrapped in code blocks (markdown)
    if "```" in cleaned:
        # Extract content between backticks
        code_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.I | re.S)
        if code_match:
            json_content = code_match.group(1).strip()
            try:
                parsed = json.loads(json_content)
                if isinstance(parsed, dict):
                    sections = {}
                    for key in REPORT_SECTION_KEYS:
                        value = parsed.get(key)
                        if isinstance(value, str) and value.strip() and len(value.strip()) > 5:
                            sections[key] = value.strip()
                    if len(sections) >= 6:
                        for key in REPORT_SECTION_KEYS:
                            if key not in sections:
                                sections[key] = "Based on the analysis, please consult with your healthcare provider."
                        return sections
            except (json.JSONDecodeError, ValueError):
                pass
    
    # Try 3: Find JSON object anywhere in the text (handles extra text before/after)
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.S)
    if json_match:
        json_str = json_match.group(0)
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, dict):
                sections = {}
                for key in REPORT_SECTION_KEYS:
                    value = parsed.get(key)
                    if isinstance(value, str) and value.strip() and len(value.strip()) > 5:
                        sections[key] = value.strip()
                if len(sections) >= 6:
                    for key in REPORT_SECTION_KEYS:
                        if key not in sections:
                            sections[key] = "Based on the analysis, please consult with your healthcare provider."
                    return sections
        except (json.JSONDecodeError, ValueError):
            pass
    
    # Try 4: Markdown/heading-based extraction
    sections = {}
    text_lines = cleaned.split('\n')
    current_section = None
    current_content = []
    
    for line in text_lines:
        line = line.strip()
        if not line or line.startswith('{') or line.startswith('['):
            continue
        
        matched_header = False
        for key in REPORT_SECTION_KEYS:
            # Match section headers
            if (re.match(rf"^#+\s*{re.escape(key)}", line, re.I) or 
                re.match(rf"^{re.escape(key)}\s*[:\-]", line, re.I) or
                re.match(rf"^\*\*{re.escape(key)}\*\*", line, re.I) or
                re.match(rf"^{re.escape(key)}$", line, re.I)):
                
                if current_section and current_content:
                    content = ' '.join(current_content).strip()
                    content = re.sub(r'\s+', ' ', content)  # Clean up whitespace
                    if content and len(content) > 5:
                        sections[current_section] = content
                
                current_section = key
                current_content = []
                
                # Extract inline content
                remaining = re.sub(rf"^#+\s*{re.escape(key)}|^{re.escape(key)}\s*[:|\-]|^\*\*{re.escape(key)}\*\*|^{re.escape(key)}$", "", line, flags=re.I).strip()
                if remaining and not remaining.startswith('{'):
                    current_content.append(remaining)
                
                matched_header = True
                break
        
        if not matched_header and current_section and line and not line.startswith('{'):
            # Clean the line
            clean_line = re.sub(r"^[\-\*\•]\s*|\d+\.\s*|\`+", "", line)
            if clean_line and not clean_line.startswith('{') and len(clean_line) > 3:
                current_content.append(clean_line)
    
    # Save last section
    if current_section and current_content:
        content = ' '.join(current_content).strip()
        content = re.sub(r'\s+', ' ', content)
        if content and len(content) > 5:
            sections[current_section] = content
    
    # If we got good sections, return
    if len(sections) >= 6:
        for key in REPORT_SECTION_KEYS:
            if key not in sections:
                sections[key] = "Based on the analysis, please consult with your healthcare provider."
        return sections
    
    # Try 5: As last resort, distribute paragraphs if we have any content
    if len(sections) >= 3 and len(cleaned) > 100:
        # Fill missing sections with combined content
        combined = ' '.join(sections.values())
        for key in REPORT_SECTION_KEYS:
            if key not in sections:
                sections[key] = combined[:180]
        return sections
    
    return None


def generate_dynamic_medical_report(prediction, request_id=None, strict=True, api_key=None):
    """
    Generate a fresh, Gemini-produced medical report for the retina prediction.
    CRITICAL: Only return properly parsed sections, never raw response text.
    """
    prompt = build_report_prompt(prediction=prediction, request_id=request_id)
    
    try:
        reply = chatbot_response(prompt, strict=False, api_key=api_key)
    except Exception as exc:
        print(f"[REPORT] Gemini API Error: {exc}")
        if strict:
            raise RuntimeError("Gemini API is currently unavailable. Please check your internet connection and API key.") from exc
        return None

    if not reply or not reply.strip():
        print(f"[REPORT] Gemini returned empty response")
        if strict:
            raise RuntimeError("Gemini API returned an empty response. Please try again.")
        return None

    print(f"[REPORT] Received response from Gemini (length: {len(reply)})")
    
    # Parse the response - handles JSON, markdown, plain text
    sections = extract_report_sections(reply)
    
    if sections and len(sections) == len(REPORT_SECTION_KEYS):
        print(f"[REPORT] Successfully extracted {len(sections)} sections from Gemini response")
        return sections
    
    # If we got partial sections, complete them
    if sections and len(sections) > 3:
        print(f"[REPORT] Got {len(sections)} sections, completing missing sections...")
        for key in REPORT_SECTION_KEYS:
            if key not in sections:
                sections[key] = "Based on the analysis, please consult with your healthcare provider for personalized medical guidance."
        return sections
    
    # Parsing failed - don't use raw response
    print(f"[REPORT] Failed to parse response into structured sections")
    if strict:
        raise RuntimeError("Failed to parse Gemini response into proper format. Please try again.")
    
    # Non-strict mode: return None instead of garbage data
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