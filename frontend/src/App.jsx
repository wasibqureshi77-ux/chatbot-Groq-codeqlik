import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Chatbot from "./pages/Chatbot";
import Admin from "./pages/Admin";
import "./App.css";

function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/" element={<Navigate to="/chatbot" />} />
                <Route path="/chatbot" element={<Chatbot />} />
                <Route path="/admin" element={<Admin />} />
            </Routes>
        </BrowserRouter>
    );
}

export default App;