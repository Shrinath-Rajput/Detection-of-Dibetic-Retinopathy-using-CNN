import os
import requests

# -------------------------
# Gemini REST API Configuration
# -------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyAFWeR3aVkOiXREIXDmJdPd6mr06akABZQ")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent"

# Medical assistant system prompt
SYSTEM_PROMPT = (
    "You are CareSense AI healthcare assistant. "
    "Give useful healthcare information and general guidance. "
    "Do not diagnose with certainty. "
    "Always recommend consulting healthcare professionals for serious concerns. "
    "Keep responses brief and clear."
)

# -------------------------
# Main chatbot function using REST API
# -------------------------
def chatbot_response(user_message: str) -> str:
    """Get intelligent response using Gemini REST API"""
    
    # Input validation
    if not user_message or len(user_message.strip()) < 2:
        return "Please ask a clear question 🙂"

    try:
        # Check API key
        if not GEMINI_API_KEY or GEMINI_API_KEY == "":
            return "API configuration missing. Please set GEMINI_API_KEY environment variable. ⚠️"
        
        # Prepare request
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": f"{SYSTEM_PROMPT}\n\nUser question: {user_message}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 150,
                "topP": 0.95,
                "topK": 40
            }
        }
        
        # Call Gemini API
        response = requests.post(
            f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
            headers=headers,
            json=payload,
            timeout=10
        )
        
        # Handle response
        if response.status_code == 200:
            data = response.json()
            
            # Extract text from response
            try:
                candidates = data.get("candidates", [])
                if candidates and len(candidates) > 0:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts and len(parts) > 0:
                        return parts[0].get("text", "I couldn't generate a response. Try again. 🙂").strip()
            except (KeyError, IndexError, TypeError):
                return "Error parsing API response. Try again. 🙂"
            
            return "I couldn't generate a response. Try again. 🙂"
        
        elif response.status_code == 401:
            return "Invalid API key. Please check GEMINI_API_KEY configuration. 🔑"
        elif response.status_code == 429:
            return "API rate limit exceeded. Please try again in a moment. ⏳"
        elif response.status_code >= 500:
            return "Gemini service is temporarily unavailable. Try again later. 🌐"
        else:
            return f"API error ({response.status_code}). Please try again. ⚠️"
            
    except requests.exceptions.Timeout:
        return "Request timeout. Please check your internet connection. 🌐"
    except requests.exceptions.ConnectionError:
        return "Connection error. Please check your internet. 🌐"
    except requests.exceptions.RequestException as e:
        return "Network error. Please try again. 🌐"
    except Exception as e:
        # Generic fallback
        return f"Unexpected error. Please try again. 🙂"
