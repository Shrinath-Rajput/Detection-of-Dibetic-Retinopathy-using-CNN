##Detection of Dibetic Retinopathy using CNN

#  Clinsense-AI
### AI-Powered Healthcare Assistant for Disease Detection & Live Health Monitoring

Clinsense-AI is an end-to-end **AI Healthcare System** that combines **Deep Learning (CNN)**, **Machine Learning**, **Live Sensor Data**, and an **AI Chatbot** to provide early disease detection, health risk prediction, and preventive medical guidance.

---

##  Key Features

-  CNN-based **Diabetic Retinopathy Detection**
-  **Live Health Monitoring** (Heart Rate & SpO₂)
-  **AI Healthcare Chatbot** (Single Entry Point)
-  **MLflow Experiment Tracking**
-  **MongoDB Integration**
-  **DagsHub Dataset & Version Control**
-  **Flask Web Application**
-  **Docker Ready Deployment**

---

##  Problem Statement

Early detection of diseases like **Diabetic Retinopathy** is critical but often unavailable in rural and underdeveloped regions.  
Continuous health monitoring and preventive medical advice are also limited.

**Clinsense-AI bridges this gap using AI + IoT + Chatbot technology.**

---

##  Complete System Flow


User
↓
AI Healthcare Chatbot
↓
Image Upload / Sensor Data
↓
CNN / ML Models
↓
Disease Detection & Risk Prediction
↓
Preventive Medical Advice


---

##  Core Modules

### 1️ Diabetic Retinopathy Detection (MAIN MODULE)

- User uploads retina image
- Image preprocessing using OpenCV
- CNN model predicts disease stage:

| Classes |
|-------|
| No Diabetic Retinopathy |
| Mild |
| Moderate |
| Severe |
| Proliferative DR |

- Output shown with confidence score

---

### 2️ Live Health Monitoring (IoT)

**Sensor:** MAX30102  

Captured Parameters:
-  Heart Rate (BPM)
-  SpO₂ (%)

---

### 3️⃣ Health Risk Analysis

| Parameter | Normal Range |
|---------|--------------|
| Heart Rate | 60 – 100 BPM |
| SpO₂ | 95 – 100 % |

System identifies:
- What is low / high
- Risk level
- Possible health conditions

 *This is risk prediction, not medical diagnosis.*

---

### 4️⃣ AI Chatbot Preventive Guidance

Chatbot provides:
- Detected disease / risk
- Possible causes
- Preventive actions
- Doctor consultation advice

---

##  Future Enhancements

-  PCOD Detection
-  Hypertension Prediction
-  Cancer Detection (CNN)
-  Mobile App
-  Cloud Deployment

---

##  Tech Stack

### Backend & AI
- Python
- TensorFlow / Keras
- OpenCV
- Scikit-learn

### Web
- Flask
- HTML / CSS / Bootstrap
- Jinja2

### MLOps
- MLflow
- DagsHub

### Database
- MongoDB

### Deployment
- Docker
- Gunicorn

---

##  Project Structure

Clinsense-AI/
│
├── app.py
├── requirements.txt
├── Dockerfile
├── README.md
│
├── src/
│ ├── components/
│ │ ├── data_ingestion.py
│ │ ├── data_transformation.py
│ │ └── model_trainer.py
│ │
│ ├── pipeline/
│ │ └── train_pipeline.py
│ │
│ ├── utils/
│ │ └── preprocess.py
│
├── templates/
├── static/
├── mlruns/
└── logs/

---

##  How to Run Project

## Clone Repository
```bash
git clone https://github.com/Shrinath-Rajput/Detection-of-Dibetic-Retinopathy-using-CNN
cd Clinsense-AI
