import fitz  # PyMuPDF
try:
    from services import summarize
except ImportError:
    from backend.services import summarize

class DocumentService:
    def __init__(self):
        # The memory now lives inside the service!
        self.memory_text = None

    def process_pdf(self, file_bytes: bytes) -> int:
        """Extracts text from PDF bytes and saves to memory."""
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        extracted_text = ""
        for page in doc:
            extracted_text += page.get_text()
            
        self.memory_text = extracted_text
        doc.close()
        return len(self.memory_text)

    def ask_question(self, question: str) -> str:
        """Sends the question and document text to the AI."""
        if not self.memory_text:
            raise ValueError("No document found. Please upload a PDF first.")
            
        document_text = self.memory_text[:5000]
        prompt = f"Answer using only this document:\n\n{document_text}\n\nQUESTION: {question}"
        
        # Call your Google Gemini function
        return summarize(prompt)

# Create a single instance to be shared across the app
doc_service = DocumentService()