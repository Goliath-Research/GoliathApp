import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Goliath platform host",
  description: "GoliathApp-owned platform UI shell (P0 fixture host)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
