import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import type { PropsWithChildren } from "react";
import { Zh } from "../locales/zh";
import { En } from "../locales/en";

void i18n.use(initReactI18next).init({
  resources: { zh: { translation: Zh }, en: { translation: En } },
  lng: localStorage.getItem("df-language") || "zh",
  fallbackLng: "zh",
  interpolation: { escapeValue: false },
});

const Client = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5000, retry: 1 },
    mutations: { retry: false },
  },
});

export function Providers({ children }: PropsWithChildren) {
  return <QueryClientProvider client={Client}>{children}</QueryClientProvider>;
}
