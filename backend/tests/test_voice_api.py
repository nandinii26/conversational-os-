import os
import io
import sys
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.api import app

@patch('backend.api.llm_client.files.upload')
@patch('backend.api.llm_client.models.generate_content')
@patch('backend.api.orchestrator.run')
def test_voice_endpoint(mock_orchestrator_run, mock_generate_content, mock_upload):
    # 1. Mock Gemini Files upload
    mock_file_obj = MagicMock()
    mock_file_obj.name = "files/mock-voice-file-id"
    mock_upload.return_value = mock_file_obj
    
    # 2. Mock Gemini content generation (transcription)
    mock_response = MagicMock()
    mock_response.text = "search for resume"
    mock_generate_content.return_value = mock_response
    
    # 3. Mock Orchestrator run
    mock_orchestrator_run.return_value = {
        "status": "success",
        "result": "Here are the files I found matching 'resume': Nandini_Srivastava_Resume.pdf",
        "steps": ["Step 6: Executing file search...", "Step 7: Found Nandini_Srivastava_Resume.pdf"],
        "action_metadata": {},
        "state": {}
    }

    client = TestClient(app)
    mock_file = io.BytesIO(b"RIFFmockaudiodata")
    
    print("Testing POST /agent/voice with mock audio file...")
    response = client.post(
        "/agent/voice",
        files={"audio": ("test_voice.webm", mock_file, "audio/webm")}
    )
    
    print("Response Status:", response.status_code)
    print("Response JSON:", response.json())
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["transcribed_text"] == "search for resume"
    assert "result" in data
    assert "Step 1: Received audio input" in data["steps"][0]
    assert "Step 2: Saved audio to temporary file" in data["steps"][1]
    assert "Step 3: Transcribing audio" in data["steps"][2]
    assert "Step 4: Transcribed voice command" in data["steps"][3]
    assert "Step 5: Directing transcribed command to NLU" in data["steps"][4]

if __name__ == "__main__":
    test_voice_endpoint()
    print("Voice API test completed successfully!")
