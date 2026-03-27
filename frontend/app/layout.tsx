import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/components/providers/query-provider";
import { AuthGate } from "@/components/auth/auth-gate";

export const metadata: Metadata = {
  title: "OpenACM — Dashboard",
  description: "OpenACM - Open AI Computer Manager. Monitor, configure, and chat with your autonomous agent.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
      </head>
      <body className="antialiased">
        <QueryProvider>
          <AuthGate>
            {children}
          </AuthGate>
        </QueryProvider>
      </body>
    </html>
  );
}
