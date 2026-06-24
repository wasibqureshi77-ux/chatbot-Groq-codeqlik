import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
// import "./Admin.css"; // Reuse styling for simplicity, or create AdminLogin.css

export default function AdminLogin() {
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    const handleLogin = async (e) => {
        e.preventDefault();
        setError("");
        setLoading(true);

        try {
            const res = await fetch("/api/admin/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password })
            });

            const data = await res.json();
            if (res.ok && data.access_token) {
                sessionStorage.setItem("admin_token", data.access_token);
                navigate("/admin/dashboard");
            } else {
                setError(data.detail || "Login failed");
            }
        } catch (err) {
            setError("Connection error. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="admin-container" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', backgroundColor: '#07090e', fontFamily: "'Inter', sans-serif" }}>
            <div className="admin-content" style={{ maxWidth: '400px', width: '100%', padding: '2.5rem', backgroundColor: 'rgba(15, 23, 42, 0.45)', borderRadius: '20px', backdropFilter: 'blur(12px)', boxShadow: '0 8px 32px rgba(0,0,0,0.4)', border: '1px solid rgba(255, 126, 33, 0.15)' }}>
                <div className="admin-header" style={{ marginBottom: '2rem', textAlign: 'center' }}>
                    <h1 style={{ color: '#ffffff', fontSize: '1.75rem', marginBottom: '0.5rem', fontWeight: '700', textShadow: '0 0 12px rgba(255, 126, 33, 0.35)', fontFamily: "'Outfit', sans-serif" }}>Admin Portal</h1>
                    <p style={{ color: '#94a3b8', fontSize: '0.9rem' }}>Sign in to manage chatbot settings</p>
                </div>

                <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                    <div>
                        <label style={{ display: 'block', color: '#f8fafc', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: '500' }}>Username</label>
                        <input
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            className="form-input"
                            style={{ width: '100%', padding: '0.75rem', borderRadius: '10px', backgroundColor: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(255, 126, 33, 0.15)', color: '#f8fafc', outline: 'none', fontSize: '0.95rem' }}
                            required
                        />
                    </div>
                    
                    <div>
                        <label style={{ display: 'block', color: '#f8fafc', marginBottom: '0.5rem', fontSize: '0.9rem', fontWeight: '500' }}>Password</label>
                        <input
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            className="form-input"
                            style={{ width: '100%', padding: '0.75rem', borderRadius: '10px', backgroundColor: 'rgba(15, 23, 42, 0.65)', border: '1px solid rgba(255, 126, 33, 0.15)', color: '#f8fafc', outline: 'none', fontSize: '0.95rem' }}
                            required
                        />
                    </div>

                    {error && <div style={{ color: '#ef4444', fontSize: '0.9rem', padding: '0.75rem', backgroundColor: 'rgba(239, 68, 68, 0.1)', borderRadius: '8px', border: '1px solid rgba(239, 68, 68, 0.2)' }}>{error}</div>}

                    <button 
                        type="submit" 
                        disabled={loading}
                        style={{ 
                            marginTop: '1rem', 
                            padding: '0.75rem', 
                            backgroundColor: '#ff7e21', 
                            color: 'white', 
                            border: 'none', 
                            borderRadius: '10px', 
                            cursor: loading ? 'not-allowed' : 'pointer',
                            fontWeight: '600',
                            opacity: loading ? 0.7 : 1,
                            transition: 'all 0.2s ease',
                            boxShadow: '0 4px 12px rgba(255, 126, 33, 0.3)',
                            fontSize: '0.95rem'
                        }}
                    >
                        {loading ? 'Signing in...' : 'Sign In'}
                    </button>
                </form>
            </div>
        </div>
    );
}
