# app.py
import sys

# Ensure UTF-8 stdout and stderr encoding on Windows to prevent UnicodeEncodeError with emojis/translations
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from flask import send_file, session
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import io
import os
import json
import numpy as np
import tensorflow as tf
import time

from flask import Flask, render_template, request, redirect, url_for, jsonify, Response
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from src.services.sensor_service import sensor_data, start_sensor_thread
from src.chatbot.bot import chatbot_response, generate_dynamic_medical_report, get_severity_report_fallback
from src.i18n import DEFAULT_LANGUAGE, SUPPORTED_LANGUAGES, get_language_label, get_translation

app = Flask(__name__)
app.secret_key = "clinsense_ai_secret"

# Keep the full AI report out of Flask's client-side cookie session.
DR_REPORT_CACHE = {}

@app.before_request
def ensure_language():
    lang = session.get("lang")
    if not lang or lang not in SUPPORTED_LANGUAGES:
        session["lang"] = DEFAULT_LANGUAGE

@app.context_processor
def inject_translations():
    lang = session.get("lang", DEFAULT_LANGUAGE)
    def t(key):
        return get_translation(key, lang)
    def lang_url(code):
        return url_for("set_language", lang=code, next=request.path)
    return {
        "t": t,
        "current_lang": lang,
        "languages": SUPPORTED_LANGUAGES,
        "lang_url": lang_url,
        "language_label": get_language_label(lang)
    }

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    session["lang"] = lang
    next_url = request.args.get("next") or request.referrer or url_for("home")
    return redirect(next_url)

@app.errorhandler(404)
def handle_not_found(error):
    lang = session.get("lang", DEFAULT_LANGUAGE)
    return get_translation("common.error_not_found", lang), 404

@app.errorhandler(Exception)
def handle_uncaught_exception(error):
    if isinstance(error, HTTPException):
        return error

    import traceback
    print("=" * 80)
    print("UNHANDLED EXCEPTION")
    print(error)
    traceback.print_exc()
    print("=" * 80)
    lang = session.get("lang", DEFAULT_LANGUAGE)
    return get_translation("common.internal_server_error", lang), 500

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['JSON_SORT_KEYS'] = False

def get_translator():
    lang = session.get("lang", DEFAULT_LANGUAGE)
    return lambda key: get_translation(key, lang)

import gdown

MODEL_PATH = "dr_cnn_model.h5"

if not os.path.exists(MODEL_PATH):
    url = "https://drive.google.com/uc?id=1r-jqC-X67DQo2yf_ozOr2LiGLVMbNL_J"
    gdown.download(url, MODEL_PATH, quiet=False)

# Compatibility shim for older saved models using groups in DepthwiseConv2D config
try:
    from tensorflow.keras.layers import DepthwiseConv2D
    _original_depthwise_from_config = DepthwiseConv2D.from_config
    _original_depthwise_init = DepthwiseConv2D.__init__

    @classmethod
    def _depthwise_from_config_class(cls, config, **kwargs):
        if isinstance(config, dict):
            config = dict(config)
            config.pop('groups', None)
        # Only pass kwargs that the original method accepts
        return _original_depthwise_from_config.__func__(cls, config)

    def _depthwise_init(self, *args, **kwargs):
        kwargs.pop('groups', None)
        return _original_depthwise_init(self, *args, **kwargs)

    DepthwiseConv2D.from_config = _depthwise_from_config_class
    DepthwiseConv2D.__init__ = _depthwise_init
except Exception:
    pass

model = tf.keras.models.load_model(MODEL_PATH, compile=False)

with open("class_indices.json") as f:
    class_indices = json.load(f)

INDEX_TO_CLASS = {v: k for k, v in class_indices.items()}

print("[STARTUP] Initializing sensor thread...")
start_sensor_thread()
print(f"[STARTUP] Sensor data: {sensor_data}")

def preprocess_image(img_path):
    img = tf.keras.preprocessing.image.load_img(img_path, target_size=(224, 224))
    img = tf.keras.preprocessing.image.img_to_array(img) / 255.0
    return np.expand_dims(img, axis=0)


def get_pdf_font(lang_code):
    """Return a TrueType font name registered with reportlab that supports the requested language.
    Tries common Windows Devanagari fonts and falls back to Helvetica.
    """
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        return 'Helvetica'

    candidates = [
        'Nirmala.ttc',
        'Nirmala.ttf',
        'NirmalaUI.ttf',
        'Mangal.ttf',
        'DejaVuSans.ttf',
        'ArialUnicodeMS.ttf',
        'NotoSansDevanagari-Regular.ttf'
    ]

    fonts_dir = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
    for fname in candidates:
        path = os.path.join(fonts_dir, fname)
        if os.path.exists(path):
            try:
                font_key = 'Deva' + fname.replace('.', '_')
                if font_key not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(font_key, path))
                return font_key
            except Exception:
                continue

    # Fallback to Helvetica
    return 'Helvetica'

def analyze_health(hr, spo2, lang=DEFAULT_LANGUAGE):
    trans = lambda key: get_translation(key, lang)
    hr_status = "UNKNOWN"
    spo2_status = "UNKNOWN"
    risk = []
    advice = []

    try:
        if hr != "--":
            hr = int(hr)
        else:
            hr = None
    except Exception as e:
        print("=" * 80)
        print("HEALTH ANALYSIS PARSE ERROR")
        print(e)
        import traceback
        traceback.print_exc()
        print("=" * 80)
        hr = None

    try:
        if spo2 != "--":
            spo2 = int(spo2)
        else:
            spo2 = None
    except Exception as e:
        print("=" * 80)
        print("HEALTH ANALYSIS PARSE ERROR")
        print(e)
        import traceback
        traceback.print_exc()
        print("=" * 80)
        spo2 = None

    if hr is not None:
        if hr < 60:
            hr_status = "LOW"
            risk.append(trans('health.low_heart_rate'))
        elif hr > 100:
            hr_status = "HIGH"
            risk.append(trans('health.high_heart_rate'))
        else:
            hr_status = "NORMAL"
    else:
        hr_status = "WAITING"

    if spo2 is not None:
        if spo2 < 95:
            spo2_status = "LOW"
            risk.append(trans('health.low_oxygen'))
        else:
            spo2_status = "NORMAL"
    else:
        spo2_status = "WAITING"

    if not risk:
        advice = [
            trans('health.normal_vitals_1'),
            trans('health.normal_vitals_2'),
            trans('health.normal_vitals_3'),
            trans('health.normal_vitals_4')
        ]
    else:
        advice = [
            trans('health.advice_rest'),
            trans('health.advice_breathe'),
            trans('health.advice_reduce_stress'),
            trans('health.advice_hydrate'),
            trans('health.advice_consult')
        ]

    return {
        "heart_rate_status_code": hr_status,
        "heart_rate_status": trans(f'live_health.status_{hr_status.lower()}') if hr_status in ['NORMAL', 'LOW', 'HIGH', 'WAITING'] else hr_status,
        "spo2_status_code": spo2_status,
        "spo2_status": trans(f'live_health.status_{spo2_status.lower()}') if spo2_status in ['NORMAL', 'LOW', 'HIGH', 'WAITING'] else spo2_status,
        "risk": risk,
        "advice": advice
    }

