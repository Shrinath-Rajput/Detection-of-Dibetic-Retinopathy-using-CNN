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

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_API_VERSION = "v1beta"
GEMINI_BASE_URL = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}"

GENAI_AVAILABLE = False
GENAI_SDK_VERSION = "REST-only"
GEMINI_MODELS = []
GEMINI_MODEL = None
GEMINI_RUNTIME_INFO = {}

# Rate limiting configuration
REQUEST_DELAY = 2  # Minimum seconds between requests
RETRY_ATTEMPTS = 1  # Only one request per selected model to avoid burning quota
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


def discover_supported_gemini_models(api_key=None, timeout=20):
    """Discover Gemini models that officially support generateContent using the public list models API."""
    runtime_key = (api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY or "").strip()
    if not runtime_key:
        return []

    url = f"{GEMINI_BASE_URL}/models?key={runtime_key}"
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            return []
        payload = response.json() if hasattr(response, 'json') else {}
    except Exception as exc:
        print(f"[GEMINI] Failed to discover Gemini models: {exc}")
        return []

    supported = []
    for model in payload.get("models", []):
        name = model.get("name", "")
        methods = model.get("supportedGenerationMethods", []) or []
        if "generateContent" in methods and name.startswith("models/"):
            supported.append(name.split("/", 1)[1])
    return supported


def _initialize_gemini_runtime(api_key=None):
    """Resolve the available Gemini models once and print startup information."""
    global GEMINI_MODELS, GEMINI_MODEL, GEMINI_RUNTIME_INFO
    load_dotenv(override=False)
    runtime_key = (api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY or "").strip()

    discovered_models = discover_supported_gemini_models(runtime_key)
    env_models = [
        model.strip()
        for model in os.getenv("GEMINI_MODELS", "").split(",")
        if model.strip()
    ]

    if discovered_models:
        GEMINI_MODELS = discovered_models
    elif env_models:
        GEMINI_MODELS = env_models
    else:
        GEMINI_MODELS = []

    GEMINI_MODEL = GEMINI_MODELS[0] if GEMINI_MODELS else None
    GEMINI_RUNTIME_INFO = {
        "api_key_prefix": runtime_key[:10] if runtime_key else "MISSING",
        "api_version": GEMINI_API_VERSION,
        "rest_endpoint": f"{GEMINI_BASE_URL}/models",
        "available_models": GEMINI_MODELS,
        "selected_model": GEMINI_MODEL,
    }

    print("[GEMINI] Startup configuration")
    print(f"[GEMINI] SDK version: {GENAI_SDK_VERSION}")
    print(f"[GEMINI] API version: {GEMINI_RUNTIME_INFO['api_version']}")
    print(f"[GEMINI] REST endpoint: {GEMINI_RUNTIME_INFO['rest_endpoint']}")
    print(f"[GEMINI] Loaded API key prefix: {GEMINI_RUNTIME_INFO['api_key_prefix']}")
    print(f"[GEMINI] Available Gemini models: {', '.join(GEMINI_MODELS) if GEMINI_MODELS else 'None'}")
    print(f"[GEMINI] Selected model: {GEMINI_MODEL or 'None'}")
    return GEMINI_RUNTIME_INFO


def _get_gemini_runtime_config(api_key=None, model_name=None):
    """Load the current Gemini key/model settings from the environment at runtime."""
    load_dotenv(override=False)
    runtime_key = (api_key or os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY or "").strip()
    runtime_models = list(GEMINI_MODELS)
    if not runtime_models:
        runtime_models = discover_supported_gemini_models(runtime_key)
    if not runtime_models:
        env_models = [
            model.strip()
            for model in os.getenv("GEMINI_MODELS", "").split(",")
            if model.strip()
        ]
        runtime_models = env_models

    runtime_model = (model_name or os.getenv("GEMINI_MODEL") or runtime_models[0] if runtime_models else None or GEMINI_MODEL or None)
    if runtime_model is None and runtime_models:
        runtime_model = runtime_models[0]

    runtime_url = f"{GEMINI_BASE_URL}/models/{runtime_model}:generateContent" if runtime_model else None
    return runtime_key, runtime_models, runtime_model, runtime_url


