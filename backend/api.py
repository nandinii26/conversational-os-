import os
import sys
import time
import logging
import asyncio
from urllib.parse import quote_plus
from pathlib import Path

# Add current directory (backend) to sys.path so sibling module imports resolve properly
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Request, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional
from google import genai
from jose import JWTError, jwt
from passlib.context import CryptContext

# Clean, relative imports (No "backend." prefixes!)
import database
from database import save_chat
from services import summarize
from ppt_gen import generate_slides_content, create_pptx
from config import get_genai_model

logger = logging.getLogger("voice_to_text")


# Load configuration both when running from source and from the packaged desktop
# application.  electron-builder copies .env next to the bundled backend binary.
_backend_dir = Path(__file__).resolve().parent
for _env_file in (_backend_dir / ".env", _backend_dir.parent / ".env"):
    if _env_file.exists():
        load_dotenv(_env_file, override=True)

JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "fallback-secret")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", 1440))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Initializing database...")
    database.execute_query(database.DB_FILE)
    logger.info("Voice-to-text service initialized")
    yield
    print("Application shutting down.")
    logger.info("Voice-to-text service shutting down")


# .env already loaded above

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "null",   # Electron file:// protocol sends origin: null
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-session document state — keyed by session_id.
# Prevents one session's loaded PDF from polluting another session's context.
_session_states: dict[str, dict] = {}

def _get_session_state(session_id: str) -> dict:
    """Return (and lazily create) the isolated state dict for a session."""
    if session_id not in _session_states:
        _session_states[session_id] = {"text": None, "filename": None, "filepath": None}
    return _session_states[session_id]

# Legacy alias kept so the /analyze endpoint (which has no session context) still works
app_state: dict[str, Optional[str]] = _get_session_state("__global__")

try:
    from orchestrator import AgentOrchestrator
except ImportError:
    from orchestrator import AgentOrchestrator

orchestrator = AgentOrchestrator()

llm_client = None
MODEL_NAME = get_genai_model()


def _get_llm_client():
    global llm_client
    if llm_client is not None:
        return llm_client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")

    llm_client = genai.Client(api_key=api_key)
    return llm_client

class AgentRunRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"

