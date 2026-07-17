import React from "react";
import { Link } from "react-router-dom";

const BRAND_LOGO = "/api/uploads/default_logo_light.png";

function Home() {
    return (
        <div className="cq-landing-container">
            {/* Top Navbar */}
            <nav className="cq-navbar">
                <div className="cq-nav-logo">
                    <img className="cq-logo-img" src={BRAND_LOGO} alt="CodeQlik Logo" style={{ width: '32px', height: '32px', borderRadius: '4px' }} />
                    <span className="cq-logo-text">CodeQlik</span>
                </div>
                <div className="cq-nav-right">
                    <span className="cq-nav-tag">CodeQlik Chatbot</span>
                    <span className="cq-version-badge">Admin Panel</span>
                </div>
            </nav>

            {/* Central Content */}
            <main className="cq-hero-content">
                <div className="cq-center-logo-wrapper">
                    <img className="cq-center-logo-img" src={BRAND_LOGO} alt="CodeQlik Logo" style={{ width: '80px', height: '80px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(249, 115, 22, 0.25)' }} />
                </div>
                
                <h1 className="cq-hero-title">CodeQlik Chatbot Console</h1>
                <p className="cq-hero-subtitle">Manage, test, and monitor your AI chatbot with ease.</p>
                <div className="cq-divider"></div>

                <div className="cq-cards-container">
                    {/* Card 1: Test Chatbot */}
                    <div className="cq-card cq-card-orange">
                        <div className="cq-card-icon-circle orange-glow">
                            <svg viewBox="0 0 24 24" fill="none" stroke="#f97316" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="cq-card-icon">
                                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                            </svg>
                        </div>
                        <h2 className="cq-card-title">Test Chatbot</h2>
                        <p className="cq-card-desc">Open the chatbot testing interface and try it out.</p>
                        <Link to="/chatbot" className="cq-card-btn btn-orange">
                            Open Chatbot <span className="arrow">&rarr;</span>
                        </Link>
                    </div>

                    {/* Card 2: Admin Login */}
                    <div className="cq-card cq-card-gray">
                        <div className="cq-card-icon-circle gray-glow">
                            <svg viewBox="0 0 24 24" fill="none" stroke="#94a3b8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="cq-card-icon">
                                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                                <circle cx="12" cy="7" r="4"></circle>
                            </svg>
                        </div>
                        <h2 className="cq-card-title">Admin Login</h2>
                        <p className="cq-card-desc">Login to the admin panel to manage your chatbot.</p>
                        <Link to="/admin" className="cq-card-btn btn-gray">
                            Admin Login <span className="arrow">&rarr;</span>
                        </Link>
                    </div>
                </div>
            </main>

            {/* Footer */}
            <footer className="cq-footer">
                <p className="cq-copyright">&copy; {new Date().getFullYear()} Powered by Codeqlik.</p>
            </footer>
        </div>
    );
}

export default Home;
