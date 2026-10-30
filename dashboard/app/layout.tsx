import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Compute Mint",
  description: "Savings, lanes and exposure ledger of the Compute Mint gateway.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
