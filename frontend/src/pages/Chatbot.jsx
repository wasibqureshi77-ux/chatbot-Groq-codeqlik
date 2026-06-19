import { useState, useEffect, useRef } from "react";
import React from "react";

const CHAT_API = "http://localhost:8000/api/chat";

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
    
    // Static fixed configurations matching user preference and screenshot
    const settings = {
        companyName: "CodeQlik",
        companyDescription: "CodeQlik provides software development, AI automation, and cloud consulting services.",
        title: "CodeQlik Assistant",
        subtitle: "SaaS Support Channel",
        welcomeMessage: "Hello! I'm CodeQlik's support assistant. How can I help you today?",
        placeholder: "Describe your inquiry...",
        primaryColor: "#4f46e5",
        theme: "dark",
        suggestions: [],
        footerText: "",
        showNewChat: true,
        botAvatar: "🤖"
    };

    const messagesEndRef = useRef(null);

    // Set greeting from static configurations
    useEffect(() => {
        setMessages([
            {
                sender: "bot",
                text: settings.welcomeMessage,
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
            }
        ]);
    }, [threadId]);

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
        setLoading(false);
        setMessages([
            {
                sender: "bot",
                text: settings.welcomeMessage,
                timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
            }
        ]);
    }

    async function sendMessage() {
        if (!input.trim()) return;

        const userMessage = input;
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

            setMessages((prev) => [
                ...prev,
                {
                    sender: "bot",
                    text: data.reply || data.response || data.message || "Sorry, I could not process that.",
                    timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                }
            ]);
        } catch (error) {
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

    const chatbotStyle = {
        background: "#090d16",
        fontFamily: "system-ui, -apple-system, sans-serif"
    };
    const chatBoxStyle = {
        background: "#0b0f19",
        borderLeft: "1px solid rgba(255, 255, 255, 0.08)",
        borderRight: "1px solid rgba(255, 255, 255, 0.08)"
    };
    const headerStyle = {
        background: "#0d121f",
        borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        color: "#ffffff"
    };
    const headerTitleStyle = {
        color: "#ffffff",
        margin: 0
    };
    const headerSubtitleStyle = {
        color: "var(--text-muted)",
        margin: "4px 0 0"
    };
    const messagesStyle = {
        background: "#0b0f19"
    };
    const inputAreaStyle = {
        background: "#0d121f",
        borderTop: "1px solid rgba(255, 255, 255, 0.08)"
    };
    const inputStyle = {
        background: "rgba(0, 0, 0, 0.35)",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        color: "#ffffff"
    };
    const buttonStyle = {
        background: "#4f46e5",
        color: "#ffffff"
    };
    const botBubbleStyle = {
        background: "#1e293b",
        color: "#f3f4f6",
        border: "1px solid rgba(255, 255, 255, 0.05)"
    };
    const userBubbleStyle = {
        background: "#4f46e5",
        color: "#ffffff"
    };

    return (
        <div className="chatbotPage" style={chatbotStyle}>
            <div className="chatbotContainer">
                <div className="chatPanelContainer">
                    <div className="chatBox" style={chatBoxStyle}>
                        <div className="chatHeader" style={headerStyle}>
                            <div>
                                <h2 style={headerTitleStyle}>{settings.title || "CodeQlik Assistant"}</h2>
                                <p style={headerSubtitleStyle}>{settings.subtitle || "SaaS Support Channel"}</p>
                            </div>
                            <div className="chatHeaderRight">
                                <div className="statusIndicator" style={{ background: "rgba(16, 185, 129, 0.1)", color: "var(--success)" }}>
                                    <span className="statusDot" style={{ background: "var(--success)", boxShadow: "0 0 8px var(--success)" }}></span>
                                    <span>Online</span>
                                </div>
                                {settings.showNewChat !== false && (
                                    <button className="resetChatBtn" onClick={resetChat} style={{ background: "rgba(255, 255, 255, 0.05)", border: "1px solid rgba(255, 255, 255, 0.2)", color: "#ffffff" }}>
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
                                        <div className="chatAvatar botAvatar" style={{ background: "rgba(255, 255, 255, 0.1)", color: "#ffffff" }}>
                                            {settings.botAvatar || "🤖"}
                                        </div>
                                    )}
                                    <div
                                        className={`messageBubble ${msg.sender === "user" ? "userBubble" : "botBubble"}`}
                                        style={msg.sender === "user" ? userBubbleStyle : botBubbleStyle}
                                    >
                                        <div className="messageText">{msg.text}</div>
                                        <div className="messageTime" style={{ color: msg.sender === "user" ? "rgba(255, 255, 255, 0.7)" : "var(--text-muted)" }}>
                                            {msg.timestamp || new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                        </div>
                                    </div>
                                    {msg.sender === "user" && <div className="chatAvatar userAvatar">👤</div>}
                                </div>
                            ))}

                            {loading && (
                                <div className="messageRow botRow">
                                    <div className="chatAvatar botAvatar" style={{ background: "rgba(255, 255, 255, 0.1)", color: "#ffffff" }}>
                                        {settings.botAvatar || "🤖"}
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

                        {settings.suggestions && settings.suggestions.length > 0 && !loading && (
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
                                style={inputStyle}
                            />
                            <button onClick={sendMessage} disabled={loading} style={buttonStyle}>
                                Send Input
                            </button>
                        </div>
                        {settings.footerText && (
                            <div style={{ textAlign: "center", fontSize: "11px", padding: "6px", color: "var(--text-muted)", background: "#0d121f", borderTop: "1px solid rgba(255, 255, 255, 0.05)" }}>
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