@app.route("/")
def home():
    return render_template("home.html")

@app.route("/dr")
def dr_page():
    return render_template("index.html")

@app.route("/predict", methods=["POST"])
def predict():
    try:
        import uuid
        file = request.files.get("image")
        if not file or file.filename == "":
            return redirect(url_for("dr_page"))

        filename = secure_filename(file.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(path)
        print(f"[DR_PREDICT] Uploaded file: {filename}")
        print(f"[DR_PREDICT] Saved image path: {path}")
        print(f"[DR_PREDICT] Image exists on disk: {os.path.exists(path)}")
        print(f"[DR_PREDICT] Image size bytes: {os.path.getsize(path) if os.path.exists(path) else 'N/A'}")

        preds = model.predict(preprocess_image(path))
        class_id = int(np.argmax(preds))
        confidence = round(float(preds[0][class_id] * 100), 2)
        print(f"[DR_PREDICT] Prediction array: {preds[0]}")
        print(f"[DR_PREDICT] Predicted class id: {class_id}")
        print(f"[DR_PREDICT] Confidence: {confidence}%")

        lang = session.get("lang", DEFAULT_LANGUAGE)
        trans = lambda key: get_translation(key, lang)

        if confidence >= 90:
            risk_level = trans("risk.high")
        elif confidence >= 70:
            risk_level = trans("risk.moderate")
        else:
            risk_level = trans("risk.low")

        session["dr_prediction"] = INDEX_TO_CLASS[class_id]
        session["dr_image_name"] = filename
        session["dr_confidence"] = confidence
        session["dr_risk_level"] = risk_level
        analysis_id = str(uuid.uuid4())
        analysis_data = {
            "prediction": session["dr_prediction"],
            "confidence": confidence,
            "risk_level": risk_level,
            "image_name": filename,
            "image_path": path,
        }
        try:
            DR_REPORT_CACHE[analysis_id] = generate_dynamic_medical_report(
                prediction=session["dr_prediction"],
                request_id=analysis_id[:8],
                strict=True,
                lang=lang,
                analysis_data=analysis_data,
                image_path=path,
            )
        except Exception as report_err:
            print(f"[DR_PREDICT] Dynamic report note: {report_err}")
            DR_REPORT_CACHE[analysis_id] = get_severity_report_fallback(
                prediction=session["dr_prediction"],
                confidence=confidence,
                risk_level=risk_level,
            )
        session["dr_analysis_id"] = analysis_id
        print(f"[DR_PREDICT] Stored prediction: {session.get('dr_prediction')}")
        print(f"[DR_PREDICT] Stored image name: {session.get('dr_image_name')}")
        print(f"[DR_PREDICT] Stored confidence: {session.get('dr_confidence')}")
        try:
            print(f"[DR_PREDICT] Stored risk level: {session.get('dr_risk_level')}")
        except Exception:
            pass

        return redirect(url_for("dr_result"))

    except Exception as e:
        import traceback
        print("=" * 80)
        print("PREDICT ERROR")
        print(e)
        traceback.print_exc()
        print("=" * 80)
        return render_template(
            "index.html",
            processing_error=get_translation("common.internal_server_error", session.get("lang", DEFAULT_LANGUAGE)),
        ), 500


@app.route("/dr_result")
def dr_result():
    prediction = session.get("dr_prediction", "Not Available")
    image_name = session.get("dr_image_name")
    confidence = session.get("dr_confidence")
    risk_level = session.get("dr_risk_level")
    image_path = None
    if image_name:
        image_path = url_for("static", filename=f"uploads/{image_name}")
    return render_template(
        "result.html",
        prediction=prediction,
        image_path=image_path,
        confidence=confidence,
        risk_level=risk_level,
        health=None
    )

@app.route('/favicon.ico')
def favicon():
    favicon_path = os.path.join(app.static_folder, 'favicon.ico')
    if os.path.exists(favicon_path):
        return send_file(favicon_path, mimetype='image/vnd.microsoft.icon')
    return '', 204


@app.route("/download_dr_pdf")
def download_dr_pdf():
    import traceback
    try:
        import io
        import re
        import uuid
        from datetime import datetime
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib.colors import HexColor, white, black
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from xml.sax.saxutils import escape

        lang = session.get("lang", DEFAULT_LANGUAGE)
        trans = lambda key: get_translation(key, lang)
        font_name = get_pdf_font(lang)

        prediction = session.get("dr_prediction", "Not Available")
        image_name = session.get("dr_image_name")
        image_path = None
        if image_name:
            image_path = os.path.join(app.root_path, app.config["UPLOAD_FOLDER"], image_name)

        print(f"[DOWNLOAD_DR_PDF] Session lang: {lang}")
        print(f"[DOWNLOAD_DR_PDF] Session prediction: {prediction}")
        print(f"[DOWNLOAD_DR_PDF] Session image name: {image_name}")
        print(f"[DOWNLOAD_DR_PDF] Session image path: {image_path}")
        print(f"[DOWNLOAD_DR_PDF] Session image exists: {os.path.exists(image_path) if image_path else False}")
        report_content = None
        report_id = session.get("dr_analysis_id")
        if report_id:
            report_content = DR_REPORT_CACHE.get(report_id)
        if report_content is None:
            report_content = session.get("dr_analysis")

        print(f"[DOWNLOAD_DR_PDF] Reusing stored report: {bool(report_content)}")
        if not report_content:
            print(f"[DOWNLOAD_DR_PDF] Generating dynamic report for {prediction}...")
            report_content = generate_dynamic_medical_report(
                prediction=prediction,
                lang=lang,
                analysis_data={
                    "prediction": prediction,
                    "confidence": session.get("dr_confidence"),
                    "risk_level": session.get("dr_risk_level"),
                    "image_name": image_name,
                    "image_path": image_path,
                },
                image_path=image_path,
            )
            if report_id:
                DR_REPORT_CACHE[report_id] = report_content

        target_lang = "English" if lang == "en" else ("Marathi" if lang == "mr" else "Hindi")
        fallback_data = get_severity_report_fallback(
            prediction=prediction,
            confidence=session.get("dr_confidence"),
            risk_level=session.get("dr_risk_level"),
        )

        key_alias_map = {
            "Risk Level": ["risk level", "risklevel", "risk"],
            "Clinical Interpretation": ["clinical interpretation", "clinicalinterpretation"],
            "Disease Summary": ["disease summary", "diseasesummary", "summary"],
            "Possible Medical Concerns": ["possible medical concerns", "possiblemedicalconcerns", "medical concerns", "medicalconcerns"],
            "Treatment Guidance": ["treatment guidance", "treatmentguidance", "recommended next steps", "recommendednextsteps"],
            "Lifestyle Recommendations": ["lifestyle recommendations", "lifestylerecommendations", "lifestyle"],
            "Follow-up Advice": ["follow up advice", "followupadvice", "follow up", "followup"],
            "Medical Disclaimer": ["medical disclaimer", "medicaldisclaimer", "disclaimer"],
            "Notes": ["notes", "additional notes", "additionalnotes"],
        }

        def _find_section_value(data_dict, canonical_name):
            if not isinstance(data_dict, dict):
                return None
            if canonical_name in data_dict and data_dict[canonical_name]:
                return data_dict[canonical_name]
            aliases = key_alias_map.get(canonical_name, [])
            norm_canonical = canonical_name.replace(" ", "").replace("_", "").replace("-", "").lower()
            for k, v in data_dict.items():
                norm_k = str(k).replace(" ", "").replace("_", "").replace("-", "").lower()
                if norm_k == norm_canonical or any(a.replace(" ", "").lower() == norm_k for a in aliases):
                    if v:
                        return v
            return None

        def _extract_language_items(val, target_language, fb_items):
            items = []
            if isinstance(val, dict):
                # 1. Target language
                for lk, lv in val.items():
                    if str(lk).strip().lower() == target_language.lower():
                        if isinstance(lv, list):
                            items = [str(x).strip() for x in lv if str(x).strip()]
                        elif isinstance(lv, str) and lv.strip():
                            items = [lv.strip()]
                        break
                # 2. English fallback if target empty
                if not items:
                    for lk, lv in val.items():
                        if str(lk).strip().lower() == "english":
                            if isinstance(lv, list):
                                items = [str(x).strip() for x in lv if str(x).strip()]
                            elif isinstance(lv, str) and lv.strip():
                                items = [lv.strip()]
                            break
                # 3. Any non-empty language
                if not items:
                    for lk, lv in val.items():
                        if isinstance(lv, list) and any(str(x).strip() for x in lv):
                            items = [str(x).strip() for x in lv if str(x).strip()]
                            break
                        elif isinstance(lv, str) and lv.strip():
                            items = [lv.strip()]
                            break
            elif isinstance(val, list):
                items = [str(x).strip() for x in val if str(x).strip()]
            elif isinstance(val, str) and val.strip():
                items = [val.strip()]

            # 4. Fallback if still empty
            if not items and fb_items:
                if isinstance(fb_items, dict):
                    fb_list = fb_items.get(target_language) or fb_items.get("English") or []
                    items = [str(x).strip() for x in fb_list if str(x).strip()]
                elif isinstance(fb_items, list):
                    items = [str(x).strip() for x in fb_items if str(x).strip()]

            return items

        # 8 required sections
        sections = [
            ("Clinical Interpretation", trans('pdf.dr.clinical_interpretation'), "clinical_interpretation"),
            ("Disease Summary", trans('pdf.dr.disease_summary'), "disease_summary"),
            ("Possible Medical Concerns", trans('pdf.dr.possible_medical_concerns'), "possible_medical_concerns"),
            ("Treatment Guidance", trans('pdf.dr.treatment_guidance'), "treatment_guidance"),
            ("Lifestyle Recommendations", trans('pdf.dr.lifestyle_recommendations'), "lifestyle_recommendations"),
            ("Follow-up Advice", trans('pdf.dr.follow_up_advice'), "follow_up_advice"),
            ("Medical Disclaimer", trans('pdf.dr.medical_disclaimer'), "medical_disclaimer"),
            ("Notes", trans('pdf.dr.notes') if trans('pdf.dr.notes') != 'pdf.dr.notes' else ('टीपा' if lang == 'mr' else ('टिप्पणियाँ' if lang == 'hi' else 'Notes')), "notes"),
        ]

        # Extract items for each section in the active language
        report_data = {}
        for canonical_name, title, field_name in sections:
            raw_val = _find_section_value(report_content, canonical_name)
            fb_val = fallback_data.get(canonical_name, {})
            items = _extract_language_items(raw_val, target_lang, fb_val)
            report_data[field_name] = items

        # Verify all 8 fields are NON-EMPTY before building PDF
        print("=" * 80)
        print(f"[PDF_PRE_VERIFICATION] Language: {lang} ({target_lang}) | Prediction: {prediction}")
        all_fields_valid = True
        for canonical_name, title, field_name in sections:
            item_count = len(report_data.get(field_name, []))
            first_preview = (report_data[field_name][0][:55] + "...") if item_count > 0 else "EMPTY!"
            status_tag = "[OK]" if item_count > 0 else "[FAIL]"
            print(f"  {status_tag} {field_name} ({canonical_name}): {item_count} items -> \"{first_preview}\"")
            if item_count == 0:
                all_fields_valid = False
        print(f"[PDF_PRE_VERIFICATION] All 8 sections verified non-empty: {all_fields_valid}")
        print("=" * 80)

        # Extract Risk Level
        risk_raw = _find_section_value(report_content, "Risk Level")
        risk_items = _extract_language_items(risk_raw, target_lang, fallback_data.get("Risk Level", {}))
        risk_text = " • ".join(risk_items) if risk_items else str(session.get("dr_risk_level", prediction))

        report_date = datetime.now().strftime("%d-%m-%Y")
        report_time = datetime.now().strftime("%H:%M:%S")
        report_id = str(uuid.uuid4())[:12].upper()

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.6 * inch,
            leftMargin=0.6 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=22,
            textColor=HexColor('#1a3d5c'),
            spaceAfter=8,
            alignment=TA_CENTER,
            fontName=font_name
        )

        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=13,
            textColor=HexColor('#2c5aa0'),
            spaceAfter=8,
            spaceBefore=6,
            fontName=font_name
        )

        section_header_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading3'],
            fontSize=11,
            textColor=HexColor('#1e40af'),
            spaceAfter=4,
            spaceBefore=6,
            fontName=font_name,
        )

        risk_style = ParagraphStyle(
            'RiskStyle',
            parent=styles['Heading3'],
            fontSize=11,
            textColor=HexColor('#b91c1c') if any(x in risk_text.lower() for x in ['high', 'तीव्र', 'उच्च']) else (HexColor('#d97706') if any(x in risk_text.lower() for x in ['mod', 'मध्यम']) else HexColor('#15803d')),
            spaceAfter=6,
            spaceBefore=4,
            fontName=font_name,
        )

        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=9.5,
            textColor=HexColor('#333333'),
            spaceAfter=4,
            leading=13.5,
            alignment=TA_LEFT,
            fontName=font_name,
        )

        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=8.5,
            textColor=HexColor('#666666'),
            spaceAfter=3,
            alignment=TA_CENTER,
            fontName=font_name,
        )

        story = []
        story.append(Paragraph(trans('pdf.dr.title'), title_style))
        story.append(Spacer(1, 4))
        story.append(Paragraph(trans('pdf.dr.subtitle'), heading_style))
        story.append(Spacer(1, 8))

        meta_data = [
            [trans('pdf.dr.report_date'), report_date, trans('pdf.dr.report_id'), report_id],
            [trans('pdf.dr.prediction'), prediction, trans('pdf.dr.analysis_time'), report_time],
        ]
        meta_table = Table(meta_data, colWidths=[1.5*inch, 1.8*inch, 1.5*inch, 1.5*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f0f4f8')),
            ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#1a3d5c')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), font_name),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 1, HexColor('#cccccc')),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 10))

        if image_path and os.path.exists(image_path):
            try:
                img = Image(image_path)
                img._restrictSize(4.5 * inch, 3.2 * inch)
                story.append(img)
                story.append(Spacer(1, 8))
            except Exception as img_e:
                print(f"[DOWNLOAD_DR_PDF] Image embed notice: {img_e}")
                story.append(Paragraph(trans('pdf.dr.image_error'), normal_style))
                story.append(Spacer(1, 6))

        if risk_text:
            story.append(Paragraph(f"{trans('risk.level') if trans('risk.level') != 'risk.level' else 'Risk Level'}: {escape(risk_text)}", risk_style))
            story.append(Spacer(1, 4))

        # Render all 8 sections with actual content
        for canonical_name, title, field_name in sections:
            items = report_data.get(field_name, [])
            story.append(Paragraph(title, section_header_style))
            story.append(Spacer(1, 3))
            for item in items:
                story.append(Paragraph(f'• {escape(item)}', normal_style))
            story.append(Spacer(1, 6))

        story.append(Spacer(1, 6))
        story.append(Paragraph(trans('pdf.dr.generated_by'), footer_style))
        story.append(Paragraph(trans('pdf.dr.report_label'), footer_style))
        story.append(Paragraph(trans('pdf.dr.version'), footer_style))

        print("[DOWNLOAD_DR_PDF] Building PDF document...")
        doc.build(story)
        buffer.seek(0)
        print(f"[DOWNLOAD_DR_PDF] PDF built successfully, size: {buffer.getbuffer().nbytes} bytes")

        return send_file(
            buffer,
            as_attachment=True,
            download_name="DR_Analysis_Report.pdf",
            mimetype="application/pdf"
        )

    except Exception as e:
        print("=" * 80)
        print("DOWNLOAD PDF ERROR")
        print(e)
        traceback.print_exc()
        print("=" * 80)
        raise

@app.route("/live_health")
def live_health():
    return render_template("live_health.html")

@app.route("/get_sensor_data")
@app.route("/live_sensor")
def get_sensor_data():
    data = {
        "heart_rate": sensor_data.get("heart_rate", "--"),
        "spo2": sensor_data.get("spo2", "--"),
        "status": sensor_data.get("status", "DISCONNECTED"),
        "port": sensor_data.get("port")
    }
    response = jsonify(data)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Accel-Expires'] = '0'
    return response

@app.route("/health_analysis")
def health_analysis():
    hr = sensor_data.get("heart_rate")
    spo2 = sensor_data.get("spo2")
    lang = session.get("lang", DEFAULT_LANGUAGE)
    return jsonify(analyze_health(hr, spo2, lang))

@app.route("/pcod")
def pcod():
    return render_template("pcod.html")

@app.route("/pcod_predict", methods=["POST"])
def pcod_predict():
    try:
        age = int(request.form.get("age", 0))
        gender = request.form.get("gender", "")
        bmi = float(request.form.get("bmi", 0))
        fatigue = int(request.form.get("fatigue", 0))
        sleep = int(request.form.get("sleep", 0))
        stress = int(request.form.get("stress", 0))
        activity = request.form.get("activity", "moderate")
        diet = request.form.get("diet", "balanced")
        family = request.form.get("family_history", "no")

        trans = get_translator()
        score = 0
        score += 2 if bmi >= 25 else 0
        score += fatigue + stress
        score += 2 if family == "yes" else 0
        score += 1 if activity == "low" else 0
        score += 1 if diet == "junk" else 0

        risk_code = "high_pcod" if score >= 10 else "moderate_pcod" if score >= 6 else "low_pcod"
        risk = trans(f"risk.{risk_code}")

        advice = [
            trans('advice.pcod_bmi'),
            trans('advice.pcod_diet'),
            trans('advice.pcod_exercise'),
            trans('advice.pcod_sleep'),
            trans('advice.pcod_stress'),
            trans('advice.pcod_consult')
        ]
        from flask import session
        session["pcod_age"] = age
        session["pcod_gender"] = gender
        session["pcod_bmi"] = bmi
        session["pcod_fatigue"] = fatigue
        session["pcod_sleep"] = sleep
        session["pcod_stress"] = stress
        session["pcod_activity"] = activity
        session["pcod_diet"] = diet
        session["pcod_family"] = family
        session["pcod_risk_code"] = risk_code
        session["pcod_risk"] = risk
        session["pcod_advice"] = advice
        return render_template("pcod_result.html", risk=risk, advice=advice)

    except Exception as e:
        return f"PCOD Error: {e}"

@app.route("/diabetes")
def diabetes():
    return render_template("diabetes.html")

@app.route("/diabetes_predict", methods=["POST"])
def diabetes_predict():
    try:
        age = int(request.form.get("age", 0))
        gender = request.form.get("gender", "")
        height = float(request.form.get("height", 0))
        weight = float(request.form.get("weight", 0))
        bmi = float(request.form.get("bmi", 0))
        family = request.form.get("family", "no")
        urination = request.form.get("urination", "no")
        thirst = request.form.get("thirst", "no")
        fatigue = request.form.get("fatigue", "no")
        activity = request.form.get("activity", "moderate")
        diet = request.form.get("diet", "no")
        bp = request.form.get("bp", "no")

        trans = get_translator()
        score = (
            (2 if bmi >= 25 else 0) +
            (2 if family == "yes" else 0) +
            (1 if urination == "yes" else 0) +
            (1 if thirst == "yes" else 0) +
            (1 if fatigue == "yes" else 0) +
            (1 if activity == "low" else 0) +
            (1 if diet == "yes" else 0) +
            (1 if bp == "yes" else 0)
        )

        risk_code = "high_diabetes" if score >= 7 else "moderate_diabetes" if score >= 4 else "low_diabetes"
        risk = trans(f"risk.{risk_code}")

        advice = [
            trans('advice.diabetes_weight'),
            trans('advice.diabetes_diet'),
            trans('advice.diabetes_exercise'),
            trans('advice.diabetes_monitor'),
            trans('advice.diabetes_consult')
        ]

        session["diabetes_age"] = age
        session["diabetes_gender"] = gender
        session["diabetes_height"] = height
        session["diabetes_weight"] = weight
        session["diabetes_bmi"] = bmi
        session["diabetes_family"] = family
        session["diabetes_urination"] = urination
        session["diabetes_thirst"] = thirst
        session["diabetes_fatigue"] = fatigue
        session["diabetes_activity"] = activity
        session["diabetes_diet"] = diet
        session["diabetes_bp"] = bp
        session["diabetes_risk_code"] = risk_code
        session["diabetes_risk"] = risk
        session["diabetes_advice"] = advice

        return render_template("diabetes_result.html", risk=risk, advice=advice)

    except Exception as e:
        return f"DIABETES Error: {e}"

@app.route("/download_diabetes_pdf")
def download_diabetes_pdf():
    from flask import session
    import io
    import uuid
    from datetime import datetime
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

    lang = session.get("lang", DEFAULT_LANGUAGE)
    trans = lambda key: get_translation(key, lang)
    font_name = get_pdf_font(lang)

    report_date = datetime.now().strftime("%d-%m-%Y")
    report_time = datetime.now().strftime("%H:%M:%S")
    report_id = str(uuid.uuid4())[:12].upper()

    age = session.get("diabetes_age", "N/A")
    gender = session.get("diabetes_gender", "N/A")
    height = session.get("diabetes_height", "N/A")
    weight = session.get("diabetes_weight", "N/A")
    bmi = session.get("diabetes_bmi", "N/A")
    family = session.get("diabetes_family", "N/A")
    risk = session.get("diabetes_risk", "Not Available")
    risk_code = session.get("diabetes_risk_code", "low_diabetes")
    advice = session.get("diabetes_advice", [])

    if risk_code == "high_diabetes":
        concerns = [
            trans('pdf.diabetes.concern_high_blood_sugar'),
            trans('pdf.diabetes.concern_insulin_resistance'),
            trans('pdf.diabetes.concern_cardiovascular_risk'),
            trans('pdf.diabetes.concern_kidney_complications'),
            trans('pdf.diabetes.concern_vision_problems')
        ]
        risk_color = HexColor('#DC2626')
        risk_display = trans('risk.high_diabetes')
    elif risk_code == "moderate_diabetes":
        concerns = [
            trans('pdf.diabetes.concern_prediabetes_risk'),
            trans('pdf.diabetes.concern_weight_management'),
            trans('pdf.diabetes.concern_lifestyle_improvement')
        ]
        risk_color = HexColor('#F59E0B')
        risk_display = trans('risk.moderate_diabetes')
    else:
        concerns = [
            trans('pdf.diabetes.concern_no_significant_risk'),
            trans('pdf.diabetes.concern_continue_healthy_lifestyle')
        ]
        risk_color = HexColor('#10B981')
        risk_display = trans('risk.low_diabetes')

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.65 * inch,
        leftMargin=0.65 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontName=font_name,
        fontSize=24,
        textColor=HexColor('#2F3B8A'),
        alignment=TA_CENTER,
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'ReportSubtitle',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=13,
        textColor=HexColor('#4A4A4A'),
        alignment=TA_CENTER,
        spaceAfter=14
    )
    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName=font_name,
        fontSize=11,
        textColor=white,
        backColor=HexColor('#3C4DA0'),
        leftIndent=6,
        rightIndent=6,
        spaceBefore=12,
        spaceAfter=8,
        leading=14
    )
    normal_style = ParagraphStyle(
        'Normal',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=13,
        textColor=HexColor('#333333')
    )
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        leading=12,
        textColor=HexColor('#555555'),
        backColor=HexColor('#F3F4FB'),
        leftIndent=6,
        rightIndent=6,
        spaceAfter=6
    )
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=9,
        textColor=HexColor('#777777'),
        alignment=TA_CENTER
    )

    story = []
    story.append(Spacer(1, 10))
    story.append(Paragraph(trans('pdf.diabetes.title'), title_style))
    story.append(Paragraph(trans('pdf.diabetes.subtitle'), subtitle_style))
    story.append(Spacer(1, 8))

    meta_table = Table(
        [
            [trans('pdf.diabetes.report_date'), report_date, trans('pdf.diabetes.report_time'), report_time],
            [trans('pdf.diabetes.report_id'), report_id, '', '']
        ],
        colWidths=[1.35 * inch, 2.15 * inch, 1.2 * inch, 1.2 * inch]
    )
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#444444')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph(trans('pdf.diabetes.patient_details'), section_header_style))

    patient_table = Table(
        [
            ['Age', str(age), 'Gender', str(gender)],
            ['Height (cm)', str(height), 'Weight (kg)', str(weight)],
            ['BMI', str(bmi), 'Family History', str(family)]
        ],
        colWidths=[1.25 * inch, 2.25 * inch, 1.25 * inch, 1.25 * inch]
    )
    patient_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#2E3B60')),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#F1F5FF')),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#FFFFFF')),
        ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#D9DBE3')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, HexColor('#D9DBE3')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6)
    ]))
    story.append(patient_table)
    story.append(Spacer(1, 14))
    story.append(Paragraph(trans('pdf.diabetes.assessment_result'), section_header_style))
    story.append(Spacer(1, 6))

    risk_table = Table(
        [[Paragraph(trans('pdf.diabetes.risk_level'), ParagraphStyle('Label', parent=styles['Normal'], fontName=font_name, fontSize=10, textColor=HexColor('#ffffff'))),
          Paragraph(risk_display, ParagraphStyle('RiskText', parent=styles['Normal'], fontName=font_name, fontSize=11, textColor=white, alignment=TA_CENTER))]],
        colWidths=[1.4 * inch, 4.35 * inch]
    )
    risk_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name),
        ('BACKGROUND', (0, 0), (0, 0), HexColor('#3C4DA0')),
        ('BACKGROUND', (1, 0), (1, 0), risk_color),
        ('TEXTCOLOR', (0, 0), (-1, -1), white),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, white),
        ('BOX', (0, 0), (-1, -1), 0.5, HexColor('#D9DBE3'))
    ]))
    story.append(risk_table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(trans('pdf.diabetes.assessment_summary'), normal_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph(trans('pdf.diabetes.possible_concerns'), section_header_style))
    story.append(Spacer(1, 4))

    for concern in concerns:
        story.append(Paragraph(f'• {concern}', normal_style))

    story.append(Spacer(1, 12))
    story.append(Paragraph(trans('pdf.diabetes.personalized_recommendations'), section_header_style))
    story.append(Spacer(1, 4))

    if advice:
        for item in advice:
            story.append(Paragraph(f'• {item}', normal_style))
    else:
        story.append(Paragraph(f'• {trans("pdf.diabetes.no_recommendations")}', normal_style))

    story.append(Spacer(1, 12))
    story.append(Paragraph(trans('pdf.diabetes.medical_disclaimer'), section_header_style))
    story.append(Spacer(1, 4))
    disclaimer_text = trans('pdf.diabetes.disclaimer')
    story.append(Paragraph(disclaimer_text, disclaimer_style))
    story.append(Spacer(1, 16))
    story.append(Paragraph(trans('pdf.diabetes.generated_by'), footer_style))
    story.append(Paragraph(trans('pdf.diabetes.report_label'), footer_style))
    story.append(Paragraph(trans('pdf.diabetes.version'), footer_style))

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="Diabetes_Report.pdf",
        mimetype="application/pdf"
    )

