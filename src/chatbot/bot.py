import os
import requests
from dotenv import load_dotenv
import json

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 2.0 Flash API
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1/models/"
    "gemini-2.0-flash:generateContent"
)

SYSTEM_PROMPT = """
You are a helpful AI assistant. Answer any question the user asks.
Be informative, accurate, and concise.
"""

def chatbot_response(user_message):
    """
    Send user message to Gemini API and return the generated response.
    Sends the exact user message, returns the exact Gemini response.
    No hardcoded answers. All responses are dynamically generated.
    """

    if not user_message or len(user_message.strip()) < 2:
        return "Please enter a valid question."

    try:
        # Diagnostic: Log API key info
        api_key_prefix = GEMINI_API_KEY[:10] if GEMINI_API_KEY else "NOT_SET"
        api_key_suffix = GEMINI_API_KEY[-10:] if GEMINI_API_KEY else "NOT_SET"
        api_key_length = len(GEMINI_API_KEY) if GEMINI_API_KEY else 0
        
        print("\n" + "=" * 80)
        print("[GEMINI API DIAGNOSTIC]")
        print("=" * 80)
        print(f"Loaded API Key (first 10)  : {api_key_prefix}")
        print(f"Loaded API Key (last 10)   : {api_key_suffix}")
        print(f"API Key Length             : {api_key_length}")
        print(f"API Key Source             : .env file (GEMINI_API_KEY)")
        print("=" * 80)
        
        print("\n[GEMINI API CALL]")
        print("=" * 80)
        print(f"API URL         : {GEMINI_API_URL}")
        print(f"Request Method  : POST")
        print(f"User Message    : {user_message}")
        print("=" * 80)

        # Prepare request payload - send exact user message
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": user_message
                        }
                    ]
                }
            ]
        }

        # Make API request
        response = requests.post(
            f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
            headers={
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=20
        )

        print(f"\nStatus Code     : {response.status_code}")
        print(f"Response Headers: {dict(response.headers)}")
        print(f"\nFull Response Body:")
        print("-" * 80)
        
        # Pretty print response
        try:
            response_json = response.json()
            print(json.dumps(response_json, indent=2))
        except:
            print(response.text)
            
        print("-" * 80)

        # Handle successful response
        if response.status_code == 200:
            data = response.json()

            if (
                "candidates" in data
                and len(data["candidates"]) > 0
                and "content" in data["candidates"][0]
                and "parts" in data["candidates"][0]["content"]
                and len(data["candidates"][0]["content"]["parts"]) > 0
            ):
                # Return exact Gemini response
                reply = data["candidates"][0]["content"]["parts"][0]["text"]
                print(f"\n[SUCCESS] Received response from Gemini")
                return reply

            print(f"\n[ERROR] Unexpected response structure from Gemini")
            return "Unable to generate response. Please try again."

        # Handle API errors with diagnostics
        else:
            error_code = response.status_code
            print(f"\n[API ERROR] Status {error_code}")
            
            try:
                error_detail = response.json()
                error_message = error_detail.get("error", {}).get("message", "Unknown error")
                print(f"[ERROR MESSAGE] {error_message}")
                
                # Specific diagnostics for common errors
                if error_code == 429:
                    print("\n[QUOTA ISSUE]")
                    print("- Gemini API quota exhausted")
                    print("- Check Google Cloud Console quota status")
                    print("- Enable billing if not already enabled")
                    print("- Request quota increase if needed")
                    
                elif error_code == 403:
                    print("\n[PERMISSION ISSUE]")
                    print("- API key doesn't have permission")
                    print("- Generative Language API may not be enabled")
                    print("- Check Google Cloud Console > Enable APIs")
                    
                elif error_code == 401:
                    print("\n[AUTHENTICATION ISSUE]")
                    print("- API key is invalid or corrupted")
                    print("- Regenerate key from Google Cloud Console")
                    
                elif error_code == 404:
                    print("\n[API NOT FOUND]")
                    print("- Model or endpoint not found")
                    print("- Check if Generative Language API is enabled")
                    
            except:
                print(f"[ERROR DETAIL] {response.text}")
            
            return f"Service error ({error_code}). Please try again later."

    except requests.exceptions.Timeout:
        error_msg = "Request timed out. Please try again."
        print(f"\n[TIMEOUT] {error_msg}")
        return error_msg

    except requests.exceptions.ConnectionError as e:
        error_msg = f"Connection error. Please check your internet connection."
        print(f"\n[CONNECTION ERROR] {str(e)}")
        return error_msg

    except Exception as e:
        error_msg = "An unexpected error occurred. Please try again."
        print(f"\n[ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return error_msg