export async function apiFetch(url, options = {}) {
    const token = sessionStorage.getItem("admin_token");
    const headers = { ...options.headers };

    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(url, {
        ...options,
        headers
    });

    if (response.status === 401) {
        sessionStorage.removeItem("admin_token");
        window.location.href = "/admin/login";
    }

    return response;
}
