import { clearToken, setToken, User } from "./api";

export async function login(body: { email: string; password: string }): Promise<User> {
    const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
        throw Object.assign(new Error(data?.detail || "Login failed"), { status: res.status });
    }

    if (res.status === 401) {
        logout();
    }

    // TEMP: keeps the old req() working. Delete this line later.
    setToken(data.token);
    return data.user;
}

export async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => { });
    clearToken();
}