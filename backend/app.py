from fastapi import FastAPI

app = FastAPI(title="RiskLab AI")

@app.get("/")
def home():
    return {"status": "RiskLab AI online 🚀"}
