import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Mesa de micros",
  description: "Simulador paper de MNQ y MES. Enrutado en vivo apagado.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className="min-h-screen font-sans">{children}</body>
    </html>
  );
}
