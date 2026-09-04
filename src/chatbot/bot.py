import os
import base64
import mimetypes
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
GEMINI_RETRY_ATTEMPTS = 3  # Retry transient Gemini failures a few times before falling back
GEMINI_REQUEST_DEADLINE = 90  # Bound the complete request across retries and fallback models

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

    preferred_order = [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-flash-latest",
        "gemini-2.5-flash",
        "gemini-3.1-flash-lite-preview",
        "gemini-2.5-flash-lite",
        "gemini-pro-latest"
    ]
    excluded_keywords = ["tts", "image", "transcribe", "clip", "robotics", "computer-use", "gemma"]
    filtered = [m for m in supported if not any(k in m.lower() for k in excluded_keywords)]
    ordered = [p for p in preferred_order if p in filtered]
    for m in filtered:
        if m not in ordered:
            ordered.append(m)
    return ordered if ordered else supported


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


def build_gemini_request(user_message, api_key=None, model_name=None, image_path=None):
    """Build a Gemini request using the official REST endpoint and API key authentication."""
    key, _, model, url = _get_gemini_runtime_config(api_key=api_key, model_name=model_name)
    parts = [{"text": user_message}]
    if image_path and os.path.isfile(image_path):
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as image_file:
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(image_file.read()).decode("ascii"),
                }
            })

    is_json_request = "return only valid json" in user_message.lower() or "exact top-level keys" in user_message.lower()
    gen_config = {
        "temperature": 0.3 if is_json_request else 0.7,
        "topP": 0.95,
        "topK": 40,
        "maxOutputTokens": 8192 if is_json_request else 2048,
    }
    if is_json_request:
        gen_config["responseMimeType"] = "application/json"

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_config,
    }
    if not is_json_request:
        payload["system_instruction"] = {
            "parts": [{"text": SYSTEM_PROMPT}]
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

REPORT_LANGUAGES = ("English", "Marathi", "Hindi")


def build_report_prompt(prediction, request_id=None, lang=None, analysis_data=None):
    """Create a fresh Gemini prompt from the current retinal analysis only."""
    if isinstance(prediction, dict):
        analysis = dict(prediction)
    else:
        analysis = dict(analysis_data or {})
        analysis.setdefault("prediction", prediction)
    analysis_json = json.dumps(analysis, ensure_ascii=False, sort_keys=True)
    nonce = request_id or str(uuid.uuid4())[:8]
    return f"""You are an expert ophthalmologist writing a professional hospital-style medical assessment report for the CURRENT retinal image. Request ID: {nonce}.

Use the attached CURRENT image together with this current analysis payload. Do not infer or reuse facts from another patient, image, request, or previous report:
{analysis_json}

CRITICAL: Return ONLY valid JSON with these exact top-level keys: riskLevel, clinicalInterpretation, diseaseSummary, possibleMedicalConcerns, treatmentGuidance, lifestyleRecommendations, followUpAdvice, medicalDisclaimer, notes.
Each key must contain an object with exactly these keys: English, Marathi, Hindi. Each language value must be a JSON array of 2-5 concise, meaningful bullet-point strings.
The human-readable "Notes" section is required and is represented by the JSON key "notes".

Rules:
- Every point must describe findings, limitations, concerns, guidance, or follow-up supported by the CURRENT image and supplied analysis data.
- Inspect the image for supported retinal features such as optic disc/cup, vessels, macula, hemorrhages, exudates, and other visible abnormalities; explicitly state when a feature cannot be assessed from image quality.
- Set riskLevel separately in all three languages and make all sections consistent with that risk: High Risk, Moderate Risk, Low Risk, or Normal / No Significant Abnormality.
- Marathi and Hindi must be complete, meaningful clinical explanations of the current findings, not translated headings or empty copies.
- Generate fresh content for every request. Do not use placeholder text, generic ophthalmology teaching, fixed disease summaries, or content from a previous report.
- Do not return "Information not available" for any section when the image findings and supplied analysis provide enough evidence to populate it; only use that fallback when the evidence is genuinely insufficient.
- Never invent unsupported patient-specific facts. State uncertainty clearly and recommend professional ophthalmological evaluation wherever the image cannot establish a diagnosis or management plan.
- Do not include markdown, explanations, or any keys beyond the required schema.

Return ONLY valid JSON, no markdown, no code blocks, no explanations. Start with {{ and end with }}.

Example format:
{{
    "riskLevel": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "clinicalInterpretation": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "diseaseSummary": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "possibleMedicalConcerns": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "treatmentGuidance": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "lifestyleRecommendations": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "followUpAdvice": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "medicalDisclaimer": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}},
    "notes": {{"English": ["..."], "Marathi": ["..."], "Hindi": ["..."]}}
}}"""


def _normalize_section_heading(line):
    """Normalize a potential section heading so numbered headers are parsed correctly."""
    if not isinstance(line, str):
        return ""

    cleaned = line.strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"^\s*[-*•]+\s*", "", cleaned)
    cleaned = re.sub(r"^(?:section\s*\d+|\d+[\.)])\s*[:\-–—]?\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.strip()
    cleaned = re.sub(r"\*\*|__", "", cleaned)
    cleaned = re.sub(r"^\*|\*$|^_|_$", "", cleaned)
    cleaned = cleaned.rstrip(":").strip()
    return cleaned


def _canonicalize_report_key(raw_key):
    """Map varied section-name formats to the canonical report keys."""
    if not isinstance(raw_key, str):
        return None

    key_map = {
        "risk level": "Risk Level",
        "risklevel": "Risk Level",
        "clinical interpretation": "Clinical Interpretation",
        "clinicalinterpretation": "Clinical Interpretation",
        "disease summary": "Disease Summary",
        "diseasesummary": "Disease Summary",
        "possible medical concerns": "Possible Medical Concerns",
        "possiblemedicalconcerns": "Possible Medical Concerns",
        "treatment guidance": "Treatment Guidance",
        "treatmentguidance": "Treatment Guidance",
        "lifestyle recommendations": "Lifestyle Recommendations",
        "lifestylerecommendations": "Lifestyle Recommendations",
        "follow up advice": "Follow-up Advice",
        "followup advice": "Follow-up Advice",
        "followupadvice": "Follow-up Advice",
        "medical disclaimer": "Medical Disclaimer",
        "medicaldisclaimer": "Medical Disclaimer",
        "notes": "Notes",
    }

    normalized = re.sub(r"[^a-z0-9]+", " ", raw_key.strip().lower()).strip()
    return key_map.get(normalized)


def _coerce_report_value(value):
    """Normalize Gemini section values while preserving point-wise arrays."""
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, dict):
        language_keys = {
            "english": "English",
            "hindi": "Hindi",
            "marathi": "Marathi",
        }
        return {
            language_keys.get(str(key).strip().lower(), str(key)): _coerce_report_value(item)
            for key, item in value.items()
            if _coerce_report_value(item) not in ("", [], {})
        }
    if isinstance(value, str):
        text = value.strip()
    elif value is None:
        text = ""
    else:
        text = str(value).strip()

    if not text:
        return ""

    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_severity_report_fallback(prediction=None, confidence=None, risk_level=None):
    """
    Generate dynamic, medically accurate, and complete fallback report content
    for every supported DR severity level (Low, Moderate, High, No_DR, Mild, Severe, Proliferate_DR)
    as well as Cataract and Glaucoma across all 3 languages (English, Hindi, Marathi).
    GUARANTEE: Returns non-empty bullet points for all 8 required sections in all 3 languages.
    """
    pred_str = str(prediction or "").strip().lower()
    risk_str = str(risk_level or "").strip().lower()

    if "proliferat" in pred_str or "pdr" in pred_str:
        category = "proliferative"
    elif "severe" in pred_str:
        category = "severe"
    elif "moderate" in pred_str:
        category = "moderate"
    elif "mild" in pred_str:
        category = "mild"
    elif "no_dr" in pred_str or "normal" in pred_str:
        category = "no_dr"
    elif "cataract" in pred_str:
        category = "cataract"
    elif "glaucoma" in pred_str:
        category = "glaucoma"
    elif "high" in pred_str or "high" in risk_str or (isinstance(confidence, (int, float)) and confidence >= 90):
        category = "severe"
    elif "mod" in pred_str or "mod" in risk_str or (isinstance(confidence, (int, float)) and confidence >= 70):
        category = "moderate"
    elif "low" in pred_str or "low" in risk_str:
        category = "mild"
    else:
        category = "moderate"

    data = {
        "no_dr": {
            "Risk Level": {
                "English": ["Low Risk / No Retinopathy"],
                "Hindi": ["कम जोखिम / कोई रेटिनोपैथी नहीं"],
                "Marathi": ["कमी जोखीम / रेटिनोपॅथी नाही"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Retinal fundus image analysis reveals normal retinal architecture without pathological changes.",
                    "Optic disc margins are well-defined, and the neuroretinal rim demonstrates healthy coloration.",
                    "Macular zone is intact with no detectable microaneurysms, hemorrhages, or exudative deposits."
                ],
                "Hindi": [
                    "रेटिनल फंडस छवि विश्लेषण बिना किसी पैथोलॉजिकल परिवर्तन के सामान्य रेटिनल संरचना को प्रकट करता है।",
                    "ऑप्टिक डिस्क के किनारे स्पष्ट हैं, और न्यूरोरेटिनल रिम स्वस्थ रंग प्रदर्शित करता है।",
                    "मैक्युलर क्षेत्र सुरक्षित है और इसमें कोई माइक्रोएन्यूरिज्म, रक्तस्राव या एक्स्युडेट जमा नहीं पाया गया है।"
                ],
                "Marathi": [
                    "रेटिनल फंडस इमेज विश्लेषण कोणत्याही विकृतीशिवाय सामान्य रेटिनल रचना दर्शवते.",
                    "ऑप्टिक डिस्कच्या कडा स्पष्ट आहेत आणि न्यूरोरेटिनल रिम निरोगी स्वरूप दर्शवते.",
                    "मॅक्युलर भाग सुरक्षित असून कोणतेही मायक्रोएन्युरिझम्स, रक्तस्राव किंवा एक्स्युडेट्स आढळले नाहीत."
                ]
            },
            "Disease Summary": {
                "English": [
                    "No signs of diabetic retinopathy were detected on the evaluated retinal examination.",
                    "Retinal blood vessels demonstrate normal caliber without caliber variation, beading, or leakage."
                ],
                "Hindi": [
                    "मूल्यांकन किए गए रेटिनल परीक्षण में डायबेटिक रेटिनोपैथी का कोई लक्षण नहीं पाया गया।",
                    "रेटिना की रक्त वाहिकाएं बिना किसी असामान्यता या रिसाव के सामान्य स्थिति प्रदर्शित करती हैं।"
                ],
                "Marathi": [
                    "तपासणीमध्ये डायबेटिक रेटिनोपॅथीची कोणतीही लक्षणे आढळली नाहीत.",
                    "रेटिनामधील रक्तवाहिन्या सामान्य स्थितीत असून कोणतीही गळती किंवा विकृती नाही."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "Patients diagnosed with diabetes remain at ongoing risk for gradual microvascular changes.",
                    "Subclinical vascular damage may develop over time if blood glucose or blood pressure fluctuates."
                ],
                "Hindi": [
                    "मधुमेह से पीड़ित रोगियों में समय के साथ क्रमिक सूक्ष्म संवहनी परिवर्तनों का निरंतर जोखिम रहता है।",
                    "यदि रक्त शर्करा या रक्तचाप में उतार-चढ़ाव होता है तो भविष्य में संवहनी क्षति विकसित हो सकती है।"
                ],
                "Marathi": [
                    "मधुमेह असलेल्या रुग्णांमध्ये कालांतराने सूक्ष्म रक्तवाहिन्यांचे नुकसान होण्याचा संभाव्य धोका असतो.",
                    "रक्तातील साखर किंवा रक्तदाब अनियमित राहिल्यास रक्तवाहिन्यांवर ताण निर्माण होऊ शकतो."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "No active ocular treatment or laser intervention is required at this stage.",
                    "Maintain proactive systemic management under the supervision of your primary physician.",
                    "Ensure final diagnosis and management plans are confirmed by a qualified ophthalmologist."
                ],
                "Hindi": [
                    "इस स्तर पर किसी प्रत्यक्ष नेत्र उपचार या लेजर हस्तक्षेप की आवश्यकता नहीं है।",
                    "अपने प्राथमिक चिकित्सक की देखरेख में सक्रिय रूप से स्वास्थ्य प्रबंधन बनाए रखें।",
                    "अंतिम निदान और उपचार योजना की पुष्टि किसी योग्य नेत्र रोग विशेषज्ञ द्वारा अवश्य कराएं।"
                ],
                "Marathi": [
                    "या टप्प्यावर डोळ्यांवर कोणत्याही सक्रिय वैद्यकीय किंवा लेझर उपचारांची आवश्यकता नाही.",
                    "आपल्या प्राथमिक डॉक्टरांच्या देखरेखीखाली नियमित आरोग्य नियंत्रण सुरू ठेवा.",
                    "अंतिम निदान आणि उपचारांची खात्री नेहमी पात्र नेत्ररोग तज्ज्ञांकडून करून घ्या."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Maintain optimal glycemic control with an HbA1c target below 7% as recommended by your physician.",
                    "Consume a balanced, nutrient-dense diet rich in green vegetables, whole grains, and healthy fats.",
                    "Engage in regular moderate physical exercise (150 minutes per week) and avoid tobacco usage."
                ],
                "Hindi": [
                    "चिकित्सक की सलाह अनुसार HbA1c का स्तर 7% से कम रखने का प्रयास करें।",
                    "हरी सब्जियों, साबुत अनाज और स्वस्थ वसा से भरपूर संतुलित आहार का सेवन करें।",
                    "नियमित मध्यम शारीरिक व्यायाम (प्रति सप्ताह 150 मिनट) करें और तंबाकू के सेवन से बचें।"
                ],
                "Marathi": [
                    "डॉक्टरांच्या सल्ल्यानुसार HbA1c पातळी ७% पेक्षा कमी राखण्याचा प्रयत्न करा.",
                    "हिरव्या पालेभाज्या, तृणधान्ये आणि पोषक घटकांनी युक्त संतुलित आहाराचे सेवन करा.",
                    "नियमित हलका ते मध्यम व्यायाम (आठवड्याला १५० मिनिटे) करा आणि तंबाखूचे सेवन टाळा."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Schedule an annual dilated eye examination for routine diabetic eye screening.",
                    "Consult an eye specialist promptly if you observe sudden blurriness, floaters, or visual changes."
                ],
                "Hindi": [
                    "नियमित डायबेटिक नेत्र जांच के लिए वार्षिक पुतली फैलाकर परीक्षण का समय निर्धारित करें।",
                    "यदि आपको अचानक धुंधलापन, तैरते धब्बे या दृष्टि परिवर्तन दिखाई दे तो तुरंत नेत्र चिकित्सक से परामर्श लें।"
                ],
                "Marathi": [
                    "नियमित तपासणीसाठी वर्षातून एकदा डोळ्यांची सविस्तर तपासणी करून घ्या.",
                    "अचानक अंधुक दिसणे, काळे ठिपके किंवा दृष्टीमध्ये बदल जाणवल्यास त्वरित डॉक्टरांशी संपर्क साधा."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "This AI-assisted screening assessment is an auxiliary tool and not a definitive medical diagnosis.",
                    "Complete clinical evaluation by a certified ophthalmologist is required for diagnostic verification."
                ],
                "Hindi": [
                    "यह एआई-समर्थित स्क्रीनिंग मूल्यांकन एक सहायक उपकरण है, अंतिम चिकित्सीय निदान नहीं।",
                    "सत्यापन के लिए प्रमाणित नेत्र रोग विशेषज्ञ द्वारा संपूर्ण क्लिनिकल मूल्यांकन आवश्यक है।"
                ],
                "Marathi": [
                    "हे एआय-आधारित मूल्यांकन केवळ प्राथमिक मार्गदर्शनासाठी आहे, अंतिम वैद्यकीय निदान नाही.",
                    "खात्रीशीर निदानासाठी प्रमाणित नेत्रतज्ज्ञांकडून सविस्तर डोळ्यांची तपासणी आवश्यक आहे."
                ]
            },
            "Notes": {
                "English": [
                    "Automated image screening demonstrates high image clarity compatible with reliable screening.",
                    "Screening results should always be correlated with clinical history and lab biomarkers."
                ],
                "Hindi": [
                    "स्वचालित छवि स्क्रीनिंग विश्वसनीय परिणामों के लिए उपयुक्त उच्च गुणवत्ता प्रदर्शित करती है।",
                    "स्क्रीनिंग परिणामों को हमेशा रोगी के क्लिनिकल इतिहास और प्रयोगशाला परीक्षणों से जोड़कर देखना चाहिए।"
                ],
                "Marathi": [
                    "स्वयंचलित प्रतिमा तपासणी विश्वासार्ह निष्कर्षांसाठी योग्य उच्च दर्जा दर्शवते.",
                    "या निष्कर्षांचा ताळमेळ नेहमी रुग्णाच्या वैद्यकीय पार्श्वभूमी आणि रक्त तपासणीशी घातला पाहिजे."
                ]
            }
        },
        "mild": {
            "Risk Level": {
                "English": ["Low to Mild Risk"],
                "Hindi": ["कम से हल्का जोखिम"],
                "Marathi": ["कमी ते सौम्य जोखीम"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Retinal evaluation reveals early microvascular changes characterized by isolated microaneurysms.",
                    "No significant retinal hemorrhages, hard exudates, or macular thickening are evident in the image.",
                    "Retinal background and vessel architecture remain largely stable with localized early capillary outpouchings."
                ],
                "Hindi": [
                    "रेटिनल मूल्यांकन अलग-थलग माइक्रोएन्यूरिज्म की उपस्थिति के साथ प्रारंभिक संवहनी परिवर्तनों को दर्शाता है।",
                    "छवि में कोई महत्वपूर्ण रेटिनल रक्तस्राव, हार्ड एक्स्युडेट्स या मैक्युलर सूजन नहीं दिखती है।",
                    "रेटिनल पृष्ठभूमि और वाहिका संरचना काफी हद तक स्थिर है, जिसमें स्थानीय सूक्ष्म बदलाव देखे गए हैं।"
                ],
                "Marathi": [
                    "रेटिनल तपासणीमध्ये काही मायक्रोएन्युरिझम्सच्या उपस्थितीसह सुरुवातीचे रक्तवाहिन्यांमधील बदल दिसून येतात.",
                    "प्रतिमेमध्ये मोठा रक्तस्राव, चरबीचे साठे किंवा मॅक्युलर भागात सूज आढळलेली नाही.",
                    "रेटिनाची पार्श्वभूमी आणि रक्तवाहिन्यांची रचना बऱ्याच अंशी स्थिर आहे."
                ]
            },
            "Disease Summary": {
                "English": [
                    "Findings are consistent with Mild Non-Proliferative Diabetic Retinopathy (NPDR).",
                    "Prolonged elevated blood glucose has led to localized weakening of tiny retinal capillary pericytes."
                ],
                "Hindi": [
                    "निष्कर्ष माइल्ड नॉन-प्रोलिफेरेटिव डायबेटिक रेटिनोपैथी (NPDR) के अनुरूप हैं।",
                    "रक्त शर्करा के लंबे समय तक बढ़े रहने से रेटिना की सूक्ष्म केशिकाओं में स्थानीय कमजोरी आई है।"
                ],
                "Marathi": [
                    "निष्कर्ष सौम्य नॉन-प्रोलिफेरेटिव्ह डायबेटिक रेटिनोपॅथीशी (NPDR) सुसंगत आहेत.",
                    "रक्तातील साखर वाढल्यामुळे डोळ्यातील सूक्ष्म रक्तवाहिन्यांच्या पेशींवर ताण निर्माण झाला आहे."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "Potential progression to moderate or severe stages if systemic parameters are poorly controlled.",
                    "Slight risk of developing macular edema if vascular permeability worsens over time."
                ],
                "Hindi": [
                    "यदि स्वास्थ्य मापदंडों को नियंत्रित नहीं किया गया तो मध्यम या गंभीर चरणों में प्रगति की संभावना।",
                    "यदि समय के साथ रक्त वाहिकाओं की पारगम्यता बिगड़ती है तो मैक्युलर एडिमा का हल्का जोखिम।"
                ],
                "Marathi": [
                    "आरोग्य घटकांवर नियंत्रण न ठेवल्यास आजार मध्यम किंवा तीव्र टप्प्यात वाढण्याचा धोका.",
                    "रक्तवाहिन्यांमधून द्रव गळती वाढल्यास डोळ्याच्या पडद्यावर सूज येण्याची शक्यता."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "No surgical procedure, laser therapy, or ocular injections are required at this early stage.",
                    "Work with your primary physician to optimize glycemic, lipid, and blood pressure control.",
                    "Final management decisions must be established by a qualified ophthalmologist."
                ],
                "Hindi": [
                    "इस प्रारंभिक चरण में किसी शल्यक्रिया, लेजर थेरेपी या इंजेक्शन की आवश्यकता नहीं है।",
                    "रक्त शर्करा, लिपिड और रक्तचाप को अनुकूलित करने के लिए अपने डॉक्टर के साथ काम करें।",
                    "उपचार के अंतिम निर्णय किसी योग्य नेत्र रोग विशेषज्ञ द्वारा ही निर्धारित किए जाने चाहिए।"
                ],
                "Marathi": [
                    "या सुरुवातीच्या टप्प्यावर शस्त्रक्रिया, लेझर किंवा इंजेक्शन उपचारांची आवश्यकता नाही.",
                    "रक्तातील साखर, कोलेस्टेरॉल आणि रक्तदाब नियंत्रित करण्यासाठी डॉक्टरांचा सल्ला घ्या.",
                    "उपचारांविषयीचे अंतिम निर्णय नेहमी पात्र नेत्रतज्ज्ञांच्या मार्गदर्शनाखाली घ्यावेत."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Target strict HbA1c control (< 7.0%) and monitor blood pressure (< 130/80 mmHg).",
                    "Follow a low-glycemic Mediterranean or diabetic dietary plan rich in antioxidants.",
                    "Incorporate daily moderate cardiovascular exercise and avoid smoking or nicotine products."
                ],
                "Hindi": [
                    "कड़ा HbA1c नियंत्रण (< 7.0%) बनाए रखें और रक्तचाप की नियमित जांच करें (< 130/80 mmHg)।",
                    "एंटीऑक्सीडेंट से भरपूर कम-ग्लाइसेमिक या डायबेटिक आहार योजना का पालन करें।",
                    "दैनिक मध्यम व्यायाम शामिल करें और धूम्रपान या निकोटीन उत्पादों से बचें।"
                ],
                "Marathi": [
                    "HbA1c पातळी ७.०% पेक्षा कमी ठेवा आणि रक्तदाबाची नियमित तपासणी करा (< १३०/८० mmHg).",
                    "अँटिऑक्सिडंट्सने युक्त आणि कमी साखरेच्या पोषक आहाराचे पालन करा.",
                    "दररोज हलका ते मध्यम व्यायाम करा आणि धूम्रपान किंवा तंबाखूचे सेवन पूर्णपणे टाळा."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Undergo a comprehensive dilated fundus examination every 6 to 9 months.",
                    "Seek immediate medical attention if you experience changes in clarity, floaters, or blind spots."
                ],
                "Hindi": [
                    "हर 6 से 9 महीने में एक व्यापक पुतली फैलाकर फंडस जांच करवाएं।",
                    "यदि आपको दृष्टि की स्पष्टता में कमी, तैरते धब्बे या अंधे धब्बे महसूस हों तो तुरंत संपर्क करें।"
                ],
                "Marathi": [
                    "दर ६ ते ९ महिन्यांनी डोळ्यांची सविस्तर तपासणी करून घ्या.",
                    "दृष्टी अंधुक होणे, तरळणारे डाग किंवा अस्पष्टता जाणवल्यास त्वरित डॉक्टरांशी संपर्क साधा."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "This automated report is designed for screening assistance and does not replace in-person diagnosis.",
                    "Consult a certified ophthalmologist for complete clinical assessment and monitoring."
                ],
                "Hindi": [
                    "यह स्वचालित रिपोर्ट स्क्रीनिंग सहायता के लिए है और प्रत्यक्ष निदान का विकल्प नहीं है।",
                    "संपूर्ण नैदानिक मूल्यांकन और निगरानी के लिए प्रमाणित नेत्र रोग विशेषज्ञ से परामर्श लें।"
                ],
                "Marathi": [
                    "हा अहवाल केवळ तपासणीच्या मदतीसाठी असून प्रत्यक्ष निदानाचा पर्याय नाही.",
                    "सविस्तर तपासणी आणि योग्य मार्गदर्शनासाठी मान्यताप्राप्त नेत्रतज्ज्ञांचा सल्ला घ्या."
                ]
            },
            "Notes": {
                "English": [
                    "Early lesions detected; proactive lifestyle changes are highly effective at this stage.",
                    "Serial fundus photographic evaluations help track microvascular stability over time."
                ],
                "Hindi": [
                    "प्रारंभिक घाव पाए गए हैं; सक्रिय जीवनशैली परिवर्तन इस चरण में अत्यधिक प्रभावी होते हैं।",
                    "नियमित फंडस तस्वीरें समय के साथ रक्त वाहिकाओं की स्थिरता पर नज़र रखने में मदद करती हैं।"
                ],
                "Marathi": [
                    "सुरुवातीचे बदल आढळले आहेत; या टप्प्यावर जीवनशैलीतील बदल अत्यंत प्रभावी ठरतात.",
                    "वेळोवेळी केलेली डोळ्यांची तपासणी रक्तवाहिन्यांच्या आरोग्याचा मागोवा घेण्यास मदत करते."
                ]
            }
        },
        "moderate": {
            "Risk Level": {
                "English": ["Moderate Risk"],
                "Hindi": ["मध्यम जोखिम"],
                "Marathi": ["मध्यम जोखीम"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Retinal analysis demonstrates definite microvascular changes consistent with moderate retinopathy.",
                    "Multiple microaneurysms, blot hemorrhages, and scattered lipid exudates are visible in the posterior pole.",
                    "Macular zone warrants careful evaluation for potential localized thickening or early edema."
                ],
                "Hindi": [
                    "रेटिनल विश्लेषण मध्यम रेटिनोपैथी के अनुरूप स्पष्ट सूक्ष्म संवहनी परिवर्तनों को दर्शाता है।",
                    "पोस्टीरियर पोल में कई माइक्रोएन्यूरिज्म, रक्तस्राव के धब्बे और बिखरे हुए लिपिड एक्स्युडेट्स दिखाई देते हैं।",
                    "मैक्युलर क्षेत्र में संभावित सूजन या शुरुआती एडिमा के लिए सावधानीपूर्वक मूल्यांकन की आवश्यकता है।"
                ],
                "Marathi": [
                    "रेटिनल तपासणी मध्यम रेटिनोपॅथीशी सुसंगत असलेले रक्तवाहिन्यांचे स्पष्ट बदल दर्शवते.",
                    "पडद्यावर अनेक मायक्रोएन्युरिझम्स, लहान रक्तस्राव आणि चरबीचे साठे (हार्ड एक्स्युडेट्स) दिसून येतात.",
                    "मॅक्युलर भागात सूज किंवा द्रव साचण्याच्या शक्यतेसाठी सविस्तर तपासणी आवश्यक आहे."
                ]
            },
            "Disease Summary": {
                "English": [
                    "Findings indicate Moderate Non-Proliferative Diabetic Retinopathy (NPDR).",
                    "Increased vascular permeability and microvascular occlusions are causing regional retinal ischemia.",
                    "Progression toward macular edema and advanced stages requires timely clinical management."
                ],
                "Hindi": [
                    "निष्कर्ष मॉडरेट नॉन-प्रोलिफेरेटिव डायबेटिक रेटिनोपैथी (NPDR) का संकेत देते हैं।",
                    "बढ़ी हुई संवहनी पारगम्यता और सूक्ष्म रुकावटों के कारण रेटिना में रक्त प्रवाह प्रभावित हो रहा है।",
                    "मैक्युलर एडिमा और गंभीर चरणों की ओर बढ़ने से रोकने के लिए समय पर नैदानिक प्रबंधन आवश्यक है।"
                ],
                "Marathi": [
                    "निष्कर्ष मध्यम नॉन-प्रोलिफेरेटिव्ह डायबेटिक रेटिनोपॅथी (NPDR) दर्शवतात.",
                    "रक्तवाहिन्यांची गळती आणि सूक्ष्म अडथळ्यांमुळे डोळ्याच्या पडद्यावर ऑक्सिजनचा पुरवठा कमी होत आहे.",
                    "स्थिती अधिक गंभीर होऊ नये म्हणून वेळेवर वैद्यकीय उपचार घेणे गरजेचे आहे."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "Risk of developing Center-Involved Diabetic Macular Edema (CI-DME) leading to visual impairment.",
                    "Risk of progressing to Severe NPDR or proliferative retinopathy with capillary non-perfusion."
                ],
                "Hindi": [
                    "सेंटर-इनवॉल्व्ड डायबेटिक मैक्युलर एडिमा (CI-DME) विकसित होने का जोखिम जिससे दृष्टि प्रभावित हो सकती है।",
                    "केशिका गैर-छिड़काव के साथ गंभीर NPDR या प्रोलिफेरेटिव रेटिनोपैथी में बदलने का खतरा।"
                ],
                "Marathi": [
                    "मॅक्युलर सूज (DME) येण्याचा धोका ज्यामुळे दृष्टी कमी होऊ शकते.",
                    "रक्तपुरवठा खंडित झाल्याने आजार अधिक तीव्र टप्प्यात जाण्याची शक्यता."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "Consult an ophthalmologist or retinal specialist for a comprehensive dilated examination.",
                    "Optical Coherence Tomography (OCT) or Fluorescein Angiography (FFA) may be advised by the specialist.",
                    "Intensify medical control of blood sugar, blood pressure, and cholesterol in coordination with your doctor."
                ],
                "Hindi": [
                    "विस्तृत परीक्षण के लिए किसी नेत्र रोग विशेषज्ञ या रेटिना विशेषज्ञ से परामर्श लें।",
                    "विशेषज्ञ द्वारा ऑप्टिकल कोहेरेंस टोमोग्राफी (OCT) या फ्लोरोसीन एंजियोग्राफी (FFA) की सलाह दी जा सकती है।",
                    "अपने डॉक्टर के समन्वय में रक्त शर्करा, रक्तचाप और कोलेस्ट्रॉल का कड़ा नियंत्रण करें।"
                ],
                "Marathi": [
                    "सविस्तर तपासणीसाठी नेत्ररोग तज्ज्ञ किंवा रेटिना तज्ज्ञांचा तातडीने सल्ला घ्या.",
                    "तज्ज्ञांकडून OCT स्कॅन किंवा फ्लोरोसीन अँजिओग्राफी (FFA) चाचणीची शिफारस केली जाऊ शकते.",
                    "डॉक्टरांच्या मदतीने रक्तातील साखर, रक्तदाब आणि कोलेस्टेरॉलचे काटेकोर नियंत्रण करा."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Maintain disciplined blood glucose management with frequent self-monitoring.",
                    "Reduce dietary sodium intake to support blood pressure targets below 130/80 mmHg.",
                    "Follow a high-fiber, low-saturated-fat diet, perform regular aerobic exercise, and refrain from smoking."
                ],
                "Hindi": [
                    "नियमित आत्म-निगरानी के साथ अनुशासित रक्त शर्करा प्रबंधन बनाए रखें।",
                    "रक्तचाप को 130/80 mmHg से नीचे रखने के लिए आहार में नमक की मात्रा कम करें।",
                    "उच्च फाइबर युक्त आहार लें, नियमित व्यायाम करें और धूम्रपान से पूरी तरह बचें।"
                ],
                "Marathi": [
                    "रक्तातील साखरेची नियमित तपासणी करून त्यावर काटेकोर नियंत्रण ठेवा.",
                    "रक्तदाब १३०/८० mmHg च्या खाली ठेवण्यासाठी आहारातील मिठाचे प्रमाण कमी करा.",
                    "तंतुमय (फायबरयुक्त) पोषक आहार घ्या, हलका व्यायाम करा आणि तंबाखूचे सेवन टाळा."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Schedule a clinical evaluation by an ophthalmologist within 2 to 4 weeks.",
                    "Seek immediate emergency eye care if experiencing sudden darkness, shadows, or distorted vision."
                ],
                "Hindi": [
                    "2 से 4 सप्ताह के भीतर किसी नेत्र रोग विशेषज्ञ से क्लिनिकल जांच का समय निर्धारित करें।",
                    "यदि दृष्टि में अचानक कालापन, परछाइयां या विकृति महसूस हो तो तुरंत आपातकालीन नेत्र देखभाल लें।"
                ],
                "Marathi": [
                    "२ ते ४ आठवड्यांच्या आत नेत्रतज्ज्ञांकडून डोळ्यांची क्लिनिकल तपासणी करून घ्या.",
                    "अचानक अंधुकपणा, दृष्टीसमोर काळा पडदा किंवा अस्पष्टता जाणवल्यास त्वरित आपत्कालीन वैद्यकीय मदत घ्या."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "This assessment is generated by an automated computational system for triage and informational purposes.",
                    "Definitive treatment plans must be formulated by a certified ophthalmologist following physical exam."
                ],
                "Hindi": [
                    "यह मूल्यांकन सूचना और मार्गदर्शन के लिए एक स्वचालित प्रणाली द्वारा तैयार किया गया है।",
                    "उपचार योजनाएं प्रत्यक्ष जांच के बाद प्रमाणित नेत्र रोग विशेषज्ञ द्वारा ही बनाई जानी चाहिए।"
                ],
                "Marathi": [
                    "हा अहवाल केवळ प्राथमिक माहितीसाठी स्वयंचलित प्रणालीद्वारे तयार करण्यात आला आहे.",
                    "उपचारांचे नियोजन प्रत्यक्ष तपासणीनंतर केवळ पात्र नेत्रतज्ज्ञांकडूनच केले जावे."
                ]
            },
            "Notes": {
                "English": [
                    "Moderate-grade retinopathy signs detected; prompt specialized correlation is strongly advised.",
                    "High-resolution OCT imaging remains the gold standard for assessing subretinal fluid accumulation."
                ],
                "Hindi": [
                    "मध्यम स्तर की रेटिनोपैथी के लक्षण पाए गए हैं; त्वरित विशेषज्ञ परामर्श की दृढ़ता से सलाह दी जाती है।",
                    "तरल पदार्थ के जमाव का आकलन करने के लिए उच्च-रिज़ॉल्यूशन OCT इमेजिंग सबसे विश्वसनीय तकनीक है।"
                ],
                "Marathi": [
                    "मध्यम स्वरूपाची रेटिनोपॅथी आढळली आहे; तातडीने तज्ज्ञांचा सल्ला घेणे आवश्यक आहे.",
                    "पडद्यावरील द्रव आणि सूज तपासण्यासाठी उच्च दर्जाची OCT तपासणी अत्यंत उपयुक्त ठरते."
                ]
            }
        },
        "severe": {
            "Risk Level": {
                "English": ["High Risk / Severe"],
                "Hindi": ["उच्च जोखिम / गंभीर"],
                "Marathi": ["उच्च जोखीम / तीव्र"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Retinal evaluation reveals advanced microvascular pathology consistent with high-risk diabetic retinopathy.",
                    "Extensive retinal hemorrhages, marked venous beading, cotton wool spots, or neovascularization are identified.",
                    "Significant capillary non-perfusion indicates severe retinal ischemia requiring urgent medical intervention."
                ],
                "Hindi": [
                    "रेटिनल मूल्यांकन उच्च जोखिम वाली डायबेटिक रेटिनोपैथी के अनुरूप उन्नत संवहनी विकृति को दर्शाता है।",
                    "व्यापक रेटिनल रक्तस्राव, शिरापरक असामान्यताएं, कॉटन वूल स्पॉट्स या नई रक्त वाहिकाओं का निर्माण देखा गया है।",
                    "गंभीर रेटिनल इस्किमिया के लिए तत्काल चिकित्सीय हस्तक्षेप की आवश्यकता है।"
                ],
                "Marathi": [
                    "रेटिनल तपासणी उच्च जोखमीच्या डायबेटिक रेटिनोपॅथीशी सुसंगत असलेले गंभीर नुकसान दर्शवते.",
                    "पडद्यावर मोठा रक्तस्राव, शिरांचे विकृतीकरण, पांढरे डाग किंवा नवीन नाजूक रक्तवाहिन्यांची निर्मिती दिसून येते.",
                    "रक्तपुरवठ्याची तीव्र कमतरता दर्शवते की तातडीने वैद्यकीय उपचारांची गरज आहे."
                ]
            },
            "Disease Summary": {
                "English": [
                    "Findings correspond to Severe NPDR with high probability of rapid conversion to proliferative retinopathy.",
                    "Severe retinal ischemia has triggered pathological vascular growth factors causing microvascular failure.",
                    "Urgent specialized treatment is critical to prevent vitreous hemorrhage, retinal detachment, or permanent vision loss."
                ],
                "Hindi": [
                    "निष्कर्ष गंभीर NPDR के अनुरूप हैं, जिसमें प्रोलिफेरेटिव रेटिनोपैथी में तेजी से बदलने की उच्च संभावना है।",
                    "गंभीर रेटिनल इस्किमिया ने संवहनी विफलता पैदा करने वाले पैथोलॉजिकल कारकों को ट्रिगर किया है।",
                    "रक्तस्राव, पर्दा हटने या स्थायी अंधेपन को रोकने के लिए तत्काल विशेष उपचार अत्यंत आवश्यक है।"
                ],
                "Marathi": [
                    "हे निष्कर्ष तीव्र NPDR चे असून आजार झपाट्याने वाढण्याची शक्यता दर्शवतात.",
                    "रक्तपुरवठ्याच्या तीव्र अभावामुळे डोळ्याच्या पडद्यावर गंभीर संवहनी बिघाड निर्माण झाला आहे.",
                    "रक्तस्राव, पडदा निसटणे किंवा दृष्टी जाण्यापासून वाचवण्यासाठी त्वरित विशेष उपचार आवश्यक आहेत."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "Imminent risk of sudden, severe vitreous hemorrhage resulting in acute vision loss.",
                    "High danger of tractional retinal detachment, neovascular glaucoma, and irreversible visual impairment."
                ],
                "Hindi": [
                    "अचानक गंभीर विट्रीयस रक्तस्राव का तत्काल जोखिम जिसके परिणामस्वरूप तीव्र दृष्टि हानि हो सकती है।",
                    "ट्रैक्शनल रेटिनल डिटैचमेंट, नवसंवहनी ग्लूकोमा और स्थायी दृष्टि दोष का अत्यधिक खतरा।"
                ],
                "Marathi": [
                    "डोळ्यात अंतर्गत रक्तस्राव (विट्रीयस हेमरेज) होण्याचा मोठा धोका, ज्यामुळे दृष्टी अचानक जाऊ शकते.",
                    "रेटिना निसटणे (डिटॅचमेंट), काचबिंदू आणि कायमस्वरूपी अंधत्व येण्याची गंभीर शक्यता."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "Immediate referral to a vitreoretinal specialist or tertiary eye care facility is urgently required (within 24-48 hours).",
                    "Clinical therapies may include Panretinal Photocoagulation (PRP) laser, anti-VEGF injections, or vitrectomy surgery.",
                    "Strict multi-disciplinary medical management under specialist supervision to stabilize systemic parameters."
                ],
                "Hindi": [
                    "विट्रीयोरेटिनल विशेषज्ञ या उच्च नेत्र अस्पताल में तत्काल रेफरल अत्यंत आवश्यक है (24-48 घंटों के भीतर)।",
                    "उपचारों में पैनरेटिनल फोटोकोएग्यूलेशन (PRP) लेजर, एंटी-VEGF इंजेक्शन या विट्रेक्टॉमी सर्जरी शामिल हो सकती है।",
                    "स्वास्थ्य मापदंडों को स्थिर करने के लिए विशेषज्ञों की देखरेख में सख्त बहु-विषयक प्रबंधन आवश्यक है।"
                ],
                "Marathi": [
                    "तातडीने (२४ ते ४८ तासांच्या आत) रेटिना तज्ज्ञ किंवा मोठ्या नेत्र रुग्णालयाशी संपर्क साधा.",
                    "उपचारांमध्ये लेझर (PRP), डोळ्यातील इंजेक्शन्स किंवा विट्रेक्टॉमी शस्त्रक्रियेची आवश्यकता असू शकते.",
                    "रक्तातील साखर आणि इतर घटक नियंत्रित ठेवण्यासाठी तज्ज्ञ डॉक्टरांचे तातडीने मार्गदर्शन घ्या."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Avoid heavy lifting, intense straining, vigorous exercise, or inverted postures that could trigger bleeding.",
                    "Sleep with head slightly elevated and maintain continuous records of blood pressure and glucose levels.",
                    "Follow prescribed medical nutrition strictly and avoid adjusting medications without specialist guidance."
                ],
                "Hindi": [
                    "भारी वजन उठाने, अत्यधिक तनाव, ज़ोरदार व्यायाम या उल्टे आसनों से बचें जो रक्तस्राव को ट्रिगर कर सकते हैं।",
                    "सिर को थोड़ा ऊंचा करके सोएं और रक्तचाप व रक्त शर्करा के स्तर का निरंतर रिकॉर्ड रखें।",
                    "विशेषज्ञ के मार्गदर्शन के बिना दवाएं बदलने से बचें और निर्धारित पोषण का कड़ाई से पालन करें।"
                ],
                "Marathi": [
                    "वजन उचलणे, अतिश्रम, डोक्यावर ताण येईल असे व्यायाम टाळा ज्यामुळे रक्तस्राव होऊ शकतो.",
                    "झोपताना डोके थोडे वर ठेवा आणि रक्तदाब व रक्तातील साखरेची नियमित नोंद ठेवा.",
                    "डॉक्टरांच्या सल्ल्याशिवाय औषधांमध्ये कोणताही बदल करू नका आणि आहाराचे तंतोतंत पालन करा."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Report to an ophthalmic emergency department or retina clinic immediately without delay.",
                    "Emergency evaluation is vital if experiencing a sudden dark veil, red streaks, or acute loss of vision."
                ],
                "Hindi": [
                    "बिना किसी देरी के तुरंत किसी नेत्र आपातकालीन विभाग या रेटिना क्लिनिक में जाएं।",
                    "यदि अचानक काला पर्दा, लाल लकीरें या दृष्टि की गंभीर हानि हो तो तत्काल आपातकालीन मूल्यांकन आवश्यक है।"
                ],
                "Marathi": [
                    "कोणताही उशीर न करता तातडीने नेत्र रुग्णालयातील आपत्कालीन विभागात जा.",
                    "दृष्टीसमोर अचानक काळा पडदा, लाल रेषा किंवा दृष्टी अचानक गेल्यास त्वरित वैद्यकीय मदत घ्या."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "High-risk computational screening findings require immediate in-person clinical verification and urgent care.",
                    "This screening report does not constitute a formal diagnosis or substitute for emergency medical treatment."
                ],
                "Hindi": [
                    "उच्च जोखिम वाले स्वचालित निष्कर्षों के लिए तत्काल व्यक्तिगत क्लिनिकल जांच और देखभाल आवश्यक है।",
                    "यह स्क्रीनिंग रिपोर्ट औपचारिक निदान नहीं है और न ही आपातकालीन चिकित्सा उपचार का विकल्प है।"
                ],
                "Marathi": [
                    "उच्च जोखमीच्या स्वयंचलित निष्कर्षांसाठी तातडीने प्रत्यक्ष वैद्यकीय तपासणी आणि उपचारांची गरज आहे.",
                    "हा अहवाल प्रत्यक्ष वैद्यकीय निदान किंवा तातडीच्या उपचारांचा पर्याय नाही."
                ]
            },
            "Notes": {
                "English": [
                    "Critical microvascular disease identified; immediate vitreoretinal intervention significantly reduces vision loss risk.",
                    "Serial multimodal tracking is essential to evaluate structural stability and therapeutic response."
                ],
                "Hindi": [
                    "गंभीर सूक्ष्म संवहनी बीमारी की पहचान की गई है; तत्काल हस्तक्षेप दृष्टि हानि के जोखिम को काफी कम करता है।",
                    "संरचनात्मक स्थिरता और उपचार की प्रभावशीलता का मूल्यांकन करने के लिए नियमित निगरानी आवश्यक है।"
                ],
                "Marathi": [
                    "डोळ्याच्या पडद्याला गंभीर इजा आढळली आहे; तातडीने घेतलेल्या उपचारांमुळे अंधत्वाचा धोका मोठ्या प्रमाणावर टाळता येतो.",
                    "उपचारांनंतर पडद्याची स्थिती तपासण्यासाठी नियमित डोळ्यांची तपासणी आवश्यक असते."
                ]
            }
        },
        "proliferative": {
            "Risk Level": {
                "English": ["High Risk / Proliferative"],
                "Hindi": ["उच्च जोखिम / प्रोलिफेरेटिव"],
                "Marathi": ["उच्च जोखीम / प्रोलिफेरेटिव्ह"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Retinal imaging indicates advanced Proliferative Diabetic Retinopathy with hallmark neovascularization.",
                    "Fragile new abnormal vessels are evident on the disc (NVD) or elsewhere in the retina (NVE).",
                    "Evidence of preretinal or early vitreous hemorrhage and fibrovascular tissue proliferation."
                ],
                "Hindi": [
                    "रेटिनल इमेजिंग नवसंवहनी की पहचान के साथ उन्नत प्रोलिफेरेटिव डायबेटिक रेटिनोपैथी का संकेत देती है।",
                    "ऑप्टिक डिस्क (NVD) या रेटिना में अन्यत्र (NVE) नाज़ुक नई रक्त वाहिकाएं स्पष्ट दिखाई देती हैं।",
                    "प्रिरेटिनल या विट्रीयस रक्तस्राव और फाइब्रोवैस्कुलर ऊतक के प्रसार के संकेत मिलते हैं।"
                ],
                "Marathi": [
                    "रेटिनल इमेजिंग नवीन नाजूक रक्तवाहिन्यांसह प्रगत प्रोलिफेरेटिव्ह डायबेटिक रेटिनोपॅथी दर्शवते.",
                    "ऑप्टिक डिस्कवर (NVD) किंवा पडद्यावर इतरत्र (NVE) नवीन कमकुवत रक्तवाहिन्या तयार झाल्याचे स्पष्ट दिसते.",
                    "डोळ्यात अंतर्गत रक्तस्राव आणि फायब्रोव्हॅस्क्युलर ऊतींची वाढ झाल्याचे संकेत आहेत."
                ]
            },
            "Disease Summary": {
                "English": [
                    "Findings correspond to Proliferative Diabetic Retinopathy (PDR), an advanced sight-threatening stage.",
                    "Severe wide-field retinal ischemia stimulates excessive vascular endothelial growth factors.",
                    "Without emergency specialist care, rapid progression to catastrophic vision loss can occur."
                ],
                "Hindi": [
                    "निष्कर्ष प्रोलिफेरेटिव डायबेटिक रेटिनोपैथी (PDR) के अनुरूप हैं, जो दृष्टि के लिए गंभीर खतरा है।",
                    "व्यापक रेटिनल इस्किमिया अत्यधिक संवहनी विकास कारकों को उत्तेजित करता है।",
                    "आपातकालीन विशेषज्ञ देखभाल के बिना दृष्टि की गंभीर हानि तेजी से हो सकती है।"
                ],
                "Marathi": [
                    "हे निष्कर्ष प्रोलिफेरेटिव्ह डायबेटिक रेटिनोपॅथी (PDR) चे आहेत, जो दृष्टीसाठी अत्यंत धोकादायक टप्पा आहे.",
                    "रक्तपुरवठ्याच्या गंभीर कमतरतेमुळे डोळ्याच्या पडद्यावर घातक रक्तवाहिन्यांची अनियंत्रित वाढ होते.",
                    "तातडीच्या विशेष उपचारांशिवाय कायमचे अंधत्व येण्याचा धोका खूप जास्त असतो."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "High probability of massive vitreous hemorrhage causing acute painless profound vision loss.",
                    "Severe risk of tractional retinal detachment and intractable neovascular glaucoma."
                ],
                "Hindi": [
                    "भारी विट्रीयस रक्तस्राव की उच्च संभावना जिससे अचानक गंभीर दृष्टि हानि हो सकती है।",
                    "ट्रैक्शनल रेटिनल डिटैचमेंट और नवसंवहनी ग्लूकोमा का गंभीर खतरा।"
                ],
                "Marathi": [
                    "डोळ्यात मोठा रक्तस्राव होण्याचा मोठा धोका ज्यामुळे दृष्टी अचानक जाऊ शकते.",
                    "रेटिना निसटणे (ट्रॅक्शनल डिटॅचमेंट) आणि गंभीर काचबिंदूचा धोका."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "Emergency consultation with a vitreoretinal surgeon is required within 24 to 48 hours.",
                    "Urgent Panretinal Photocoagulation (PRP) laser or anti-VEGF pharmacotherapy is clinically indicated.",
                    "Vitrectomy surgical intervention may be required if vitreous hemorrhage or traction persists."
                ],
                "Hindi": [
                    "24 से 48 घंटों के भीतर किसी विट्रीयोरेटिनल सर्जन से आपातकालीन परामर्श आवश्यक है।",
                    "तत्काल पैनरेटिनल फोटोकोएग्यूलेशन (PRP) लेजर या एंटी-VEGF दवा की आवश्यकता है।",
                    "विट्रीयस रक्तस्राव या खिंचाव बना रहने पर विट्रेक्टॉमी सर्जरी की आवश्यकता हो सकती है।"
                ],
                "Marathi": [
                    "२४ ते ४८ तासांच्या आत रेटिना सर्जनशी तातडीने संपर्क साधणे आवश्यक आहे.",
                    "तातडीने लेझर (PRP) किंवा अँटी-VEGF इंजेक्शन्स देणे गरजेचे आहे.",
                    "रक्तस्राव किंवा पडद्यावर ताण कायम राहिल्यास विट्रेक्टॉमी शस्त्रक्रिया करावी लागू शकते."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Strictly avoid any strenuous physical activity, lifting, bending down, or sudden head movements.",
                    "Rest in an upright or head-elevated position to facilitate settling of any intraocular blood.",
                    "Maintain rigorous glycemic and blood pressure control in close consultation with your physician."
                ],
                "Hindi": [
                    "भारी शारीरिक गतिविधि, झुकने, वजन उठाने या अचानक सिर हिलाने से सख्ती से बचें।",
                    "सिर को ऊंचा रखकर आराम करें ताकि आंख के भीतर रक्त नीचे बैठ सके।",
                    "चिकित्सक के परामर्श से रक्त शर्करा और रक्तचाप का कड़ा नियंत्रण बनाए रखें।"
                ],
                "Marathi": [
                    "कोणतीही जड कामे, वजन उचलणे, पुढे वाकणे किंवा डोक्यावर ताण येईल अशा कृती पूर्णपणे टाळा.",
                    "डोके वर ठेवून झोपा किंवा विश्रांती घ्या ज्यामुळे अंतर्गत रक्त खाली स्थिरावण्यास मदत होते.",
                    "डॉक्टरांच्या मार्गदर्शनाखाली रक्तातील साखर आणि रक्तदाब अत्यंत काटेकोरपणे नियंत्रित ठेवा."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Proceed directly to a specialized retina emergency service without postponement.",
                    "Immediate hospital attendance is mandatory if you perceive a dark shadow, red film, or sudden blackout."
                ],
                "Hindi": [
                    "बिना किसी देरी के सीधे किसी विशेष रेटिना आपातकालीन सेवा में जाएं।",
                    "यदि आपको गहरा साया, लाल पर्दा या अचानक अंधापन महसूस हो तो तुरंत अस्पताल जाना अनिवार्य है।"
                ],
                "Marathi": [
                    "कोणताही उशीर न करता थेट विशेष रेटिना आपत्कालीन केंद्रात जा.",
                    "दृष्टीसमोर काळी सावली, लाल पडदा किंवा अचानक अंधत्व जाणवल्यास तातडीने रुग्णालयात जाणे बंधनकारक आहे."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "Proliferative findings require immediate in-person vitreoretinal emergency care.",
                    "This screening analysis cannot substitute for hospital diagnostics and surgical evaluation."
                ],
                "Hindi": [
                    "प्रोलिफेरेटिव निष्कर्षों के लिए तत्काल व्यक्तिगत विट्रीयोरेटिनल आपातकालीन देखभाल की आवश्यकता होती है।",
                    "यह स्क्रीनिंग विश्लेषण अस्पताल के नैदानिक और सर्जिकल मूल्यांकन का विकल्प नहीं हो सकता।"
                ],
                "Marathi": [
                    "प्रोलिफेरेटिव्ह निष्कर्षांसाठी तातडीने प्रत्यक्ष रेटिना आपत्कालीन उपचारांची गरज असते.",
                    "हा तपासणी अहवाल रुग्णालयातील प्रत्यक्ष तपासणी किंवा शस्त्रक्रियेचा पर्याय असू शकत नाही."
                ]
            },
            "Notes": {
                "English": [
                    "High-urgency vascular proliferation identified; immediate clinical management is essential.",
                    "Early intervention preserves functional vision and limits severe complications."
                ],
                "Hindi": [
                    "अत्यधिक आपातकालीन संवहनी प्रसार की पहचान की गई है; तत्काल क्लिनिकल प्रबंधन आवश्यक है।",
                    "शीघ्र हस्तक्षेप दृष्टि को सुरक्षित रखने और गंभीर जटिलताओं को सीमित करने में मदद करता है।"
                ],
                "Marathi": [
                    "अत्यंत गंभीर संवहनी वाढ आढळली आहे; त्वरित क्लिनिकल उपचार घेणे अत्यावश्यक आहे.",
                    "वेळेवर उपचार सुरू केल्यास दृष्टी वाचवणे आणि धोके टाळणे शक्य होते."
                ]
            }
        },
        "cataract": {
            "Risk Level": {
                "English": ["Moderate Risk / Lens Opacity"],
                "Hindi": ["मध्यम जोखिम / मोतियाबिंद"],
                "Marathi": ["मध्यम जोखीम / मोतीबिंदू"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Retinal imaging indicates media haziness and lens opacification consistent with cataract changes.",
                    "Underlying retinal details are partially obscured due to optical media attenuation.",
                    "Visual clarity reduction is primarily linked to crystalline lens clouding."
                ],
                "Hindi": [
                    "रेटिनल इमेजिंग मोतियाबिंद के परिवर्तनों के अनुरूप लेंस के धुंधलेपन का संकेत देती है।",
                    "लेंस के धुंधलेपन के कारण नीचे की रेटिनल विशेषताएं आंशिक रूप से अस्पष्ट हैं।",
                    "दृष्टि की स्पष्टता में कमी मुख्य रूप से लेंस के अपारदर्शी होने से जुड़ी है।"
                ],
                "Marathi": [
                    "रेटिनल इमेजिंग मोतीबिंदूच्या बदलांशी सुसंगत असा डोळ्यातील भिंगाचा अंधुकपणा दर्शवते.",
                    "भिंगातील धुरकटपणामुळे पडद्याची सविस्तर तपासणी अंशतः मर्यादित झाली आहे.",
                    "दृष्टी कमी होण्याचे मुख्य कारण डोळ्यातील नैसर्गिक भिंगाचा अपारदर्शकपणा आहे."
                ]
            },
            "Disease Summary": {
                "English": [
                    "Findings indicate cataractous opacification of the ocular crystalline lens.",
                    "Progressive protein aggregation reduces light transmission onto the retina.",
                    "Cataract is a treatable condition with highly effective modern surgical remedies."
                ],
                "Hindi": [
                    "निष्कर्ष आंख के प्राकृतिक क्रिस्टलीय लेंस के मोतियाबिंद से संबंधित धुंधलेपन का संकेत देते हैं।",
                    "प्रोटीन का क्रमिक जमाव रेटिना पर प्रकाश के संचरण को कम करता है।",
                    "मोतियाबिंद आधुनिक सर्जिकल उपचारों के साथ एक पूरी तरह से इलाज योग्य स्थिति है।"
                ],
                "Marathi": [
                    "निष्कर्ष डोळ्याच्या नैसर्गिक भिंगामध्ये मोतीबिंदू झाल्याचे दर्शवतात.",
                    "प्रथिनांच्या बदलांमुळे पडद्यावर जाणारा प्रकाश कमी होतो.",
                    "मोतीबिंदू हा आधुनिक शस्त्रक्रियेद्वारे पूर्णपणे बरा होऊ शकणारा आजार आहे."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "Gradual reduction in visual acuity, contrast sensitivity, and glare sensitivity.",
                    "Difficulty performing routine tasks such as night driving or reading."
                ],
                "Hindi": [
                    "दृष्टि तीक्ष्णता, कंट्रास्ट संवेदनशीलता और चकाचौंध के प्रति संवेदनशीलता में क्रमिक कमी।",
                    "रात में वाहन चलाने या पढ़ने जैसे नियमित कार्यों को करने में कठिनाई।"
                ],
                "Marathi": [
                    "दृष्टी कमी होणे, उजेडात डोळे दिपणे आणि अस्पष्ट दिसणे यात हळूहळू वाढ.",
                    "रात्री गाडी चालवणे किंवा वाचण्यासारख्या दैनंदिन कामांमध्ये अडचण येणे."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "Consult an ophthalmologist for comprehensive slit-lamp and visual acuity assessment.",
                    "Phacoemulsification with intraocular lens (IOL) implantation is the standard curative treatment.",
                    "Timing of surgery should be determined collaboratively based on functional impairment."
                ],
                "Hindi": [
                    "स्लिट-लैंप और दृष्टि तीक्ष्णता मूल्यांकन के लिए किसी नेत्र रोग विशेषज्ञ से परामर्श लें।",
                    "इंट्राओकुलर लेंस (IOL) प्रत्यारोपण के साथ फेकोइमल्सीफिकेशन मानक उपचारात्मक सर्जरी है।",
                    "सर्जरी का समय दृष्टि पर प्रभाव के आधार पर डॉक्टर के साथ मिलकर तय किया जाना चाहिए।"
                ],
                "Marathi": [
                    "डोळ्यांच्या तपासणीसाठी आणि दृष्टी क्षमतेच्या मूल्यमापनासाठी नेत्रतज्ज्ञांचा सल्ला घ्या.",
                    "इंट्राओक्युलर लेन्स (IOL) बसवून फेको शस्त्रक्रिया करणे हा यावरील खात्रीशीर उपचार आहे.",
                    "शस्त्रक्रियेची वेळ दैनंदिन गरजांनुसार डॉक्टरांच्या सल्ल्याने ठरवावी."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Wear UV-protective sunglasses outdoors to reduce further photo-oxidative stress.",
                    "Ensure adequate, well-positioned lighting when reading or engaging in detailed work.",
                    "Maintain stable blood glucose control, as diabetes accelerates cataract progression."
                ],
                "Hindi": [
                    "फोटो-ऑक्सीडेटिव तनाव को कम करने के लिए धूप में यूवी-सुरक्षात्मक धूप का चश्मा पहनें।",
                    "पढ़ते समय या विस्तृत कार्य करते समय पर्याप्त रोशनी सुनिश्चित करें।",
                    "रक्त शर्करा का स्तर स्थिर रखें, क्योंकि मधुमेह मोतियाबिंद को तेजी से बढ़ा सकता है।"
                ],
                "Marathi": [
                    "उन्हात जाताना अतिनील (UV) किरणांपासून संरक्षण करणारे गॉगल वापरा.",
                    "वाचताना किंवा बारीक काम करताना डोळ्यांवर ताण येणार नाही असा योग्य प्रकाश ठेवा.",
                    "रक्तातील साखर नियंत्रित ठेवा, कारण मधुमेहामुळे मोतीबिंदू वेगाने वाढू शकतो."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Schedule an ophthalmic evaluation within 1 to 2 months for formal cataract grading.",
                    "Seek prompt care if experiencing sudden pain, halos around lights, or vision loss."
                ],
                "Hindi": [
                    "मोतियाबिंद ग्रेडिंग के लिए 1 से 2 महीने के भीतर नेत्र जांच का समय निर्धारित करें।",
                    "यदि अचानक दर्द, रोशनी के चारों ओर घेरे या दृष्टि हानि महसूस हो तो तुरंत परामर्श लें।"
                ],
                "Marathi": [
                    "मोतीबिंदूच्या प्रमाणाची खात्री करण्यासाठी १ ते २ महिन्यांत नेत्रतज्ज्ञांची भेट घ्या.",
                    "अचानक डोकेदुखी, डोळ्यांत दुखणे किंवा प्रकाशाभोवती वलये दिसल्यास त्वरित डॉक्टरांशी संपर्क साधा."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "Automated lens assessment is an advisory tool and does not constitute a surgical plan.",
                    "A slit-lamp biomicroscopy examination by a licensed ophthalmologist is essential."
                ],
                "Hindi": [
                    "स्वचालित लेंस मूल्यांकन एक सलाहकारी उपकरण है और यह सर्जिकल योजना नहीं है।",
                    "लाइसेंस प्राप्त नेत्र रोग विशेषज्ञ द्वारा स्लिट-लैंप बायोमाइक्रोस्कोपी जांच आवश्यक है।"
                ],
                "Marathi": [
                    "स्वयंचलित प्रणालीने केलेले मूल्यांकन केवळ मार्गदर्शनासाठी आहे, शस्त्रक्रियेचा अंतिम निर्णय नाही.",
                    "मान्यताप्राप्त नेत्रतज्ज्ञांकडून स्लिट-लॅम्प चाचणी करून घेणे आवश्यक आहे."
                ]
            },
            "Notes": {
                "English": [
                    "Cataract-induced media opacity may limit detailed evaluation of posterior retinal structures.",
                    "Post-surgical retinal re-assessment is advised following lens extraction."
                ],
                "Hindi": [
                    "मोतियाबिंद के धुंधलेपन के कारण रेटिना की गहरी संरचनाओं का मूल्यांकन सीमित हो सकता है।",
                    "मोतियाबिंद सर्जरी के बाद रेटिना की पुनः जांच की सलाह दी जाती है।"
                ],
                "Marathi": [
                    "मोतीबिंदूच्या धुरकटपणामुळे पडद्याची काही भागांची तपासणी मर्यादित होऊ शकते.",
                    "शस्त्रक्रियेनंतर डोळ्याच्या पडद्याची पुन्हा तपासणी करून घेणे हितावह ठरते."
                ]
            }
        },
        "glaucoma": {
            "Risk Level": {
                "English": ["Moderate to High Risk / Optic Nerve Concern"],
                "Hindi": ["मध्यम से उच्च जोखिम / ग्लूकोमा"],
                "Marathi": ["मध्यम ते उच्च जोखीम / काचबिंदू"]
            },
            "Clinical Interpretation": {
                "English": [
                    "Optic disc evaluation reveals suspicious neuroretinal rim thinning or increased cup-to-disc ratio.",
                    "Peripapillary nerve fiber layer changes suggestive of glaucomatous optic neuropathy.",
                    "Macular architecture remains structurally preserved without prominent diabetic microaneurysms."
                ],
                "Hindi": [
                    "ऑप्टिक डिस्क मूल्यांकन कप-टू-डिस्क अनुपात में वृद्धि या न्यूरोरेटिनल रिम के पतले होने का संकेत देता है।",
                    "पेरिपैपिलरी तंत्रिका फाइबर परत में ग्लूकोमा जैसी ऑप्टिक न्यूरोपैथी के संकेत मिलते हैं।",
                    "मैक्युलर संरचना बिना किसी प्रमुख डायबेटिक घाव के संरचनात्मक रूप से सुरक्षित है।"
                ],
                "Marathi": [
                    "ऑप्टिक डिस्क तपासणी कप-टू-डिस्क प्रमाणात वाढ किंवा मज्जातंतूच्या कडांचे नुकसान दर्शवते.",
                    "मज्जातंतूंच्या थरांमध्ये काचबिंदूशी (ग्लुकोमा) सुसंगत असलेले संशयास्पद बदल दिसून येतात.",
                    "मॅक्युलर भाग सुरक्षित असून मधुमेहाशी संबंधित मोठे बदल दिसत नाहीत."
                ]
            },
            "Disease Summary": {
                "English": [
                    "Findings are suspicious for Glaucomatous Optic Neuropathy, a progressive condition affecting the optic nerve.",
                    "Elevated intraocular pressure or compromised microvascular perfusion can cause irreversible ganglion cell loss.",
                    "Early intervention is essential to halt progressive visual field constriction."
                ],
                "Hindi": [
                    "निष्कर्ष ग्लूकोमेटस ऑप्टिक न्यूरोपैथी के लिए संदेहास्पद हैं, जो ऑप्टिक तंत्रिका को प्रभावित करती है।",
                    "आंख के बढ़े हुए दबाव से गैंग्लियन कोशिकाओं का अपरिवर्तनीय नुकसान हो सकता है।",
                    "दृष्टि क्षेत्र के नुकसान को रोकने के लिए प्रारंभिक चिकित्सीय हस्तक्षेप आवश्यक है।"
                ],
                "Marathi": [
                    "निष्कर्ष काचबिंदूशी (ग्लुकोमा) सुसंगत बदल दर्शवतात, ज्यामुळे डोळ्याच्या मुख्य मज्जातंतूवर परिणाम होतो.",
                    "डोळ्यातील अंतर्गत दाब वाढल्याने दृष्टीच्या पेशींचे नुकसान होऊ शकते.",
                    "दृष्टीचे क्षेत्र कमी होण्यापासून रोखण्यासाठी वेळेवर उपचार घेणे अत्यंत महत्त्वाचे आहे."
                ]
            },
            "Possible Medical Concerns": {
                "English": [
                    "Risk of asymptomatic, irreversible peripheral visual field loss if unmanaged.",
                    "Potential for elevated intraocular pressure (IOP) accelerating optic nerve damage."
                ],
                "Hindi": [
                    "उपचार न किए जाने पर परिधीय दृष्टि क्षेत्र के अपरिवर्तनीय नुकसान का गंभीर जोखिम।",
                    "आंख के आंतरिक दबाव (IOP) में वृद्धि जो ऑप्टिक तंत्रिका के नुकसान को तेज कर सकती है।"
                ],
                "Marathi": [
                    "उपचार न केल्यास परिधीय (बाजूची) दृष्टी कायमस्वरूपी जाण्याचा गंभीर धोका.",
                    "डोळ्यातील अंतर्गत दाब वाढल्यास डोळ्याच्या मुख्य मज्जातंतूला अधिक इजा पोहोचण्याची शक्यता."
                ]
            },
            "Treatment Guidance": {
                "English": [
                    "Consult an ophthalmologist or glaucoma specialist promptly for tonometry and visual field testing.",
                    "Standard management includes hypotensive eye drops, selective laser trabeculoplasty (SLT), or filtration surgery.",
                    "Strict daily adherence to prescribed ocular hypotensive medications is vital."
                ],
                "Hindi": [
                    "टोनोमेट्री (आंख का दबाव) और दृष्टि क्षेत्र परीक्षण के लिए तुरंत नेत्र रोग विशेषज्ञ से मिलें।",
                    "मानक उपचार में दबाव कम करने वाले आई ड्रॉप्स, लेजर थेरेपी या सर्जरी शामिल हैं।",
                    "निर्धारित आई ड्रॉप्स का प्रतिदिन नियमित उपयोग अत्यंत महत्वपूर्ण है।"
                ],
                "Marathi": [
                    "डोळ्याचा दाब (टोनोमेट्री) आणि दृष्टी कक्षा (पेरीमेट्री) तपासणीसाठी नेत्रतज्ज्ञांचा तातडीने सल्ला घ्या.",
                    "उपचारांमध्ये डोळ्यातील दाब कमी करणारे ड्रॉप्स, लेझर उपचार किंवा शस्त्रक्रियेचा समावेश असतो.",
                    "डॉक्टरांनी दिलेले आय ड्रॉप्स दररोज वेळेवर वापरणे अत्यंत आवश्यक आहे."
                ]
            },
            "Lifestyle Recommendations": {
                "English": [
                    "Avoid prolonged head-down inverted postures, heavy breath-holding straining, and tight neckwear.",
                    "Engage in moderate, regular aerobic exercise such as brisk walking, which may help regulate ocular pressure.",
                    "Limit excessive caffeine intake and stay well-hydrated throughout the day."
                ],
                "Hindi": [
                    "लंबे समय तक सिर नीचे करने वाले व्यायाम, भारी वजन उठाने और तंग कॉलर पहनने से बचें।",
                    "नियमित मध्यम एरोबिक व्यायाम जैसे तेज चलना करें, जो आंखों के दबाव को नियंत्रित करने में मदद करता है।",
                    "अत्यधिक कैफीन के सेवन को सीमित करें और दिन भर में पर्याप्त पानी पिएं।"
                ],
                "Marathi": [
                    "शीर्षासन, डोके खाली ठेवणारे व्यायाम, जड वजन उचलणे आणि मानेवर ताण येईल अशा गोष्टी टाळा.",
                    "नियमित चालण्यासारखा हलका व्यायाम करा ज्यामुळे डोळ्यातील दाब नियंत्रणात राहण्यास मदत होते.",
                    "चहा किंवा कॉफीचे अतिसेवन टाळा आणि दिवसभरात पुरेसे पाणी प्या."
                ]
            },
            "Follow-up Advice": {
                "English": [
                    "Schedule a glaucoma diagnostic workup within 2 to 3 weeks including perimetry and RNFL OCT.",
                    "Seek immediate emergency care if experiencing severe eye pain, headache, nausea, or rainbow halos."
                ],
                "Hindi": [
                    "पेरीमेट्री और RNFL OCT सहित 2 से 3 सप्ताह के भीतर ग्लूकोमा परीक्षण का समय निर्धारित करें।",
                    "यदि आंख में तेज दर्द, सिरदर्द, मतली या रोशनी के चारों ओर इंद्रधनुषी घेरे दिखें तो तुरंत आपातकालीन देखभाल लें।"
                ],
                "Marathi": [
                    "२ ते ३ आठवड्यांच्या आत डोळ्याची तपासणी, दाब आणि RNFL OCT चाचणी करून घ्या.",
                    "अचानक डोळ्यात तीव्र वेदना, डोकेदुखी, मळमळ किंवा दिव्यांभोवती रंगीत कडी दिसल्यास त्वरित आपत्कालीन सेवा घ्या."
                ]
            },
            "Medical Disclaimer": {
                "English": [
                    "Optic disc automated findings are screening indicators and do not establish a glaucoma diagnosis.",
                    "Comprehensive visual field testing and intraocular pressure measurement are mandatory."
                ],
                "Hindi": [
                    "स्वचालित ऑप्टिक डिस्क निष्कर्ष केवल स्क्रीनिंग संकेतक हैं और ग्लूकोमा निदान स्थापित नहीं करते।",
                    "व्यापक दृष्टि क्षेत्र परीक्षण और आंख के दबाव का मापन अनिवार्य है।"
                ],
                "Marathi": [
                    "स्वयंचलित प्रणालीने नोंदवलेले निष्कर्ष केवळ प्राथमिक सूचक आहेत, अंतिम निदान नाही.",
                    "डोळ्याचा दाब मोजणे आणि सविस्तर दृष्टी कक्षा तपासणे अनिवार्य आहे."
                ]
            },
            "Notes": {
                "English": [
                    "Structural optic nerve evaluation flags suspicious features; functional visual field correlation is advised.",
                    "Glaucoma progression can be successfully prevented when detected and managed early."
                ],
                "Hindi": [
                    "ऑप्टिक तंत्रिका में संदेहास्पद विशेषताएं पाई गई हैं; कार्यात्मक दृष्टि परीक्षण की सलाह दी जाती है।",
                    "समय पर पहचान और उपचार से ग्लूकोमा के कारण दृष्टि हानि को सफलतापूर्वक रोका जा सकता है।"
                ],
                "Marathi": [
                    "मज्जातंतूच्या तपासणीत संशयास्पद बदल आढळले आहेत; प्रत्यक्ष डोळ्यांच्या तपासणीची गरज आहे.",
                    "वेळेवर निदान आणि उपचारांनी काचबिंदूमुळे होणारे नुकसान पूर्णपणे रोखता येते."
                ]
            }
        }
    }

    selected = data.get(category, data["moderate"])
    return {k: {lang: list(pts) for lang, pts in v.items()} for k, v in selected.items()}


