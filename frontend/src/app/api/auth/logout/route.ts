import { NextResponse } from 'next/server';
import { cookies } from 'next/headers';

export async function POST() {
    const store = await cookies();
    store.delete('access_token');
    store.delete('user_info');
    return NextResponse.json({ ok: true });
}