import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import React from "react";

const CHAT_API = "/api/chat";

function formatMessageText(text) {
    if (!text) return "";
    
    let formatted = text
        .replace(/\u2011/g, "-")
        .replace(/\u202f/g, " ")
        .replace(/\u2019/g, "'");

    const paragraphs = formatted.split("\n\n");

    return paragraphs.map((para, paraIdx) => {
        const lines = para.split("\n");
        
        return (
            <div key={paraIdx} style={{ marginBottom: "12px" }}>
                {lines.map((line, lineIdx) => {
                    const isListItem = /^\s*(\d+\.|\*|-)\s+/.test(line);
                    const parts = line.split(/(\*\*.*?\*\*)/g);
                    const parsedLine = parts.map((part, partIdx) => {
                        if (part.startsWith("**") && part.endsWith("**")) {
                            return <strong key={partIdx}>{part.slice(2, -2)}</strong>;
                        }
                        return part;
                    });

                    return (
                        <div 
                            key={lineIdx} 
                            style={{ 
                                paddingLeft: isListItem ? "20px" : "0px",
                                textIndent: isListItem ? "-20px" : "0px",
                                marginBottom: "4px"
                            }}
                        >
                            {parsedLine}
                        </div>
                    );
                })}
            </div>
        );
    });
}

function audioExtensionFromMime(mimeType = "") {
    const type = String(mimeType || "").toLowerCase();
    if (type.includes("ogg")) return "ogg";
    if (type.includes("mp4") || type.includes("m4a")) return "mp4";
    if (type.includes("wav")) return "wav";
    if (type.includes("mpeg") || type.includes("mp3")) return "mp3";
    return "webm";
}

