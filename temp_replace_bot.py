from pathlib import Path
path = Path('src/chatbot/bot.py')
text = path.read_text(encoding='utf-8')
start = text.rfind('def chatbot_response(user_message, strict=False, api_key=None, lang=None):')
if start == -1:
    raise SystemExit('chatbot function not found')
new_block = '''def chatbot_response(user_message, strict=False, api_key=None, lang=None):
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
'''
path.write_text(text[:start] + new_block, encoding='utf-8')
print('updated')
