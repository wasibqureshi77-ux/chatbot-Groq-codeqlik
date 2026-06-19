import React from "react";
import { Navigate } from "react-router-dom";

export default function ProtectedRoute({ children }) {
    const token = sessionStorage.getItem("admin_token");

    if (!token) {
        // If there's no token, redirect to login immediately
        // `replace` prevents the user from going back to the protected route via the browser's back button
        return <Navigate to="/admin/login" replace />;
    }

    // Token exists, render the protected component
    return children;
}
