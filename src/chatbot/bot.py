import os
import google.generativeai as genai

# -------------------------
# Configure Gemini API
# -------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyAFWeR3aVkOiXREIXDmJdPd6mr06akABZQ")
genai.configure(api_key=GEMINI_API_KEY)

# Medical assistant system prompt
SYSTEM_PROMPT = (
    "You are CareSense AI healthcare assistant. "
    "Give concise, useful healthcare information and general guidance. "
    "Do not diagnose with certainty. "
    "Always recommend consulting healthcare professionals for serious concerns. "
    "Keep responses brief and clear."
)

# -------------------------
# Main chatbot function
# -------------------------
def chatbot_response(user_message: str) -> str:
    """Get intelligent response using Gemini API"""
    
    # Input validation
    if not user_message or len(user_message.strip()) < 2:
        return "Please ask a clear question 🙂"

    try:
        # Initialize Gemini model
        model = genai.GenerativeModel(
            model_name="gemini-pro",
            system_instruction=SYSTEM_PROMPT
        )
        
        # Generate response
        response = model.generate_content(
            user_message,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=150,
                temperature=0.7
            )
        )
        
        # Extract text from response
        if response and response.text:
            return response.text.strip()
        else:
            return "I couldn't generate a response. Please try again. 🙂"
            
    except Exception as e:
        # Graceful error handling
        error_msg = str(e).lower()
        
        if "api_key" in error_msg or "authentication" in error_msg:
            return "API configuration issue. Please contact support. ⚠️"
        elif "network" in error_msg or "timeout" in error_msg:
            return "Network connection issue. Please check your internet. 🌐"
        elif "rate limit" in error_msg:
            return "Service temporarily busy. Please try again in a moment. ⏳"
        else:
            return "Unable to process your request. Please try again. 🙂"
