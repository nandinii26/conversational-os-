// In Electron (desktop app): window.location.protocol is "file:"
// so we always talk to the local bundled backend on port 8001.
// In browser (web deployment): use VITE_API_URL env var or the Render URL.
const isElectron = window.location.protocol === "file:";

export const API_BASE = isElectron
  ? "http://localhost:8001"
  : (import.meta.env.VITE_API_URL || "https://conversational-os.onrender.com");
