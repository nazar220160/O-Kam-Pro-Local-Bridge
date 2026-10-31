import type { Metadata } from "next";
import "./globals.css";
import "@fontsource-variable/inter";
import "@fontsource-variable/manrope";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "O-Kam Bridge · Камеры под контролем",
  description: "Камеры, прямой эфир и интеграции в одном пространстве.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru" className="dark">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