@app.route("/migraine")
def migraine():
    return render_template("migraine.html")

@app.route("/migraine_predict", methods=["POST"])
def migraine_predict():
    try:
        score = 0
        risks = []

        # Collect form data
        age = request.form.get("age", "N/A")
        gender = request.form.get("gender", "N/A")
        family = request.form.get("family", "no")
        frequency = request.form.get("frequency", "0")
        duration = request.form.get("duration", "0")
        intensity = request.form.get("intensity", "0")
        unilateral = request.form.get("unilateral", "no")
        throbbing = request.form.get("throbbing", "no")
        nausea = request.form.get("nausea", "no")
        light = request.form.get("light", "no")
        sound = request.form.get("sound", "no")
        aura = request.form.get("aura", "no")
        dizziness = request.form.get("dizziness", "no")
        activity_worse = request.form.get("activity_worse", "no")
        sleep = request.form.get("sleep", "0")
        insomnia = request.form.get("insomnia", "no")
        stress = request.form.get("stress", "0")
        meals = request.form.get("meals", "no")
        caffeine = request.form.get("caffeine", "low")
        hormonal = request.form.get("hormonal", "no")

        yes_fields = [
            "family","unilateral","throbbing","nausea","light",
            "sound","aura","dizziness","activity_worse",
            "insomnia","meals","hormonal"
        ]

        for field in yes_fields:
            if request.form.get(field) == "yes":
                score += 1
                risks.append(field.replace("_"," ").title())

        def safe_int(val):
            try: return int(val)
            except: return 0

        intensity_int = safe_int(intensity)
        stress_int = safe_int(stress)
        sleep_int = safe_int(sleep)

        score += intensity_int // 3 + stress_int // 3

        if sleep_int and sleep_int < 6:
            score += 1
            risks.append("Low Sleep Duration")

        risk_code = "high_migraine" if score >= 10 else "moderate_migraine" if score >= 6 else "low_migraine"
        risk = trans(f"risk.{risk_code}")

        advice = [
            trans('advice.migraine_sleep'),
            trans('advice.migraine_stress'),
            trans('advice.migraine_triggers'),
            trans('advice.migraine_hydrate'),
            trans('advice.migraine_caffeine'),
            trans('advice.migraine_consult')
        ]

        risk_label_map = {
            'family': trans('migraine.field_family_history'),
            'unilateral': trans('migraine.field_unilateral'),
            'throbbing': trans('migraine.field_throbbing'),
            'nausea': trans('migraine.field_nausea'),
            'light': trans('migraine.field_light'),
            'sound': trans('migraine.field_sound'),
            'aura': trans('migraine.field_aura'),
            'dizziness': trans('migraine.field_dizziness'),
            'activity_worse': trans('migraine.field_activity_worse'),
            'insomnia': trans('migraine.field_insomnia'),
            'meals': trans('migraine.field_meals'),
            'hormonal': trans('migraine.field_hormonal')
        }

        risks = [risk_label_map.get(field, field.replace('_', ' ').title()) for field in risks]

        # Store data in session
        session["migraine_age"] = age
        session["migraine_gender"] = gender
        session["migraine_family"] = family
        session["migraine_frequency"] = frequency
        session["migraine_duration"] = duration
        session["migraine_intensity"] = intensity
        session["migraine_unilateral"] = unilateral
        session["migraine_throbbing"] = throbbing
        session["migraine_nausea"] = nausea
        session["migraine_light"] = light
        session["migraine_sound"] = sound
        session["migraine_aura"] = aura
        session["migraine_dizziness"] = dizziness
        session["migraine_activity_worse"] = activity_worse
        session["migraine_sleep"] = sleep
        session["migraine_insomnia"] = insomnia
        session["migraine_stress"] = stress
        session["migraine_meals"] = meals
        session["migraine_caffeine"] = caffeine
        session["migraine_hormonal"] = hormonal
        session["migraine_risk_code"] = risk_code
        session["migraine_risk"] = risk
        session["migraine_risks"] = risks
        session["migraine_advice"] = advice

        return render_template("migraine_result.html", risk=risk, risks=risks, advice=advice)

    except Exception as e:
        return render_template(
            "migraine_result.html",
            risk="Unable to calculate risk",
            risks=["Please fill all fields correctly"],
            advice=["Try submitting the form again", "Contact support if issue persists"]
        )
    

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html")

