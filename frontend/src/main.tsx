import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { PortalApp } from "./portal/PortalApp";
import "./styles/global.css";
import "./portal/portal.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

/** The portal (ТЗ р.7) is a separate interface, not a route inside the staff
 * SPA: it has its own authentication, its own token storage and none of the
 * staff chrome. Branching at the root rather than inside the staff router
 * means nothing under /portal can fall through to a staff screen. In
 * production it is meant to live on its own subdomain - nginx points that
 * subdomain here and the same bundle serves both. */
const isPortal = window.location.pathname.startsWith("/portal");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {isPortal ? (
        <PortalApp />
      ) : (
        <BrowserRouter>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      )}
    </QueryClientProvider>
  </StrictMode>
);
