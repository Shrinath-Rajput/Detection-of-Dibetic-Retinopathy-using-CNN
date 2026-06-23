#!/usr/bin/env python3
"""
Complete Updated bot.py File
Chatbot response handler with rate limiting, retry logic, and comprehensive diagnostics
"""

import os
import requests
from dotenv import load_dotenv
import json
import time
from datetime import datetime

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini 1.5 Flash API (proven stable, fixed from 2.0-flash)
GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1/models/"
    "gemini-1.5-flash:generateContent"
)

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
    
    if not GEMINI_API_KEY.startswith("AI"):
        return False, f"API key has invalid format (should start with 'AI')"
    
    return True, "API key format valid"

def chatbot_response(user_message):
    """
    Send user message to Gemini API and return the generated response.
    Includes rate limiting, retry logic, and comprehensive diagnostics.
    """

    if not user_message or len(user_message.strip()) < 2:
        return "Please enter a valid question."

    # Print timestamp and start of diagnostic session
    print("\n" + "=" * 80)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] GEMINI API CALL")
    print("=" * 80)

    # Validate API key
    is_valid, validation_msg = validate_api_key()
    print(f"\n[API KEY VALIDATION] {validation_msg}")
    
    if not is_valid:
        print("[CRITICAL] API key validation failed!")
        print("[ACTION REQUIRED] Update GEMINI_API_KEY in .env file")
        return "Chatbot service is not properly configured. Contact support."

    # Log API configuration
    api_key_prefix = GEMINI_API_KEY[:10] if GEMINI_API_KEY else "NOT_SET"
    api_key_suffix = GEMINI_API_KEY[-6:] if GEMINI_API_KEY else "NOT_SET"
    api_key_length = len(GEMINI_API_KEY) if GEMINI_API_KEY else 0
    
    print(f"\n[API CONFIGURATION]")
    print(f"  - API Key (first 10)  : {api_key_prefix}...")
    print(f"  - API Key (last 6)    : ...{api_key_suffix}")
    print(f"  - API Key Length      : {api_key_length}")
    print(f"  - API URL             : {GEMINI_API_URL}")
    print(f"  - Request Method      : POST")
    print(f"  - Timeout             : 25 seconds")
    print(f"  - Retry Attempts      : {RETRY_ATTEMPTS}")
    print(f"  - Rate Limit Delay    : {REQUEST_DELAY}s between requests")

    print(f"\n[REQUEST DETAILS]")
    print(f"  - User Message        : {user_message}")
    print(f"  - Timestamp           : {datetime.now().isoformat()}")

    # Enforce rate limiting
    rate_limit_check()

    # Prepare request payload
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": user_message
                    }
                ]
            }
        ],
        "system_instruction": {
            "parts": [
                {
                    "text": SYSTEM_PROMPT
                }
            ]
        },
        "generationConfig": {
            "temperature": 0.7,
            "topK": 40,
            "topP": 0.95,
            "maxOutputTokens": 1000
        }
    }

    # Retry logic with exponential backoff
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            print(f"\n[REQUEST ATTEMPT {attempt}/{RETRY_ATTEMPTS}]")
            
            # Make API request
            response = requests.post(
                f"{GEMINI_API_URL}?key={GEMINI_API_KEY}",
                headers={
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=25
            )

            print(f"  - Status Code         : {response.status_code}")
            print(f"  - Content-Type        : {response.headers.get('content-type', 'N/A')}")

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
                    reply = data["candidates"][0]["content"]["parts"][0]["text"]
                    print(f"\n[SUCCESS ✓]")
                    print(f"  - Response received   : {len(reply)} characters")
                    print(f"  - Generation complete : {datetime.now().isoformat()}")
                    print("=" * 80 + "\n")
                    return reply

                print(f"\n[ERROR] Unexpected response structure")
                print(f"  - Response keys       : {list(data.keys())}")
                return "Unable to generate response. Please try again."

            # Handle 429 - Rate Limit/Quota Error
            elif response.status_code == 429:
                print(f"  - Error Type          : Rate Limit / Quota Exceeded (429)")
                
                if attempt < RETRY_ATTEMPTS:
                    backoff_delay = RETRY_DELAY * (2 ** (attempt - 1))
                    print(f"\n[RETRYING] Waiting {backoff_delay}s before retry {attempt + 1}...")
                    time.sleep(backoff_delay)
                    continue
                
                error_msg = response.json().get("error", {})
                print(f"\n[QUOTA EXHAUSTED - FINAL ATTEMPT]")
                print(f"  - Error Message       : {error_msg.get('message', 'Unknown')}")
                print(f"  - Status              : {error_msg.get('status', 'RESOURCE_EXHAUSTED')}")
                print(f"\n[DIAGNOSTICS]")
                print(f"  1. Check Google Cloud Console > Quotas")
                print(f"  2. Verify billing is enabled on Google Cloud project")
                print(f"  3. Check if API quota limit is reached")
                print(f"  4. Request quota increase if needed")
                print(f"  5. Try again in a few minutes")
                
                return "API quota temporarily exhausted. Please try again in a few moments."

            # Handle 403 - Permission Error
            elif response.status_code == 403:
                error_msg = response.json().get("error", {})
                print(f"\n[PERMISSION ERROR]")
                print(f"  - Error Message       : {error_msg.get('message', 'Access denied')}")
                print(f"\n[DIAGNOSTICS]")
                print(f"  1. Verify API key has Generative Language API access")
                print(f"  2. Check Google Cloud Console > APIs & Services > Credentials")
                print(f"  3. Ensure Generative Language API is enabled in the project")
                print(f"  4. Regenerate API key if needed")
                
                return "API access denied. Please check configuration."

            # Handle 401 - Authentication Error
            elif response.status_code == 401:
                error_msg = response.json().get("error", {})
                print(f"\n[AUTHENTICATION ERROR]")
                print(f"  - Error Message       : {error_msg.get('message', 'Invalid credentials')}")
                print(f"\n[DIAGNOSTICS]")
                print(f"  1. API key is invalid or corrupted")
                print(f"  2. Generate new API key from Google Cloud Console")
                print(f"  3. Update .env file with new GEMINI_API_KEY")
                print(f"  4. Restart application")
                
                return "Invalid API credentials. Please check configuration."

            # Handle 404 - Not Found Error
            elif response.status_code == 404:
                error_msg = response.json().get("error", {})
                print(f"\n[MODEL NOT FOUND ERROR]")
                print(f"  - Error Message       : {error_msg.get('message', 'Model not found')}")
                print(f"\n[DIAGNOSTICS]")
                print(f"  1. Verify model name is correct: {GEMINI_API_URL}")
                print(f"  2. Check if Generative Language API is enabled")
                print(f"  3. Ensure project has access to Gemini models")
                
                return "API model not found. Please check configuration."

            # Handle other HTTP errors
            else:
                error_msg = response.json().get("error", {}) if response.text else {}
                print(f"  - Error Type          : HTTP {response.status_code}")
                print(f"  - Error Message       : {error_msg.get('message', response.text)}")
                
                if attempt < RETRY_ATTEMPTS:
                    backoff_delay = RETRY_DELAY * (2 ** (attempt - 1))
                    print(f"\n[RETRYING] Waiting {backoff_delay}s before retry {attempt + 1}...")
                    time.sleep(backoff_delay)
                    continue
                
                return f"Service error ({response.status_code}). Please try again later."

        except requests.exceptions.Timeout:
            print(f"\n[TIMEOUT ERROR]")
            print(f"  - Request took longer than 25 seconds")
            
            if attempt < RETRY_ATTEMPTS:
                backoff_delay = RETRY_DELAY * (2 ** (attempt - 1))
                print(f"\n[RETRYING] Waiting {backoff_delay}s before retry {attempt + 1}...")
                time.sleep(backoff_delay)
                continue
            
            return "Request timed out. Please try again."

        except requests.exceptions.ConnectionError as e:
            print(f"\n[CONNECTION ERROR]")
            print(f"  - Error                : {str(e)}")
            print(f"  - Check internet connection")
            
            if attempt < RETRY_ATTEMPTS:
                backoff_delay = RETRY_DELAY * (2 ** (attempt - 1))
                print(f"\n[RETRYING] Waiting {backoff_delay}s before retry {attempt + 1}...")
                time.sleep(backoff_delay)
                continue
            
            return "Connection error. Please check your internet connection."

        except Exception as e:
            print(f"\n[UNEXPECTED ERROR]")
            print(f"  - Error Type          : {type(e).__name__}")
            print(f"  - Error Message       : {str(e)}")
            
            import traceback
            traceback.print_exc()
            
            if attempt < RETRY_ATTEMPTS:
                backoff_delay = RETRY_DELAY * (2 ** (attempt - 1))
                print(f"\n[RETRYING] Waiting {backoff_delay}s before retry {attempt + 1}...")
                time.sleep(backoff_delay)
                continue
            
            return "An unexpected error occurred. Please try again."

    print("\n[FINAL RESULT] All retry attempts exhausted")
    print("=" * 80 + "\n")
    return "Unable to reach chatbot service. Please try again later."
