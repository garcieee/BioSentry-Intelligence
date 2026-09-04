import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Session } from "../types";
import styles from "./SessionMenu.module.css";

interface Props {
  session: Session;
  onSignOut: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  rn: "Staff Nurse",
  md: "Attending Physician",
  charge_rn: "Charge Nurse",
};

export function SessionMenu({ session, onSignOut }: Props) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);

  return (
    <div className={styles.wrapper}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
      >
        {session.clinician_id}
        <span className={styles.caret}>{open ? "\u25B4" : "\u25BE"}</span>
      </button>

      {open && (
        <>
          <div className={styles.backdrop} onClick={() => setOpen(false)} />
          <div className={styles.dropdown}>
            <div className={styles.info}>
              <span className={styles.role}>{ROLE_LABELS[session.role] ?? session.role}</span>
              <span className={styles.ward}>Ward {session.ward}</span>
            </div>

            <div className={styles.divider} />

            <Link to="/ward" className={styles.menuItem} onClick={() => setOpen(false)}>
              Ward Monitor
            </Link>
            {(session.role === "md" || session.role === "charge_rn") && (
              <Link to="/station" className={styles.menuItem} onClick={() => setOpen(false)}>
                Station
              </Link>
            )}

            <div className={styles.divider} />

            <button
              type="button"
              className={styles.menuItem}
              onClick={() => {
                setOpen(false);
                onSignOut();
                navigate("/");
              }}
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}
