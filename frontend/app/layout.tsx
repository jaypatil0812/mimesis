import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Memesis — Market Intelligence Graph",
  description: "Provenance-first deterministic market intelligence & reasoning engine",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-zinc-950 text-zinc-100 antialiased selection:bg-blue-600 selection:text-white">
        {children}
      </body>
    </html>
  );
}
