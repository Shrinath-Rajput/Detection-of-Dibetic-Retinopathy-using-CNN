# app.py
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
from werkzeug.utils import secure_filename

from src.services.sensor_service import sensor_data, start_sensor_thread
from src.chatbot.bot import chatbot_response, generate_dynamic_medical_report

app = Flask(__name__)
app.secret_key = "clinsense_ai_secret"

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config['JSON_SORT_KEYS'] = False

import gdown

MODEL_PATH = "dr_cnn_model.h5"

if not os.path.exists(MODEL_PATH):
    url = "https://drive.google.com/uc?id=1r-jqC-X67DQo2yf_ozOr2LiGLVMbNL_J"
    gdown.download(url, MODEL_PATH, quiet=False)

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

def analyze_health(hr, spo2):
    hr_status = "UNKNOWN"
    spo2_status = "UNKNOWN"
    risk = []
    advice = []

    try:
        if hr != "--":
            hr = int(hr)
        else:
            hr = None
    except:
        hr = None

    try:
        if spo2 != "--":
            spo2 = int(spo2)
        else:
            spo2 = None
    except:
        spo2 = None

    if hr is not None:
        if hr < 60:
            hr_status = "LOW"
            risk.append("Low heart rate (Bradycardia)")
        elif hr > 100:
            hr_status = "HIGH"
            risk.append("High heart rate (Stress/Hypertension)")
        else:
            hr_status = "NORMAL"
    else:
        hr_status = "WAITING"

    if spo2 is not None:
        if spo2 < 95:
            spo2_status = "LOW"
            risk.append("Low oxygen level (Breathing issue)")
        else:
            spo2_status = "NORMAL"
    else:
        spo2_status = "WAITING"

    if not risk:
        advice = [
            "All vitals are normal. Maintain healthy lifestyle.",
            "Continue monitoring your health regularly.",
            "Stay active and exercise regularly.",
            "Ensure proper sleep and rest."
        ]
    else:
        advice = [
            "Take proper rest",
            "Practice deep breathing",
            "Reduce stress",
            "Drink enough water",
            "Consult doctor if values persist"
        ]

    return {
        "heart_rate_status": hr_status,
        "spo2_status": spo2_status,
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
    file = request.files.get("image")
    if not file or file.filename == "":
        return redirect(url_for("dr_page"))

    path = os.path.join(app.config["UPLOAD_FOLDER"], secure_filename(file.filename))
    file.save(path)

    preds = model.predict(preprocess_image(path))
    class_id = int(np.argmax(preds))

    # store prediction and image path in session for PDF generation
    session["dr_prediction"] = INDEX_TO_CLASS[class_id]
    session["dr_image_path"] = path

    return render_template(
        "result.html",
        prediction=INDEX_TO_CLASS[class_id],
        image_path=path
    )


@app.route("/download_dr_pdf")
def download_dr_pdf():
    import io
    import uuid
    from datetime import datetime
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    # Get stored prediction and image
    prediction = session.get("dr_prediction", "Not Available")
    image_path = session.get("dr_image_path")

    try:
        report_content = generate_dynamic_medical_report(
            prediction=prediction,
            request_id=str(uuid.uuid4())[:8],
            strict=True,
        )
    except Exception as exc:
        app.logger.exception("Retina AI report generation failed")
        report_content = {
            "Clinical Interpretation": "The AI medical report could not be completed at this moment. Your retinal analysis was received successfully and the report will be generated as soon as the service becomes available again.",
            "Disease Summary": "A temporary service issue prevented the automatic report from being completed. This is an operational notice rather than a medical conclusion.",
            "Possible Medical Concerns": "Please retry the report generation shortly. If you are experiencing symptoms or urgent vision changes, seek prompt ophthalmic care.",
            "Treatment Guidance": "No treatment guidance was generated because the AI report service is temporarily unavailable.",
            "Lifestyle Recommendations": "No lifestyle recommendations were generated because the AI report service is temporarily unavailable.",
            "Follow-up Advice": "Please try again later for a full AI-generated follow-up plan.",
            "Medical Disclaimer": "This notice is intended to keep you informed about a temporary service interruption. It is not a medical diagnosis. Please consult a qualified ophthalmologist for clinical guidance."
        }

    if not report_content:
        report_content = {
            "Clinical Interpretation": "The AI medical report could not be completed at this moment. Please try again shortly.",
            "Disease Summary": "The system is currently unavailable for report generation.",
            "Possible Medical Concerns": "Please retry the report generation later.",
            "Treatment Guidance": "No treatment guidance was generated because the service is temporarily unavailable.",
            "Lifestyle Recommendations": "No lifestyle guidance was generated because the service is temporarily unavailable.",
            "Follow-up Advice": "Please try again later for a full AI-generated follow-up plan.",
            "Medical Disclaimer": "This notice is operational and not a medical diagnosis. Please consult a qualified ophthalmologist for clinical advice."
        }


    # PDF metadata
    report_date = datetime.now().strftime("%d-%m-%Y")
    report_time = datetime.now().strftime("%H:%M:%S")
    report_id = str(uuid.uuid4())[:12].upper()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.6 * inch,
        leftMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ReportTitle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=22, textColor=HexColor('#0B3D91'), alignment=TA_CENTER)
    subtitle_style = ParagraphStyle('ReportSubtitle', parent=styles['Heading2'], fontName='Helvetica', fontSize=12, textColor=HexColor('#333333'), alignment=TA_CENTER)
    section_header_style = ParagraphStyle('SectionHeader', parent=styles['Heading2'], fontName='Helvetica-Bold', fontSize=11, textColor=white, backColor=HexColor('#0B61B1'), leftIndent=6, rightIndent=6, spaceBefore=10, spaceAfter=6)
    normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=13, textColor=HexColor('#333333'))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontName='Helvetica', fontSize=9, textColor=HexColor('#777777'), alignment=TA_CENTER)

    story = []
    story.append(Spacer(1, 8))
    story.append(Paragraph('CareSense AI', title_style))
    story.append(Paragraph('Diabetic Retinopathy Analysis Report', subtitle_style))
    story.append(Spacer(1, 8))

    meta_table = Table([
        ['Report Date:', report_date, 'Report Time:', report_time],
        ['Unique Report ID:', report_id, '', '']
    ], colWidths=[1.2 * inch, 2.0 * inch, 1.2 * inch, 1.2 * inch])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#444444')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph('PATIENT EYE EXAMINATION', section_header_style))
    story.append(Spacer(1, 8))

    # Add image if available
    if image_path and os.path.exists(image_path):
        try:
            img = Image(image_path)
            img._restrictSize(5.5 * inch, 4.0 * inch)
            story.append(img)
            story.append(Spacer(1, 8))
        except Exception:
            story.append(Paragraph('Retinal image could not be embedded.', normal_style))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph('No retinal image available.', normal_style))
        story.append(Spacer(1, 8))

    story.append(Paragraph('AI DIAGNOSIS', section_header_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(prediction, normal_style))
    story.append(Spacer(1, 8))

    def _split_items(s):
        if not s:
            return []
        if '\n' in s:
            parts = [p.strip() for p in s.splitlines() if p.strip()]
            return parts
        if '•' in s:
            parts = [p.strip() for p in s.split('•') if p.strip()]
            return parts
        if ';' in s:
            parts = [p.strip() for p in s.split(';') if p.strip()]
            return parts
        if s.count(',') >= 2:
            parts = [p.strip() for p in s.split(',') if p.strip()]
            return parts
        return [s.strip()]

    sections = [
        ("Clinical Interpretation", "CLINICAL INTERPRETATION"),
        ("Disease Summary", "DISEASE SUMMARY"),
        ("Possible Medical Concerns", "POSSIBLE MEDICAL CONCERNS"),
        ("Treatment Guidance", "TREATMENT GUIDANCE"),
        ("Lifestyle Recommendations", "LIFESTYLE RECOMMENDATIONS"),
        ("Follow-up Advice", "FOLLOW-UP ADVICE"),
        ("Medical Disclaimer", "MEDICAL DISCLAIMER"),
    ]

    for key, title in sections:
        value = report_content.get(key, '')
        story.append(Paragraph(title, section_header_style))
        story.append(Spacer(1, 6))
        items = _split_items(value)
        if items:
            for item in items:
                story.append(Paragraph(f'• {item}', normal_style))
        else:
            story.append(Paragraph('• No additional information was generated for this section.', normal_style))
        story.append(Spacer(1, 8))

    story.append(Paragraph('Generated by CareSense AI', footer_style))
    story.append(Paragraph('Professional Eye Disease Analysis Report', footer_style))
    story.append(Paragraph('Version 1.0', footer_style))

    doc.build(story)
    buffer.seek(0)

    # Ensure we return exact bytes with Content-Length to avoid browser partial-download issues
    pdf_bytes = buffer.getvalue()
    from flask import Response
    headers = {
        'Content-Type': 'application/pdf',
        'Content-Disposition': 'attachment; filename="Retina_Report.pdf"',
        'Content-Length': str(len(pdf_bytes)),
    }
    return Response(pdf_bytes, headers=headers)

@app.route("/live_health")
def live_health():
    return render_template("live_health.html")

@app.route("/get_sensor_data")
def get_sensor_data():
    data = {
        "heart_rate": sensor_data.get("heart_rate", "--"),
        "spo2": sensor_data.get("spo2", "--"),
        "status": sensor_data.get("status", "DISCONNECTED")
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
    return jsonify(analyze_health(hr, spo2))

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

        score = 0
        score += 2 if bmi >= 25 else 0
        score += fatigue + stress
        score += 2 if family == "yes" else 0
        score += 1 if activity == "low" else 0
        score += 1 if diet == "junk" else 0

        risk = "HIGH PCOD RISK" if score >= 10 else "MODERATE PCOD RISK" if score >= 6 else "LOW PCOD RISK"

        advice = [
            "Maintain healthy BMI",
            "Follow balanced diet",
            "Exercise regularly",
            "Improve sleep quality",
            "Reduce stress",
            "Consult gynecologist if symptoms persist"
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

        risk = "HIGH DIABETES RISK" if score >= 7 else "MODERATE DIABETES RISK" if score >= 4 else "LOW DIABETES RISK"

        advice = [
            "Maintain healthy body weight",
            "Follow low sugar balanced diet",
            "Exercise regularly",
            "Monitor blood glucose levels",
            "Consult physician if symptoms persist"
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
    advice = session.get("diabetes_advice", [])

    if "HIGH" in risk:
        concerns = [
            "High Blood Sugar Risk",
            "Insulin Resistance",
            "Cardiovascular Risk",
            "Kidney Complications",
            "Vision Problems"
        ]
        risk_color = HexColor('#DC2626')
    elif "MODERATE" in risk:
        concerns = [
            "Prediabetes Risk",
            "Weight Management Required",
            "Lifestyle Improvement Needed"
        ]
        risk_color = HexColor('#F59E0B')
    else:
        concerns = [
            "No significant diabetes risk detected",
            "Continue healthy lifestyle"
        ]
        risk_color = HexColor('#10B981')

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
        fontName='Helvetica-Bold',
        fontSize=24,
        textColor=HexColor('#2F3B8A'),
        alignment=TA_CENTER,
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'ReportSubtitle',
        parent=styles['Heading2'],
        fontName='Helvetica',
        fontSize=13,
        textColor=HexColor('#4A4A4A'),
        alignment=TA_CENTER,
        spaceAfter=14
    )
    section_header_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
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
        fontName='Helvetica',
        fontSize=10,
        leading=13,
        textColor=HexColor('#333333')
    )
    disclaimer_style = ParagraphStyle(
        'Disclaimer',
        parent=styles['Normal'],
        fontName='Helvetica',
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
        fontName='Helvetica',
        fontSize=9,
        textColor=HexColor('#777777'),
        alignment=TA_CENTER
    )

    story = []
    story.append(Spacer(1, 10))
    story.append(Paragraph('CareSense AI', title_style))
    story.append(Paragraph('Diabetes Risk Assessment Report', subtitle_style))
    story.append(Spacer(1, 8))

    meta_table = Table(
        [
            ['Report Date:', report_date, 'Report Time:', report_time],
            ['Unique Report ID:', report_id, '', '']
        ],
        colWidths=[1.35 * inch, 2.15 * inch, 1.2 * inch, 1.2 * inch]
    )
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (-1, -1), HexColor('#444444')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 2)
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 12))
    story.append(Paragraph('PATIENT DETAILS', section_header_style))

    patient_table = Table(
        [
            ['Age', str(age), 'Gender', str(gender)],
            ['Height (cm)', str(height), 'Weight (kg)', str(weight)],
            ['BMI', str(bmi), 'Family History', str(family)]
        ],
        colWidths=[1.25 * inch, 2.25 * inch, 1.25 * inch, 1.25 * inch]
    )
    patient_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
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
    story.append(Paragraph('ASSESSMENT RESULT', section_header_style))
    story.append(Spacer(1, 6))

    risk_table = Table(
        [[Paragraph('Risk Level', ParagraphStyle('Label', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10, textColor=HexColor('#ffffff'))),
          Paragraph(risk, ParagraphStyle('RiskText', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=11, textColor=white, alignment=TA_CENTER))]],
        colWidths=[1.4 * inch, 4.35 * inch]
    )
    risk_table.setStyle(TableStyle([
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
    story.append(Paragraph('Assessment based on BMI, fatigue symptoms, activity levels, diet, family history, and blood pressure indicators.', normal_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph('POSSIBLE HEALTH CONCERNS', section_header_style))
    story.append(Spacer(1, 4))

    for concern in concerns:
        story.append(Paragraph(f'• {concern}', normal_style))

    story.append(Spacer(1, 12))
    story.append(Paragraph('PERSONALIZED RECOMMENDATIONS', section_header_style))
    story.append(Spacer(1, 4))

    if advice:
        for item in advice:
            story.append(Paragraph(f'• {item}', normal_style))
    else:
        story.append(Paragraph('• No recommendations available at this time.', normal_style))

    story.append(Spacer(1, 12))
    story.append(Paragraph('MEDICAL DISCLAIMER', section_header_style))
    story.append(Spacer(1, 4))
    disclaimer_text = ("This AI-generated report is intended only for preliminary health awareness and should not replace professional medical diagnosis "
                       "or treatment. Please consult a qualified physician or diabetologist for proper evaluation.")
    story.append(Paragraph(disclaimer_text, disclaimer_style))
    story.append(Spacer(1, 16))
    story.append(Paragraph('Generated by CareSense AI', footer_style))
    story.append(Paragraph('Professional Diabetes Assessment Report', footer_style))
    story.append(Paragraph('Version 1.0', footer_style))

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

        risk = "HIGH MIGRAINE RISK" if score >= 10 else "MODERATE MIGRAINE RISK" if score >= 6 else "LOW MIGRAINE RISK"

        advice = [
            "Maintain regular sleep routine",
            "Reduce stress",
            "Avoid migraine triggers",
            "Stay hydrated",
            "Limit caffeine",
            "Consult neurologist if frequent headaches"
        ]

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
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#003D7A'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
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
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#333333'),
        spaceAfter=6,
        leading=12
    )
    
    # Determine risk colors and concerns
    if "HIGH" in risk:
        risk_color = HexColor('#DC2626')
        concerns = [
            "Hormonal Imbalance",
            "Irregular Menstrual Cycle",
            "Insulin Resistance",
            "Weight Gain",
            "Fertility Issues"
        ]
    elif "MODERATE" in risk:
        risk_color = HexColor('#F59E0B')
        concerns = [
            "Hormonal Imbalance",
            "Lifestyle-related Metabolic Changes",
            "Irregular Periods"
        ]
    else:
        risk_color = HexColor('#10B981')
        concerns = [
            "No significant concerns detected",
            "Continue maintaining a healthy lifestyle"
        ]
    
    # Build story
    story = []
    
    # Header
    story.append(Spacer(1, 12))
    story.append(Paragraph("CareSense AI", title_style))
    story.append(Paragraph("PCOD Risk Assessment Report", subtitle_style))
    story.append(Spacer(1, 6))
    
    # Separator
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Report Info
    report_info_data = [
        ["Report Date", report_date],
        ["Report Time", report_time],
        ["Report ID", report_id]
    ]
    report_info_table = Table(report_info_data, colWidths=[2*inch, 2*inch])
    report_info_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
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
    story.append(Paragraph("PATIENT DETAILS", section_header_style))
    
    patient_data = [
        ["Age", str(age)],
        ["Gender", str(gender)],
        ["BMI", str(bmi)],
        ["Fatigue Level (1-10)", str(fatigue)],
        ["Sleep Quality (1-10)", str(sleep)],
        ["Stress Level (1-10)", str(stress)],
        ["Activity Level", str(activity).title()],
        ["Diet Type", str(diet).title()],
        ["Family History", "Yes" if family == "yes" else "No"]
    ]
    
    patient_table = Table(patient_data, colWidths=[2.5*inch, 2*inch])
    patient_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
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
    story.append(Paragraph("ASSESSMENT RESULT", section_header_style))
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
        fontName='Helvetica-Bold',
        alignment=TA_LEFT
    )
    story.append(Paragraph(f"Risk Level: {risk}", risk_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Assessment based on BMI, fatigue, sleep quality, stress level, activity level, diet type, and family history.", normal_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Possible Health Concerns Section
    story.append(Paragraph("POSSIBLE HEALTH CONCERNS", section_header_style))
    story.append(Spacer(1, 6))
    
    for concern in concerns:
        concern_para = Paragraph(f"• {concern}", normal_style)
        story.append(concern_para)
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Personalized Recommendations Section
    story.append(Paragraph("PERSONALIZED RECOMMENDATIONS", section_header_style))
    story.append(Spacer(1, 6))
    
    for rec in advice:
        rec_para = Paragraph(f"• {rec}", normal_style)
        story.append(rec_para)
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Medical Disclaimer Section
    story.append(Paragraph("MEDICAL DISCLAIMER", section_header_style))
    story.append(Spacer(1, 6))
    
    disclaimer_text = """This report is AI-generated by CareSense AI and is intended only for preliminary health awareness. It should not replace professional medical diagnosis or treatment. Please consult a qualified gynecologist or endocrinologist for medical advice, diagnosis, or treatment recommendations."""
    
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
    story.append(Paragraph("Generated by CareSense AI", footer_style))
    story.append(Paragraph("Professional Medical Assessment Report", footer_style))
    story.append(Paragraph("Version 1.0", footer_style))
    
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
    
    # Get session data
    risk = session.get("migraine_risk", "Not Available")
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
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#6B3FA0'),
        spaceAfter=12,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
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
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#333333'),
        spaceAfter=6,
        leading=12
    )
    
    # Determine risk colors and recommendations
    if "HIGH" in risk:
        risk_color = HexColor('#DC2626')
        risk_display = "HIGH MIGRAINE RISK"
    elif "MODERATE" in risk:
        risk_color = HexColor('#F59E0B')
        risk_display = "MODERATE MIGRAINE RISK"
    else:
        risk_color = HexColor('#10B981')
        risk_display = "LOW MIGRAINE RISK"
    
    # Build story
    story = []
    
    # Header
    story.append(Spacer(1, 12))
    story.append(Paragraph("CareSense AI", title_style))
    story.append(Paragraph("Migraine Risk Assessment Report", subtitle_style))
    story.append(Spacer(1, 6))
    
    # Separator
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Report Info
    report_info_data = [
        ["Report Date", report_date],
        ["Report Time", report_time],
        ["Report ID", report_id]
    ]
    report_info_table = Table(report_info_data, colWidths=[2*inch, 2*inch])
    report_info_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 10),
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
    story.append(Paragraph("PATIENT DETAILS", section_header_style))
    
    patient_data = [
        ["Age", str(age)],
        ["Gender", str(gender).title()],
        ["Family History", "Yes" if family == "yes" else "No"],
        ["Frequency (per month)", str(frequency)],
        ["Duration (hours)", str(duration)],
        ["Intensity (1-10)", str(intensity)],
        ["One-sided Pain", "Yes" if unilateral == "yes" else "No"],
        ["Throbbing Pain", "Yes" if throbbing == "yes" else "No"],
        ["Nausea", "Yes" if nausea == "yes" else "No"],
        ["Light Sensitivity", "Yes" if light == "yes" else "No"],
        ["Sound Sensitivity", "Yes" if sound == "yes" else "No"],
        ["Aura Symptoms", "Yes" if aura == "yes" else "No"],
        ["Dizziness", "Yes" if dizziness == "yes" else "No"],
        ["Activity Worsens Pain", "Yes" if activity_worse == "yes" else "No"],
        ["Sleep Hours (per night)", str(sleep)],
        ["Insomnia", "Yes" if insomnia == "yes" else "No"],
        ["Stress Level (1-10)", str(stress)],
        ["Skipped Meals", "Yes" if meals == "yes" else "No"],
        ["Caffeine Intake", str(caffeine).title()],
        ["Hormonal Trigger", "Yes" if hormonal == "yes" else "No"],
    ]
    
    patient_table = Table(patient_data, colWidths=[2.5*inch, 2*inch])
    patient_table.setStyle(TableStyle([
        ('FONT', (0, 0), (-1, -1), 'Helvetica', 9),
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
    story.append(Paragraph("ASSESSMENT RESULT", section_header_style))
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
        fontName='Helvetica-Bold',
        alignment=TA_LEFT
    )
    story.append(Paragraph(f"Risk Level: {risk_display}", risk_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Assessment based on migraine symptoms, triggers, family history, lifestyle factors, and environmental sensitivities.", normal_style))
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Identified Triggers Section
    story.append(Paragraph("IDENTIFIED TRIGGERS / SYMPTOMS", section_header_style))
    story.append(Spacer(1, 6))
    
    if triggers:
        for trigger in triggers:
            trigger_para = Paragraph(f"• {trigger}", normal_style)
            story.append(trigger_para)
    else:
        story.append(Paragraph("• No significant triggers identified", normal_style))
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Personalized Recommendations Section
    story.append(Paragraph("PERSONALIZED RECOMMENDATIONS", section_header_style))
    story.append(Spacer(1, 6))
    
    for rec in advice:
        rec_para = Paragraph(f"• {rec}", normal_style)
        story.append(rec_para)
    
    story.append(Spacer(1, 12))
    story.append(Paragraph("_" * 80, normal_style))
    story.append(Spacer(1, 12))
    
    # Medical Disclaimer Section
    story.append(Paragraph("MEDICAL DISCLAIMER", section_header_style))
    story.append(Spacer(1, 6))
    
    disclaimer_text = """This AI-generated report is intended only for preliminary health awareness and should not replace professional medical diagnosis or treatment. Please consult a qualified neurologist for proper evaluation."""
    
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
    story.append(Paragraph("Generated by CareSense AI", footer_style))
    story.append(Paragraph("Professional Migraine Assessment Report", footer_style))
    story.append(Paragraph("Version 1.0", footer_style))
    
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
            return jsonify({"reply": "Invalid request format"}), 400
        
        user_msg = data.get("message", "").strip()
        
        if not user_msg:
            return jsonify({"reply": "Please ask a question"}), 400
        
        # Call chatbot
        try:
            reply = chatbot_response(user_msg)
            return jsonify({"reply": reply}), 200
        except Exception as bot_error:
            import traceback
            error_msg = f"{type(bot_error).__name__}: {str(bot_error)}\n{traceback.format_exc()}"
            return jsonify({"reply": f"ERROR: {error_msg}"}), 500
            
    except Exception as e:
        import traceback
        error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        return jsonify({"reply": f"ERROR: {error_msg}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)