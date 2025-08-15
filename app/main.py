from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.routes.prs import router as prs_router
from app.routes.files import router as files_router
from app.routes.review import router as review_router
from dotenv import load_dotenv,find_dotenv
import os
import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

load_dotenv(find_dotenv(),override=True)

os.environ["GITHUB_TOKEN"]=os.getenv("GITHUB_TOKEN")
print(os.environ["GITHUB_TOKEN"])

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Custom HTTP logging middleware
class HTTPLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        logger.info(f"Request: {request.method} {request.url.path} - Query: {dict(request.query_params)}")
        
        # Process request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Log response
        logger.info(f"Response: {response.status_code} - Duration: {duration:.3f}s")
        
        return response

app = FastAPI(title="PR API", version="1.0.0")

# Add middleware in order
app.add_middleware(HTTPLoggingMiddleware)  # Custom HTTP logging
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(prs_router)
app.include_router(files_router)  # NEW
app.include_router(review_router) 


# Optional: health check
@app.get("/health")
def health():
    return {"ok": True}
