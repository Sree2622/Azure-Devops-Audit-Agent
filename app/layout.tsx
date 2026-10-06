import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Azure DevOps Audit Logger",
  description: "AI-powered Azure DevOps Board and Sprint Intelligence Agent",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