@app.post("/agent/run")
async def run_agent(request: AgentRunRequest):
    try:
        session_id = request.session_id or "default"
        state = _get_session_state(session_id)  # isolated per-session state
        # Save user message
        database.save_chat(session_id, "user", request.message)

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, orchestrator.run, request.message, state)
        # Persist updated state back into the session store
        _session_states[session_id] = res["state"]
        database.save_steps(session_id, res["steps"])
        database.save_chat(session_id, "bot", res["result"])
        return {
            "status": "success",
            "result": res["result"],
            "steps": res["steps"],
            "action_metadata": res["action_metadata"],
            "ppt_filename": res.get("ppt_filename"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution error: {str(e)}")

def call_llm(prompt: str) -> str:
    response = _get_llm_client().models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    return (response.text or "").strip()


@app.get("/")
def read_root():
    return {
        "message": "Welcome to the Workspace Assistant API!",
        "status": "Online",
        "docs_url": "/docs"
    }
   
@app.post("/analyze")
async def analyze_document(
    file: Optional[UploadFile] = File(None),
    pdf: Optional[UploadFile] = File(None),
    document: Optional[UploadFile] = File(None),
):
    global app_state
    
    try:
        import fitz

        uploaded_file = file or pdf or document
        if uploaded_file is None:
            raise HTTPException(
                status_code=400,
                detail="No file received. Upload a PDF using field name 'file', 'pdf', or 'document'.",
            )

        if not (uploaded_file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        
        # READ DIRECTLY FROM MEMORY - No temp files saved to disk
        file_bytes = await uploaded_file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        
        extracted_text = ""
        for page in doc:
            extracted_text += str(page.get_text("text"))
            
        # Save to memory
        app_state["text"] = extracted_text
        app_state["filename"] = uploaded_file.filename
        doc.close()

        if not extracted_text.strip():
            raise HTTPException(
                status_code=400,
                detail="PDF loaded, but no readable text was found.",
            )
        safe_filename = uploaded_file.filename or "upload.pdf"
        ppt_filename = f"{os.path.splitext(safe_filename)[0]}.pptx"
        try:
            
            slides_data = generate_slides_content(extracted_text)
            create_pptx(slides_data, ppt_filename)
            app_state["ppt_filename"] = ppt_filename
        except Exception as ppt_err:
            print(f"Error generating PPT on upload: {ppt_err}")
            app_state["ppt_filename"] = None
        # Generate a short summary message for the chat UI
        word_count = len(app_state["text"].split())
        result_message = (
            f"✅ **{uploaded_file.filename}** loaded successfully!\n\n"
            f"📄 {word_count} words extracted across the document."
        )
        if app_state.get("ppt_filename"):
            result_message += f"\n\n📊 PowerPoint presentation generated: `{app_state['ppt_filename']}`"
        else:
            result_message += "\n\n⚠️ PPT generation was skipped (could not extract structured content)."

        return {
            "status": "success",
            "result": result_message,
            "filename": uploaded_file.filename,
            "character_count": len(app_state["text"]),
            "ppt_filename": app_state.get("ppt_filename")
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process PDF: {str(e)}")

from fastapi.responses import FileResponse

@app.get("/download-ppt")
def download_ppt(filename: str):
    """Serve a generated .pptx file for download."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    filepath = os.path.join(static_dir, filename)
    if not os.path.isfile(filepath):
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found.")
    return FileResponse(
        path=filepath,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=filename,
    )

@app.get("/summarize")
def summarize_api(data: dict):

    text = data["text"]

    summary = summarize(text)

    return {
        "summary": summary
    }
    
@app.post("/chat")
def chat_api(data: dict):
    message = data.get("message", "Can you summarize this document?")
    
    # pdf upload check
    document_text = app_state.get("text")
    if not document_text:
        raise HTTPException(
            status_code=400, 
            detail="No document found. Please upload a PDF to /analyze first!"
        )
    
    prompt = f"""
    You are a professional workspace assistant. 
    Answer the user's question using ONLY the provided document text. If the answer is not in the text, say "I cannot find this in the document."
    
    USER QUESTION: {message}
    
    DOCUMENT TEXT:
    ---
         {document_text[:5000]}
    ---
    """
    ai_response = call_llm(prompt)
    return {"question": message, "response": ai_response}

@app.post("/task")
def task_api(data:dict):
    task_description=data.get("description","No description provided")
    if "task_type" not in data or "message" not in data:
        return {"error": "Missing mandatory fields: 'task_type' and 'message' are required."}
    task_type = data.get("task_type")
    user_message = data.get("message")
    ALLOWED_TASKS = ["summarize", "extract_keywords", "action_items"]
    if task_type not in ALLOWED_TASKS:
        return  {"error": f"Unknown task type. Must be one of: {ALLOWED_TASKS}"}
    document_text = app_state.get("text")
    if not document_text:
        return {"error": "No document found. Please upload a PDF to /analyze first!"}
    
    if user_message and len(user_message) > 1000:
        return {"error": "Your task instruction message is too long. Keep it under 1000 characters."}
    try:
        # Step A: Build a context-aware template dynamically
        # Injecting the task instruction and the document text into the prompt
        engineered_prompt = f"""
        You are an advanced workspace agent. Execute the following task strictly using the provided context document.
        
        TASK: {task_type.upper()}
        ADDITIONAL INSTRUCTIONS: {user_message}
        
        CONTEXT DOCUMENT TEXT:
        ---
        {document_text}
        ---
        """
        ai_response_text = call_llm(engineered_prompt)
    except Exception as e:
        return {"error": f"An error occurred while processing the task: {str(e)}"}
    return {"response_data": {
            "status": "success",
            "task_executed": task_type,
            "result": ai_response_text,
            "task_description": task_description
        }
    }
class EmailRequest(BaseModel):
    recipient_name: str
    goal: str
    tone: str = "professional"
    raw_response: str 
@app.post("/email")
def email_api(data: EmailRequest):
    recipient = data.recipient_name
    goal = data.goal
    tone = data.tone

    # PHASE 2: State Checking
    document_text = app_state.get("text")
    if not document_text:
        raise HTTPException(
            status_code=400, 
            detail="No document loaded. Please upload a PDF to /analyze first!"
        )
        
    document_context = document_text[:2000]
    prompt = f"""
You are an expert executive assistant. Draft an email to {recipient}.
    
    GOAL: {goal}
    TONE: {tone}
    
    DOCUMENT CONTEXT:
    ---
    {document_context}
    ---
    
    STRICT OUTPUT FORMATTING:
    You must output your response EXACTLY in this format, with no extra conversation:
    [SUBJECT]
    Write the subject line here
    [BODY]
    Write the email body here
    """
    try:
        raw_response = call_llm(prompt)
        if "[SUBJECT]" in raw_response and "[BODY]" in raw_response:
            # Split the text in half at the "[BODY]" marker
            parts = raw_response.split("[BODY]")
            
            # Clean up the subject half (remove the [SUBJECT] tag and extra spaces)
            subject_line = parts[0].replace("[SUBJECT]", "").strip()
            
            # Clean up the body half
            email_body = parts[1].strip()
        else:
            # Fallback just in case the AI ignores our formatting rules
            subject_line = "Drafted Email based on Document"
            email_body = raw_response.strip()
            
        # Return the beautiful, structured JSON response
        return {
            "status": "success",
            "data": {
                "to": recipient,
                "subject": subject_line,
                "body": email_body
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI Engine Error: {str(e)}")
    
# Combined orchestrator run agent endpoint is defined at the top of api.py
    
@app.get("/chat/history")
def chat_history(session_id: str = "default"):    
    db_history = database.get_chat(session_id)

    formatted_history = []
    for row in db_history:
        formatted_history.append({
            "sender": row[0], 
            "text": row[1]   
        })
        
    return formatted_history
@app.post("/session-list")
def session_list():
    return database.session_list()

@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    """Delete all chat history and logs for a given session."""
    database.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}

@app.get("/session-titles")
def session_titles():
    """
    Returns the first user message for every session in a single DB query.
    Shape: [{ session_id: str, first_message: str }, ...]
    """
    return database.get_session_first_messages()


import uuid
import logging

logger = logging.getLogger("uvicorn")

@app.post("/agent/voice")
async def agent_voice(audio: UploadFile = File(...), session_id: str = "default"):
    state = _get_session_state(session_id)  # isolated per-session state
    if not audio.content_type or not audio.content_type.startswith("audio/"):
        if audio.content_type != "application/octet-stream" and not (audio.filename or "").lower().endswith((".wav", ".webm", ".mp3", ".ogg", ".m4a")):
            raise HTTPException(status_code=400, detail="Uploaded file must be an audio file.")

    steps = ["Step 1: Received audio input recording from UI."]
    audio_bytes = await audio.read()
    os.makedirs("temp", exist_ok=True)
    suffix = Path(audio.filename or "voice.wav").suffix or ".wav"
    temp_filename = f"temp/voice_{uuid.uuid4().hex}{suffix}"

    try:
        # Save temp file
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
        steps.append(f"Step 2: Saved audio to temporary file on disk: {temp_filename}")
        logger.info(f"Saved temp voice recording to: {temp_filename}")

        # Determine MIME type
        mime_type = audio.content_type or "audio/wav"
        if mime_type == "application/octet-stream":
            if suffix == ".webm":
                mime_type = "audio/webm"
            elif suffix in (".m4a", ".mp4"):
                mime_type = "audio/mp4"
            elif suffix == ".aac":
                mime_type = "audio/aac"
            elif suffix == ".mp3":
                mime_type = "audio/mp3"
            else:
                mime_type = "audio/wav"

        # Transcribe using Gemini Files API
        steps.append("Step 3: Transcribing audio recording using Gemini AI...")
        client = _get_llm_client()

        gemini_file = client.files.upload(
            file=Path(temp_filename),
            config=genai.types.UploadFileConfig(mime_type=mime_type)
        )

        # Wait for the file to become ACTIVE before transcribing.
        # Sending a PROCESSING file causes Gemini to hallucinate.
        max_wait = 30  # seconds
        waited = 0
        poll_interval = 1
        gemini_file_name = gemini_file.name
        if not gemini_file_name:
            raise ValueError("Gemini upload did not return a file name")

        while waited < max_wait:
            file_state = client.files.get(name=gemini_file_name)
            state_name = file_state.state.name if file_state.state else None
            if state_name == "ACTIVE":
                break
            if state_name == "FAILED":
                raise ValueError(f"Gemini file processing failed: {gemini_file_name}")
            time.sleep(poll_interval)
            waited += poll_interval
        else:
            raise ValueError("Timed out waiting for Gemini audio file to become ACTIVE")

        # Use a strict transcription-only prompt to prevent hallucination.
        # Instruct the model not to generate anything if the audio is unclear.
        transcription_prompt = (
            "You are a transcription engine. "
            "Listen to the audio and output ONLY the exact words spoken — nothing else. "
            "Do NOT add any commentary, greetings, explanations, or markdown formatting. "
            "Do NOT invent or guess words that were not clearly spoken. "
            "If the audio is silent, inaudible, or contains no speech, output exactly: [EMPTY]"
        )

        response = client.models.generate_content(
            model="gemini-2.0-flash",  # use a model with confirmed audio support
            contents=[
                gemini_file,
                transcription_prompt,
            ]
        )
        raw_transcript = (response.text or "").strip()
        # Treat the explicit empty marker as an empty result
        transcript = "" if raw_transcript == "[EMPTY]" else raw_transcript
        
        # Clean up Gemini file
        try:
            if gemini_file_name:
                client.files.delete(name=gemini_file_name)
        except Exception:
            pass

        steps.append(f"Step 4: Transcribed voice command successfully: '{transcript}'")
        
        if not transcript:
            steps.append("Step 5: Voice command was empty.")
            database.save_chat(session_id, "bot", "I could not hear anything. Please try speaking again.")
            
            # Clean up temp file
            try:
                os.remove(temp_filename)
            except Exception:
                pass
                
            return {
                "status": "success",
                "result": "I could not hear anything. Please try speaking again.",
                "transcribed_text": "",
                "steps": steps,
                "action_metadata": {}
            }

        # Save user message to database
        database.save_chat(session_id, "user", f"[Voice] {transcript}")

        # Run orchestrator
        steps.append(f"Step 5: Directing transcribed command to NLU orchestrator: '{transcript}'")
        result = orchestrator.run(transcript, state)
        _session_states[session_id] = result["state"]
        
        # Save steps and response to DB
        database.save_steps(session_id, result["steps"])
        database.save_chat(session_id, "bot", result["result"])

        # Combine steps
        combined_steps = steps + result["steps"]

        # Clean up temp file
        try:
            os.remove(temp_filename)
        except Exception:
            pass

        return {
            "status": "success",
            "result": result["result"],
            "steps": combined_steps,
            "transcribed_text": transcript,
            "action_metadata": result["action_metadata"]
        }
    except Exception as e:
        logger.error(f"Failed to process voice agent command: {e}")
        # Clean up temp file if exists
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"Voice agent error: {str(e)}")
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

# Detect production (non-localhost) so we can harden the session cookie.
_IS_PRODUCTION = not os.environ.get("OAUTH_REDIRECT_URI", "").startswith("http://localhost")

# SessionMiddleware must use https_only=True on prod so the Secure flag is set,
# otherwise Render's HTTPS proxy drops the cookie on the callback.
app.add_middleware(
    SessionMiddleware,
    secret_key=JWT_SECRET_KEY,
    https_only=_IS_PRODUCTION,
    same_site="lax",
)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

@app.get("/auth/login")
async def auth_login(request: Request):
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI")
    if not redirect_uri:
        raise HTTPException(status_code=500, detail="OAUTH_REDIRECT_URI is not configured")

    # OAuth takes place in the system browser for the desktop build. Remember
    # where to return after Google's callback, rather than sending that user to
    # the hosted web app.
    if request.query_params.get("desktop") == "1":
        request.session["oauth_return_to"] = os.environ.get(
            "DESKTOP_APP_REDIRECT_URI", "docpilot://auth"
        )
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    import traceback
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[auth_callback] authorize_access_token FAILED:\n{tb}")
        error_type = type(e).__name__
        error_msg = str(e)

        # Most common callback failure on hosted environments: lost/blocked
        # session cookie causes state mismatch during token exchange.
        if error_type == "MismatchingStateError":
            human_error = "Google sign-in session expired or state mismatch. Please retry login and allow cookies."
        else:
            human_error = f"Google sign-in failed ({error_type}). Please retry."

        return_to = request.session.pop("oauth_return_to", None)
        if not return_to:
            return_to = os.environ.get(
                "FRONTEND_URL", "https://conversational-os.vercel.app"
            ).rstrip("/")

        separator = "&" if "?" in return_to else "?"
        safe_error = quote_plus(human_error)
        safe_debug = quote_plus(f"{error_type}: {error_msg}")
        return RedirectResponse(
            url=f"{return_to}{separator}oauth_error={safe_error}&oauth_debug={safe_debug}"
        )

    # Modern authlib: userinfo is populated automatically via OIDC when scope includes 'openid'
    user_info = token.get("userinfo")
    if not user_info:
        # Fallback: fetch from userinfo endpoint
        try:
            user_info = await oauth.google.userinfo(token=token)
        except Exception as e:
            logger.error(f"[auth_callback] userinfo fetch failed: {e}")
            user_info = None

    if not user_info:
        raise HTTPException(status_code=400, detail="Failed to obtain user info from Google")

    # Keep session for server-side use
    request.session["user"] = {
        "name": user_info.get("name", ""),
        "email": user_info.get("email", ""),
        "picture": user_info.get("picture", "")
    }

    # Create a JWT token so the frontend can store it
    jwt_token = create_access_token({
        "sub": user_info.get("email", ""),
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", "")
    })

    # Return to desktop app or web frontend
    return_to = request.session.pop("oauth_return_to", None)
    if not return_to:
        return_to = os.environ.get(
            "FRONTEND_URL", "https://conversational-os.vercel.app"
        ).rstrip("/")
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(url=f"{return_to}{separator}token={jwt_token}")

@app.get("/auth/session/me")
async def auth_session_me(request: Request):
    """Check auth via Bearer token (sent in Authorization header)."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
        try:
            payload = jwt.decode(raw_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return {
                "email": payload.get("sub"),
                "name": payload.get("name"),
                "picture": payload.get("picture")
            }
        except JWTError:
            pass
    # Fallback: check session cookie
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user

@app.get("/auth/logout")
async def auth_logout(request: Request):
    request.session.clear()
    return {"status": "logged out"}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(data: dict) -> str:
    payload = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    # JWT `exp` should be a numeric timestamp (int seconds since epoch)
    payload.update({"exp": int(expire.timestamp())})
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return str(email)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


from pydantic import BaseModel

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

@app.post("/auth/register")
def register(data: RegisterRequest):
    hashed = hash_password(data.password)
    try:
        database.create_user(data.email, hashed, data.name)
        return {"status": "registered"}
    except Exception:
        raise HTTPException(status_code=400, detail="Email already registered")

@app.post("/auth/token")
def login(form: OAuth2PasswordRequestForm = Depends()):
    user = database.get_user_by_email(form.username)  # username = email
    if not user or not verify_password(form.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token({"sub": user["email"], "name": user["name"]})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/auth/me")
def auth_me(current_user: str = Depends(get_current_user), token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return {
            "email": payload.get("sub"),
            "name": payload.get("name") or payload.get("sub"),
            "picture": payload.get("picture") or "",
        }
    except JWTError:
        return {"email": current_user, "name": current_user, "picture": ""}


if __name__ == "__main__":
    import uvicorn
  
    uvicorn.run(app, host="127.0.0.1", port=8001)
 


    

  
