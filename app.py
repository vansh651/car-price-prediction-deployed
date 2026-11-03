import os
import time

import joblib
import numpy as np
from flask import Flask, Response, g, jsonify, render_template, request
from flask_cors import CORS
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# ------------------------------------------------------------------
# Prometheus metrics
# ------------------------------------------------------------------
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)
PREDICTIONS = Counter("predictions_total", "Successful price predictions")
PREDICTION_ERRORS = Counter("prediction_errors_total", "Failed price predictions")
PREDICTED_PRICE = Histogram(
    "predicted_price_lakhs",
    "Distribution of predicted resale prices (INR lakhs)",
    buckets=(1, 2, 3, 5, 8, 12, 20, 35, 50),
)
MODEL_LOADED = Gauge("model_loaded", "1 if model.sav loaded correctly, else 0")

# Paths we do not want to count as "real" traffic
UNTRACKED_PATHS = {"/metrics", "/health"}

# ------------------------------------------------------------------
# Load the trained model
# ------------------------------------------------------------------
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.sav")
try:
    model = joblib.load(MODEL_PATH)
    model_ok = True
    print("Model loaded successfully!")
except Exception as e:
    print(f"Error loading model: {e}")
    # Create a simple backup model in case the saved model isn't available
    from sklearn.ensemble import RandomForestRegressor

    model = RandomForestRegressor(n_estimators=100, random_state=0)
    model_ok = False

MODEL_LOADED.set(1 if model_ok else 0)


@app.before_request
def _start_timer():
    g.start_time = time.perf_counter()


@app.after_request
def _record_metrics(response):
    if request.path not in UNTRACKED_PATHS and hasattr(g, "start_time"):
        # Use the route pattern (not the raw URL) so label values stay few
        endpoint = request.url_rule.rule if request.url_rule else "unmatched"
        REQUEST_LATENCY.labels(request.method, endpoint).observe(
            time.perf_counter() - g.start_time
        )
        REQUEST_COUNT.labels(request.method, endpoint, response.status_code).inc()
    return response


@app.route("/health")
def health():
    """Liveness/readiness probe target. 503 if the model did not load."""
    if model_ok:
        return jsonify({"status": "ok", "model_loaded": True})
    return jsonify({"status": "degraded", "model_loaded": False}), 503


@app.route("/metrics")
def metrics():
    """Prometheus scrapes this endpoint."""
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    try:
        # Get data from form
        if request.form:
            present_price = float(request.form.get("present_price", 0))
            kms_driven = int(request.form.get("kms_driven", 0))
            fuel_type = request.form.get("fuel_type", "").upper()
            seller_type = request.form.get("seller_type", "").upper()
            transmission = request.form.get("transmission", "").upper()
            owner = int(request.form.get("owner", 0))
            year = int(request.form.get("year", 2020))
        # Get data from JSON (API requests)
        else:
            data = request.get_json()
            present_price = float(data.get("present_price", 0))
            kms_driven = int(data.get("kms_driven", 0))
            fuel_type = data.get("fuel_type", "").upper()
            seller_type = data.get("seller_type", "").upper()
            transmission = data.get("transmission", "").upper()
            owner = int(data.get("owner", 0))
            year = int(data.get("year", 2020))

        # Convert categorical inputs to numeric
        fuel_dict = {"PETROL": 0, "DIESEL": 1, "CNG": 2}
        seller_dict = {"DEALER": 0, "INDIVIDUAL": 1}
        transmission_dict = {"MANUAL": 0, "AUTOMATIC": 1}

        fuel_type_num = fuel_dict.get(fuel_type, 0)
        seller_type_num = seller_dict.get(seller_type, 0)
        transmission_num = transmission_dict.get(transmission, 0)
        age = 2025 - year

        # Create features array for prediction
        features = np.array(
            [
                [
                    present_price,
                    kms_driven,
                    fuel_type_num,
                    seller_type_num,
                    transmission_num,
                    owner,
                    age,
                ]
            ]
        )

        # Make prediction
        predicted_price = float(model.predict(features)[0])
        PREDICTIONS.inc()
        PREDICTED_PRICE.observe(predicted_price)

        # Return prediction based on request type
        if request.form:
            return render_template(
                "index.html",
                prediction=round(predicted_price, 2),
                form_data={
                    "present_price": present_price,
                    "kms_driven": kms_driven,
                    "fuel_type": fuel_type,
                    "seller_type": seller_type,
                    "transmission": transmission,
                    "owner": owner,
                    "year": year,
                },
            )
        else:
            return jsonify(
                {
                    "success": True,
                    "predicted_price": round(predicted_price, 2),
                    "message": f"Predicted Resale Price: INR{predicted_price:.2f} lakhs",
                }
            )

    except Exception as e:
        PREDICTION_ERRORS.inc()
        if request.form:
            return render_template("index.html", error=str(e))
        else:
            # 400 (instead of 200) so failed API calls show up in the error-rate panel
            return (
                jsonify(
                    {
                        "success": False,
                        "error": str(e),
                        "message": "Failed to make prediction. Please check your input data.",
                    }
                ),
                400,
            )


@app.route("/model-info", methods=["GET"])
def model_info():
    """Return information about the model"""
    if hasattr(model, "feature_importances_"):
        feature_importance = model.feature_importances_.tolist()
        features = [
            "Present Price",
            "Kms Driven",
            "Fuel Type",
            "Seller Type",
            "Transmission",
            "Owner",
            "Age",
        ]

        importance_pairs = list(zip(features, feature_importance))
        importance_pairs.sort(key=lambda x: x[1], reverse=True)

        return render_template(
            "model_info.html",
            feature_importance=importance_pairs,
            model_type="Random Forest Regressor",
        )
    else:
        return render_template(
            "model_info.html",
            model_type="Machine Learning Model",
            message="Feature importance not available for this model",
        )


if __name__ == "__main__":
    # Local development only. In Docker/Kubernetes, gunicorn runs the app instead.
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