def _classify_gemini_error(status_code, payload):
    """Convert Gemini API failures into a human-readable reason."""
    if not isinstance(payload, dict):
        return "Gemini API returned an unexpected response"

    error_info = payload.get("error") if isinstance(payload.get("error"), dict) else payload
    message = ""
    status_text = ""
    if isinstance(error_info, dict):
        message = str(error_info.get("message", ""))
        status_text = str(error_info.get("status", ""))

    combined = f"{message} {status_text}".lower()

    if status_code == 429 or "quota" in combined or "free_tier" in combined or "resource_exhausted" in combined:
        return "Quota exceeded for the Gemini API free tier or project quota"
    if status_code == 429 or "rate limit" in combined or "too many requests" in combined:
        return "Rate limit exceeded"
    if status_code in {401, 403} or "invalid api key" in combined or "api key" in combined and "invalid" in combined:
        return "Invalid or unauthorized API key"
    if status_code == 400 and "billing" in combined:
        return "Billing is not enabled for the project"
    if status_code in {404, 400} and ("not found" in combined or "model" in combined or "unsupported" in combined):
        return "Unsupported model, wrong endpoint, or model not enabled for the project"
    if status_code in {403} and ("project" in combined or "permission" in combined):
        return "Project restriction or access issue"
    return "Gemini API returned a non-success response"


def _print_gemini_error_details(status_code, payload, request_url, model_name, endpoint):
    """Print the full Gemini API error response for debugging and support."""
    error_info = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else payload
    error_code = None
    error_message = None
    if isinstance(error_info, dict):
        error_code = error_info.get("code")
        error_message = error_info.get("message")

    reason = _classify_gemini_error(status_code, payload)
    print("[CHATBOT] Gemini API Error Details")
    print(f"HTTP Status: {status_code}")
    print(f"Error Code: {error_code if error_code is not None else 'N/A'}")
    print(f"Error Message: {error_message if error_message else 'N/A'}")
    print(f"Full JSON Response: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    print(f"Request URL: {request_url}")
    print(f"Model Name: {model_name}")
    print(f"API Endpoint: {endpoint}")
    print(f"Reason: {reason}")


def _should_fallback_to_next_model(status_code, payload=None, error_message=None):
    """Return True when the current Gemini model should be skipped and the next one tried."""
    if status_code in {429, 404, 403}:
        return True

    if payload is None:
        payload = {}
    if isinstance(payload, dict):
        error_info = payload.get("error") if isinstance(payload.get("error"), dict) else payload
        if isinstance(error_info, dict):
            message = str(error_info.get("message", "")).lower()
            status_text = str(error_info.get("status", "")).lower()
            if "quota" in message or "free_tier" in message or "resource_exhausted" in status_text:
                return True
            if "not found" in message or "unsupported" in message or "model" in message and "not" in message:
                return True
    if error_message:
        message = str(error_message).lower()
        if "quota" in message or "resource_exhausted" in message or "free_tier" in message or "unsupported" in message:
            return True
    return False


def build_gemini_request(user_message, api_key=None, model_name=None):
    """Build a Gemini request using the official REST endpoint and API key authentication."""
    key, _, model, url = _get_gemini_runtime_config(api_key=api_key, model_name=model_name)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "system_instruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "generationConfig": {
            "temperature": 0.7,
            "topP": 0.95,
            "topK": 40,
            "maxOutputTokens": 1000,
        },
    }

    headers = {
        "Content-Type": "application/json",
    }

    if key:
        headers["x-goog-api-key"] = key

    return {"url": url, "headers": headers, "payload": payload, "model": model}


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
    load_dotenv(override=False)
    key = (os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY or "").strip()
    if not key:
        return False, "API key not set in .env file"
    
    if len(key) < 20:
        return False, f"API key too short (length: {len(key)})"
    
    # Accept keys starting with AI, AQ, or other valid prefixes
    if not (key.startswith("AI") or key.startswith("AQ")):
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
    "Notes",
]


