import { useState } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import type { Session } from "./types";
import { initSession, clearSession } from "./api";
import { SignIn } from "./pages/SignIn";
import { Ward } from "./pages/Ward";
import { PatientDetail } from "./pages/PatientDetail";
import { Station } from "./pages/Station";

export function App() {
  const [session, setSession] = useState<Session | null>(null);

  const handleSignIn = (s: Session) => {
    initSession(s.clinician_id);
    setSession(s);
  };

  const signOut = () => {
    clearSession();
    setSession(null);
  };

  return (
    <Routes>
      <Route
        path="/"
        element={<SignIn onSignIn={handleSignIn} />}
      />
      <Route
        path="/ward"
        element={
          session ? (
            <Ward session={session} onSignOut={signOut} />
          ) : (
            <Navigate to="/" replace />
          )
        }
      />
      <Route
        path="/patient/:id"
        element={
          session ? <PatientDetail /> : <Navigate to="/" replace />
        }
      />
      <Route
        path="/station"
        element={
          session && (session.role === "md" || session.role === "charge_rn")
            ? <Station session={session} onSignOut={signOut} />
            : <Navigate to={session ? "/ward" : "/"} replace />
        }
      />
    </Routes>
  );
}
