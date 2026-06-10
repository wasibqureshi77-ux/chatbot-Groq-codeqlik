import { useState, useEffect, useRef } from "react";
import React from "react";

const SETTINGS_API = "http://localhost:8000/api/settings";
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
    const [settings, setSettings] = useState({
        company_name: "CodeQlik",
        company_description: "CodeQlik provides software development, AI automation, and cloud consulting services.",
        chatbot_greeting: "Hello! I’m CodeQlik’s support assistant. How can I help you today?",
        support_email: "info@codeqlik.com",
        support_phone: "+91-8949687368"
    });

    const messagesEndRef = useRef(null);

    // Fetch dynamic chatbot configurations on mount
    useEffect(() => {
        async function fetchSettings() {
            try {
                const res = await fetch(SETTINGS_API);
                if (res.ok) {
                    const data = await res.json();
                    setSettings(data);
                    
                    // Set default greeting from DB
                    setMessages([
                        {
                            sender: "bot",
                            text: data.chatbot_greeting || "Hello! How can I assist you today?",
                            timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                        }
                    ]);
                }
            } catch (err) {
                console.error("Failed to load settings:", err);
                setMessages([
                    {
                        sender: "bot",
                        text: "Hello! I’m CodeQlik’s support assistant. How can I help you today?",
                        timestamp: new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                    }
                ]);
            }
        }
        fetchSettings();
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
                    text: data.reply || "Sorry, I could not process that.",
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

    return (
        <div className="chatbotPage">
            <div className="chatbotContainer">
                
                {/* Clean, realistic full-width/centered support chat room */}
                <div className="chatPanelContainer">
                    <div className="chatBox">
                        <div className="chatHeader">
                            <div>
                                <h2>{settings.company_name} Assistant</h2>
                                <p>SaaS Support Channel</p>
                            </div>
                            <div className="chatHeaderRight">
                                <div className="statusIndicator">
                                    <span className="statusDot"></span>
                                    <span>Online</span>
                                </div>
                                <button className="resetChatBtn" onClick={resetChat}>
                                    🔄 Clear Chat
                                </button>
                            </div>
                        </div>

                        <div className="messages">
                            {messages.map((msg, index) => (
                                <div
                                    key={index}
                                    className={`messageRow ${msg.sender === "user" ? "userRow" : "botRow"}`}
                                >
                                    {msg.sender === "bot" && <div className="chatAvatar botAvatar">🤖</div>}
                                    <div
                                        className={`messageBubble ${msg.sender === "user" ? "userBubble" : "botBubble"}`}
                                    >
                                        <div className="messageText">{msg.text}</div>
                                        <div className="messageTime">
                                            {msg.timestamp || new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}
                                        </div>
                                    </div>
                                    {msg.sender === "user" && <div className="chatAvatar userAvatar">👤</div>}
                                </div>
                            ))}

                            {loading && (
                                <div className="messageRow botRow">
                                    <div className="chatAvatar botAvatar">🤖</div>
                                    <div className="messageBubble botBubble typingBubble">
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

                        <div className="inputArea">
                            <input
                                type="text"
                                placeholder="Describe your inquiry..."
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && sendMessage()}
                            />
                            <button onClick={sendMessage} disabled={loading}>
                                Send Input
                            </button>
                        </div>
                    </div>
                </div>
                
            </div>
        </div>
    );
}

export default Chatbot;