def build_report_prompt(prediction, request_id=None, lang=None):
    """Create a fresh, highly specific Gemini prompt for a retina medical report."""
    diagnosis = (prediction or "unknown diagnosis").strip()
    nonce = request_id or str(uuid.uuid4())[:8]
    language_label = {
        'en': 'English',
        'hi': 'Hindi',
        'mr': 'Marathi'
    }.get(lang, 'English')
    language_instruction = (
        f"Write all section values in {language_label}. "
        f"Keep the JSON keys exactly in English: Clinical Interpretation, Disease Summary, Possible Medical Concerns, "
        f"Treatment Guidance, Lifestyle Recommendations, Follow-up Advice, Medical Disclaimer, and Notes."
    )

    return f"""You are an expert ophthalmologist writing a professional hospital-style medical assessment report for retinal imaging. Request ID: {nonce}.

Based on the imaging assessment showing \"{diagnosis}\", create a complete, clinically meaningful report.

CRITICAL: You MUST return valid JSON with EXACTLY these 8 keys (and no other keys):
1. Clinical Interpretation
2. Disease Summary
3. Possible Medical Concerns
4. Treatment Guidance
5. Lifestyle Recommendations
6. Follow-up Advice
7. Medical Disclaimer
8. Notes

{language_instruction}

Rules:
- Write each section as 3-6 meaningful sentences.
- Use professional medical language appropriate for ophthalmology and retinal disease.
- Include specific clinical details and management guidance related to \"{diagnosis}\".
- Do not use placeholder text, generic fallback messages, or phrases such as "not available", "unavailable", "clinical interpretation not available", "disease summary not available", or "information not available".
- Do not repeat the same wording or phrasing across sections.
- Do not include any additional keys, explanations, or metadata.

Return ONLY valid JSON, no markdown, no code blocks, no explanations. Start with {{ and end with }}.

Example format:
{{
  "Clinical Interpretation": "Your detailed clinical text here...",
  "Disease Summary": "Your summary text here...",
  "Possible Medical Concerns": "Your concerns text here...",
  "Treatment Guidance": "Your guidance text here...",
  "Lifestyle Recommendations": "Your recommendations here...",
  "Follow-up Advice": "Your follow-up text here...",
  "Medical Disclaimer": "Standard medical disclaimer...",
  "Notes": "Additional clinical notes here..."
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

    forbidden_markers = [
        "not available",
        "unavailable",
        "information not available",
        "clinical interpretation not available",
        "disease summary not available",
        "placeholder",
        "fallback",
        "could not generate",
        "could not be generated",
        "उपलब्ध नहीं",
        "उपलब्ध नाही",
        "माहिती उपलब्ध नाही",
    ]

    def is_valid_section(value):
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        if len(normalized) < 20:
            return False
        for marker in forbidden_markers:
            if marker in normalized:
                return False
        return True

    # Try 1: Direct JSON parsing - MUST WORK for well-formed JSON
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            sections = {}
            for key in REPORT_SECTION_KEYS:
                value = parsed.get(key)
                if is_valid_section(value):
                    sections[key] = value.strip()
            if len(sections) >= len(REPORT_SECTION_KEYS) - 1:
                for key in REPORT_SECTION_KEYS:
                    if key not in sections:
                        sections[key] = ""
                return sections
    except (json.JSONDecodeError, ValueError):
        pass
    except Exception:
        pass

    def parse_json_sections(parsed):
        if not isinstance(parsed, dict):
            return None
        sections = {}
        for key in REPORT_SECTION_KEYS:
            value = parsed.get(key)
            if is_valid_section(value):
                sections[key] = value.strip()
        if len(sections) == len(REPORT_SECTION_KEYS):
            return sections
        if len(sections) == len(REPORT_SECTION_KEYS) - 1 and "Medical Disclaimer" not in sections:
            sections["Medical Disclaimer"] = "This report is for informational purposes only and cannot substitute professional medical evaluation. Please consult a licensed healthcare provider."
            return sections
        return None

    # Try 2: JSON wrapped in code blocks (markdown)
    if "```" in cleaned:
        code_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.I | re.S)
        if code_match:
            json_content = code_match.group(1).strip()
            try:
                parsed = json.loads(json_content)
                sections = parse_json_sections(parsed)
                if sections:
                    return sections
            except (json.JSONDecodeError, ValueError):
                pass

    # Try 3: Find JSON object anywhere in the text (handles extra text before/after)
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned, re.S)
    if json_match:
        json_str = json_match.group(0)
        try:
            parsed = json.loads(json_str)
            sections = parse_json_sections(parsed)
            if sections:
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
    if len(sections) >= len(REPORT_SECTION_KEYS) - 1:
        for key in REPORT_SECTION_KEYS:
            if key not in sections:
                sections[key] = ""
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


def generate_dynamic_medical_report(prediction, request_id=None, strict=True, api_key=None, lang=None):
    """
    Generate a fresh, Gemini-produced medical report for the retina prediction.
    CRITICAL: Only return properly parsed sections, never raw response text.
    """
    prompt = build_report_prompt(prediction=prediction, request_id=request_id, lang=lang)
    
    try:
        reply = chatbot_response(prompt, strict=True, api_key=api_key, lang=lang)
    except Exception as exc:
        print(f"[REPORT] Gemini API Error: {exc}")
        raise RuntimeError(f"Gemini medical report generation failed: {exc}") from exc

    if not reply or not reply.strip():
        print(f"[REPORT] Gemini returned empty response")
        raise RuntimeError("Gemini API returned an empty response. Please try again.")

    print(f"[REPORT] Received response from Gemini (length: {len(reply)})")
    print(f"[REPORT] Raw Gemini response: {reply}")
    
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
                sections[key] = ""
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


def chatbot_response(user_message, strict=False, api_key=None, lang=None):
    """
    Send user message to Gemini API once per selected model and surface the real error if the request fails.
    """
    global quota_reset_time

    if not user_message or len(user_message.strip()) < 2:
        return "Please enter a valid question."

    if not rate_limit_check():
        raise RuntimeError("Gemini requests are temporarily rate-limited. Please try again shortly.")

    runtime_key, runtime_models, runtime_model, runtime_url = _get_gemini_runtime_config(api_key=api_key)
    if not runtime_key:
        raise RuntimeError("GEMINI_API_KEY is not configured. Set it in the environment or .env file.")

    if not runtime_models:
        raise RuntimeError("No Gemini models are available for this API key. Verify the key and account access.")

    _initialize_gemini_runtime(runtime_key)
    runtime_key, runtime_models, runtime_model, runtime_url = _get_gemini_runtime_config(api_key=api_key)

    print("[CHATBOT] Gemini configuration")
    print(f"API Key loaded: yes")
    print(f"API Key length: {len(runtime_key)}")
    print(f"API Key prefix: {runtime_key[:10]}")
    print(f"Model Name: {runtime_model}")
    print(f"API Endpoint: {runtime_url}")

    if lang:
        lang_label = {
            'en': 'English',
            'hi': 'Hindi',
            'mr': 'Marathi'
        }.get(lang, lang)
        user_message = f"Respond ONLY in {lang_label}.\n\n" + user_message

    last_error = None
    for model_name in runtime_models:
        print(f"[CHATBOT] Attempting Gemini model: {model_name}")
        try:
            request = build_gemini_request(user_message, api_key=runtime_key, model_name=model_name)
            response = requests.post(
                request["url"],
                headers=request["headers"],
                json=request["payload"],
                timeout=30,
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                if ("candidates" in data and len(data["candidates"]) > 0 and
                    "content" in data["candidates"][0] and
                    "parts" in data["candidates"][0]["content"] and
                    len(data["candidates"][0]["content"]["parts"]) > 0):
                    reply = data["candidates"][0]["content"]["parts"][0]["text"]
                    print(f"[CHATBOT] Gemini Response Generated via {model_name}")
                    return reply

            try:
                payload = response.json()
            except ValueError:
                payload = {"raw_text": response.text}

            _print_gemini_error_details(
                response.status_code,
                payload,
                request["url"],
                model_name,
                request["url"],
            )

            if response.status_code in {401, 403}:
                raise RuntimeError(f"Gemini API request failed: {response.status_code} - configuration or authorization issue")

            last_error = payload
            if _should_fallback_to_next_model(response.status_code, payload):
                if model_name != runtime_models[-1]:
                    print(f"[CHATBOT] Switching to the next Gemini model after {model_name}")
                    continue
                raise RuntimeError(f"Gemini API request failed for all available models: {response.status_code}")
            raise RuntimeError(f"Gemini API request failed: {response.status_code}")
        except requests.RequestException as exc:
            print(f"[CHATBOT] Gemini REST request failed for {model_name}: {exc}")
            last_error = {"error": {"message": str(exc)}}
            if model_name != runtime_models[-1]:
                continue
            raise RuntimeError(f"Gemini REST request failed for {model_name}: {exc}") from exc
        except RuntimeError:
            raise
        except Exception as exc:
            print(f"[CHATBOT] Gemini request error for {model_name}: {exc}")
            if model_name != runtime_models[-1]:
                continue
            raise RuntimeError(f"Gemini request error for {model_name}: {exc}") from exc

    quota_reset_time = time.time() + 60
    if last_error is not None:
        raise RuntimeError(f"Gemini API did not return a usable response: {last_error}")
    raise RuntimeError("Gemini API did not return a usable response")
