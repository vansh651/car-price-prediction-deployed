# car-price-prediction

Flask web app + REST API that predicts the resale price of a used car (Random Forest model),
packaged with Docker, Kubernetes, GitHub Actions CI/CD, Prometheus and Grafana.

## Endpoints

| Path | Purpose |
|------|---------|
| `/` | Web form |
| `/predict` (POST) | Form or JSON prediction |
| `/model-info` | Feature importance |
| `/health` | Health check (503 if the model failed to load) |
| `/metrics` | Prometheus metrics |

JSON example:

    curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" \
      -d '{"present_price":5.5,"kms_driven":30000,"fuel_type":"petrol","seller_type":"dealer","transmission":"manual","owner":0,"year":2018}'

## Run it

Docker only:

    docker build -t car-price-prediction:latest .
    docker run -p 8000:8000 car-price-prediction:latest

App + Prometheus + Grafana (Docker Compose):

    docker compose up --build
    # app        http://localhost:8000
    # Prometheus http://localhost:9090
    # Grafana    http://localhost:3000   (admin / admin) -> Dashboards -> Car Price

Generate some traffic so the dashboard has data:

    python scripts/generate_traffic.py

Kubernetes (minikube):

    minikube start
    docker build -t car-price-prediction:latest .
    minikube image load car-price-prediction:latest
    kubectl apply -f k8s/namespace.yaml
    kubectl apply -f k8s/
    kubectl -n car-price create configmap grafana-dashboards --from-file=monitoring/grafana/dashboards/car-price.json
    kubectl apply -f k8s/monitoring/
    kubectl -n car-price port-forward svc/car-price-api 8000:80
    kubectl -n car-price port-forward svc/prometheus 9090:9090
    kubectl -n car-price port-forward svc/grafana 3000:3000

## CI/CD

`.github/workflows/ci-cd.yml` runs the tests on every push/PR, and on `main` builds the Docker
image and pushes it to `ghcr.io/<owner>/<repo>`.

## Tests

    pip install -r requirements-dev.txt
    pytest -q tests

## Streamlit version

`streamlit_app.py` is a separate UI and is not part of the container:

    pip install -r requirements-streamlit.txt
    streamlit run streamlit_app.py