def _empty_report_sections(prediction=None):
    """Return a complete, valid report schema populated for the detected condition."""
    return get_severity_report_fallback(prediction=prediction)


def extract_report_sections(text):
    """
    Parse Gemini response (JSON, Markdown, or plain text) into structured report sections.
    CRITICAL: Extract actual values, never return raw JSON strings into PDF.
    Handles: valid JSON, JSON in code blocks, Markdown headings, numbered/bulleted headings, and plain text with section markers.
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
        if isinstance(value, list):
            return any(isinstance(item, str) and len(item.strip()) >= 2 for item in value)
        if isinstance(value, dict):
            return any(is_valid_section(item) for item in value.values())
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower()
        if len(normalized) < 10:
            return False
        if len(normalized.split()) < 2:
            return False
        for marker in forbidden_markers:
            if marker in normalized:
                return False
        return True

    def parse_json_sections(parsed):
        if not isinstance(parsed, dict):
            return None

        sections = {}
        for item_key, value in parsed.items():
            canonical_key = _canonicalize_report_key(item_key)
            if not canonical_key:
                continue
            clean_value = _coerce_report_value(value)
            if is_valid_section(clean_value):
                sections[canonical_key] = clean_value

        if sections:
            for key in REPORT_SECTION_KEYS:
                if key not in sections:
                    sections[key] = []
            return sections

        return None

    def _extract_json_candidates(text_value):
        candidates = []
        start_positions = [m.start() for m in re.finditer(r"\{", text_value)]
        for start in start_positions:
            depth = 0
            in_string = False
            escaped = False
            for idx in range(start, len(text_value)):
                char = text_value[idx]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue

                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        candidates.append(text_value[start:idx + 1])
                        break
        return candidates

    # Try 1: Direct JSON parsing - MUST WORK for well-formed JSON
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            sections = parse_json_sections(parsed)
            if sections:
                return sections
    except (json.JSONDecodeError, ValueError):
        pass
    except Exception:
        pass

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
    for json_candidate in _extract_json_candidates(cleaned):
        try:
            parsed = json.loads(json_candidate)
            sections = parse_json_sections(parsed)
            if sections:
                return sections
        except (json.JSONDecodeError, ValueError):
            pass

    def _canonical_section_key(raw_key):
        raw = raw_key.strip().lower()
        for key in REPORT_SECTION_KEYS:
            if raw == key.lower():
                return key
        return None

    def _split_text_into_sections(text):
        key_patterns = []
        for key in REPORT_SECTION_KEYS:
            escaped = re.escape(key)
            key_patterns.append(rf'(?:\*\*|__)?{escaped}(?:\*\*|__)?')
        keys_pattern = '|'.join(key_patterns)
        pattern = re.compile(
            rf'(?P<key>{keys_pattern})\s*[:\-–—]?\s*(?P<value>.*?)(?=(?:\n\s*(?:{keys_pattern})\s*[:\-–—]?)|$)',
            re.I | re.S,
        )
        sections = {}
        for match in pattern.finditer(text):
            section_key = _canonical_section_key(re.sub(r'\*\*|__', '', match.group('key')).strip())
            if not section_key:
                continue
            section_text = match.group('value').strip()
            section_text = re.sub(r'\s+', ' ', section_text)
            if section_text:
                sections[section_key] = section_text
        return sections

    def _find_heading(line):
        normalized = _normalize_section_heading(line)
        for key in REPORT_SECTION_KEYS:
            key_lower = key.lower()
            if normalized.lower().startswith(key_lower):
                remaining = normalized[len(key):].strip()
                remaining = re.sub(r'^[:\-–—]\s*', '', remaining)
                return key, remaining
        return None, None

    sections = {}
    lines = cleaned.split('\n')
    current_section = None
    current_content = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('{') or stripped.startswith('['):
            continue

        section_key, inline_value = _find_heading(stripped)
        if section_key:
            if current_section and current_content:
                content = ' '.join(current_content).strip()
                content = re.sub(r'\s+', ' ', content)
                if content and len(content) > 5:
                    sections[current_section] = content
            current_section = section_key
            current_content = []
            if inline_value:
                current_content.append(inline_value)
            continue

        if current_section:
            clean_line = re.sub(r'^[\-\*\u2022\•\d+\.)\s]*', '', stripped)
            if clean_line:
                current_content.append(clean_line)

    if current_section and current_content:
        content = ' '.join(current_content).strip()
        content = re.sub(r'\s+', ' ', content)
        if content and len(content) > 5:
            sections[current_section] = content

    if len(sections) >= 1:
        for key in REPORT_SECTION_KEYS:
            if key not in sections:
                sections[key] = []
        return sections

    fallback_sections = _split_text_into_sections(cleaned)
    if len(fallback_sections) >= 1:
        for key in REPORT_SECTION_KEYS:
            if key not in fallback_sections:
                fallback_sections[key] = []
        return fallback_sections

    if len(sections) >= 3 and len(cleaned) > 100:
        combined = ' '.join(sections.values())
        for key in REPORT_SECTION_KEYS:
            if key not in sections:
                sections[key] = combined[:180]
        return sections

    return _empty_report_sections()


def _complete_report_translations(sections, api_key=None, image_path=None):
    """Translate populated English report points without changing the source report."""
    english_sections = {
        key: value.get("English") if isinstance(value, dict) else value
        for key, value in sections.items()
        if key in REPORT_SECTION_KEYS and (
            (isinstance(value, dict) and value.get("English"))
            or (not isinstance(value, dict) and value)
        )
    }
    if not english_sections:
        return sections

    sections_needing_translation = {
        key: value
        for key, value in english_sections.items()
        if not isinstance(sections.get(key), dict)
        or not sections[key].get("Marathi")
        or not sections[key].get("Hindi")
    }
    if not sections_needing_translation:
        return sections

    translation_prompt = f"""Translate the following AI-generated medical report points into Marathi and Hindi.
