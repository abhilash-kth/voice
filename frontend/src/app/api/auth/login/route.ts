import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function POST(req: Request) {
    const res = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: await req.text(),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.token) {
        return NextResponse.json(data, { status: res.ok ? 500 : res.status });
    }

    // read expiry from inside the JWT
    const payload = JSON.parse(Buffer.from(data.token.split('.')[1], 'base64url').toString());
    const maxAge = Math.max(payload.exp - Math.floor(Date.now() / 1000), 0);

    const base = {
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'lax' as const,
        path: '/',
        maxAge,
    };

    const store = await cookies();
    store.set('access_token', data.token, { ...base, httpOnly: true });
    store.set('user_info', Buffer.from(JSON.stringify(data.user)).toString('base64url'), {
        ...base,
        httpOnly: false,
    });

    return NextResponse.json({ user: data.user, token: data.token });
}