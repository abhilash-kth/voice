import { NextResponse, type NextRequest } from 'next/server';

export function proxy(request: NextRequest) {
    const loggedIn = request.cookies.has('va_session');
    const isLogin = request.nextUrl.pathname.startsWith('/login');

    if (!loggedIn && !isLogin) return NextResponse.redirect(new URL('/login', request.url));
    if (loggedIn && isLogin) return NextResponse.redirect(new URL('/', request.url)); // CHANGE
    return NextResponse.next();
}

export const config = {
    matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};