import { useState, useEffect, useRef } from "react";
import AuthPage from "./AuthPage";
import { API_BASE } from "./config";
import "./App.css";
import { FaMicrophone, FaPaperclip } from "react-icons/fa";
import { IoSend } from "react-icons/io5";
import { HiOutlineMenu, HiOutlineX, HiOutlineTrash } from "react-icons/hi";


type Message = {
  sender: "user" | "bot";
  text: string;
  pptLink?: string; // if present, render as a download-PPT card
};

interface VoiceResponse {
  result: string;
  transcribed_text: string;
  steps: string[];
}

function App() {
  const [query, setQuery] = useState("");
  const [showVoice, setShowVoice] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [agentSteps, setAgentSteps] = useState<string[]>([]);
  const [activeSession, setActiveSession] = useState<string>(() => {
    return localStorage.getItem("activeSession") ?? "session_1";
  });
  const [sessions, setSessions] = useState<string[]>([]);
  const [answer, setAnswer] = useState<string>("");
  const [transcript, setTranscript] = useState<string>("");
  const [steps, setSteps] = useState<string[]>([]);
  const [recording, setRecording] = useState<boolean>(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadingFile, setUploadingFile] = useState<boolean>(false);
  const [user, setUser] = useState<{ name: string; email: string; picture: string } | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("jwt_token"));
  // Always start as true — the restoreSession effect checks BOTH localStorage AND
  // URL ?token= param (Google OAuth callback). Without this, the app shows AuthPage
  // immediately before the effect runs, breaking the Google login redirect flow.
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [sessionTitles, setSessionTitles] = useState<Record<string, string>>(() => {
    try { return JSON.parse(localStorage.getItem("sessionTitles") || "{}"); } catch { return {}; }
  });

  const updateSessionTitle = (sid: string, title: string) => {
    setSessionTitles((prev) => {
      const updated = { ...prev, [sid]: title };
      localStorage.setItem("sessionTitles", JSON.stringify(updated));
      return updated;
    });
  };

  const handleLoginSuccess = (newToken: string, userData: { name: string; email: string; picture: string }) => {
    setToken(newToken);
    setUser(userData);
    // Always start a fresh chat session on login
    const newSession = `session_${Date.now()}`;
    setActiveSession(newSession);
    setMessages([]);
    localStorage.setItem("activeSession", newSession);
  };

  const handleLogout = () => {
    localStorage.removeItem("jwt_token");
    localStorage.removeItem("auth_token");
    localStorage.removeItem("activeSession");
    setToken(null);
    setUser(null);
    setMessages([]);
    setSessions([]);
  };


  const handleSearch = async () => {
    if (!query.trim()) return;
    const userQuery = query;
    setQuery("");
    // Capture first message as session title
    if (messages.length === 0 && !sessionTitles[activeSession]) {
      updateSessionTitle(activeSession, userQuery);
    }
    setMessages((prev) => [...prev, { sender: "user", text: userQuery, }]);
    setLoading(true)

    try {
      const response = await fetch(`${API_BASE}/agent/run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: userQuery,
          session_id: activeSession,
        }),
      });

      if (!response.ok) {
        throw new Error("Request failed");
      }

      const data = await response.json();
      if (data.ppt_filename) {
        // Inject download link as a persistent chat message
        setMessages((prev) => [
          ...prev,
          { sender: "bot", text: "", pptLink: data.ppt_filename },
        ]);
      }
      if (data.steps) {
        setAgentSteps(data.steps);
      }

      console.log(data);

      if (data.result) {
        setMessages((prev) => [...prev, { sender: "bot", text: data.result }]);
      }
    } catch (err) {
      console.error(err);
      setMessages((prev) => [...prev, { sender: "bot", text: "Failed to connect to backend" }]);
    } finally {
      setLoading(false);
    }
  };

  const handleNewChat = () => {
    if (messages.length === 0) {
      console.log("Chat is already new. Reusing the current active session.");
      return;
    }
    const newsid = `session_${Date.now()}`;
    setSessions((prev) => [newsid, ...prev]);
    setActiveSession(newsid);
    setMessages([]);
  };

  const handleDeleteSession = async (sid: string) => {
    try {
      await fetch(`${API_BASE}/session/${sid}`, { method: "DELETE" });
    } catch {
      // best-effort: still remove from UI even if network fails
    }
    // Remove from local UI state
    setSessions((prev) => prev.filter((s) => s !== sid));
    // Remove stored title
    setSessionTitles((prev) => {
      const updated = { ...prev };
      delete updated[sid];
      localStorage.setItem("sessionTitles", JSON.stringify(updated));
      return updated;
    });
    // If we deleted the active session, start a fresh one
    if (activeSession === sid) {
      const newSid = `session_${Date.now()}`;
      setSessions((prev) => [newSid, ...prev.filter((s) => s !== sid)]);
      setActiveSession(newSid);
      setMessages([]);
      localStorage.setItem("activeSession", newSid);
    }
  };

  useEffect(() => {
    localStorage.setItem("activeSession", activeSession);
  }, [activeSession]);

  // Auto-scroll to bottom when messages update
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Restore session on mount: handle Google OAuth redirect OR existing jwt_token
  useEffect(() => {
    const restoreSession = async () => {
      try {
        // Check if Google OAuth just redirected back with a token in the URL
        const params = new URLSearchParams(window.location.search);
        const urlToken = params.get("token");
        const activeToken = urlToken ?? localStorage.getItem("jwt_token");

        if (urlToken) {
          localStorage.setItem("jwt_token", urlToken);
          setToken(urlToken);
          // Clean the token out of the URL bar
          window.history.replaceState({}, document.title, window.location.pathname);
        }

        if (!activeToken) {
          setAuthLoading(false);
          return;
        }

        const meRes = await fetch(`${API_BASE}/auth/me`, {
          headers: { Authorization: `Bearer ${activeToken}` },
        });
        if (meRes.ok) {
          const userData = await meRes.json();
          // This is the critical step — set user so the app renders instead of AuthPage
          setUser({
            name: userData.name || userData.email,
            email: userData.email,
            picture: userData.picture || "",
          });
          if (urlToken) {
            // Start a fresh session for the new Google login
            const newSession = `session_${Date.now()}`;
            setActiveSession(newSession);
            setMessages([]);
            localStorage.setItem("activeSession", newSession);
          }
        } else if (meRes.status === 401) {
          // Only clear the token if it's definitively invalid/expired (401)
          localStorage.removeItem("jwt_token");
          setToken(null);
        }
        // For other errors (500, network issues), keep the token and let the user try again
      } catch (err) {
        console.error("Failed to restore session:", err);
        // Network error — don't remove token, backend may be temporarily down
      } finally {
        setAuthLoading(false);
      }
    };
    restoreSession();
  }, [])

  useEffect(() => {
    const loadInitialData = async () => {
      try {

        const histRes = await fetch(`${API_BASE}/chat/history?session_id=${activeSession}`);
        let currentHistData: any[] = [];
        if (histRes.ok) {
          currentHistData = await histRes.json();
          setMessages(currentHistData);
        }

        const sessRes = await fetch(`${API_BASE}/session-list`, { method: "POST" });
        if (sessRes.ok) {
          const sessData = await sessRes.json();
          const extractedSessions: string[] = sessData.map((s: any) => s[0]);

          const allSessions = activeSession && !extractedSessions.includes(activeSession)
            ? [activeSession, ...extractedSessions]
            : extractedSessions;

          setSessions(allSessions);

          // Backfill titles with a single bulk request instead of N individual fetches
          const stored: Record<string, string> = (() => {
            try { return JSON.parse(localStorage.getItem("sessionTitles") || "{}"); } catch { return {}; }
          })();

          const sessionsNeedingTitle = allSessions.filter((sid) => !stored[sid]);

          if (sessionsNeedingTitle.length > 0) {
            const newTitles = { ...stored };

            // Use already-loaded history for the active session
            if (!newTitles[activeSession] && currentHistData.length > 0) {
              const firstUser = (currentHistData as any[]).find((m: any) => m.sender === "user");
              if (firstUser) {
                const raw: string = firstUser.text || "";
                newTitles[activeSession] = raw.length > 60 ? raw.slice(0, 60) + "…" : raw;
              }
            }

            // Single request to get first messages for ALL sessions at once
            try {
              const titlesRes = await fetch(`${API_BASE}/session-titles`);
              if (titlesRes.ok) {
                const titlesData: { session_id: string; first_message: string }[] = await titlesRes.json();
                for (const { session_id, first_message } of titlesData) {
                  if (!newTitles[session_id] && first_message) {
                    const raw = first_message.replace(/^\[Voice\]\s*/i, "🎙️ ");
                    newTitles[session_id] = raw.length > 60 ? raw.slice(0, 60) + "…" : raw;
                  }
                }
              }
            } catch { /* ignore — titles are cosmetic */ }

            localStorage.setItem("sessionTitles", JSON.stringify(newTitles));
            setSessionTitles(newTitles);
          }
        }
      } catch (err) {
        console.error("Error initializing app data:", err);
      }
    };

    loadInitialData();
  }, [activeSession]);


  // Auth gate is handled below after authLoading check (see lines ~446-457)



  const uploadAudio = async (audioBlob: Blob): Promise<void> => {
    // Explicitly name the file with the correct extension so backend can detect MIME type
    const mimeType = audioBlob.type || "audio/webm";
    const extension = mimeType.includes("ogg") ? ".ogg" : mimeType.includes("mp4") ? ".mp4" : ".webm";
    const formData = new FormData();
    formData.append("audio", audioBlob, `recording${extension}`);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/agent/voice?session_id=${activeSession}`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errText = await response.text();
        console.error("Voice upload error:", errText);
        setMessages((prev) => [...prev, { sender: "bot", text: `⚠️ Voice error: ${errText}` }]);
        return;
      }

      const data: VoiceResponse = await response.json();

      setAnswer(data.result);
      setTranscript(data.transcribed_text);
      setSteps(data.steps);

      // Append voice command and response to visual chat screen
      if (data.transcribed_text) {
        // Capture first voice message as session title
        setMessages((prev) => {
          if (prev.length === 0 && !sessionTitles[activeSession]) {
            updateSessionTitle(activeSession, `🎙️ ${data.transcribed_text}`);
          }
          return [...prev, { sender: "user", text: `🎙️ ${data.transcribed_text}` }];
        });
      }
      if (data.result) {
        setMessages((prev) => [...prev, { sender: "bot", text: data.result }]);
      }
      if (data.steps) {
        setAgentSteps(data.steps);
      }
    } catch (error) {
      console.error("Upload failed:", error);
      setMessages((prev) => [...prev, { sender: "bot", text: "⚠️ Could not reach the voice backend. Is the server running?" }]);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (!fileInputRef.current) return;
    fileInputRef.current.value = ""; // reset so same file can be re-selected
    if (!file) return;

    setUploadingFile(true);
    setLoading(true);
    setMessages((prev) => [...prev, { sender: "user", text: `📎 ${file.name}` }]);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(
        `${API_BASE}/analyze?session_id=${activeSession}`,
        { method: "POST", body: formData }
      );
      const data = await response.json();

      if (!response.ok) {
        setMessages((prev) => [
          ...prev,
          { sender: "bot", text: `⚠️ Upload failed: ${data.detail || "Unknown error"}` },
        ]);
        return;
      }

      if (data.result) {
        setMessages((prev) => [...prev, { sender: "bot", text: data.result }]);
      }
      if (data.ppt_filename) {
        setMessages((prev) => [
          ...prev,
          { sender: "bot", text: "", pptLink: data.ppt_filename },
        ]);
      }
      // Capture first message as session title
      if (!sessionTitles[activeSession]) {
        updateSessionTitle(activeSession, `📎 ${file.name}`);
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { sender: "bot", text: "⚠️ Could not reach the backend. Is the server running?" },
      ]);
    } finally {
      setUploadingFile(false);
      setLoading(false);
    }
  };

  const startRecording = async (): Promise<void> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      // Prefer webm/opus (Chrome), fall back to whatever the browser supports
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
        ? "audio/webm"
        : "";

      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      audioChunksRef.current = [];

      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        await uploadAudio(audioBlob);
        stream.getTracks().forEach((track) => track.stop());
      };

      mediaRecorderRef.current = recorder;
      recorder.start(250);
      setRecording(true);
    } catch (error) {
      console.error("Microphone access denied:", error);
      alert("Microphone access was denied. Please allow microphone permissions in your browser and try again.");
    }
  };

  const stopRecording = (): void => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  };

  // ── Auth Gate ─────────────────────────────────────────────────────────────
  // Show spinner while checking stored token on startup
  if (authLoading) {
    return (
      <div style={{ display: "flex", height: "100vh", width: "100vw", alignItems: "center", justifyContent: "center", background: "#1a1a1a" }}>
        <div style={{ color: "white", fontSize: "1.5rem", fontFamily: "sans-serif" }}>Loading...</div>
      </div>
    );
  }

  // Show auth page when not logged in
  if (!user) {
    return <AuthPage onLoginSuccess={handleLoginSuccess} />;
  }

  return (
    <div className="h-screen w-screen p-4 bg-amber-950 flex overflow-hidden">
      {/* Sidebar Container */}
      <div
        className={`transition-all duration-300 ease-in-out overflow-hidden flex flex-col h-full ${sidebarOpen ? "w-80 mr-4 opacity-100" : "w-0 mr-0 opacity-0 pointer-events-none"
          }`}
      >
        <div className="w-80 h-full border border-black rounded-md bg-gradient-to-b from-white to-gray-400 p-4 flex flex-col ">
          <div className="flex flex-col gap-4">
            <h2 className="text-xl font-bold text-black border-b border-black/10 pb-2 select-none">
              DOCPILOT
            </h2>
            <button
              onClick={handleNewChat}
              className="text-left w-full p-3 rounded-lg bg-white/20 hover:bg-white/30 text-black font-semibold text-sm transition-colors duration-200 cursor-pointer"
            >
              + New Chat
            </button>
            </div>
          <div className="mt-4 flex flex-1 min-h-0 flex-col gap-2 overflow-y-auto border-t border-black/10 pt-4">
            <p className="text-black/50 text-xs font-bold uppercase tracking-wider select-none px-2 mb-1">Recent Chats</p>
            {sessions.map((sid) => {
              const title = sessionTitles[sid];
              const displayTitle = title
                ? title.length > 32 ? title.slice(0, 32) + "…" : title
                : "New Chat";
              const isActive = activeSession === sid;
              return (
                <div
                  key={sid}
                  className={`group relative flex items-center w-full rounded-lg text-xs font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-white text-black border border-black shadow-sm font-semibold"
                      : "bg-white/10 hover:bg-white/20 text-black border border-transparent"
                  }`}
                >
                  {/* Session title button */}
                  <button
                    onClick={() => setActiveSession(sid)}
                    className="flex-1 text-left p-2.5 leading-tight cursor-pointer"
                  >
                    <span className="block text-[10px] font-bold opacity-40 uppercase tracking-wider mb-0.5">
                      {isActive ? "● Active" : "💬 Chat"}
                    </span>
                    <span className="block truncate">{displayTitle}</span>
                  </button>
                  {/* Delete button — visible on hover */}
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDeleteSession(sid); }}
                    title="Delete chat"
                    className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 p-1.5 mr-1.5 rounded hover:bg-red-100 hover:text-red-600 text-black/40 flex-shrink-0 cursor-pointer"
                  >
                    <HiOutlineTrash size={14} />
                  </button>
                </div>
              );
            })}
          </div>
          {user && (
            <div className="flex items-center gap-2 p-2 border-t border-black/10">
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-white font-bold text-sm select-none">
                {(user.name || user.email).charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-bold truncate">{user.name || user.email}</p>
                <p className="text-xs text-black/50 truncate">{user.email}</p>
              </div>
              <button
                onClick={handleLogout}
                className="text-xs text-black hover:text-red-600 transition-colors"
              >
                Logout
              </button>
            </div>
          )}


          <div className="text-black/50 text-xs border-t border-black/10 pt-2 text-center">
            DocPilot v1.0
          </div>
        </div>
      </div>
      {/* Main Content */}
      <div className="flex-1 h-full border-4 border-black rounded-md relative bg-gradient-to-b from-white to-gray-300 flex flex-col shadow-xl overflow-hidden p-6">
        {/* Sidebar Toggle Button */}
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="absolute top-4 left-4 z-20 p-2.5 rounded-lg border border-black bg-white hover:bg-gray-100 text-black shadow-md cursor-pointer transition-all duration-200 hover:scale-105 active:scale-95 flex items-center justify-center"
          title={sidebarOpen ? "Collapse Sidebar" : "Expand Sidebar"}
        >
          {sidebarOpen ? <HiOutlineX size={20} /> : <HiOutlineMenu size={20} />}
        </button>

        {/* Listening Voice Overlay */}
        {showVoice && (
          <div className="absolute inset-0 bg-white/90 backdrop-blur-sm z-30 flex flex-col justify-center items-center">
            <h1 className="text-4xl font-extrabold text-black mb-8 drop-shadow-sm select-none animate-pulse flex items-center gap-2">
              <span className="w-3 h-3 rounded-full bg-black animate-ping"></span>
              Listening...
            </h1>
            <button onClick={() => { setShowVoice(false); stopRecording(); }}
              className="w-30 h-30 rounded-full border border-gray-500 bg-white flex items-center justify-center hover:bg-gray-200 transition-colors duration-300 cursor-pointer shadow-md"
            >
              <FaMicrophone size={50} className="text-red-500 animate-pulse" />
            </button>
          </div>
        )}

        {/* Main Chat/Display Content Area */}
        <div className="flex-1 flex flex-col overflow-hidden relative mb-24">
          {messages.length === 0 ? (
            <div className="flex-1 flex flex-col justify-center items-center">
              <h1 className="text-4xl font-extrabold text-black mb-2 drop-shadow-sm select-none">
                DOCPILOT
              </h1>
              <p className="text-black/70 text-lg mb-8 select-none">
                How can I assist you today?
              </p>

              <button onClick={() => { setShowVoice(true); startRecording(); }}
                className="w-30 h-30 rounded-full border border-gray-500 bg-white flex items-center justify-center hover:bg-gray-200 transition-colors duration-300 cursor-pointer shadow-md"
              >
                <FaMicrophone size={50} className="text-black" />
              </button>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto px-4 py-16 space-y-4">
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
                >
                  {msg.pptLink ? (
                    // Persistent PPT download card in chat
                    <div className="max-w-2xl px-4 py-3 rounded-2xl shadow-sm border border-black bg-white text-black rounded-tl-none flex items-center gap-3">
                      <span className="text-2xl">📊</span>
                      <div className="flex flex-col gap-1">
                        <p className="text-sm font-semibold text-black">Presentation ready!</p>
                        <a
                          href={`${API_BASE}/download-ppt?filename=${msg.pptLink}`}
                          download
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-black text-white text-xs font-bold hover:bg-gray-800 transition-colors duration-200 shadow w-fit"
                        >
                          ⬇ Download PPT
                        </a>
                      </div>
                    </div>
                  ) : (
                  <div
                    className={`max-w-2xl px-4 py-3 rounded-2xl shadow-sm border border-black ${
                      msg.sender === "user"
                        ? "bg-white text-black rounded-tr-none"
                        : "bg-white text-black rounded-tl-none"
                    }`}
                  >
                    <p className="text-lg whitespace-pre-wrap leading-relaxed">{msg.text}</p>
                  </div>
                  )}
                </div>
              ))}
              {loading && (
                <div className="flex justify-start">
                  <div className="bg-white text-black border border-black max-w-2xl px-4 py-3 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-2">
                    <span className="w-2.5 h-2.5 rounded-full bg-black animate-bounce" style={{ animationDelay: "0ms" }}></span>
                    <span className="w-2.5 h-2.5 rounded-full bg-black animate-bounce" style={{ animationDelay: "150ms" }}></span>
                    <span className="w-2.5 h-2.5 rounded-full bg-black animate-bounce" style={{ animationDelay: "300ms" }}></span>
                  </div>
                </div>
              )}
              {/* Auto-scroll*/}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
        

        {/* Bottom Controls */}
        <div className="absolute bottom-6 left-6 right-6 flex items-center gap-4">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf"
            className="hidden"
            onChange={handleFileUpload}
          />

          {/* Upload File Button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadingFile}
            title="Upload a PDF file"
            className={`h-20 w-20 border rounded-md flex items-center justify-center transition-colors duration-300 cursor-pointer shadow-md ${
              uploadingFile
                ? "bg-blue-100 border-blue-400 text-blue-500 animate-pulse cursor-not-allowed"
                : "bg-white border-gray-500 hover:bg-blue-50 hover:border-blue-400 text-black hover:text-blue-600"
            }`}
          >
            <FaPaperclip size={24} />
          </button>

          {/* Search Box */}
          <input
            type="text"
            placeholder="What You Want me to do?"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="flex-1 h-20 rounded-full bg-white text-center text-2xl outline-none shadow-inner border border-gray-300 focus:border-black transition-colors duration-200 px-8"
          />

          <button onClick={() => { setShowVoice(true); startRecording(); }}
            className="h-20 w-20 border border-gray-500 bg-white rounded-md flex items-center justify-center hover:bg-gray-200 transition-colors duration-300 cursor-pointer shadow-md"
            title="Record voice command"
          >
            <FaMicrophone size={24} className="text-black" />
          </button>

          <button onClick={handleSearch}
            className="h-20 px-6 border border-gray-500 bg-white rounded-md flex items-center justify-center hover:bg-gray-200 transition-colors duration-300 cursor-pointer shadow-md"
          >
            <IoSend size={24} className="text-black" />
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;