@app.route("/chat-health", methods=["GET"])
def chat_health():
    """Debug endpoint to verify chatbot route is available"""
    return jsonify({"status": "ok", "message": "Chat endpoint is available"}), 200

@app.route("/download_pcod_pdf")
def download_pcod_pdf():
    from flask import session
    import io
    from datetime import datetime
    import uuid
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    
    lang = session.get("lang", DEFAULT_LANGUAGE)
    trans = lambda key: get_translation(key, lang)
    font_name = get_pdf_font(lang)

    # Get session data
    risk = session.get("pcod_risk", "Not Available")
    age = session.get("pcod_age", "N/A")
    gender = session.get("pcod_gender", "N/A")
    bmi = session.get("pcod_bmi", "N/A")
    fatigue = session.get("pcod_fatigue", "N/A")
    sleep = session.get("pcod_sleep", "N/A")
    stress = session.get("pcod_stress", "N/A")
    activity = session.get("pcod_activity", "N/A")
    diet = session.get("pcod_diet", "N/A")
    family = session.get("pcod_family", "N/A")
    advice = session.get("pcod_advice", [])
    
    # Generate report metadata
    report_date = datetime.now().strftime("%d-%m-%Y")
    report_time = datetime.now().strftime("%H:%M:%S")
    report_id = str(uuid.uuid4())[:12].upper()
    
    # Create PDF buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    # Define styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#003D7A'),
        spaceAfter=3,
        alignment=TA_CENTER,
        fontName=font_name
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#003D7A'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName=font_name
    )
    
    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=white,
        backColor=HexColor('#003D7A'),
        spaceAfter=12,
        spaceBefore=6,
        leftIndent=6,
        fontName=font_name
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#333333'),
        spaceAfter=6,
        leading=12,
        fontName=font_name
    )
    
    # Determine risk colors and concerns
    risk_code = session.get('pcod_risk_code', 'low_pcod')
    if risk_code == 'high_pcod':
        risk_color = HexColor('#DC2626')
        concerns = [
            trans('pdf.pcod.concern_hormonal'),
            trans('pdf.pcod.concern_metabolic'),
            trans('pdf.pcod.concern_weight_gain'),
            trans('pdf.pcod.concern_insulin_resistance'),
            trans('pdf.pcod.concern_fertility_issues')
        ]
    elif risk_code == 'moderate_pcod':
        risk_color = HexColor('#F59E0B')
        concerns = [
            trans('pdf.pcod.concern_hormonal'),
            trans('pdf.pcod.concern_metabolic_changes'),
            trans('pdf.pcod.concern_irregular_periods')
        ]
    else:
        risk_color = HexColor('#10B981')
        concerns = [
            trans('pdf.pcod.concern_no_significant_concerns'),
            trans('pdf.pcod.concern_continue_healthy_lifestyle')
        ]
    
    # Build story
    story = []
    
    # Header
    story.append(Spacer(1, 12))
    story.append(Paragraph(trans('pdf.pcod.title'), title_style))
    story.append(Paragraph(trans('pdf.pcod.subtitle'), subtitle_style))
    story.append(Spacer(1, 6))
    
    # Separator
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Report Info
    report_info_data = [
        [trans('pdf.pcod.report_date'), report_date],
        [trans('pdf.pcod.report_time'), report_time],
        [trans('pdf.pcod.report_id'), report_id]
    ]
    report_info_table = Table(report_info_data, colWidths=[2*inch, 2*inch])
    report_info_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), font_name, 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#333333')),
        ('GRID', (0, 0), (-1, -1), 1, HexColor('#E5E7EB')),
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#F3F4F6')),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(report_info_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Patient Details Section
    story.append(Paragraph(trans('pdf.pcod.patient_details'), section_header_style))
    
    def _translate_activity(value):
        try:
            return trans(f'pcod.activity_{value}')
        except Exception:
            return str(value).title()

    def _translate_diet(value):
        try:
            return trans(f'pcod.diet_{value}')
        except Exception:
            return str(value).title()

    def _translate_gender(value):
        if isinstance(value, str):
            lower = value.lower()
            if lower == 'male':
                return trans('common.male')
            if lower == 'female':
                return trans('common.female')
        return str(value).title()

    patient_data = [
        [trans('pdf.pcod.field_age'), str(age)],
        [trans('pdf.pcod.field_gender'), _translate_gender(gender)],
        [trans('pdf.pcod.field_bmi'), str(bmi)],
        [trans('pdf.pcod.field_fatigue'), str(fatigue)],
        [trans('pdf.pcod.field_sleep'), str(sleep)],
        [trans('pdf.pcod.field_stress'), str(stress)],
        [trans('pdf.pcod.field_activity'), _translate_activity(activity)],
        [trans('pdf.pcod.field_diet'), _translate_diet(diet)],
        [trans('pdf.pcod.field_family_history'), trans('common.yes') if family == 'yes' else trans('common.no')]
    ]
    
    patient_table = Table(patient_data, colWidths=[2.5*inch, 2*inch])
    patient_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), font_name, 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#333333')),
        ('GRID', (0, 0), (-1, -1), 1, HexColor('#E5E7EB')),
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#F3F4F6')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#F9FAFB')]),
    ]))
    story.append(patient_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Assessment Result Section
    story.append(Paragraph(trans('pdf.pcod.assessment_result'), section_header_style))
    story.append(Spacer(1, 6))
    
    risk_style = ParagraphStyle(
        'RiskLevel',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=white,
        backColor=risk_color,
        spaceAfter=12,
        spaceBefore=6,
        leftIndent=8,
        rightIndent=8,
        fontName=font_name,
        alignment=TA_LEFT
    )
    story.append(Paragraph(f"{trans('pdf.pcod.risk_level')}: {risk}", risk_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(trans('pdf.pcod.assessment_summary'), normal_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Possible Health Concerns Section
    story.append(Paragraph(trans('pdf.pcod.possible_concerns'), section_header_style))
    story.append(Spacer(1, 6))
    
    for concern in concerns:
        concern_para = Paragraph(f"• {concern}", normal_style)
        story.append(concern_para)
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Personalized Recommendations Section
    story.append(Paragraph(trans('pdf.pcod.personalized_recommendations'), section_header_style))
    story.append(Spacer(1, 6))
    
    for rec in advice:
        rec_para = Paragraph(f"• {rec}", normal_style)
        story.append(rec_para)
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Medical Disclaimer Section
    story.append(Paragraph(trans('pdf.pcod.medical_disclaimer'), section_header_style))
    story.append(Spacer(1, 6))
    
    disclaimer_text = trans('pdf.pcod.disclaimer')
    
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#666666'),
        spaceAfter=6,
        leading=11,
        alignment=TA_JUSTIFY,
        backColor=HexColor('#FEF3C7'),
        leftIndent=8,
        rightIndent=8,
        topPadding=8,
        bottomPadding=8
    )
    story.append(Paragraph(disclaimer_text, disclaimer_style))
    story.append(Spacer(1, 20))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#999999'),
        spaceAfter=3,
        alignment=TA_CENTER
    )
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph(trans('pdf.pcod.generated_by'), footer_style))
    story.append(Paragraph(trans('pdf.pcod.report_label'), footer_style))
    story.append(Paragraph(trans('pdf.pcod.version'), footer_style))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name="PCOD_Report.pdf",
        mimetype="application/pdf"
    )

