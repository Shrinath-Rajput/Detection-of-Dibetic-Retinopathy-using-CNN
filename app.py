from flask import Flask, request, render_template
from src.pipeline.predict_pipeline import PredictPipeline

app = Flask(__name__)

@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        img = request.files["image"]
        img_path = "temp.jpg"
        img.save(img_path)

        pred = PredictPipeline().predict(img_path)
        return render_template("result.html", result=str(pred))

    return render_template("chatbot.html")

if __name__ == "__main__":
    app.run(debug=True)
