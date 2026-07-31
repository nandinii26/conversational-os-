import os


DEFAULT_GENAI_MODEL = "gemini-flash-latest"

SUPPORTED_GENAI_MODELS = {
	"gemini-flash-latest",
	"gemini-3.5-flash",
	"gemini-2.5-flash",
	"gemini-2.0-flash",
	"gemini-2.0-flash-001",
	"gemini-2.0-flash-lite",
	"gemini-2.0-flash-lite-001",
}


def get_genai_model(default: str = DEFAULT_GENAI_MODEL) -> str:
	model_name = os.environ.get("GENAI_MODEL", default).strip()
	if not model_name:
		return default

	if model_name not in SUPPORTED_GENAI_MODELS:
		return default

	return model_name
