from fastapi import FastAPI
from app.routes.prs import router as prs_router
from app.routes.projects import router as projects_router
from dotenv import load_dotenv, find_dotenv
import os

load_dotenv(find_dotenv(),override=True)

os.environ["GITHUB_TOKEN"]=os.getenv("GITHUB_TOKEN")

app = FastAPI(title="PR API", version="1.0.0")
app.include_router(prs_router)
app.include_router(projects_router)

# Optional: health check
@app.get("/health")
def health():
    return {"ok": True}
