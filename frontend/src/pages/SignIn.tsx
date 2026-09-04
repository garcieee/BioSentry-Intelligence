import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import type { Session, SessionRole } from "../types";
import ch from "../components/Crosshair.module.css";
import styles from "./SignIn.module.css";

// --- Types ---

interface Props {
  onSignIn: (session: Session) => void;
}

type Department = "nursing" | "medical";
type Phase = "department" | "profile" | "auth" | "destination";

interface Profile {
  id: string;
  label: string;
  role: string;
  department: Department;
  sessionRole: SessionRole;
  patients: number;
  ward: string;
}

// --- Demo profiles ---

const PROFILES: Profile[] = [
  {
    id: "rn-delacruz",
    label: "Nurse de la Cruz",
    role: "Staff Nurse",
    department: "nursing",
    sessionRole: "rn",
    patients: 6,
    ward: "W4",
  },
  {
    id: "rn-reyes",
    label: "Nurse Reyes",
    role: "Staff Nurse",
    department: "nursing",
    sessionRole: "rn",
    patients: 6,
    ward: "W4",
  },
  {
    id: "rn-manalo",
    label: "Nurse Manalo",
    role: "Charge Nurse",
    department: "nursing",
    sessionRole: "charge_rn",
    patients: 12,
    ward: "W4",
  },
  {
    id: "md-santos",
    label: "Dr. Santos",
    role: "Attending Physician",
    department: "medical",
    sessionRole: "md",
    patients: 5,
    ward: "W4",
  },
  {
    id: "md-aquino",
    label: "Dr. Aquino",
    role: "Attending Physician",
    department: "medical",
    sessionRole: "md",
    patients: 5,
    ward: "W4",
  },
];

// --- Component ---

