import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Chatbot from "./pages/Chatbot";
import Admin from "./pages/Admin";
import AdminLogin from "./pages/AdminLogin";
import ProtectedRoute from "./components/ProtectedRoute";
import "./App.css";

function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Navigate to="/chatbot" />} />
                <Route path="/chatbot" element={<Chatbot />} />
                <Route path="/admin/login" element={<AdminLogin />} />
                <Route path="/admin/dashboard" element={
                    <ProtectedRoute>
                        <Admin />
                    </ProtectedRoute>
                } />
                <Route path="/admin" element={<Navigate to="/admin/dashboard" />} />
            </Routes>
        </BrowserRouter>
    );
}

export default App;