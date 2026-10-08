import type { Metadata } from "next";
import "./globals.css";
import { Plus_Jakarta_Sans } from "next/font/google";
import { cn } from "@/lib/utils";
import QueryProvider from "@/providers/query-provider";

const fontSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  title: "Super Admin — Voice Agent SaaS",
  description:
    "Platform administration: users, provider catalog, API keys, billing, usage and audit logs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={cn("h-full scroll-smooth antialiased", fontSans.variable)}
    >
      <body className="min-h-full bg-background font-sans text-foreground selection:bg-primary selection:text-primary-foreground">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