Use the exact section keys and return ONLY valid JSON in this shape:
{{"Section Name": {{"Marathi": ["..."], "Hindi": ["..."]}}}}
Preserve the number and order of points for every section. Do not add, remove, summarize, or invent information.

Source report points:
{json.dumps({key: english_sections[key] for key in sections_needing_translation}, ensure_ascii=False)}
"""
    try:
        translated = chatbot_response(
            translation_prompt,
            strict=True,
            api_key=api_key,
            lang=None,
            image_path=image_path,
        )
        translated_sections = extract_report_sections(translated)
        if not translated_sections:
            return sections

        for key, value in translated_sections.items():
            if key not in sections_needing_translation or not isinstance(value, dict):
                continue
            current = sections.setdefault(key, {})
            if not isinstance(current, dict):
                current = {"English": english_sections[key]}
                sections[key] = current
            for language in ("Marathi", "Hindi"):
                language_value = value.get(language)
                if language_value and not current.get(language):
                    current[language] = language_value
    except Exception as exc:
        print(f"[REPORT] Translation completion failed: {exc}")

    return sections


def generate_dynamic_medical_report(
    prediction,
    request_id=None,
    strict=True,
    api_key=None,
    lang=None,
    analysis_data=None,
    image_path=None,
):
    """
    Generate a dynamic Gemini-produced medical report for the retina prediction.
    Guarantees non-empty clinical text across all 8 required sections in English, Hindi, and Marathi.
    """
    prompt = build_report_prompt(
        prediction=prediction,
        request_id=request_id,
        lang=lang,
        analysis_data=analysis_data,
    )
    
    reply = None
    try:
        reply = chatbot_response(
            prompt,
            strict=True,
            api_key=api_key,
            lang=None,
            image_path=image_path or (analysis_data or {}).get("image_path"),
        )
    except Exception as exc:
        print(f"[REPORT] Gemini API Note: {exc}")

    sections = None
    if reply and reply.strip():
        print(f"[REPORT] Received response from Gemini (length: {len(reply)})")
        sections = extract_report_sections(reply)

    fallback = get_severity_report_fallback(
        prediction=prediction,
        confidence=(analysis_data or {}).get("confidence"),
        risk_level=(analysis_data or {}).get("risk_level"),
    )

    if not sections or not isinstance(sections, dict):
        print(f"[REPORT] Utilizing complete clinical report for severity: {prediction}")
        sections = fallback
    else:
        # Merge: ensure all 8 canonical sections + Risk Level are populated in English, Hindi, and Marathi
        for key in REPORT_SECTION_KEYS + ["Risk Level"]:
            fb_val = fallback.get(key, {})
            if key not in sections or not sections[key]:
                sections[key] = fb_val
            elif isinstance(sections[key], dict):
                for lk in ("English", "Marathi", "Hindi"):
                    cur_val = sections[key].get(lk)
                    if not cur_val or (isinstance(cur_val, list) and not any(str(x).strip() for x in cur_val)):
                        sections[key][lk] = fb_val.get(lk, [])
            elif isinstance(sections[key], list):
                if not sections[key] or not any(str(x).strip() for x in sections[key]):
                    sections[key] = fb_val
                else:
                    sections[key] = {
                        "English": sections[key],
                        "Marathi": fb_val.get("Marathi", []),
                        "Hindi": fb_val.get("Hindi", [])
                    }

    print(f"[REPORT] Final report verified for '{prediction}':")
    for sec_key in REPORT_SECTION_KEYS:
        sec_val = sections.get(sec_key, {})
        if isinstance(sec_val, dict):
            en_items = [str(x) for x in sec_val.get("English", []) if str(x).strip()]
            hi_items = [str(x) for x in sec_val.get("Hindi", []) if str(x).strip()]
            mr_items = [str(x) for x in sec_val.get("Marathi", []) if str(x).strip()]
            print(f"  [OK] {sec_key}: English={len(en_items)}, Hindi={len(hi_items)}, Marathi={len(mr_items)}")
        else:
            print(f"  [OK] {sec_key}: plain={len(sec_val)}")

    return sections


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


def chatbot_response(user_message, strict=False, api_key=None, lang=None, image_path=None):
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
    request_deadline = time.monotonic() + GEMINI_REQUEST_DEADLINE
    for model_name in runtime_models:
        for attempt in range(1, GEMINI_RETRY_ATTEMPTS + 1):
            remaining_time = request_deadline - time.monotonic()
            if remaining_time <= 0:
                raise RuntimeError("Gemini request timed out while processing the uploaded image.")
            print(f"[CHATBOT] Attempting Gemini model: {model_name} (attempt {attempt}/{GEMINI_RETRY_ATTEMPTS})")
            try:
                request = build_gemini_request(
                    user_message,
                    api_key=runtime_key,
                    model_name=model_name,
                    image_path=image_path,
                )
                response = requests.post(
                    request["url"],
                    headers=request["headers"],
                    json=request["payload"],
                    timeout=min(30, remaining_time),
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

                if response.status_code == 503 and attempt < GEMINI_RETRY_ATTEMPTS:
                    wait_time = RETRY_DELAY * (2 ** (attempt - 1))
                    print(f"[CHATBOT] Gemini returned HTTP 503 for {model_name}; retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue

                if response.status_code in {401, 403}:
                    raise RuntimeError(f"Gemini API request failed: {response.status_code} - configuration or authorization issue")

                last_error = payload
                if _should_fallback_to_next_model(response.status_code, payload):
                    if model_name != runtime_models[-1]:
                        print(f"[CHATBOT] Switching to the next Gemini model after {model_name}")
                        break
                    raise RuntimeError(f"Gemini API request failed for all available models: {response.status_code}")
                raise RuntimeError(f"Gemini API request failed: {response.status_code}")
            except requests.RequestException as exc:
                print(f"[CHATBOT] Gemini REST request failed for {model_name}: {exc}")
                last_error = {"error": {"message": str(exc)}}
                if attempt < GEMINI_RETRY_ATTEMPTS:
                    wait_time = RETRY_DELAY * (2 ** (attempt - 1))
                    print(f"[CHATBOT] Retrying Gemini request after transient error in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                if model_name != runtime_models[-1]:
                    break
                raise RuntimeError(f"Gemini REST request failed for {model_name}: {exc}") from exc
            except RuntimeError:
                raise
            except Exception as exc:
                print(f"[CHATBOT] Gemini request error for {model_name}: {exc}")
                if attempt < GEMINI_RETRY_ATTEMPTS:
                    wait_time = RETRY_DELAY * (2 ** (attempt - 1))
                    print(f"[CHATBOT] Retrying Gemini request after transient error in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                if model_name != runtime_models[-1]:
                    break
                raise RuntimeError(f"Gemini request error for {model_name}: {exc}") from exc

        if model_name != runtime_models[-1]:
            continue

    quota_reset_time = time.time() + 60
    if last_error is not None:
        raise RuntimeError(f"Gemini API did not return a usable response: {last_error}")
    raise RuntimeError("Gemini API did not return a usable response")