function Chatbot() {
    const [threadId, setThreadId] = useState(() => {
        let id = localStorage.getItem("thread_id");
        if (!id) {
            id = "user_" + Date.now();
            localStorage.setItem("thread_id", id);
        }
        return id;
    });

    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [fixedOptions, setFixedOptions] = useState([]);
    
    // Voice recording states
    const [isRecording, setIsRecording] = useState(false);
    const [mediaRecorder, setMediaRecorder] = useState(null);

    const startRecording = async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Specify supported MIME type for consistent browser output
            let options = {};
            if (MediaRecorder.isTypeSupported("audio/webm")) {
                options = { mimeType: "audio/webm" };
            } else if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
                options = { mimeType: "audio/webm;codecs=opus" };
            } else if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
                options = { mimeType: "audio/ogg;codecs=opus" };
            } else if (MediaRecorder.isTypeSupported("audio/mp4")) {
                options = { mimeType: "audio/mp4" };
            }

            const recorder = new MediaRecorder(stream, options);
            const chunks = [];
            
            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) {
                    chunks.push(e.data);
                }
            };
            
            recorder.onstop = async () => {
                const audioBlob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
                await sendVoiceMessage(audioBlob);
                stream.getTracks().forEach(track => track.stop());
            };
            
            setMediaRecorder(recorder);
            recorder.start(250);
            setIsRecording(true);
        } catch (err) {
            console.error("Error accessing microphone:", err);
            alert("Could not access microphone. Please check permissions.");
        }
    };

    const stopRecording = () => {
        if (mediaRecorder && mediaRecorder.state !== "inactive") {
            try {
                mediaRecorder.requestData();
            } catch (err) {
                console.warn("Could not request final audio data:", err);
            }
            mediaRecorder.stop();
            setIsRecording(false);
        }
    };

    const toggleRecording = () => {
        if (isRecording) {
            stopRecording();
        } else {
            startRecording();
        }
    };

    const sendVoiceMessage = async (audioBlob) => {
        setLoading(true);
        setMessages((prev) => [
            ...prev,
            { 
                sender: "user", 
                text: "🎙️ Sending voice message...", 
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) 
            }
        ]);

        try {
            const formData = new FormData();
            const extension = audioExtensionFromMime(audioBlob.type);
            formData.append("file", audioBlob, `recording.${extension}`);
            formData.append("thread_id", threadId);

            const res = await fetch("/api/voice/process", {
                method: "POST",
                body: formData
            });

            if (!res.ok) {
                throw new Error("Voice API request failed");
            }

            const data = await res.json();
            
            if (data.success) {
                setMessages((prev) => {
                    const updated = [...prev];
                    for (let i = updated.length - 1; i >= 0; i--) {
                        if (updated[i].sender === "user" && updated[i].text === "🎙️ Sending voice message...") {
                            updated[i].text = `🎙️ ${data.user_text}`;
                            break;
                        }
                    }
                    return updated;
                });

                const nextFixedOptions = Array.isArray(data.fixed_options) ? data.fixed_options : [];
                setMessages((prev) => [
                    ...prev,
                    {
                        sender: "bot",
                        text: data.bot_text,
                        options: nextFixedOptions,
                        timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                    }
                ]);
                setFixedOptions(nextFixedOptions);

                if (data.audio_url) {
                    const audio = new Audio(data.audio_url);
                    audio.play().catch(e => console.error("Error playing audio:", e));
                }
            } else {
                throw new Error(data.error || "Failed processing voice");
            }
        } catch (error) {
            console.error("Voice processing error:", error);
            setMessages((prev) => {
                const updated = [...prev];
                for (let i = updated.length - 1; i >= 0; i--) {
                    if (updated[i].sender === "user" && updated[i].text === "🎙️ Sending voice message...") {
                        updated[i].text = "🎙️ [Voice transmission failed]";
                        break;
                    }
                }
                return updated;
            });
        }
        setLoading(false);
    };
    
    const [settings, setSettings] = useState({
        companyName: "CodeQlik",
        companyDescription: "CodeQlik provides software development, AI automation, and cloud consulting services.",
        title: "CodeQlik Assistant",
        subtitle: "AI powered chatbot",
        welcomeMessage: "Hello! I'm CodeQlik's support assistant. How can I help you today?",
        placeholder: "Describe your inquiry...",
        primaryColor: "#d96216",
        theme: "dark",
        suggestions: [],
        footerText: "",
        showNewChat: true,
        botAvatar: "CQ",
        logoUrl: "",
        logoUrlLight: "",
        logoUrlDark: ""
    });

    useEffect(() => {
        async function fetchSettings() {
            try {
                const res = await fetch("/api/public/settings");
                if (res.ok) {
                    const data = await res.json();
                    setSettings(prev => ({ ...prev, ...data }));
                }
            } catch (err) {
                console.error("Error loading settings:", err);
            }
        }
        fetchSettings();
    }, []);

    const messagesEndRef = useRef(null);

    // Set greeting from configurations
    useEffect(() => {
        setMessages([
            {
                sender: "bot",
                text: settings.welcomeMessage,
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
            }
        ]);
    }, [threadId, settings.welcomeMessage]);

    // Auto scroll to bottom when messages list updates
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, loading]);

    // Reset Chat function
    function resetChat() {
        const newId = "user_" + Date.now();
        localStorage.setItem("thread_id", newId);
        setThreadId(newId);
        setInput("");
        setFixedOptions([]);
        setLoading(false);
        setMessages([
            {
                sender: "bot",
                text: settings.welcomeMessage,
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
            }
        ]);
    }

    async function sendMessage(messageOverride = "") {
        const userMessage = String(messageOverride || input || "").trim();
        if (!userMessage) return;

        setFixedOptions([]);
        setMessages((prev) => [
            ...prev,
            { 
                sender: "user", 
                text: userMessage, 
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'}) 
            }
        ]);

        setInput("");
        setLoading(true);

        try {
            const res = await fetch(CHAT_API, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    message: userMessage,
                    thread_id: threadId
                })
            });

            if (!res.ok) {
                throw new Error("API request failed");
            }

            const data = await res.json();
            const nextFixedOptions = Array.isArray(data.fixed_options) ? data.fixed_options : [];

            setMessages((prev) => [
                ...prev,
                {
                    sender: "bot",
                    text: data.reply || data.response || data.message || "Sorry, I could not process that.",
                    options: nextFixedOptions,
                    timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                }
            ]);
            setFixedOptions(nextFixedOptions);
        } catch (error) {
            setFixedOptions([]);
            setMessages((prev) => [
                ...prev,
                {
                    sender: "bot",
                    text: "Backend connection error. Please verify the API server is online.",
                    timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                }
            ]);
        }

        setLoading(false);
    }

    const isDark = settings.theme === "dark";

    const chatbotStyle = {
        background: isDark ? "#06080d" : "#f1f5f9",
        fontFamily: "'Inter', sans-serif",
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center"
    };
    const chatBoxStyle = {
        background: isDark ? "#080c12" : "#ffffff",
        border: isDark ? `1px solid ${settings.primaryColor || "#ff7e21"}26` : "1px solid rgba(0, 0, 0, 0.08)",
        borderRadius: "16px",
        boxShadow: isDark ? "0 8px 32px rgba(0, 0, 0, 0.55)" : "0 8px 32px rgba(0, 0, 0, 0.08)",
        overflow: "hidden",
        maxWidth: "1150px",
        width: "95%",
        height: "90vh",
        display: "flex",
        flexDirection: "column"
    };
    const headerStyle = {
        background: isDark ? "#0b0f19" : (settings.primaryColor || "#ff7e21"),
        borderBottom: `2px solid ${settings.primaryColor || "#ff7e21"}`,
        padding: "16px 24px",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center"
    };
    const headerTitleStyle = {
        color: "#ffffff",
        fontFamily: "'Outfit', sans-serif",
        fontSize: "18px",
        fontWeight: "700",
        margin: 0
    };
    const headerSubtitleStyle = {
        color: isDark ? "#94a3b8" : "rgba(255, 255, 255, 0.85)",
        fontSize: "12px",
        margin: "2px 0 0"
    };
    const messagesStyle = {
        background: isDark ? "#090e16" : "#f8fafc",
        flex: 1,
        padding: "24px",
        overflowY: "auto",
        display: "flex",
        flexDirection: "column",
        gap: "16px"
    };
    const inputAreaStyle = {
        background: isDark ? "#080c14" : "#ffffff",
        borderTop: isDark ? "1px solid rgba(255, 255, 255, 0.04)" : "1px solid rgba(0, 0, 0, 0.08)",
        padding: "16px 24px",
        display: "flex",
        gap: "12px"
    };
    const inputStyle = {
        background: isDark ? "rgba(255, 255, 255, 0.02)" : "#f8fafc",
        border: isDark ? "1px solid rgba(255, 255, 255, 0.06)" : "1px solid rgba(0, 0, 0, 0.08)",
        borderRadius: "8px",
        padding: "12px 16px",
        color: isDark ? "#ffffff" : "#0f172a",
        flex: 1,
        outline: "none",
        fontSize: "14px"
    };
    const fixedOptionsStyle = {
        display: "flex",
        gap: "10px",
        flexWrap: "wrap",
        marginTop: "12px"
    };
    const fixedOptionButtonStyle = {
        border: `1px solid ${settings.primaryColor || "#d96216"}`,
        background: "rgba(217, 98, 22, 0.12)",
        color: "#ffffff",
        borderRadius: "8px",
        padding: "8px 14px",
        cursor: loading ? "not-allowed" : "pointer",
        fontSize: "13px",
        fontWeight: "700",
        transition: "all 0.2s"
    };
    const buttonStyle = {
        background: settings.primaryColor || "#d96216",
        color: "#ffffff",
        border: "none",
        borderRadius: "8px",
        padding: "0 24px",
        fontWeight: "600",
        cursor: "pointer",
        transition: "background 0.2s"
    };
    const botBubbleStyle = {
        background: isDark ? "rgba(255, 255, 255, 0.03)" : "#f1f5f9",
        color: isDark ? "#f8fafc" : "#0f172a",
        border: isDark ? `1px solid ${settings.primaryColor || "#ff7e21"}22` : "1px solid rgba(0, 0, 0, 0.04)",
        borderRadius: "12px",
        padding: "12px 16px",
        fontSize: "14px",
        maxWidth: "70%",
        lineHeight: "1.5"
    };
    const userBubbleStyle = {
        background: settings.primaryColor || "#d96216",
        color: "#ffffff",
        borderRadius: "12px",
        padding: "12px 16px",
        fontSize: "14px",
        maxWidth: "70%",
        lineHeight: "1.5"
    };

    return (
        <div className="chatbotPage" style={chatbotStyle}>
            <div className="chatbotContainer">
                <div className="chatPanelContainer">
                    <div className="chatBox" style={chatBoxStyle}>
                        <div className="chatHeader" style={headerStyle}>
                            <div style={{ display: "flex", alignItems: "center", gap: "14px" }}>
                                <Link to="/" style={{ color: "#94a3b8", textDecoration: "none", display: "flex", alignItems: "center", justifyContent: "center", padding: "8px", borderRadius: "8px", background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", cursor: "pointer", transition: "all 0.2s" }} className="chat-back-btn">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg>
                                </Link>
                                <div className="chatAvatar botAvatar" style={{ width: "32px", height: "32px", background: "rgba(255, 255, 255, 0.1)", color: "#ffffff", overflow: "hidden", margin: 0, border: isDark ? "1px solid rgba(255, 255, 255, 0.1)" : "1px solid rgba(0, 0, 0, 0.08)" }}>
                                    {(isDark ? (settings.logoUrlDark || settings.logoUrl) : (settings.logoUrlLight || settings.logoUrl)) ? (
                                        <img 
                                            src={isDark ? (settings.logoUrlDark || settings.logoUrl) : (settings.logoUrlLight || settings.logoUrl)} 
                                            alt="Bot" 
                                            style={{ width: "100%", height: "100%", objectFit: "cover" }} 
                                        />
                                    ) : (
                                        settings.botAvatar || "CQ"
                                    )}
                                </div>
                                <div style={{ textAlign: "left" }}>
                                    <h2 style={headerTitleStyle}>{settings.title || "CodeQlik Assistant"}</h2>
                                    <p style={headerSubtitleStyle}>{settings.subtitle || "SaaS Support Channel"}</p>
                                </div>
                            </div>
                            <div className="chatHeaderRight" style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                                <div className="statusIndicator" style={{ background: "rgba(16, 185, 129, 0.1)", color: "var(--success)" }}>
                                    <span className="statusDot" style={{ background: "var(--success)", boxShadow: "0 0 8px var(--success)" }}></span>
                                    <span>Online</span>
                                </div>
                                {settings.showNewChat !== false && (
                                    <button className="resetChatBtn" onClick={resetChat} style={{ background: "rgba(255, 255, 255, 0.04)", border: "1px solid rgba(255, 255, 255, 0.08)", color: "#ffffff", padding: "8px 12px", borderRadius: "6px", fontSize: "12px", cursor: "pointer" }}>
                                        🔄 Clear Chat
                                    </button>
                                )}
                            </div>
                        </div>

                        <div className="messages" style={messagesStyle}>
                            {messages.map((msg, index) => (
                                <div
                                    key={index}
                                    className={`messageRow ${msg.sender === "user" ? "userRow" : "botRow"}`}
                                >
                                    {msg.sender === "bot" && (
                                        <div className="chatAvatar botAvatar" style={{ background: "rgba(255, 255, 255, 0.1)", color: "#ffffff", overflow: "hidden", border: isDark ? "1px solid rgba(255, 255, 255, 0.1)" : "1px solid rgba(0, 0, 0, 0.08)" }}>
                                            {(isDark ? (settings.logoUrlDark || settings.logoUrl) : (settings.logoUrlLight || settings.logoUrl)) ? (
                                                <img 
                                                    src={isDark ? (settings.logoUrlDark || settings.logoUrl) : (settings.logoUrlLight || settings.logoUrl)} 
                                                    alt="Bot" 
                                                    style={{ width: "100%", height: "100%", objectFit: "cover" }} 
                                                />
                                            ) : (
                                                settings.botAvatar || "CQ"
                                            )}
                                        </div>
                                    )}
                                    <div
                                        className={`messageBubble ${msg.sender === "user" ? "userBubble" : "botBubble"}`}
                                        style={msg.sender === "user" ? userBubbleStyle : botBubbleStyle}
                                    >
                                        <div className="messageText">{formatMessageText(msg.text)}</div>
                                        {msg.sender === "bot" && Array.isArray(msg.options) && msg.options.length > 0 && (
                                            <div className="chatFixedOptions" style={fixedOptionsStyle}>
                                                {msg.options.map((option, idx) => {
                                                    const optionsActive = index === messages.length - 1 && fixedOptions.length > 0 && !loading;
                                                    return (
                                                        <button
                                                            key={`${option.value || option.label}-${idx}`}
                                                            type="button"
                                                            disabled={!optionsActive}
                                                            onClick={() => optionsActive && sendMessage(option.value || option.label)}
                                                            style={{
                                                                ...fixedOptionButtonStyle,
                                                                opacity: optionsActive ? 1 : 0.5,
                                                                cursor: optionsActive ? "pointer" : "not-allowed"
                                                            }}
                                                        >
                                                            {option.label || option.value}
                                                        </button>
                                                    );
                                                })}
                                            </div>
                                        )}
                                        <div className="messageTime" style={{ color: msg.sender === "user" ? "rgba(255, 255, 255, 0.7)" : "var(--text-muted)" }}>
                                            {msg.timestamp || new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                        </div>
                                    </div>
                                    {msg.sender === "user" && <div className="chatAvatar userAvatar">👤</div>}
                                </div>
                            ))}

                            {loading && (
                                <div className="messageRow botRow">
                                    <div className="chatAvatar botAvatar" style={{ background: "rgba(255, 255, 255, 0.1)", color: "#ffffff", overflow: "hidden", border: isDark ? "1px solid rgba(255, 255, 255, 0.1)" : "1px solid rgba(0, 0, 0, 0.08)" }}>
                                        {(isDark ? (settings.logoUrlDark || settings.logoUrl) : (settings.logoUrlLight || settings.logoUrl)) ? (
                                            <img 
                                                src={isDark ? (settings.logoUrlDark || settings.logoUrl) : (settings.logoUrlLight || settings.logoUrl)} 
                                                alt="Bot" 
                                                style={{ width: "100%", height: "100%", objectFit: "cover" }} 
                                            />
                                        ) : (
                                            settings.botAvatar || "CQ"
                                        )}
                                    </div>
                                    <div className="messageBubble botBubble typingBubble" style={botBubbleStyle}>
                                        <div className="dot-pulse">
                                            <span></span>
                                            <span></span>
                                            <span></span>
                                        </div>
                                    </div>
                                </div>
                            )}
                            <div ref={messagesEndRef} />
                        </div>

                        {settings.suggestions && settings.suggestions.length > 0 && !loading && fixedOptions.length === 0 && (
                            <div className="chatSuggestions" style={{ display: "flex", gap: "8px", flexWrap: "wrap", padding: "10px 24px", background: "#0b0f19", borderTop: "1px solid rgba(255, 255, 255, 0.05)" }}>
                                {settings.suggestions.map((suggestion, idx) => (
                                    <button 
                                        key={idx} 
                                        onClick={() => {
                                            setInput(suggestion);
                                        }}
                                        className="cq-suggestion"
                                        style={{
                                            border: `1px solid ${settings.primaryColor}`,
                                            background: "rgba(79, 70, 229, 0.05)",
                                            color: "#ffffff",
                                            borderRadius: "999px",
                                            padding: "6px 12px",
                                            cursor: "pointer",
                                            fontSize: "12px",
                                            fontWeight: "500",
                                            transition: "all 0.2s"
                                        }}
                                    >
                                        {suggestion}
                                    </button>
                                ))}
                            </div>
                        )}

                        <div className="inputArea" style={inputAreaStyle}>
                            <input
                                type="text"
                                placeholder={settings.placeholder || "Describe your inquiry..."}
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                                disabled={loading}
                                style={{
                                    ...inputStyle,
                                    opacity: loading ? 0.55 : 1,
                                    cursor: loading ? "not-allowed" : "text"
                                }}
                            />
                            {(isRecording || input.trim() === "") ? (
                                <button 
                                    onClick={toggleRecording} 
                                    disabled={loading} 
                                    style={{
                                        ...buttonStyle,
                                        background: isRecording ? "#ef4444" : "#4b5563",
                                        padding: "0 18px",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center"
                                    }}
                                    title={isRecording ? "Stop recording" : "Record voice message"}
                                >
                                    {isRecording ? (
                                        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" style={{ animation: "pulse 1.2s infinite ease-in-out" }}>
                                            <rect x="6" y="6" width="12" height="12" rx="2" />
                                        </svg>
                                    ) : (
                                        <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                                            <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
                                            <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
                                        </svg>
                                    )}
                                </button>
                            ) : (
                                <button 
                                    onClick={sendMessage} 
                                    disabled={loading} 
                                    style={{
                                        ...buttonStyle,
                                        background: settings.primaryColor || "#d96216",
                                        padding: "0 18px",
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center"
                                    }}
                                    title="Send message"
                                >
                                    <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
                                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                                    </svg>
                                </button>
                            )}
                        </div>
                        {settings.footerText && (
                            <div style={{ textAlign: "center", fontSize: "11px", padding: "8px", color: isDark ? "rgba(255, 255, 255, 0.6)" : "rgba(0, 0, 0, 0.6)", background: isDark ? "#05050780" : "rgba(0, 0, 0, 0.02)", borderTop: isDark ? "1px solid rgba(255, 255, 255, 0.05)" : "1px solid rgba(0, 0, 0, 0.05)" }}>
                                {settings.footerText}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}

export default Chatbot;