@app.route("/download_migraine_pdf")
def download_migraine_pdf():
    from flask import session
    import io
    from datetime import datetime
    import uuid
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    
    lang = session.get("lang", DEFAULT_LANGUAGE)
    trans = lambda key: get_translation(key, lang)
    font_name = get_pdf_font(lang)

    # Get session data
    risk = session.get("migraine_risk", "Not Available")
    risk_code = session.get("migraine_risk_code", "low_migraine")
    age = session.get("migraine_age", "N/A")
    gender = session.get("migraine_gender", "N/A")
    family = session.get("migraine_family", "N/A")
    frequency = session.get("migraine_frequency", "N/A")
    duration = session.get("migraine_duration", "N/A")
    intensity = session.get("migraine_intensity", "N/A")
    unilateral = session.get("migraine_unilateral", "N/A")
    throbbing = session.get("migraine_throbbing", "N/A")
    nausea = session.get("migraine_nausea", "N/A")
    light = session.get("migraine_light", "N/A")
    sound = session.get("migraine_sound", "N/A")
    aura = session.get("migraine_aura", "N/A")
    dizziness = session.get("migraine_dizziness", "N/A")
    activity_worse = session.get("migraine_activity_worse", "N/A")
    sleep = session.get("migraine_sleep", "N/A")
    insomnia = session.get("migraine_insomnia", "N/A")
    stress = session.get("migraine_stress", "N/A")
    meals = session.get("migraine_meals", "N/A")
    caffeine = session.get("migraine_caffeine", "N/A")
    hormonal = session.get("migraine_hormonal", "N/A")
    triggers = session.get("migraine_risks", [])
    advice = session.get("migraine_advice", [])
    
    # Generate report metadata
    report_date = datetime.now().strftime("%d-%m-%Y")
    report_time = datetime.now().strftime("%H:%M:%S")
    report_id = str(uuid.uuid4())[:12].upper()
    
    # Create PDF buffer
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.5*inch,
        leftMargin=0.5*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )
    
    # Define styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#6B3FA0'),
        spaceAfter=3,
        alignment=TA_CENTER,
        fontName=font_name
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#6B3FA0'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName=font_name
    )
    
    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontSize=12,
        textColor=white,
        backColor=HexColor('#6B3FA0'),
        spaceAfter=12,
        spaceBefore=6,
        leftIndent=6,
        fontName=font_name
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#333333'),
        spaceAfter=6,
        leading=12,
        fontName=font_name
    )
    
    # Determine risk colors and recommendations
    if risk_code == 'high_migraine':
        risk_color = HexColor('#DC2626')
        risk_display = trans('risk.high_migraine')
    elif risk_code == 'moderate_migraine':
        risk_color = HexColor('#F59E0B')
        risk_display = trans('risk.moderate_migraine')
    else:
        risk_color = HexColor('#10B981')
        risk_display = trans('risk.low_migraine')
    
    # Build story
    story = []
    
    # Header
    story.append(Spacer(1, 12))
    story.append(Paragraph(trans('pdf.migraine.title'), title_style))
    story.append(Paragraph(trans('pdf.migraine.subtitle'), subtitle_style))
    story.append(Spacer(1, 6))
    
    # Separator
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Report Info
    report_info_data = [
        [trans('pdf.migraine.report_date'), report_date],
        [trans('pdf.migraine.report_time'), report_time],
        [trans('pdf.migraine.report_id'), report_id]
    ]
    report_info_table = Table(report_info_data, colWidths=[2*inch, 2*inch])
    report_info_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), font_name, 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#333333')),
        ('GRID', (0, 0), (-1, -1), 1, HexColor('#E5E7EB')),
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#F3F4F6')),
        ('PADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(report_info_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Patient Details Section
    story.append(Paragraph(trans('pdf.migraine.patient_details'), section_header_style))
    
    patient_data = [
        [trans('pdf.migraine.field_age'), str(age)],
        [trans('pdf.migraine.field_gender'), str(gender).title()],
        [trans('pdf.migraine.field_family_history'), trans('common.yes') if family == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_frequency'), str(frequency)],
        [trans('pdf.migraine.field_duration'), str(duration)],
        [trans('pdf.migraine.field_intensity'), str(intensity)],
        [trans('pdf.migraine.field_unilateral'), trans('common.yes') if unilateral == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_throbbing'), trans('common.yes') if throbbing == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_nausea'), trans('common.yes') if nausea == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_light'), trans('common.yes') if light == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_sound'), trans('common.yes') if sound == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_aura'), trans('common.yes') if aura == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_dizziness'), trans('common.yes') if dizziness == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_activity_worse'), trans('common.yes') if activity_worse == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_sleep'), str(sleep)],
        [trans('pdf.migraine.field_insomnia'), trans('common.yes') if insomnia == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_stress'), str(stress)],
        [trans('pdf.migraine.field_meals'), trans('common.yes') if meals == 'yes' else trans('common.no')],
        [trans('pdf.migraine.field_caffeine'), str(caffeine).title()],
        [trans('pdf.migraine.field_hormonal'), trans('common.yes') if hormonal == 'yes' else trans('common.no')],
    ]
    
    patient_table = Table(patient_data, colWidths=[2.5*inch, 2*inch])
    patient_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), font_name, 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#333333')),
        ('GRID', (0, 0), (-1, -1), 1, HexColor('#E5E7EB')),
        ('BACKGROUND', (0, 0), (0, -1), HexColor('#F3F4F6')),
        ('PADDING', (0, 0), (-1, -1), 8),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#F9FAFB')]),
    ]))
    story.append(patient_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Assessment Result Section
    story.append(Paragraph(trans('pdf.migraine.assessment_result'), section_header_style))
    story.append(Spacer(1, 6))
    
    risk_style = ParagraphStyle(
        'RiskLevel',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=white,
        backColor=risk_color,
        spaceAfter=12,
        spaceBefore=6,
        leftIndent=8,
        rightIndent=8,
        fontName=font_name,
        alignment=TA_LEFT
    )
    story.append(Paragraph(f"{trans('pdf.migraine.risk_level')}: {risk_display}", risk_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(trans('pdf.migraine.assessment_summary'), normal_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Identified Triggers Section
    story.append(Paragraph(trans('pdf.migraine.identified_triggers'), section_header_style))
    story.append(Spacer(1, 6))
    
    if triggers:
        for trigger in triggers:
            trigger_para = Paragraph(f"• {trigger}", normal_style)
            story.append(trigger_para)
    else:
        story.append(Paragraph(f"• {trans('live_health.no_risks')}", normal_style))
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Personalized Recommendations Section
    story.append(Paragraph(trans('pdf.migraine.personalized_recommendations'), section_header_style))
    story.append(Spacer(1, 6))
    
    for rec in advice:
        rec_para = Paragraph(f"• {rec}", normal_style)
        story.append(rec_para)
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Medical Disclaimer Section
    story.append(Paragraph(trans('pdf.migraine.medical_disclaimer'), section_header_style))
    story.append(Spacer(1, 6))
    
    disclaimer_text = trans('pdf.migraine.disclaimer')
    
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#666666'),
        spaceAfter=6,
        leading=11,
        alignment=TA_JUSTIFY,
        backColor=HexColor('#F3F0FF'),
        leftIndent=8,
        rightIndent=8,
        topPadding=8,
        bottomPadding=8
    )
    story.append(Paragraph(disclaimer_text, disclaimer_style))
    story.append(Spacer(1, 20))
    
    # Footer
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#999999'),
        spaceAfter=3,
        alignment=TA_CENTER
    )
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph(trans('pdf.migraine.generated_by'), footer_style))
    story.append(Paragraph(trans('pdf.migraine.report_label'), footer_style))
    story.append(Paragraph(trans('pdf.migraine.version'), footer_style))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name="Migraine_Report.pdf",
        mimetype="application/pdf"
    )

@app.route("/chat", methods=["POST"])
def chat():
    try:
        # Get JSON data
        data = request.get_json(force=True, silent=True)
        
        if data is None:
            return jsonify({"reply": get_translation('chatbot.invalid_question', session.get('lang', DEFAULT_LANGUAGE))}), 400
        
        user_msg = data.get("message", "").strip()
        
        if not user_msg:
            return jsonify({"reply": get_translation('chatbot.invalid_question', session.get('lang', DEFAULT_LANGUAGE))}), 400
        
        # Call chatbot with selected language to enforce response language
        try:
            lang = session.get('lang', DEFAULT_LANGUAGE)
            reply = chatbot_response(user_msg, lang=lang)
            return jsonify({"reply": reply}), 200
        except Exception as bot_error:
            import traceback
            error_msg = f"{type(bot_error).__name__}: {str(bot_error)}\n{traceback.format_exc()}"
            return jsonify({"reply": f"{get_translation('chatbot.error', lang)} {error_msg}"}), 500
            
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        return jsonify({"reply": f"ERROR: {error_msg}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)