export function SignIn({ onSignIn }: Props) {
  const navigate = useNavigate();
  const [department, setDepartment] = useState<Department | null>(null);
  const [selected, setSelected] = useState<Profile | null>(null);
  const [passphrase, setPassphrase] = useState("anything");
  const [phase, setPhase] = useState<Phase>("department");

  const signInAndGo = (profile: Profile, path: string) => {
    onSignIn({
      clinician_id: profile.id,
      ward: profile.ward,
      role: profile.sessionRole,
    });
    navigate(path);
  };

  const handlePickDepartment = (dept: Department) => {
    setDepartment(dept);
    setSelected(null);
    setPhase("profile");
  };

  const handleSelectProfile = (p: Profile) => {
    setSelected(p);
    setPhase("auth");
  };

  const handleAuth = (e: FormEvent) => {
    e.preventDefault();
    if (!selected) return;
    setPhase("destination");
  };

  const handleBack = () => {
    if (phase === "profile") {
      setDepartment(null);
      setSelected(null);
      setPhase("department");
    } else if (phase === "auth") {
      setSelected(null);
      setPhase("profile");
    } else if (phase === "destination") {
      setPhase("auth");
    }
  };

  const filteredProfiles = department
    ? PROFILES.filter((p) => p.department === department)
    : [];

  return (
    <main className={styles.page}>
      <div className={styles.hero}>
        <p className={styles.eyebrow}>BioSentry</p>
        <h1 className={styles.heading}>Sign in</h1>
      </div>

      <div className={styles.content}>
        {phase !== "department" && (
          <button
            type="button"
            className={styles.backLink}
            onClick={handleBack}
          >
            &larr; Back
          </button>
        )}

        {/* Phase 1: Department */}
        {phase === "department" && (
          <>
            <p className={styles.sectionLabel}>I am a</p>
            <div className={styles.cards}>
              <button
                type="button"
                className={`${ch.box} ${styles.roleCard}`}
                onClick={() => handlePickDepartment("nursing")}
              >
                <div className={ch.inner} />
                <span className={styles.roleTitle}>Nurse</span>
                <span className={styles.roleDesc}>
                  Staff Nurse, Charge Nurse
                </span>
              </button>
              <button
                type="button"
                className={`${ch.box} ${styles.roleCard}`}
                onClick={() => handlePickDepartment("medical")}
              >
                <div className={ch.inner} />
                <span className={styles.roleTitle}>Physician</span>
                <span className={styles.roleDesc}>
                  Attending Physician, Consultant
                </span>
              </button>
            </div>
          </>
        )}

        {/* Phase 2: Profile */}
        {phase === "profile" && (
          <>
            <p className={styles.sectionLabel}>
              {department === "nursing" ? "Select nurse" : "Select physician"}
            </p>
            <div className={styles.cards}>
              {filteredProfiles.map((p) => (
                <button
                  key={p.id}
                  className={`${ch.box} ${styles.profileCard}`}
                  onClick={() => handleSelectProfile(p)}
                  type="button"
                >
                  <div className={ch.inner} />
                  <div className={styles.profileHeader}>
                    <span className={styles.profileInitial}>
                      {p.label.split(" ").pop()?.charAt(0) ?? p.label.charAt(0)}
                    </span>
                    <div>
                      <div className={styles.profileName}>{p.label}</div>
                      <div className={styles.profileRole}>{p.role}</div>
                    </div>
                  </div>
                  <div className={styles.profileMeta}>
                    <span>{p.patients} patients</span>
                    <span>Ward {p.ward}</span>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}

        {/* Phase 3: Auth */}
        {phase === "auth" && selected && (
          <form onSubmit={handleAuth} className={styles.form}>
            <div className={styles.selectedInfo}>
              <span className={styles.selectedName}>{selected.label}</span>
              <span className={styles.selectedDetail}>
                {selected.role} &middot; Ward {selected.ward} &middot;{" "}
                {selected.patients} patients
              </span>
            </div>

            <div className={styles.field}>
              <label className={styles.label} htmlFor="passphrase">
                Passphrase
              </label>
              <div className={ch.box}>
                <div className={ch.inner} />
                <input
                  className={styles.input}
                  id="passphrase"
                  type="password"
                  value={passphrase}
                  onChange={(e) => setPassphrase(e.target.value)}
                  autoComplete="off"
                />
              </div>
            </div>

            <button type="submit" className={styles.btn}>
              Continue
            </button>

            <p className={styles.authNote}>
              Production deployments authenticate through the hospital
              identity provider. This pilot build accepts any passphrase.
            </p>
          </form>
        )}

        {/* Phase 4: Destination */}
        {phase === "destination" && selected && (
          <>
            <div className={styles.selectedInfo}>
              <span className={styles.selectedName}>{selected.label}</span>
              <span className={styles.selectedDetail}>
                {selected.role} &middot; Ward {selected.ward}
              </span>
            </div>

            <p className={styles.sectionLabel}>Choose destination</p>
            <div className={styles.cards}>
              <button
                type="button"
                className={`${ch.box} ${styles.destCard}`}
                onClick={() => signInAndGo(selected, "/ward")}
              >
                <div className={ch.inner} />
                <span className={styles.destTitle}>Ward Monitor</span>
                <span className={styles.destDesc}>
                  View your assigned patients, ranked by deterioration risk.
                </span>
              </button>
              {(selected.sessionRole === "md" || selected.sessionRole === "charge_rn") && (
                <button
                  type="button"
                  className={`${ch.box} ${styles.destCard}`}
                  onClick={() => signInAndGo(selected, "/station")}
                >
                  <div className={ch.inner} />
                  <span className={styles.destTitle}>Station</span>
                  <span className={styles.destDesc}>
                    Admit patients, enter lab results, upload documents.
                  </span>
                </button>
              )}
            </div>
          </>
        )}
      </div>

      <footer className={styles.footer}>
        <div className={styles.footerGrid}>
          <div className={styles.footerItem}>
            <span className={styles.footerLabel}>Privacy</span>
            <span>RA 10173 compliant</span>
          </div>
        </div>
      </footer>
    </main>
  );
}
