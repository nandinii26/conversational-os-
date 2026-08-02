// In Electron (desktop app): window.location.protocol is "file:"
// so we always talk to the local bundled backend on port 8001.
// In browser (web deployment): use VITE_API_URL env var or the Render URL.
const isElectron = window.location.protocol === "file:";
const isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

export const API_BASE = (isElectron || isLocalhost)
  ? "http://localhost:8001"
  : (import.meta.env.VITE_API_URL || "https://conversational-os.onrender.com");
