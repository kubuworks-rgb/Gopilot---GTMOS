import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GoPilot — GTM OS",
  description: "Evidence-backed GTM research and account intelligence",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
